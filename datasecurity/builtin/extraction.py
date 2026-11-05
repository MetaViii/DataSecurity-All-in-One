"""Capture ingestion delegates protocol reassembly to TShark; extraction stays inspectable."""

import json
import os
import re
import shutil
import subprocess
import tempfile
import time

from datasecurity import Origin, Parameter as P, Plugin, PluginSpec, Record, Table
from ._files import check_encoding
from ._utils import combined_record, names


HTTP_COLUMNS = ("帧号", "TCP流", "方法", "URI", "内容类型", "正文")
HTTP_FIELDS = (
    "frame.number",
    "tcp.stream",
    "http.request.method",
    "http.request.uri",
    "http.content_type",
    "http.file_data",
)


class HttpCapture(Plugin):
    spec = PluginSpec(
        "pcap.http",
        "读取PCAP中的HTTP请求正文",
        "input",
        "调用本机TShark重组明文HTTP请求，保留帧号与流编号；不解密TLS，不执行附件内容",
        outputs=("data", "invalid"),
        category="数据输入",
        parameters=(
            P(
                "path",
                str,
                "PCAP/PCAPNG文件；本机PATH需有TShark",
                required=True,
                widget="input_file",
            ),
            P("encoding", str, "HTTP正文字符编码；解码失败单独分流", default="utf-8"),
            P("timeout", int, "TShark执行超时秒数", default=120),
            P("max_output_mb", int, "协议解析中间结果大小上限MiB", default=128),
        ),
    )

    def check_config(self, c):
        names([c["path"]])
        check_encoding(c["encoding"])
        if not 1 <= c["timeout"] <= 600 or not 1 <= c["max_output_mb"] <= 512:
            raise ValueError("超时应为1到600秒，中间结果上限应为1到512MiB")

    def run(self, inputs, c, context):
        executable = shutil.which("tshark")
        if executable is None:
            raise ValueError("未找到TShark；安装Wireshark并将TShark目录加入PATH后重启服务")
        path = context.resolve_path(c["path"])
        if not path.is_file():
            raise FileNotFoundError(path)
        context.source_paths.add(path)
        command = [
            executable,
            "-n",
            "-r",
            str(path),
            "-Y",
            "http.request && http.file_data",
            "-o",
            "tcp.desegment_tcp_streams:TRUE",
            "-o",
            "http.desegment_body:TRUE",
            "-T",
            "json",
            "--no-duplicate-keys",
        ]
        for field in HTTP_FIELDS:
            command.extend(("-e", field))
        # Ignore personal Wireshark settings so parsing is reproducible. No shell or arbitrary flags.
        with (
            tempfile.TemporaryDirectory(prefix="ds-http-") as config,
            tempfile.TemporaryFile() as output,
            tempfile.TemporaryFile() as errors,
        ):
            env = {**os.environ, "WIRESHARK_CONFIG_DIR": config}
            options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
            process = subprocess.Popen(command, stdout=output, stderr=errors, env=env, **options)
            started = time.monotonic()
            try:
                while True:
                    context.check_cancelled()
                    if os.fstat(output.fileno()).st_size > c["max_output_mb"] * 1024 * 1024:
                        raise ValueError("TShark中间结果超过大小上限")
                    if time.monotonic() - started > c["timeout"]:
                        raise ValueError("TShark执行超时")
                    try:
                        process.wait(timeout=0.1)
                        break
                    except subprocess.TimeoutExpired:
                        continue
                if os.fstat(output.fileno()).st_size > c["max_output_mb"] * 1024 * 1024:
                    raise ValueError("TShark中间结果超过大小上限")
                if process.returncode:
                    errors.seek(0)
                    message = errors.read(2000).decode("utf-8", errors="replace")
                    raise ValueError("TShark解析失败：" + message)
                output.seek(0)
                packets = json.load(output)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
        data, invalid = [], []
        for packet in packets:
            context.check_cancelled()
            layers = packet["_source"]["layers"]
            values = [layers.get(field, []) for field in HTTP_FIELDS]
            values = [item if isinstance(item, list) else [item] for item in values]
            bodies = values[-1]
            frame = values[0][0] if values[0] else "0"
            # A coalesced frame can contain multiple HTTP messages. Refuse ambiguous metadata.
            ambiguous = any(len(item) not in {0, 1, len(bodies)} for item in values[1:-1])
            for index, body in enumerate(bodies):
                row = {
                    column: (
                        items[index] if len(items) == len(bodies) else items[0] if items else ""
                    )
                    for column, items in zip(HTTP_COLUMNS[:-1], values[:-1])
                }
                origin = (Origin(str(path), int(frame)),)
                try:
                    if ambiguous:
                        raise ValueError("同帧多请求的元数据无法唯一对应")
                    row["正文"] = bytes.fromhex(body.replace(":", "")).decode(c["encoding"])
                    data.append(Record(row, origin))
                except (ValueError, UnicodeError) as exc:
                    row["正文"] = body  # Preserve original hex when decoding fails.
                    invalid.append(
                        Record(row, origin).with_issue(
                            node=context.node_id, field="正文", message=str(exc)
                        )
                    )
        return {
            "data": Table(HTTP_COLUMNS, tuple(data)),
            "invalid": Table(HTTP_COLUMNS, tuple(invalid)),
        }


class FindMatches(Plugin):
    spec = PluginSpec(
        "text.find_all",
        "提取全部正则匹配",
        "transform",
        "按带标签的正则提取多个值并保留字符范围；可消除重叠，校验和与业务规则由下游节点处理",
        inputs=("data",),
        outputs=("data", "unmatched"),
        category="字段处理",
        parameters=(
            P("field", str, "待扫描字段", required=True, widget="field"),
            P(
                "rules",
                list,
                "每条包含label、pattern和可选group（默认0）",
                required=True,
                widget="extraction_rules",
            ),
            P(
                "overlap",
                str,
                "保留全部匹配，或优先保留较长的非重叠匹配",
                default="longest",
                choices=("all", "longest"),
            ),
            P("max_matches", int, "单条记录匹配数量上限；超限明确报错", default=10000),
            P("max_rows", int, "总输出行数上限", default=500000),
        ),
    )

    def check_config(self, c):
        names([c["field"]])
        if not c["rules"] or len(c["rules"]) > 30:
            raise ValueError("需要1到30条提取规则")
        for rule in c["rules"]:
            if not isinstance(rule, dict) or set(rule) - {"label", "pattern", "group"}:
                raise ValueError("提取规则仅接受label、pattern、group")
            names([rule.get("label", ""), rule.get("pattern", "")])
            pattern = re.compile(rule["pattern"])
            group = rule.get("group", 0)
            if type(group) is not int or not 0 <= group <= pattern.groups:
                raise ValueError("捕获组序号无效")
        if not 1 <= c["max_matches"] <= 100000 or not 1 <= c["max_rows"] <= 1000000:
            raise ValueError("单条匹配上限应为1到100000，总行数上限应为1到1000000")

    def run(self, inputs, c, context):
        table = inputs["data"]
        table.require_columns([c["field"]])
        patterns = [
            (rule["label"], re.compile(rule["pattern"]), rule.get("group", 0))
            for rule in c["rules"]
        ]
        records, unmatched = [], []
        for position, record in enumerate(table.records, 1):
            context.check_cancelled()
            matches = []
            for priority, (label, pattern, group) in enumerate(patterns):
                for match in pattern.finditer(record.values[c["field"]]):
                    context.check_cancelled()
                    start, end = match.span(group)
                    if start < 0 or start == end:
                        continue
                    matches.append((start, end, priority, label, match.group(group)))
                    if len(matches) > c["max_matches"]:
                        raise ValueError("单条记录匹配数量超过max_matches")
            if c["overlap"] == "longest":
                selected = []
                for item in sorted(matches, key=lambda m: (-(m[1] - m[0]), m[0], m[2])):
                    if not any(item[0] < other[1] and other[0] < item[1] for other in selected):
                        selected.append(item)
                matches = selected
            for start, end, priority, label, value in sorted(matches, key=lambda m: (m[0], m[2])):
                if len(records) >= c["max_rows"]:
                    raise ValueError("提取结果超过max_rows")
                values = {
                    "category": label,
                    "value": value,
                    "记录位置": str(position),
                    "起始字符": str(start),
                    "结束字符": str(end),
                }
                records.append(combined_record(values, (record,)))
            if not matches:
                unmatched.append(record)
        return {
            "data": Table(
                ("category", "value", "记录位置", "起始字符", "结束字符"), tuple(records)
            ),
            "unmatched": table.with_records(unmatched),
        }


PLUGINS = [HttpCapture, FindMatches]
