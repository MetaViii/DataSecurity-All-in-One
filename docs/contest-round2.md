# 浙江省赛与羊城杯：第二批完整原附件

2026-11-05记录。使用CTF-Archives公开Release中的完整原附件，不执行附件内代码。新增4条可在CLI/Web运行的流程，其中羊城杯data-analy1与之前广工复用题的数据相同，不计作一道新的独立题。另有3道原赛题完成了按公开规范生成提交和独立规则核对；尚未取得这3题的官方标准答案或在线评分结果，不能报告官方正确率。

## 找到了什么、实际跑到了哪一步

| 原题与原始资料 | 完整输入 | 当前结果 | 验证范围 |
| --- | --- | --- | --- |
| [羊城杯2024 data-analy1](https://github.com/CTF-Archives/2024-YCB-Undergraduate#data-analy1) | 10000行乱序CSV | 10000行唯一复原，保留原赛中文表头 | 10行原附示例逐格一致；完整数据在广工复用题的英文列名规范下得到其公布摘要 |
| [羊城杯2024 data-analy2](https://github.com/CTF-Archives/2024-YCB-Undergraduate#data-analy2) | 14183396字节PCAPNG | 提取8000条JSON请求，输出294条垃圾数据 | 完整原附件；独立的TCP正文与规则核对一致；没有官方正确率 |
| [浙江2024决赛 datasecurity_classify1](https://github.com/CTF-Archives/2024-zjsdxs-Finals) | 20000行单列CSV | 姓名6637、身份证6787、手机号6576，全部分类 | 直接扫描原CSV的独立校验一致，保留原行序；没有官方正确率 |
| [浙江2024决赛 datasecurity_classify2](https://github.com/CTF-Archives/2024-zjsdxs-Finals) | 24665684字节PCAPNG | 5231条请求正文，输出身份证1598、手机号1422、IP1201，共4221条 | 另一份正文与规则核对一致；没有官方正确率 |

data-analy2明确要求提交**垃圾数据**。本流程按互斥失败分支合并：格式202、身份证校验/性别59、生日不一致33，共294条；有效7706条。8千条请求全部成功解码并提取JSON，没有把解析失败记录填空后当作答案。

classify2先找到5320个候选，身份证2000、手机号1800、IP1520。校验后拒绝身份证402、手机号378、IP319。结果按请求出现顺序和字符位置输出，保留重复次数；流程没有擅自去重。所有拒绝项都另存带来源与原因的JSONL。

这里的“独立核对”是本项目自己的规则回归，不是赛事评分。测试里的小型PCAPNG读取器仅适用于这些固定Ethernet/IPv4/TCP附件，用不同的路径重组正文；实际节点调用TShark。两者结果一致能排查执行错误，不能证明我们对题目规则的解释等同官方实现。

## 正确率判分的实际来源

出题人的[ADCTF2025记录](https://astro.bili33.top/posts/Creating-Challenges-for-ADCTF2025/)解释了DAS File Checker允许达到某个正确率阈值后获flag，并公开了自己的[DSFileChecker](https://github.com/GamerNoTitle/DSFileChecker)。本次检查的版本为`3cba732fa7b3912e7a65a8ae0ef46b2ed8495167`。

其当前公开算法按完整记录的重复次数计算：

```text
正确率 = 正确行数 / (标准答案行数 + 多余行数)
```

“相同内容出现两次”不能只按集合计一次；多提交猜测结果会增加分母。错误行在该模式下会造成一条缺失、一条多余。这一数学口径与新节点`tables.score`的multiset模式相同。我们的节点使用字符串并显式配置去空白/大小写，未复制其Pandas类型推断或NA处理行为。

该开源评分器用于ADCTF，**不是已证实的羊城杯或浙江省赛官方评分器**。没有标准答案时，本工具可以统计校验通过/拒绝比例，不能把它叫作正确率，也不能从“95%数据通过格式检查”推出“官方得分95%”。

## 复现

当前工作区已下载附件：

```powershell
python scripts/contest_round2.py
python -m unittest tests.test_round2 -v
python scripts/verify_contest_web.py
```

新机器：

```powershell
python -m pip install -e ".[web,test,crypto]"
# 安装Wireshark，并把TShark所在目录加入PATH，之后重启服务
tshark --version
python scripts/contest_round2.py --fetch
```

--fetch下载4个固定Release压缩包，先验证SHA-256，再只提取指定CSV/PCAPNG/PDF。直接运行不访问网络。HTTP解析不需要Scapy、PyShark或管理员抓包权限；处理的是离线文件。

Web首页搜索“浙江2024”或“羊城杯2024”，打开流程。预览依旧处理完整输入，表格只分页显示；也可在任意结果分支点击“导出此分支”，下载完整UTF-8 CSV，不受搜索与分页影响。该下载没有按原题设置CRLF等提交参数，正式提交请使用流程中的输出节点。

## 文件与审计入口

- `scripts/contest_round2.py`：固定下载来源、附件哈希、流程生成与实际运行记录。未导入比赛解题脚本。
- `examples/ctf_real_ycb24_analysis.json`、`ctf_real_ycb24_traffic.json`：羊城杯原附件流程。
- `examples/ctf_real_zj24_classify1.json`、`ctf_real_zj24_classify2.json`：浙江决赛流程。
- `work/contest-round2/sources.json`：压缩包来源、SHA-256、实际提取文件的SHA-256和大小。
- `work/contest-round2/verification.json`：各节点完整行数、耗时、导出文件摘要与证据说明。
- `work/contest-round2/web-verification.json`：Web正式运行与完整下载核对结果，4条原附件流程的提交文件均与CLI逐字节一致。
- `work/contest-round2/results/<题目>/submission.csv`：正式生成的提交文件。
- `tests/test_round2.py`：原示例、原始CSV、独立正文扫描、CSV/XLSX纠错往返验证。

羊城杯data-analy1的`submission.csv`按原示例保留中文列名；`canonical-reference.csv`和`reuse-reference-flag.txt`仅用于与已公开的广工复用题核对。两种表头会改变文件摘要，因此复用题的flag不能充当羊城杯原题的在线判定。

本轮验证：90项Python测试、17项前端测试、TypeScript检查、生产构建和前端格式检查通过。原附件测试使用完整输入；Web校验还覆盖了纠错演练的正式运行和差异分支完整下载。页面实际操作确认了评分卡、分支计数、文档内部跳转和输出下载。`work/contest-round2/ui-score.png`记录的是自建6行纠错演练，图中的100%不是赛事得分。

## 新增通用能力与限制

`pcap.http`将明文HTTP重组交给本机TShark，以参数控制正文编码、执行超时和中间结果上限。默认UTF-8、120秒、128MiB；解码失败保留十六进制原文到invalid。禁用个人Wireshark配置，不执行shell，不接受任意命令行参数；取消或超限会终止子进程。只提取带正文的HTTP请求，不覆盖响应、TLS解密、所有协议或任意网络取证。

`text.find_all`把带分类标签的正则命中拆成多行，保留来源、记录位置及起止字符下标。下标从0起，结束位置不包含在范围内；按解码后的Unicode字符计数。可保留全部匹配，或优先选择较长的非重叠匹配。它不内置“身份证必然合法”等假设，后续连接校验节点。

两个原题的规则都使用随机地址码、虚构手机前缀，因此没有套用真实手机号前缀或非零身份证地址首位。classify2只删除规范列举的空格与连字符，不删除任意字符来“修好”数据。数字和IP候选显式检查边界，防止从更长数字或非法IP里截出一个看似合法的子串。

表格近似纠错、人工修订、逐格评分的参数和实现见[纠错与正确率](correction.md)。当前共56个节点；没有增加会擅自猜答案的全自动修复按钮。

## 仍未取得或未复现的题

- 浙江2025初赛dsEnData、决赛check1/shop：查到了参赛者[初赛WP](https://j1ya-22.github.io/2025/11/09/%E6%B5%99%E6%B1%9F%E7%9C%81%E8%B5%9B2025%E5%88%9D%E8%B5%9Bwp/)与[决赛WP](https://mak4r1.com/write-ups/2025%E6%B5%99%E6%B1%9F%E7%9C%81%E7%9C%81%E8%B5%9B%E5%86%B3%E8%B5%9Bwp/)，尚无可直接下载、能核验来源的完整原CSV，本次不计入实测。
- 羊城杯2025 dataIdSort与SM4-OFB：查到[参赛团队解法](https://ctf.njupt.edu.cn/archives/1178)，后者确实使用“个人信息表.xlsx”。未取得完整原TXT/XLSX，本次没有把自造XLSX样本当作原题。
- 浙江2024初赛ds-encode：公开附件为MySQL数据目录，需要数据库恢复步骤，本批没有运行。ds-enen是VHD磁盘附件，同样没有当作CSV纠错题计数。

这次找到的、能公开下载完整附件的题，主要是复原/清洗/分类。尚未确认有一份来自上述赛事、带可用标准答案和官方评分器的“逐格CSV/XLSX纠错题”可完整离线判分；后续应继续以这类附件补覆盖，而不是扩大已解题数量。
