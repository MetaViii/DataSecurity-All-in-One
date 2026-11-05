# 自己添加插件

0.3支持在顶部“插件”中导入源码或从模板创建、启停及热加载，详见 [界面插件管理](plugin-manager.md)。下文仍适用于直接在plugins目录编写代码；不要在流程运行期间重载模块。

## 最短路径

在插件管理选模板，或复制 `plugins/add_prefix.py`，改 ID、参数、算法，再在网页“插件”点击“重新加载”。模块库会出现新插件，字符串、数字、布尔、列表、字典参数自动生成表单，不需要手工在前端注册节点。

CLI 显式加载目录：

```powershell
python -m datasecurity plugins --plugin-dir plugins
python -m datasecurity run examples/local_plugin.json --preview
```

Web 自动加载工作区 `plugins/` 的直接 `.py` 文件。CLI 的流程可配置 `"plugin_dirs": ["../plugins"]`，路径相对流程文件。扫描不递归；每个文件独立收集错误，不覆盖同 ID 插件。修改已导入的辅助 Python 模块时建议重启服务，模块缓存不是完整的依赖热更新系统。插件是可信本地 Python，不是沙箱脚本。

## 完整的校验插件样例

例如新增 `plugins/allowed_values.py`：

```python
from datasecurity import Parameter, Plugin, PluginSpec


class AllowedValues(Plugin):
    spec = PluginSpec(
        id="custom.allowed_values",
        name="允许值校验",
        kind="transform",
        description="不在给定列表内的值进入异常分支，不修改原值",
        category="自定义校验",
        inputs=("data",),
        outputs=("valid", "invalid"),
        parameters=(
            Parameter("field", str, "待检查的字段", required=True, widget="field"),
            Parameter("allowed", list, "允许值列表", default=["男", "女"]),
        ),
        version="1",
    )

    def check_config(self, config):
        if not config["field"].strip():
            raise ValueError("字段不能为空")
        if not config["allowed"] or any(not isinstance(x, str) for x in config["allowed"]):
            raise ValueError("allowed 必须是非空字符串列表")

    def run(self, inputs, config, context):
        table = inputs["data"]
        table.require_columns((config["field"],))
        allowed = set(config["allowed"])
        valid, invalid = [], []
        for record in table.records:
            context.check_cancelled()
            if record.values[config["field"]] in allowed:
                valid.append(record)
            else:
                invalid.append(record.with_issue(
                    node=context.node_id,
                    field=config["field"],
                    message="不属于允许值",
                ))
        return {"valid": table.with_records(valid), "invalid": table.with_records(invalid)}


PLUGINS = [AllowedValues]
```

这个例子未预装；粘贴保存后才会出现。内置 `validate.rules` 的 enum 也能做同样的事，例子用于理解包装流程。先独立写算法函数，再让插件负责接收参数、遍历记录、分流和报告原因。

## 六个接口分别负责什么

| 接口 | 职责 |
| --- | --- |
| `PluginSpec` | 唯一 ID、显示名称、分类、类型、输入输出端口、版本 |
| `Parameter` | 配置类型、默认值、必填、固定选项、前端提示 |
| `check_config` | 不读附件的配置检查，如范围、嵌套列表、正则语法 |
| `run` | 检查实际字段、执行算法，返回与声明完全一致的端口字典 |
| `RunContext` | 当前节点 ID、基准目录、预览状态、取消、读写文件登记 |
| `PLUGINS` | 告诉 Registry 本文件导出哪些插件类 |

input 没有输入且至少有一个输出；transform 两侧都有；output 有输入、无输出，返回 `{}`。多输入用 `("left", "right")`，在 run 中按名字取表，不依赖连线顺序。不要把每个插件的 ID 硬编码到执行器里。

参数支持 `str`、`int`、`bool`、`list`、`dict`。类型严格匹配，`true` 不能替代整数 1，`"10"` 不自动转整数。顶层未知参数报错。嵌套内容由插件自己验证，不能只相信前端。改变参数/语义时更新 spec.version；目前没有自动迁移旧流程的机制。

## 数据修改与追踪

```python
table = inputs["data"]
table.require_columns(("姓名",))

# 保留记录，来源和历史自然保留。
selected = table.with_records(r for r in table.records if r.values["姓名"])

# 修改已有字段，只记录实际变化。
changed = record.with_updates(
    {"姓名": record.values["姓名"].strip()},
    node=context.node_id, reason="移除两端空白",
)

# 新增/删除/重命名字段，先得到新的记录，再同步 Table.columns。
from datasecurity import Table
new_record = record.rebuild(
    {**record.values, "标记": "已检查"},
    node=context.node_id, reason="增加检查标记",
)
new_table = Table((*table.columns, "标记"), (new_record,))
```

最后的示意只构造一条记录；实际节点应遍历全表。不能就地写 `record.values["姓名"] = ...`。新增字段不能只改 values 而忘记 columns。不要重新 `Record(dict(...))` 丢掉原来源；优先使用上述方法。关联/聚合要保留多来源，参照 `builtin/tables.py` 与 `_utils.combined_record`。

所有单元格都是字符串。数字请显式解析 Decimal，再格式化为字符串；身份证、电话、编号不要转浮点数。校验只报告问题，修复应单独实现、记录依据和变更，不能把“通过规则”当作“答案正确”。

## 身份证插件应该怎样拆

可以先自己写纯函数 `check_idcard(value) -> list[str]`，用公开标准验证长度、ASCII 数字、日期和校验码；明确是否接受小写 x、15 位旧号码及行政区划年代，保持这些策略可配置。然后复用上面插件骨架，把 allowed 判断替换成该函数：无原因进入 valid；每个原因调用一次 with_issue 后进入 invalid。

不要在校验时自动猜改校验码。需要修复时新增另一个插件，声明修复成立的前提，使用 with_updates 记录旧值、新值和依据。地区码列表应作为版本化数据资源，不要散落在 run 函数的 if 分支里。合法结构也不能证明号码已被签发或属于某个人。

## 前端表单如何适配

`PluginSpec.describe()` 返回 JSON，`/api/bootstrap` 把元数据交给左侧 Library 与右侧 Inspector。`ParameterField` 按类型、choices 和 widget 渲染。常用 widget：

| widget | 用法 |
| --- | --- |
| `field` | 单字段输入，附上游字段建议，仍允许手工填写 |
| `fields` / `names` | 有序字符串列表编辑 |
| `input_file` / `output_file` | 输入文件选择或输出文件名 |
| `textarea` | 多行表达式等 |
| `mapping` | 字段映射 |
| `conditions` / `validation_rules` | 条件与组合校验规则 |
| `sort_rules` / `aggregate_rules` / `case_rules` | 排序、统计与分类规则 |

没有专用 widget 的 list/dict 使用 JSON 编辑器，新的普通插件仍能用。复杂编辑器可切换 JSON，以填写界面暂时没有按钮的高级键；错误 JSON 会阻止正常参数校验，不会悄悄沿用旧值。仅当新的交互确有需要时才改 `frontend/src/components/Fields.tsx`。

## 文件、预览和取消

输入通过 `context.resolve_path` 解析路径，并登记 `context.source_paths.add(path)`。输出通过 `context.output_path(path, overwrite=...)` 检查目标，使用同目录临时文件写完再替换。参考 CSV/XLSX 输出，失败应清理临时文件，保留已有目标。

预览不会调用 output 的 run，但会调用 input/transform，所以这两类不要偷偷写磁盘、请求外部系统或修改数据库。循环中调用 `context.check_cancelled()`，允许用户取消长任务。第三方插件仍然可以绕过这些约定，这些接口不是安全沙箱。

## 自测与接入

先用 `Table.from_rows` 构造虚构数据直接调用插件，参照 `tests/test_nodes.py`。至少检查正常、非法值、空表、缺少字段、错误配置，以及两分支数量守恒。修改类节点检查原记录不变、新记录有 changes；文件类检查前导零、空字符串、编码和失败后目标是否保留。

Web 保存文件后重新加载插件，若有错误看工作区设置的提示。建立“读取 → 新插件 → 两个输出”的最短流程验证。更复杂的题目规则稳定后再扩展节点，不要一开始改动整个 Pipeline。
