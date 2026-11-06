# 从界面点击到文件导出：代码导读

当前0.7共有56个节点，包含界面插件管理、小样本演练、多条完整原附件流程、[独立Python脚本导出](python-export.md)和[正则助手](regex-assistant.md)。第一次使用先读 [解题工作流](workbench-guide.md)，源码的对照说明见 [新增节点](advanced-nodes.md)、[插件管理](plugin-manager.md)、[原题实测](real-ctf.md)、[浙江/羊城杯实测](contest-round2.md)与[纠错和评分](correction.md)。

Web 界面的排版、工作区首页、中文显示层及状态管理调整补充在 ui-notes.md；核心执行流程沿用本文的约定。

这份文档按当前源码解释实现，适合一边打开文件一边审计。先理解最小数据模型，再追一次请求，最后挑一个节点看算法。不要一开始逐行读 App.tsx 的所有按钮。

## 1. 目录地图

```text
datasecurity/
  __main__.py                 python -m datasecurity 入口
  cli.py                      plugins / validate / run / serve / export-python
  exporter.py                 校验流程、收集依赖源码、生成独立脚本
  _export_runtime.py          附加到exp.py中的标准库运行入口
  core/
    models.py                 Origin / Issue / Change / Record / Table
    plugin.py                 Parameter / PluginSpec / Plugin / RunContext
    registry.py               插件登记与本地发现
    pipeline.py               配置检查、拓扑顺序、执行、RunResult
    errors.py                 配置错误和带节点信息的执行错误
  builtin/
    __init__.py               56 个内置节点的登记清单
    csv_io.py                 CSV 读写
    file_inputs.py            JSON/JSONL、文本、XLSX 读取
    json_output.py            JSON/JSONL 写出
    excel_output.py           XLSX 文本写出
    fields.py                 字段结构和文本变换
    filter_rows.py            条件构造与筛选
    rows.py                   去重、排序、抽取、追加
    validation.py             组合校验和分类
    regex_check.py            简单正则校验
    expression.py             AST 表达式解释器与计算节点
    datetime_fields.py        日期处理
    tables.py                 关联、聚合、答案比较
    codec.py                  编解码、摘要、脱敏
    advanced.py               映射、回填、序号、展开、JSON、数值、模板
    security.py               身份证、Luhn、XOR、纯文本导出
    analysis.py               质量概览、参考表校正、标准差、时间窗口
    contest.py                列复原、多行记录、RSA验签、行拼接、提交序列化
    correction.py             字典候选、带原值检查的人工清单、逐格评分
    extraction.py             TShark读取HTTP、带位置的全部正则匹配
    _utils.py / _files.py     内部共用函数，不是公共插件接口
  web/
    app.py                    HTTP 路由、会话保护、静态前端
    workspace.py              附件、模板、项目、插件管理
    jobs.py                   异步任务、结果生命周期、分页
    plugin_manager.py         可信插件源码安装与启停
    regex_assistant.py        正则模板、规则组合和受限测试进程
    _regex_worker.py          标准库re单次测试，不参与正式数据处理
frontend/
  src/
    main.tsx                  挂载 React，安装 ReactFlowProvider
    App.tsx                   流程/选中项/项目/任务的页面状态和操作
    types.ts                  前后端通信与画布类型
    model.js                  流程 JSON 与画布转换、环检查、布局
    api.ts                    fetch、会话 token、上传、JSON/源码下载
    components/
      Library.tsx             模块库、文件列表
      PluginNode.tsx          画布节点卡片与命名端口
      Inspector.tsx           节点信息、输入连接、参数
      Fields.tsx              通用参数与复杂规则编辑器
      Results.tsx             预览表格、分页、记录、导出
      Dialogs.tsx             项目、JSON、追踪和文档弹窗
      PythonExport.tsx        独立脚本预览、附件清单与下载
      RegexInput.tsx          正则输入旁入口，按需载入助手
      RegexAssistant.tsx      模板、规则组合、样例测试与确认回填
    styles.css                本地工作台布局与响应式样式
  tests/model.test.mjs         不依赖浏览器的流程契约测试
plugins/add_prefix.py          外部插件最小样例
examples/                     基础模板、小样本演练、原题流程、外部插件样例
scripts/real_ctf.py            获取固定版本公开附件、组合通用节点、核对公布答案
scripts/contest_round2.py      浙江/羊城杯原附件下载、流程与证据记录
scripts/verify_python_export.py 独立脚本与原题完整输出的逐字节核对
tests/                        内核、节点、HTTP 集成测试
work/                         运行数据，不作为源码提交
```

`model.js` 故意保持无 React/DOM 依赖，用 Node 自带测试器就能验证流程转换。其余前端组件使用 TypeScript。项目没有 ORM、数据库或通用任务调度框架，小文件和一个线程已足够支撑当前单机版本。

## 2. 先看 5 个对象

打开 core/models.py。Table 表示一张表，Record 表示一行。`Table.from_rows` 适合测试；构造 Table 时会检查表头和每条记录字段是否一致。Record 构造时复制 values 并冻结映射，避免一路处理把另一路的原值改了。

例如 `0001,测试甲` 读取后，编号是字符串 `"0001"`，不是数字 1。来源记录记录原文件和位置。执行 strip 后返回新 Record；旧对象仍然存在，changes 追加一条实际改变。筛选只重新组合记录，不伪造新的原始行号。

再打开 core/plugin.py：Parameter 是参数定义，PluginSpec 是节点说明，Plugin 是算法接口，RunContext 是一次执行共享的上下文。prepare_config 补默认值、拒绝未知键、严格检查类型，再调用插件的 check_config。前端表单只是辅助，真正的约束在这里和算法内部。

## 3. 服务启动做什么

`python -m datasecurity serve` 进入 __main__ → cli.main → create_app → uvicorn。服务固定绑定 127.0.0.1，不是 0.0.0.0。

create_app 创建 Workspace。Workspace 建立 work/uploads、projects、exports，注册内置插件，再导入可信 plugins/*.py。然后创建 JobManager 的单线程池和本次服务的随机会话 token。`frontend/dist` 由同一个服务提供，因此正式使用不必单独启动 Node 服务。

入口页面执行 main.tsx，再进入 App.initialize：

1. GET /api/bootstrap，取得插件描述、文件信息、模板、已存项目和 token。
2. api.ts 保存 token，仅后续写请求携带。
3. 尝试恢复以工作区路径为键的 localStorage 草稿；没有草稿则打开第一个示例。
4. loadDefinition 规范化导入路径，graphOf 把 nodes.inputs 拆成画布 edges，恢复 ui 位置/标签。
5. Library 用插件描述生成模块列表，Inspector 用 Parameter 元数据生成表单。

bootstrap 没有把附件全内容发到浏览器，只快速读取表头等元数据。CSV 的 UTF-8/GBK 检测只用于列表提示，不是全面的编码识别器；正式读取仍以输入节点 encoding 为准。

## 4. 改参数和连线时发生什么

在 Inspector 改字段，调用 App.setConfig：记录撤销快照 → 标记未保存 → 仅替换对应节点的 config。Fields 中复杂规则控件只是生成列表/字典；切换 JSON 编辑仍是改同一份 config。

拖动端口触发 App.connect。model.canConnect 检查端口是否存在、自连接，以及从目标能否走回来源；能走回就会成环。建立连接时替换同一目标输入端口的旧连接。右侧输入下拉也是调用同一个逻辑，因此两种连接方式一致。

definitionOf 把当前画布转换成核心执行 JSON：每条 edge 写成目标节点 inputs 的一个键值。坐标和显示名放 ui，和算法参数分开。executionKey 只计算 version/nodes，用它判断已有结果是否对应当前配置；只移动节点或改显示名称，不会要求重新计算。

## 5. 点“预览所选”的完整调用链

```text
App.beginRun(true, selectedID)
  → api POST /api/runs
  → app.start_run
  → jobs.start
      → Pipeline.scope：目标+祖先
      → JobManager.prepare：限制插件目录，规范化输出位置
      → Pipeline.plan：先验检查并得到顺序
      → 创建 Job，提交线程池，立即返回 queued/running
  → App 记录 jobID，每 400ms GET 状态

后台线程 _execute
  → Pipeline.run
      → 共享 RunContext
      → 循环 Step
          → 从 result.tables[上游][输出端口] 取得输入
          → plugin.run(inputs, preparedConfig, context)
          → 检查返回端口和 Table 类型
          → 保存表、数量、耗时，触发回调
      → 预览直接跳过所有 output.run
  → Job 持有 RunResult，状态变 success

Results
  → GET /api/runs/{id}/table?node=...&port=...&page=1
  → 后端搜索、分页，返回这一页的 values/来源/问题/变化
  → 表格展示；点击行打开 RecordDialog
```

线程池的“异步”是指不阻塞 HTTP 等待整条任务，不是每个节点同时运行。任务内部按拓扑顺序串行计算。一次运行用同一份 Registry 快照；中途重新加载插件不会改变正在执行的算法。

错误分两类：plan 发现配置错误，API 直接返回错误，任务不会排队；run 发现附件/字段/算法错误，ExecutionError 带节点 ID、插件 ID 和已完成的结果。页面会选中错误节点，还能查看已经成功的上游表。

取消请求设置 Event；内核在节点前后检查，内置循环也定期检查。某次库调用执行期间不能强制中断。不要把这个线程当作恶意插件隔离设施。

## 6. 用通用示例手工核对数据

打开 examples/generic_cleaning.json 和 examples/data/orders.csv。全部输入是虚构数据，编号保留 0001 等字符串。

1. read 得到 6 条，不做类型推断。
2. clean 对姓名、部门、金额执行 strip，真实发生的改变进入 changes。
3. validate 同时检查编号必填与金额可解析，4 条 valid、2 条 invalid。错误值保持原样，问题写 issues。
4. calculate 对 4 条有效行求 round([金额] * 1.06, 2)，新增含税金额。Decimal 的 0.1 不先经过二进制浮点数。
5. deduplicate 按编号保留最后一条：编号 0002 的 25.00 留下，20.00 进入 duplicates。此时 unique 3 条、duplicates 1 条。
6. sort 按金额数值降序排列，0001 → 0002 → 0005。
7. aggregate 按部门：研发数量 2、含税合计 106.22；运营数量 1、含税合计 26.5。
8. output 最后才写 clean.xlsx、invalid.jsonl、duplicates.csv、summary.csv。Web 各次运行独立目录；CLI 示例覆盖 work/generic 下同名演示结果。

`26.5` 没有强制写成 `26.50`，因为当前 text(Decimal) 去除无意义零；这属于输出格式选择，不是丢失数值精度。若题目要求固定两位，后续可以单独做“数值格式化”插件。

## 7. 正式运行与原子输出

“运行全部”不传 target，preview=false。所有节点必须有效。plan 把 output 节点排到所有输入/处理完成之后，减少中途处理出错留下导出的情况。

以 csv.write 为例：先 context.output_path 检查冲突 → 在目标目录创建临时文件 → 写表头和全部记录 → 关闭并替换目标 → 清理临时文件。XLSX 还预先检查行列数和单元格长度，避免库静默截断。JSONL 一条记录一行。

Web 的输出文件名会统一重写到 work/exports/运行ID，前端拿到 artifact URL 后才显示下载链接。这里的原子性针对单个文件，不是整个流程；多文件统一回滚需要另外设计事务，不要从一个 os.replace 推导出“全流程事务”。

## 8. 项目保存与任务结果不是一回事

保存调用 POST /api/projects，内容包括 name/definition，更新已有项目还传 id/revision。Workspace 在锁内检查修订号并原子写 JSON；其他窗口抢先保存时拒绝旧版本，避免无声覆盖。保存允许未完成的画布。

运行结果是内存中的 Table，项目文件不包含它。服务重启后项目和导出文件仍在，运行记录消失。新任务会释放较早的内存结果。浏览器草稿保存当前编辑状态，不能当作附件备份或运行历史库。

## 9. 一个新插件如何从磁盘出现在页面

```text
plugins/my_check.py 的 PLUGINS
  → Registry.discover / register
  → registry.describe / spec.describe
  → /api/bootstrap 或 /api/plugins/reload
  → App.plugins
  → Library 列表
  → addPlugin + defaultsFor
  → PluginNode 卡片 + Inspector 自动参数
  → definitionOf 保存 plugin ID 和 config
  → Pipeline 从 Registry 找同一插件并执行
```

你通常只需要改自己的插件文件。没有专用 widget 的复杂参数用 JSON 编辑器兜底。插件代码示例和身份证插件拆分方法见 plugin-development.md。

## 10. 推荐的审计顺序

第一轮只追不变量：models 的不可变性和字段一致性；plugin 的参数检查；pipeline 的命名输入、拓扑排序、预览和输出延迟。对照 test_framework.py 看每项保证的可执行例子。

第二轮选一条具体数据：generic_cleaning 的 0002，观察清理、计算、重复分流和来源如何传递；对照 test_nodes.py，检查重复次数、精确小数和关联展开语义。

第三轮看 Web 边界：输入路径约束、上传文件名、输出重写、token/Origin、项目修订号、任务保留与取消。对照 test_web.py 查看真实 HTTP 请求，不要只根据界面上的提示判断约束成立。

最后读前端：model.js → api.ts → App 的 beginRun/poll → Results，再看表单和样式。App 目前集中管理页面状态，规模继续增长时可拆 useWorkflow/useJobs/useProjects；现在不引入全局状态库是为了减少追踪跳转。

建议自己做三个小练习：给 add_prefix 增加是否跳过空字符串；写一个 Luhn 校验插件；写固定小数位格式化节点。每次只新增一个能力，配一条最短样例和必要测试，先不要改执行器。
