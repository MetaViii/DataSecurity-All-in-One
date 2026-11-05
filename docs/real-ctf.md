# 三道公开原题的完整附件实测

本页记录0.4首次实测，下面的测试数量为当时记录。0.5新增的浙江/羊城杯原附件、验证范围与仍缺少的XLSX题见[第二批实测](contest-round2.md)。

这次使用实际比赛的公开附件，未替换、抽样或重生成数据。通过本项目的 Pipeline 和通用节点独立计算，三题结果均与出题人公布的 flag 相同。没有访问已结束比赛的在线评分平台，因此证据等级是“完整原附件 + 公开预期答案一致”，不是“在线提交判定通过”。

## 来源和结果

三题来自广工2025“网安卫士”出题人仓库。作者说明 Data Analysis 和 Data from Log 采用了2024羊城杯数据；本次使用的是以下公开仓库版本，不能据此声称运行了羊城杯原评分平台。[出题记录](https://bili33.top/posts/The-First-Experience-of-Making-CTF-Challenges/)

| 题目与原始来源 | 完整输入规模 | 本工具结果 | 与公布 flag |
| --- | --- | --- | --- |
| [Data Analysis](https://github.com/GDUTMeow-Challenges/Challenge-Data-Analysis) | person_data.csv，10000行 | 每行恢复8列，10000行唯一分配，歧义0行 | 一致 |
| [Data Cleaning](https://github.com/GDUTMeow-Challenges/Challenge-DataCleaning) | polluted.csv，2000行，2000个RSA公钥 | 找出100个异常编号：格式53、身份证27、验签20，三分支互斥合并 | 一致 |
| [Data from Log](https://github.com/GDUTMeow-Challenges/Challenge-Data-from-Log) | error.log，34262307字节、204076行 | 合并出4433组请求；按公开参考解答口径保留并脱敏2000行 | 一致 |

最终计算结果：

```text
Data Analysis  flag{518a8b1f87c23d94c1be372efd0f0f30}
Data Cleaning  flag{93767ebcb98095b0cd05b04d9b42e845}
Data from Log  flag{de95bf79eace2722b90fbecc35cab2ed}
```

预期值只用于验证脚本的最后比较，不参与处理节点、筛选条件或数据复原。未导入或执行仓库里的 solve.py、detect.py、generate.py；原题脚本仅作规则核对。

## 现在重跑

当前工作区已经下载原附件，直接执行：

```powershell
python scripts/real_ctf.py
python -m unittest tests.test_real_ctf -v
```

新机器先安装依赖、下载固定版本附件：

```powershell
python -m pip install -e ".[web,test,crypto]"
python scripts/real_ctf.py --fetch
```

--fetch 会下载三份公开压缩包，校验固定SHA-256，只提取CSV、日志、说明和公钥，不执行附件中的代码。不加 --fetch 时不访问网络。附件放在 work 中，不随项目源码重新分发。

CLI单题流程同样可独立运行：

```powershell
python -m datasecurity run examples/ctf_real_analysis.json
python -m datasecurity run examples/ctf_real_cleaning.json
python -m datasecurity run examples/ctf_real_log.json
```

Web重启服务后，在首页搜索“真实题”，打开相应流程，先预览节点，再运行全部。多行日志、公钥路径、序列化方式等都由节点参数控制，不是前端隐藏的专题脚本。

## 产物与证据

- work/real-ctf/input/：完整原附件，analysis / cleaning / log。
- work/real-ctf/sources.json：仓库、固定版本、下载URL、压缩包与所提取文件的SHA-256。
- work/real-ctf/verification.json：三题预期值、实际值、是否一致、耗时和各节点端口行数。
- work/real-ctf/web-verification.json：通过模板加载、Web正式运行、下载接口取得的flag及导出文件信息。
- work/real-ctf/results/analysis/submission.csv：复原后的10000行答案。
- work/real-ctf/results/cleaning/flag.txt：按100个异常编号计算的结果。
- work/real-ctf/results/log/submission.csv：2000行脱敏答案。
- examples/ctf_real_*.json：可阅读、修改和在CLI/Web执行的流程。

本机已通过71项Python测试（包含完整原附件回归）、14项前端测试及前端生产构建、格式检查。另用FastAPI TestClient逐题加载Web模板、正式运行、下载flag；Analysis和Log还校验下载CSV的MD5等于公布摘要。Web接口校验不等同逐项人工操作浏览器，也不等同比赛在线判分。

固定版本：

```text
Analysis  7fa5eaa86687769074ee261b9467dabee29f0078
Cleaning  9b7c093568c7f09f66eec548dd8c5719dc867315
Log       f4a3d564dbb1c46a84f227e2dd34bc0f2272ebc4 + attachment Release
```

## 实测发现的三处规则差异

### 1. 换行会改变最终答案

Analysis和Log的说明要求LF，但公布脚本使用csv.writer默认CRLF。实际对比确认两题公开flag对应CRLF、每条记录一个换行、无额外尾部空行。流程明确设置line_ending=crlf，绝不让操作系统决定。换成LF时Analysis会得到150042efebe8961e8b0b8f929def8204，不能与公布答案混称。

table.serialize先生成可检查的精确文本；同一内容分别送入text.write的raw模式和codec.fields摘要节点。因此导出内容与参与摘要的内容一致，不是再运行一份独立写文件脚本。

### 2. 身份证严格规则不能替代赛题规则

Cleaning的147和379号记录顺序码为000。默认严格校验会把它们额外拒绝，得到102条异常，无法匹配参考答案。原题验算只做格式、校验和与性别对照，因此本题配置显式关闭日期、非零地址码首位、非000顺序码检查；默认节点行为仍保持严格。

这不是修复身份证或把异常行放行来凑数量，而是按公开校验代码匹配其规则。是否采用严格模式由具体题目决定。

### 3. 日志题密码规则与参考解答不一致

题面说密码仅字母数字；实际原附件第185931行开始的请求恢复出密码a_jingke，公开参考结果仍保留这一行。原参考脚本未检查密码字符集。本工具提供两条明确的流程：

- ctf_real_log.json：公开参考解答口径，密码必填但不限制字符集，2000行，得到公布flag。
- ctf_real_log_strict.json：严格执行字母数字密码规则，1999行，得到flag{7558fbfa35dca8de48fe793f13f11419}，不声称它匹配公布答案。

两条流程的唯一业务差异是这一条密码校验，测试固定检查它们的行数与结果。报告不把“符合题面”和“符合参考解答”当成同一件事。

## 为原题补了哪些通用能力

columns.realign：按完整正则做一对一列分配，有唯一答案才写入valid。无解、多解和搜索超限行保留原值进入invalid。不同位置的相同值互换不算不同答案；默认最多20列、每行10000个搜索状态。规则列序决定输出列序。

text.records：流式读取日志，用起始正则划分多行记录，保留起始行号。开头未分组的128行留在unmatched，未伪装成用户数据。默认每组最多1000000字符；它依赖日志记录连续出现，不是通用并发HTTP/TCP重组器。

validate.signature：按行公钥路径模板验证RSA签名，支持PKCS1v15/PSS与SHA256/384/512、Base64/hex。用cryptography完成密码学运算，本项目不自行实现RSA。公钥路径必须遵守Web工作区约束。缺文件、错误公钥、坏签名均保留原因。需要可选crypto依赖。[库的验签接口](https://cryptography.io/en/latest/hazmat/primitives/asymmetric/rsa/#verification)

rows.collect：按当前行序把一列拼为单个值，不隐含排序或去重。Cleaning先数值排序异常编号，再用下划线拼接后求MD5。

table.serialize：按当前行序、字段序生成CSV或文本，显式配置表头、换行和额外尾部空行。输出为一行一列“提交内容”，便于预览和求摘要。汇总内容不复制全量单元格历史；原记录证据保留在上游表中。

text.extract增加occurrence=last；text.write增加raw=true，仅允许单行单列且无表头，不附加任何换行。原配置默认行为不变。

## 对工具能力的实际结论

现在已验证三类完整数据题：字段错位复原、签名完整性校验、连续日志恢复与脱敏。三题都通过组合通用节点执行，结果可重跑、可追到来源、可导出。未验证PCAP并发重组、任意SQL方言恢复、机器学习类判分和大规模流式图执行；这些仍需要真实附件驱动补充。
