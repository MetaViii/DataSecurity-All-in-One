# 把一份附件变成可审计的答案

建议先看本页掌握使用顺序，再读 `code-tour.md` 理解调用链。新节点实现和边界在 `advanced-nodes.md`，四条可运行演练在 `ctf-recipes.md`。

## 一次解题的顺序

先读题目，把输入格式、行ID、错误类型、可信冗余信息、提交格式、评分阈值单独记下。不要一上来对全部列转数字或删除异常行。

导入文件后建立输入节点，预览检查表头、编码、前导零和行数。接 profile.summary 看空值与高频值，判断问题是少量枚举错写、整列格式混乱、重复记录，还是关联关系错误。

接清洗节点，只做有依据的转换。例如题目说明电话允许空格才移除空格；姓名不要随意去掉全部空白。用 values.map 处理明确枚举，用 tables.lookup 接可信字典修复。没有依据的未命中记录单独分流。

校验放在修复前后都可以：先校验发现问题，修复后再校验确认。身份证校验通过不代表真实身份；金额可解析也不代表业务合理。分支结果要预览，尤其留意空键、重复键、数值异常和日期边界。

最后选择字段与顺序，按题目要求导出CSV/XLSX/JSONL或纯文本。确认编码、换行、表头、分隔符。若有参考答案，使用明确口径比较；保存流程JSON与结果方便复查。

## 沿一个节点读源码

以 validate.identity 为例，实现在 `datasecurity/builtin/security.py`：

1. spec 给节点ID、中文说明、data输入和valid/invalid输出。
2. parameters 决定配置字段，前端据此画控件；这些名称也写进流程JSON。
3. prepare_config 在基类中检查类型、默认值和choices，再调 check_config 检查白名单等业务约束。
4. run 要求输入字段存在，逐行读原始字符串，检查格式和一致性。
5. 正常记录直接复用；异常记录通过 with_issue 添加原因，原值不变。
6. 两个分支返回相同schema的Table，后面的节点可以各自继续处理。

这里没有前端独有的身份证算法。前端只传配置给后端；CLI和网页使用同一插件，测试也直接调用同一实现。

## 一次点击经过哪些文件

`frontend/src/App.tsx` 从画布生成definition，通过 `api.ts` POST `/api/runs`。后端 `web/app.py` 校验请求，`jobs.py` 用工作区路径准备任务，并交给串行线程执行。

`core/pipeline.py` 检查图、参数和命名端口，拓扑排序，按依赖运行。每个插件拿到 inputs/config/RunContext。core/models.py 的不可变Record/Table保证两个分支不会意外互改；changes、issues、origins记录可追查的证据。

运行完成后，前端轮询状态，通过 table接口分页展示结果。Results组件只限制展示数量，不限制计算输入量。点击正式运行才执行output节点；预览会跳过全部文件输出。

修改插件后先热加载，再重新运行。已有结果是旧代码算出来的，因此管理插件后会提示重新计算。服务重启会释放内存结果，磁盘项目和导出仍保留。

## 审计代码的建议顺序

先读 `core/models.py`、`core/plugin.py`，搞清楚数据与协议；再看 `builtin/advanced.py` 的 MapValues，它是最短的“校验配置→读表→逐行→留trace→返回分支”样例。

接着读 `builtin/security.py` 的 IdentityCheck/XorFields，注意错误行整行保留的做法。读 `builtin/analysis.py` 看唯一键索引、窗口排序和统计口径。最后回到pipeline和web/jobs，理解节点怎样组合及为什么任务期间不能换插件。

前端阅读顺序是 types → model.js → Library → Inspector/Fields → Results → App。插件管理单独看 PluginManager.tsx 与 plugin-manager.js。App负责协调状态，核心处理规则留在Python，便于你逐个替换插件而不同时改两种语言。

测试不是把每行实现再写一次。`test_advanced_nodes.py` 检查精度、异常保留、来源、不重复键、窗口端点和同时刻；`test_ctf_recipes.py` 对照独立预期文件验证整条链及提交字节；`test_plugin_manager.py` 检查安装失败和任务互斥。

## 练习：亲手加一个插件

打开插件管理，选“校验与分流”模板，改成检查工号：长度6、ASCII数字、不能以0开头。保留valid/invalid两分支；失败信息分别说明长度、字符或首位问题。把ID改为local.employee_id。

用000001、123456、12345、１２３４５６、空字符串五个输入，预期只有123456通过。先自己写这五条预期，再写实现。用Record.with_issue，不直接改record.values。安装后连在CSV输入后，预览invalid并打开追踪。这个练习完成后，再做需要第二张字典表的插件。

## 当前覆盖范围

56个节点支持表格读写、规则清洗、校验分流、字典精确/近似纠错、人工修订、关联统计、逐格评分、部分编码还原、错位列复原、连续日志恢复和RSA验签。pcap.http可通过本机TShark读取明文HTTP请求正文。证据见 [首次实测](real-ctf.md)和[浙江/羊城杯实测](contest-round2.md)，纠错参数见 [专门说明](correction.md)。SQL dump、非HTTP协议恢复、TLS解密、数据库在线操作、通用自动推断、多进程大数据执行仍未包含。

All-in-One的长期方向是让这些能力在同一个可追踪流程里组合。本版本给出可运行骨架、通用节点和验证样例；具体比赛规则仍需要人审题、配置与检查。
