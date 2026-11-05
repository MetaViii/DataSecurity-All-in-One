"""A small expression interpreter. It never calls Python eval/exec."""

from __future__ import annotations

import ast
import operator
import re
import io
import tokenize
from decimal import Decimal, ROUND_HALF_UP

from datasecurity import Parameter as P, Plugin, PluginSpec

from ._utils import map_values, number, text


class Expression:
    functions = {"abs", "round", "length", "upper", "lower", "coalesce", "number"}
    binary = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
    }
    comparisons = {
        ast.Eq: operator.eq,
        ast.NotEq: operator.ne,
        ast.Gt: operator.gt,
        ast.GtE: operator.ge,
        ast.Lt: operator.lt,
        ast.LtE: operator.le,
    }

    def __init__(self, source: str):
        if not source.strip() or len(source) > 2000:
            raise ValueError("表达式不能为空且最多 2000 字符")
        self.fields: dict[str, str] = {}
        # Brackets inside a quoted string are literal text, not field refs.
        lines = source.splitlines(keepends=True)
        offsets = [0]
        for line in lines:
            offsets.append(offsets[-1] + len(line))
        quoted = []
        try:
            for token in tokenize.generate_tokens(io.StringIO(source).readline):
                if token.type == tokenize.STRING:
                    quoted.append(
                        (
                            offsets[token.start[0] - 1] + token.start[1],
                            offsets[token.end[0] - 1] + token.end[1],
                        )
                    )
        except (tokenize.TokenError, IndentationError):
            pass  # ast.parse below supplies the user-facing syntax diagnostic.

        def replace(match):
            if any(start <= match.start() < end for start, end in quoted):
                return match.group(0)
            name = f"__field_{len(self.fields)}"
            self.fields[name] = match.group(1)
            return name

        self.source = re.sub(r"\[([^\[\]]+)\]", replace, source)
        try:
            self.tree = ast.parse(self.source, mode="eval")
        except SyntaxError as exc:
            raise ValueError(f"表达式语法错误：{exc.msg}") from exc
        nodes = list(ast.walk(self.tree))
        if len(nodes) > 120:
            raise ValueError("表达式过于复杂")
        allowed = (
            ast.Expression,
            ast.Constant,
            ast.Name,
            ast.Load,
            ast.BinOp,
            ast.UnaryOp,
            ast.BoolOp,
            ast.Compare,
            ast.Call,
            ast.IfExp,
            *self.binary,
            *self.comparisons,
            ast.USub,
            ast.UAdd,
            ast.Not,
            ast.And,
            ast.Or,
        )
        for node in nodes:
            if not isinstance(node, allowed):
                raise ValueError(f"表达式不支持 {type(node).__name__}")
            if (
                isinstance(node, ast.Name)
                and node.id not in self.fields
                and node.id not in self.functions
            ):
                raise ValueError(f"字段必须写成 [字段名]，不支持名称：{node.id}")
            if isinstance(node, ast.Call) and (
                not isinstance(node.func, ast.Name)
                or node.func.id not in self.functions
                or node.keywords
            ):
                raise ValueError("只能调用白名单函数，且不接受关键字参数")
        called_names = {id(node.func) for node in nodes if isinstance(node, ast.Call)}
        if any(
            isinstance(node, ast.Name)
            and node.id in self.functions
            and id(node) not in called_names
            for node in nodes
        ):
            raise ValueError("函数名称必须跟随调用参数")

    def evaluate(self, row):
        def numeric(value):
            return value if isinstance(value, Decimal) else number(str(value))

        def walk(node):
            if isinstance(node, ast.Constant):
                if type(node.value) in (int, float):
                    return number(ast.get_source_segment(self.source, node).replace("_", ""))
                if isinstance(node.value, (str, bool)):
                    return node.value
                raise ValueError("不支持该常量类型")
            if isinstance(node, ast.Name):
                return row[self.fields[node.id]]
            if isinstance(node, ast.BinOp):
                left, right = walk(node.left), walk(node.right)
                if (
                    isinstance(node.op, ast.Add)
                    and isinstance(left, str)
                    and isinstance(right, str)
                ):
                    return left + right
                left, right = numeric(left), numeric(right)
                if isinstance(node.op, ast.Pow) and (
                    right != right.to_integral_value() or abs(right) > 16
                ):
                    raise ValueError("次方指数必须是 -16 到 16 的整数")
                return self.binary[type(node.op)](left, right)
            if isinstance(node, ast.UnaryOp):
                value = walk(node.operand)
                if isinstance(node.op, ast.Not):
                    return not bool(value)
                return -numeric(value) if isinstance(node.op, ast.USub) else numeric(value)
            if isinstance(node, ast.BoolOp):
                values = (bool(walk(item)) for item in node.values)
                return all(values) if isinstance(node.op, ast.And) else any(values)
            if isinstance(node, ast.Compare):
                left = walk(node.left)
                for operation, comparator in zip(node.ops, node.comparators):
                    right = walk(comparator)
                    a, b = (
                        (numeric(left), numeric(right))
                        if isinstance(left, Decimal) or isinstance(right, Decimal)
                        else (left, right)
                    )
                    if not self.comparisons[type(operation)](a, b):
                        return False
                    left = right
                return True
            if isinstance(node, ast.IfExp):
                return walk(node.body) if bool(walk(node.test)) else walk(node.orelse)
            if isinstance(node, ast.Call):
                args = [walk(item) for item in node.args]
                name = node.func.id
                if name == "abs" and len(args) == 1:
                    return abs(numeric(args[0]))
                if name == "number" and len(args) == 1:
                    return numeric(args[0])
                if name == "length" and len(args) == 1:
                    return Decimal(len(str(args[0])))
                if name == "upper" and len(args) == 1:
                    return str(args[0]).upper()
                if name == "lower" and len(args) == 1:
                    return str(args[0]).lower()
                if name == "coalesce" and args:
                    return next((value for value in args if value != ""), "")
                if name == "round" and len(args) in {1, 2}:
                    digits = numeric(args[1]) if len(args) == 2 else Decimal(0)
                    if digits != digits.to_integral_value() or abs(digits) > 16:
                        raise ValueError("round 位数必须在 -16 到 16 之间")
                    return numeric(args[0]).quantize(
                        Decimal(1).scaleb(-int(digits)), rounding=ROUND_HALF_UP
                    )
                raise ValueError(f"函数 {name} 的参数数量不正确")
            raise ValueError("不支持的表达式")

        return walk(self.tree.body)


class CalculateColumn(Plugin):
    spec = PluginSpec(
        "columns.calculate",
        "计算字段",
        "transform",
        "以精确小数计算新字段，支持 [字段名]、四则运算和白名单函数",
        inputs=("data",),
        outputs=("data",),
        category="计算与分类",
        parameters=(
            P("expression", str, "例如：[单价] * [数量]", required=True, widget="textarea"),
            P("output", str, "结果字段", default="计算结果"),
        ),
    )

    def check_config(self, config):
        Expression(config["expression"])
        if not config["output"].strip():
            raise ValueError("结果字段不能为空")

    def run(self, inputs, config, context):
        table = inputs["data"]
        expression = Expression(config["expression"])
        table.require_columns(expression.fields.values())
        columns = tuple(dict.fromkeys((*table.columns, config["output"])))
        return {
            "data": map_values(
                table,
                context,
                lambda row: {**row, config["output"]: text(expression.evaluate(row))},
                columns=columns,
                reason="表达式计算",
            )
        }
