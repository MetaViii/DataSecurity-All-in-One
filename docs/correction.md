# 纠错、人工复核与正确率

0.5新增`tables.fuzzy_lookup`、`table.patch`、`tables.score`，实现集中在`datasecurity/builtin/correction.py`。它们分别负责提出字典候选、应用人工决定、根据独立答案计算结果。评分用的标准答案不接入纠错节点；有权威字典时才把它接入reference端口。

## 先跑通一个完整例子

首页搜索“字典纠错”，打开“演练：字典纠错、人工复核与评分”，也可以运行：

```powershell
python -m datasecurity run examples/ctf_correction.json
```

这是本项目自造的6行教学样本。CSV把编号`0001`等始终读成字符串。两处单字错误有唯一最优字典候选，另外三行分别是并列候选、空值和没有候选，需要人工核对。人工清单已提供，便于完整审计：

```text
dirty ───────────────→ before（对比独立标准答案）
  └→ fuzzy ← dictionary
       ├→ review / suggestions（需要人工查看）
       └→ data → patch ← patches
                    ├→ rejected
                    └→ data → score ← expected
                              └→ xlsx.write
```

原始1/6行正确；应用两个唯一候选后为3/6行；清单再修订3行，最终6/6行正确。这里评分只选择“部门”列，因此行正确率和单元格正确率相同。导出的`work/correction/corrected.xlsx`再次读回后，字段与值保持一致，包括前导零编号。这是CSV/XLSX工程验证，不是某道原赛题100%通过的证据。

## 字典近似纠错：tables.fuzzy_lookup

输入data为待处理表，reference为标准字典；配置field和reference_field。用Unicode字符的Levenshtein编辑距离，不调用网络或模型。例如“运惟部”到“运维部”的距离为1。

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| group_by | 空 | 两表同名字段精确分组后再找候选，例如按城市限定街道字典 |
| max_distance | 1 | 最多允许多少次字符插入、删除或替换，范围0到10 |
| top | 5 | 每行最多显示的候选数量；不会影响最优候选的完整判定 |
| apply | false | 默认只建议；开启后仅应用唯一最优候选 |
| strip | true | 匹配时去掉首尾空白 |
| normalization | none | 可显式选择NFC/NFKC，原表不因此被直接修改 |
| ignore_case | false | 是否在匹配时忽略大小写 |
| max_candidates | 5000 | 每个分组最多多少个不同标准值 |
| max_comparisons | 1000000 | 整次执行最多多少次距离比较，超限明确失败 |

data始终保留原表全部行；review是其中需要复核的旁路子集，**不能再与data追加合并**，否则会制造重复。suggestions给出记录位置、分组、原值、候选值、距离与是否唯一最优。位置从1开始，指当前输入表的行位置，并非永久标识；正式人工清单应使用稳定唯一键。

空值不提供足够证据，不自动填成任何字典项。并列最优即使显示top=1也不会自动应用；规范化后不同标准字符串并列也会拒绝。参考字典中完全相同的标准值可合并；参考值为空报错。匹配字段最长256字符，大字典应先分组。编辑距离只是候选排序依据，不是正确概率；唯一最优也需要你确认字典覆盖了题目允许值。

## 人工修订：table.patch

data接原表或fuzzy:data，patches接人工审核后的CSV/XLSX。默认清单如下：

```csv
编号,字段,原值,新值,理由
0004,部门,人仕部,人事部,根据原始材料确认
```

keys配置为`["编号"]`。字段、原值、新值、理由这几列的名称可用field_column、before_column、after_column、reason_column修改；reason_column留空表示不读取理由列。

执行先检查data的关联键唯一且非空，再按键收集清单。同一行的全部修订作为一个整体：字段不存在、试图改关联键、重复修改同一字段、任意原值不一致，都会拒绝这一行的所有修订。找不到键也拒绝。拒绝项完整保留在rejected，data中的该行不变；其他有效行仍可修改。新值可以是空字符串，`0001`与`1`是不同的键。

每次修改通过Record.with_updates记录原值、新值、节点和理由，并合并修订清单的来源。上游诊断属于历史记录，应用清单后仍可追查；最终状态应再接规则校验或独立答案评分，而不是依据历史问题条数判断。

## 本地评分：tables.score

answer接独立标准答案，candidate接待提交表。没有答案就不能计算正确率。它不对未知数据推断真值，也不生成赛事flag。

| mode | 对齐方法 | 适合的任务 |
| --- | --- | --- |
| multiset | 按完整记录及重复次数，不要求唯一键 | 分类/清洗结果，顺序无关且多提交应扣分 |
| keyed | 按keys中的唯一键对齐；键精确匹配 | CSV/XLSX逐格纠错，行顺序可能不同 |
| position | 按当前行位置对齐 | 题目明确保证行序、没有稳定键 |

metric为row或cell，决定阈值判断的指标。multiset没有合理的错误行配对，只能使用row；keyed和position支持逐格统计。fields指定评分字段，keyed默认排除键；空配置要求两表列集合一致。首尾空白、大小写默认都参与比较，只有显式打开strip、ignore_case才忽略，原表不变。

三种模式都把额外行加入分母：

```text
整行正确率 = 全部评分字段正确的行数 / (标准行数 + 多余行数)
单元格正确率 = 正确单元格数 / ((标准行数 + 多余行数) × 评分字段数)
```

multiset中的错误行是缺失+多余；按键或位置对齐后，匹配行里的错误格不会再当作一条多余行。空标准答案与空提交得1；空答案与非空提交得0。keyed发现重复或空键会报错，不会选第一行或做笛卡尔展开。

threshold默认`"0.95"`，使用包含等号的判断。后台以整数分数和十进制阈值的精确分数比较，避免显示四舍五入造成“看起来95%就算达标”。前端显示“本地阈值”，采用后台结论；悬停正确率能看到更完整的数值。

输出summary、differences、fields、missing、extra。differences中的定位为JSON键值数组或从1开始的行位置，同时保留标准值、提交值与状态，以及两侧来源；fields展示逐列正确率。汇总行不伪造一个来源记录。multiset不报告逐格正确率，fields为空表。

这些是可配置的本地指标，不保证与任意比赛相同。有的比赛按主键只取首次提交、有的忽略重复或有不同分母，必须按题面或可核验评分器配置。公开评分器来源和原题证据见[第二批实测](contest-round2.md)。

## 从前端追到实现

1. builtin/__init__.py登记新节点；PluginSpec输出参数元数据，前端不需要逐个硬编码节点执行。
2. Fields.tsx为text.find_all新增标签、正则、捕获组编辑器；其余普通参数继续使用通用控件。可切换JSON审计精确配置。
3. Pipeline执行后将不可变Table留在运行结果中。Results.tsx选summary端口时通过ScoreSummary.tsx展示评分卡；计算仍在Python节点完成。
4. “导出此分支”请求`GET /api/runs/{id}/table.csv`。JobManager.result_table解析命名端口，再流式导出完整表；不复算节点、不写工作区文件、不限于预览页，也不应用当前搜索。
5. tests/test_correction.py覆盖重复键、并列候选、过期原值、整行拒绝与阈值边界；tests/test_round2.py覆盖原附件与XLSX回读；Web测试检查601行下载以及CSV引号、中文、内嵌换行和前导零。

已有tables.lookup适合按权威编号精确替换多字段；有可靠对应关系时先用它。近似候选适用于字典值中的文字错误，不应用来猜身份证中丢失的数字或恢复Excel已丢失的数值精度。
