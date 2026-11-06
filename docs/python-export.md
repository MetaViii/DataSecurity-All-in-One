# 把流程导出为独立 exp.py

0.6新增。用于把网页里已经配置好的解题流程交给队友复现，或与WP一起发布。导出的是一个包含处理源码的Python文件，不需要安装DataSecurity，也不需要启动网页或FastAPI。

## 网页怎么用

1. 配好完整流程，最好先运行并检查导出的答案。
2. 在流程编辑器工具栏点击“导出 Python”。不必先保存项目，导出使用当前画布的配置。
3. 查看步骤预览、输入附件清单和依赖，点击“下载 exp.py”。勾选“显示内嵌处理源码”可审计整个文件。
4. 准备同一份附件，在终端运行脚本。输入输出目录的默认值都不依赖打开终端的位置：相对输入以脚本目录为准，结果默认在脚本旁的output目录。

```powershell
python exp.py --base-dir "E:\我的附件" --output-dir output
```

`--base-dir`指向原工作区根目录时，可以直接沿用Web流程的`work/uploads/...`等相对输入路径。分享给别人时，可复制相同目录结构，也可覆盖每一个输入路径：

```powershell
python exp.py --input "read.path=data.csv" --output-dir result
# 多个输入可以重复指定；公钥路径模板也属于输入
python exp.py --input "read.path=polluted.csv" --input "verify.key_path=cert/{序号}.pem"
```

`节点.参数`以导出窗口的附件清单为准。未知键、空路径或重复指定同一键会明确报错。编号可能是画布生成的`n_...`，可以在脚本的INPUT_FILES中查看。

## 脚本里有什么

从前往后读：

| 部分 | 内容 |
| --- | --- |
| 文件头 | 原流程名称、生成工具版本、用法、第三方依赖和外部程序要求 |
| `CONFIG` | 每个节点的完整参数，包含默认值；正则、编码、换行、列顺序均保留 |
| `INPUT_FILES` / `OUTPUT_FILES` | 附件或路径模板、导出文件名 |
| `PLUGIN_REFS` / `PLUGIN_VERSIONS` | 实际用到的节点类及其版本 |
| `solve()` | 按执行依赖排列的逐节点调用、节点名称注释和命名端口连接 |
| `SOURCES` | 所用节点模块及项目内依赖的完整源码，主要以可读的多行字符串保存 |
| 运行入口 | 内存模块加载、参数检查、步骤结果检查、命令行和运行摘要 |

例如手机号校验流程的solve会依次读取CSV、执行完整正则匹配、将valid/invalid分别送给输出节点。流程的连线变为显式Python调用，不需要额外的流程JSON。源模块仍保留原来的类、辅助函数和注释；模块中的其他类可能一并内嵌，未使用的节点不会执行。源码同时包含两种三引号等特殊情况时，生成器会使用转义的Python字符串以保证正确性。

脚本通过标准库importlib在内存中加载这些源码，不解压文件、不下载代码。对模块源码使用compile/exec是执行已导出的可信代码，不是对表格内容执行Python。它保留原算法和数据模型，并没有把所有节点翻译成另一套Pandas算法；因此文件可能几十到上百KB。写WP时重点说明CONFIG、solve中的步骤，以及实际用到的算法实现和验证结果。

## 参数与行为

```powershell
python exp.py --help
python exp.py --preview                 # 完整计算，但跳过全部输出节点
python exp.py --output-dir result       # 显式相对输出目录以当前终端目录为基准
python exp.py --overwrite               # 允许替换已存在的答案文件
python exp.py --json                    # 输出含分支行数和文件路径的JSON摘要
```

输出保留原文件名，统一放入指定输出目录，不保留Web的随机运行ID，也不沿用原绝对输出位置。默认不覆盖旧文件。输出文件名不允许重复，包括大小写不同的同名文件；请在画布上先修改。所有处理节点执行完成后才运行输出节点；多个文件间仍没有统一事务，后续输出失败不会撤回前面已经生成的文件。

运行前校验全部节点参数。空值、前导零、校验口径、重复次数和数据追踪使用同一套节点实现。修改脚本CONFIG之后无需重新导出；修改画布之后需要重新下载脚本。已经导出的脚本是当时的源码快照，不会因为本工具升级而自动改变。

## 依赖和插件

- Python 3.11+。仅使用标准库节点的流程，可在没有任何第三方包的Python环境运行。
- XLSX仍需`openpyxl`，RSA验签仍需`cryptography`；文件头和导出窗口会列出安装要求。无需FastAPI、React或Node。
- 离线HTTP流量提取仍需本机TShark位于PATH，脚本不包含TShark程序。
- CSV、XLSX、PCAP、公钥、参考字典等附件不内嵌。对方仍需原附件；这也避免把比赛数据复制进exp.py。
- 已通过插件管理加载的顶层单文件插件，可内嵌其**已加载的源码快照**，不重新执行或使用磁盘上尚未重新加载的新内容。
- 自定义插件的第三方库、额外资源不会打包。同目录本地模块的静态导入会拒绝导出，需先合并成单文件；动态导入和依赖`__file__`相邻资源的插件不保证可移植，应改为显式输入路径。导出器不是通用Python应用打包器。
- 导出不调用节点的run，也不读取输入附件。配置检查仍会调用可信插件的check_config；它和插件导入一样，不是沙箱。

请通过独立Python进程执行脚本，避免在一个已经导入datasecurity的Python进程里再调用solve；脚本会拒绝混用本机安装版本与内嵌版本。

## CLI也可以导出

```powershell
python -m datasecurity export-python examples/clean_people.json --output exp.py
python -m datasecurity export-python examples/local_plugin.json --output exp.py --force
```

CLI加载插件的规则与run相同，可使用流程plugin_dirs或`--plugin-dir`。导出不会自动重写相对输入路径基准：上例流程位于examples内，所以本地复现可运行`python exp.py --base-dir examples`。`--force`只允许替换导出的脚本；脚本运行时覆盖答案是另一个`--overwrite`参数。

## 实现与验证入口

- `datasecurity/exporter.py`：校验流程、确定依赖顺序、收集使用模块的静态导入依赖、生成参数和逐节点调用。
- `datasecurity/_export_runtime.py`：附加到脚本中的标准库运行入口。
- `datasecurity/core/registry.py`：保存可信外部插件的加载源码快照。
- `POST /api/export/python`：使用当前画布配置，返回源码、输入清单、依赖和SHA-256，不生成任务或答案文件。
- `frontend/src/components/PythonExport.tsx`：预览、附件说明与下载。
- `tests/test_python_export.py`：隔离进程、分流、逐字节比较、路径覆盖、预览、覆盖保护、外部插件快照、XLSX往返等。

标准库流程测试使用`python -I -S exp.py`，排除项目目录和site-packages，确认无需安装本工具。XLSX/RSA流程保留正常的第三方库搜索路径。已下载并生成原题基准结果后，完整检查7条原附件流程：

```powershell
python scripts/verify_python_export.py
```

它逐个生成exp.py，在独立进程运行，并将每个CSV/TXT/JSONL导出文件与原流程结果逐字节比较。报告与样例脚本位于`work/python-export/`，不随源码提交。原题本身的证据等级仍以[首次实测](real-ctf.md)和[浙江/羊城杯实测](contest-round2.md)为准，导出一致性不等于赛事在线判分。

0.6.0本机验证：99项Python测试、18项前端测试、生产构建和格式检查通过。7条原附件流程独立运行生成的19个文件与原流程逐字节一致；还通过网页实际下载了人员清洗示例exp.py，以`-I -S`运行，3个输出文件与CLI一致。前者记录在`verification.json`，后者记录在`web-verification.json`；导出窗口截图为`ui-export.png`。
