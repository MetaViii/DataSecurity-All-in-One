# 新增通用节点：0.3

0.3版增加了本页介绍的16个节点。当前0.5版共有56个内置节点：初始30个的参数见 [节点手册](node-catalog.md)，0.4增加的5个见 [首次原题实测](real-ctf.md)，0.5增加的5个见 [纠错评分](correction.md)与[第二批原题实测](contest-round2.md)。所有单元格仍是字符串；数值只在运算时转 Decimal。输入对象不可变，修改通过 `Record.rebuild` 或 `with_updates` 留下记录。

## 字段、行和嵌套结构

| ID | 用途 | 必填参数 | 输出 |
| --- | --- | --- | --- |
| values.map | 明确字典规范化，如 male→男 | field、mapping | matched / unmatched |
| values.coalesce | 多来源字段按优先级取第一个非空值 | fields | data |
| rows.number | 在当前顺序上生成序号 | 无 | data |
| rows.explode | 单元格多值展开多行 | field | data |
| columns.unpivot | 宽表转长表，保留其余标识列 | fields | data |
| json.extract | 按 JSON Pointer 提取单元格中的嵌套值 | field、mapping | valid / invalid |
| number.normalize | 千分位、百分号、精确舍入 | fields | valid / invalid |
| text.template | 用字段拼提交字符串 | template | data |

`values.map` 的 mapping 是原值到标准值的映射，例如 `{"male":"男","female":"女"}`。`output` 留空修改原字段；否则写到指定列。`strip` 和 `ignore_case` 默认关闭。规范化后字典键重复会报错，避免结果取决于字典顺序。未命中保留原字段，附加原因，不凭相似度猜答案。

`values.coalesce` 的 fields 按顺序检查；`whitespace_empty=true` 可把纯空白视为空。`fallback` 默认为空，`output` 默认为“合并值”。它只选择，不合并多个非空值。

`rows.number` 默认从 1 开始，`step=1`、`width=0`；位数可设为 3 得到 001。必须写新列，不覆盖原编号。先排序再编号，才会按排序结果提交。

`rows.explode` 按字面 separator 分割；默认逗号，不按正则。`strip=false`、`keep_empty=true`，输出默认覆盖所选列。每个新行保留原来源。`columns.unpivot` 则把 fields 的每个值写为“字段”“值”两列；列名通过 name_output、value_output 修改。二者默认 max_rows=1000000，超限报错，不悄悄截断。

`json.extract` 的 mapping 方向是**结果列 → 路径**：

```json
{"用户编号":"/user/id","首项金额":"/items/0/amount"}
```

路径遵循 RFC 6901：`~1` 表示 `/`，`~0` 表示 `~`，空路径表示整个值。它不支持 JSONPath 通配符或脚本表达式。拒绝重复 JSON 键、NaN/Infinity、越界数组下标；拒绝与原字段重名的结果列。失败行保留原 JSON，新列留空并附原因。JSON 数字解析保留精度，不先经过 float。

`number.normalize` 默认不允许千分位或百分号，允许空值。`thousands=comma|space|none` 明确千分位；`percent=true` 将末尾百分数除以100。`places=-1` 保留精度并去小数尾零；非负数固定小数位。`rounding=half_up|half_even|truncate`。错误行所有所选字段保持原值。它接受科学计数法，但限制极端指数。编号、电话和证件不要送入数值规范化。

`text.template` 默认结果列为“文本结果”，例如 `flag{{{摘要}}}` 得到 `flag{...}`。只接受 `{字段名}` 和双花括号转义，不允许属性访问、索引、格式表达式或函数调用。

## 校验和还原

| ID | 必填参数 | 关键可选项 | 输出 |
| --- | --- | --- | --- |
| validate.identity | field | gender_field、birth_field、region_codes、reference_date | valid / invalid |
| validate.luhn | field | min_length=12、max_length=19 | valid / invalid |
| codec.xor | fields、key | key_format、key_offset、input_format、output_format | valid / invalid |
| text.write | path、fields | separator、header、line_ending、encoding | 文件 |

身份证节点按 GB 11643 的18位结构与校验码处理，检查真实生日和非000顺序码，默认接受小写 x。参考：[标准正文](https://zjw.beijing.gov.cn/Portals/0/zhuanti/fazhan/%E8%BA%AB%E4%BB%BD%E8%AF%81GB11643-1999.pdf)。

填 gender_field 可与身份证第17位奇偶对照；男性接受值默认为男、male、M、1，女性为女、female、F、2，可自己改。填 birth_field 对照生日，默认格式 `%Y-%m-%d`。空值或未知性别会失败。reference_date 是显式的生日上限；留空不隐含今天，保证重跑结果可复现。

region_codes 默认为空，不提供易过期的全国历史区划字典；填写后按六位白名单检查。校验通过只说明这些规则一致，不能证明证件真实签发、当前有效或属于某人。不提供修改校验位、补生日或猜真实身份的自动修复。

Luhn 节点只接受 ASCII 数字，拒绝全零串。它检查长度和校验和，不检查卡 BIN、开户状态或银行归属。比赛若指定前缀白名单，可再接正则或组合校验。

XOR 节点直接把 Base64/hex 变为字节再异或，避免中间字节无法解为 UTF-8 的问题。key_format 默认 text，也可 hex；key_offset 默认为0，可负数。input_format 默认 base64，output_format 默认 text；二者也可选 hex，文本编码默认为 UTF-8。每个字段从同一个偏移开始循环；不是跨单元格连续密钥流。skip_empty=true 保持空值。密钥由题目或人工分析给出，本节点不猜密钥。任何一个字段出错，整行保持原值并走 invalid。

text.write 按 fields 顺序和 separator 输出，默认逗号、无表头、UTF-8、LF。不会自动加 CSV 引号，所以字段中的分隔符也会原样出现；请按题目提交协议选择。字段或表头包含换行时失败，临时文件被清除；预览不写文件。JSON/CSV/XLSX 导出仍适合一般表格。

## 参考表和统计

`tables.lookup` 有 data、reference 两个输入。keys 是两表的同名键字段，mapping 是**目标列 → 参考列**；例如 `{"部门":"标准部门"}`。默认 mode=fill_empty，仅填空值；replace 覆盖目标值。whitespace_empty=true 默认把纯空白视为空。空键不命中，非空重复参考键报错。输出 matched/unmatched；匹配行保留主表与参考表来源，并记录修改原因。关联键不能被改写。它适合“已有权威字典纠错”，一般多对多关系仍使用 tables.join。

`profile.summary` 输出原表 data 和汇总表 summary。fields 空表示全部，top 默认5，whitespace_empty=true。每列给出总行数、空值数、唯一值数、能解析为有限 Decimal 的值数量、长度范围与高频值。唯一值按原始字符串区分，包含空字符串；高频并列按首次出现顺序。汇总行代表一列，不虚构某一源行的来源。

`stats.outliers` 的 field 是数值字段，group_by 空表示整体；默认 threshold="3"、min_count=3、ddof=0。ddof=0 使用**总体方差（除以 n）**，ddof=1 使用**样本方差（除以 n−1）**，可按题目选择。严格超过阈值才异常，等于阈值不异常。小组样本不足或方差为0时不判异常。无效数字走 invalid；其余分 normal / outliers，保持输入顺序。实现比较平方偏差与 k²×方差，不需要开平方。本演练明确使用总体口径，不能与 pandas 默认样本标准差混称。

`rows.window_count` 必填 time_field、group_by；默认 seconds=3600。以每条记录的时间 t，统计**闭区间 [t−窗口,t]**，包含当前记录。同一时刻的多条记录一起计入；内部排序计算，输出回到原顺序。distinct_field 空为记录数，填写后统计不同值（空字符串也算一个值）。output 默认新增“窗口数量”，禁止覆盖已有列。无效 ISO 时间走 invalid；整表不要混用带时区和无时区时间，混用行会附原因。需要统计未来或围绕任意两端的窗口时应另写规则。

所有处理仍全量在内存执行。概览频数与窗口排序也占内存；应先用小附件核对口径，再处理大数据。
