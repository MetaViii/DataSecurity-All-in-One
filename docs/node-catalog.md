# 通用节点手册

本页介绍初始30个节点；当前0.5版共56个。0.3增加的16个节点见 [新增节点说明](advanced-nodes.md)，0.4增加的5个见 [首次原题实测](real-ctf.md)，0.5增加的5个见 [纠错与评分](correction.md)和[浙江/羊城杯实测](contest-round2.md)。

当前 30 个内置节点。机器端口名写在代码字体里，前端显示中文。所有单元格都是字符串，空字符串与 NULL 文本不同；规则明确要求时才清理、转换或解析数字。查看完整参数可执行 `python -m datasecurity plugins --id 节点ID`。

## 输入与输出：7 个

| ID | 核心配置 | 行为 |
| --- | --- | --- |
| `csv.read` | path、encoding、delimiter、skip_blank_lines | CSV/TSV；UTF-8 BOM、引号、逗号和多行字段由 csv 库处理；重复/空表头、行宽不一致明确报错 |
| `json.read` | path、format、record_path、encoding | JSON 对象/对象数组或逐行对象；字段取所有记录的并集；嵌套值转 JSON 文本 |
| `text.read` | path、encoding、skip_empty | 生成行号/内容两列，仅去掉换行；保留其他空白和原物理行号 |
| `xlsx.read` | path、sheet、formulas、skip_empty | 第一张表或指定工作表，第一行必须是合法表头 |
| `csv.write` | path、encoding、delimiter、line_ending、diagnostics、overwrite | 全量 CSV/TSV 输出，保持文本、列顺序；可附诊断列 |
| `json.write` | path、format、diagnostics、overwrite | JSON 数组或 JSONL；默认平铺 values，开启诊断后带结构化追踪信息 |
| `xlsx.write` | path、sheet、diagnostics、overwrite | 全部写成文本单元格，避免长号码和等号文本被当作数字/公式 |

所有输入输出端口都是 `data`，output 没有输出端口。Web 的 path 输出只需文件名；CLI 默认不覆盖，示例明确打开 overwrite。

JSON：显式 null → `"null"`，缺少字段 → `""`，布尔 → `"true"/"false"`；数字先按 Decimal/整数读取再变字符串，避免浮点解析损失。record_path 支持对象键的点分路径，例如 data.users，不支持数组索引或键名含点的转义。JSONL 留空 record_path。JSON 输出不承诺恢复原始数值/布尔类型。

XLSX：字符串保留原值；日期转 ISO 文本；整数且 number_format 仅由 0 组成时补足前导零，不是通用 Excel 显示格式模拟器。数值整数超过 15 位附加源精度风险提示，无法恢复 Excel 已损坏的位数。默认 formulas=text 保留公式文本；reject 报错；cached 读取已有结果缓存，缺少缓存时报错，工具不计算 Excel 公式。只处理 XLSX，不支持老式 XLS、宏或样式往返。输出限制 1,048,575 条数据行、16,384 列、每格 32,767 字符，超出报错并保留已有目标。

## 字段与文本：8 个

| ID | 核心配置 | 行为 |
| --- | --- | --- |
| `columns.select` | fields、mode=keep/drop | keep 按配置顺序保留，drop 保持剩余列原序；至少剩一列 |
| `columns.rename` | mapping | 原名→新名；允许一次交换列名，拒绝最终重名；历史字段名保留原貌 |
| `columns.split` | field、separator、outputs、keep_source | 字面分隔符；最后一列保留剩余内容，缺失列补空；结果名不可冲突 |
| `columns.combine` | fields、separator、output、drop_sources | 按给定顺序拼接，可删除来源字段；结果可以覆盖明确指定的已有字段 |
| `values.fill` | fields、value、whitespace_empty | 默认只填空字符串，选项开启后把纯空白也当空 |
| `text.clean` | fields、action、normalization | strip/lstrip/rstrip/upper/lower/collapse_whitespace/remove_whitespace；可明确选择 NFC/NFKC |
| `text.replace` | fields、search、replacement、regex、count | 字面或 Python 正则替换；count=0 全部，非零最多指定次数 |
| `text.extract` | field、pattern、group、output | search 找第一个匹配；group=0 整体，否则捕获组；未匹配写空字符串并记录问题 |

均为 `data → data`。新增/删除/实际修改字段会记录 changes，单纯重排列不伪造值修改。Unicode NFKC 会改变全角字符等形式，只有明确需要时开启。正则采用 Python re 语法；replacement 支持 Python 分组引用。复杂或灾难性回溯模式没有强制超时。

## 行处理：4 个

| ID | 配置与端口 | 语义 |
| --- | --- | --- |
| `rows.filter` | conditions、match；输出 matched/unmatched | 多条件 all/any，保留互补分支和原顺序 |
| `rows.deduplicate` | fields、keep；输出 unique/duplicates | fields 空比较整行；first/last 保留一条，none 删除所有重复键；duplicates 是被移除记录 |
| `rows.sort` | rules、empty；输出 data | 按规则优先级稳定排序，类型 text/number/date，方向 asc/desc；空字符串位置独立于方向 |
| `rows.sample` | mode、count、seed、stride；输出 data | head/random/stride，明确改变处理范围；随机结果按原序输出，种子可复现 |

filter 的条件：eq/ne、contains/not_contains、regex、length、gt/gte/lt/lte、empty/not_empty。字符串比较不自动 strip。regex 是搜索匹配；数值比较使用 Decimal，非法数字不满足数值条件；length 使用 min/max 整数，空条件列表不接受。unmatched 是整体条件的逻辑补集，不是把每个条件单独取反后继续 AND。

sort 的数值/日期解析失败会报错，避免悄悄落到某个排序位置；日期格式留空为 ISO，可在规则 format 指定 strptime。相同键保持输入顺序。sample 的 count=0 返回空表；stride 最终也受 count 上限限制。

## 校验、计算、分类：5 个

| ID | 配置与端口 | 语义 |
| --- | --- | --- |
| `validate.regex` | field、pattern、full_match、message；valid/invalid | full_match 默认 true 整串匹配，false 使用 search；失败保持原值并附问题 |
| `validate.rules` | rules；valid/invalid | 一行检查全部规则，汇总所有失败原因；全部通过才 valid |
| `columns.calculate` | expression、output；data | 白名单 AST 解释器，不运行 Python eval/exec |
| `datetime.transform` | field、operation、input_format、output_format、seconds、other、output；data | 日期格式化、增加整数秒、来源减 other 的秒差 |
| `rows.classify` | rules、default、output；data | 按配置顺序匹配，第一个命中的 label 写入结果，否则 default |

组合校验规则示例：

```json
[
  {"field": "编号", "check": "required"},
  {"field": "年龄", "check": "range", "min": "18", "max": "99"},
  {"field": "手机号", "check": "regex", "pattern": "[0-9]{11}"},
  {"field": "性别", "check": "enum", "values": ["男", "女"]}
]
```

支持 required、number、range、length、regex、enum、unique、date、equals_field。regex 为 fullmatch；unique 针对整张输入表，同一值出现多次的每条都失败；required 拒绝纯空白，普通 empty 只看空字符串。每条规则可有 message、allow_empty；后者仅跳过非 required 规则的空字符串。date 可指定 format，equals_field 指定 other。界面未提供的规则键可切 JSON 编辑。

表达式例子：`round([单价] * [数量], 2)`、`upper([姓名])`、`"成人" if number([年龄]) >= 18 else "其他"`。支持 + - * / // % **、比较、and/or/not、三元条件，函数 abs/round/length/upper/lower/coalesce/number。两个字符串的 + 是拼接；需要数值相加时写 `number([a]) + number([b])`。字段对数字常量比较会按数字解析，两个字符串字段直接比较则按文本。round 为 ROUND_HALF_UP，位数 -16～16；指数限制 -16～16 整数。禁止属性访问、索引、任意函数、导入和推导式；表达式最多 2000 字符、120 AST 节点。数字格式保留 Decimal 语义，但仍受默认 Decimal 上下文精度约束。

日期处理不是时区推断器；带时区和不带时区时间混用会报错。difference_seconds 精确表达到微秒，日期解析失败按节点错误处理，不猜测日期含义。

## 多表与统计：4 个

| ID | 端口和核心配置 | 语义 |
| --- | --- | --- |
| `rows.merge` | left/right → data；schema | strict 要求字段集合一致，按左表列序；union 并集补空；左表之后追加右表 |
| `tables.join` | left/right → data；left_keys/right_keys、how、suffix、match_empty、max_rows | left/inner/full 关系连接，支持复合键与重复键展开 |
| `group.aggregate` | data → data；group_by、measures、ignore_empty、decimal_places | count/sum/mean/min/max/distinct_count；分组按首次出现顺序 |
| `tables.compare` | answer/candidate → summary/matched/missing/extra；fields | 按选定字段及重复次数作多重集比较，不依赖行序 |

join 默认不匹配含空字符串的键，右表重名列反复加 suffix 直到唯一；重复键产生笛卡尔展开。默认结果上限 1,000,000 行，超过明确报错；该行数不是内存预算，较宽表或大量追踪信息仍可能耗尽内存。结果保留参与匹配的两侧来源。

聚合 count 是组内记录数，其他统计需要 field/output；数值空组输出空字符串，count 输出 0。group_by 为空表示全表聚合，空输入也输出一条全表摘要。均值按 decimal_places 四舍五入，数值最终去掉末尾零；distinct_count 对字符串精确比较。ignore_empty 默认开启，不会把 NULL 文本当空或当数字。

答案对比支持列序不同，fields 为空要求字段集合相同。重复记录按出现次数匹配，不会被 set 吞掉。得分口径固定为 `正确/(正确+缺失+多余)`，空集对空集为 1，展示到 6 位小数后去末尾零。这是本工具的演示口径，具体比赛可能按行、单元格、主键或不同分母评分，需要另外写插件。

## 编码与脱敏：2 个

| ID | 配置与端口 | 语义 |
| --- | --- | --- |
| `codec.fields` | fields、operation、encoding；valid/invalid | Base64/Hex/URL 编解码，MD5/SHA256/SHA512 摘要 |
| `text.mask` | fields、keep_start、keep_end、character；data | 保留前后指定字符，中间替换；短值全部遮盖 |

编解码严格按指定字符编码，非法 Base64、Hex、URL 字节解码等进入 invalid。若一行多个字段中有一个失败，整行保留原值，不留下前几个字段的半成品更新。摘要按字段原文本编码得到，不是文件哈希。摘要和遮盖均不宣称实现不可逆的匿名化；原值可能仍在 changes 或上游结果中，导出诊断时要理解这一点。

## 外部样例：另计 1 个

`example.add_prefix` 来自 plugins/add_prefix.py，给指定字段加前缀并记录变化。Web 默认自动加载；CLI 要通过流程 plugin_dirs 或 --plugin-dir 显式加载。它用于演示扩展接口，不算入 30 个内置节点。
