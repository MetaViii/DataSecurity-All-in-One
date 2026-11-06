"""Local editing helpers; never imported by processing nodes or standalone exports."""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys
from threading import BoundedSemaphore

WORKERS = BoundedSemaphore(2)
TEST_TIMEOUT = 2.0
MODES = {"fullmatch", "search", "extract", "find_all", "replace"}
OCTET = r"(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])"
DATE = r"[0-9]{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])"


def template(key, name, pattern, positive, negative, note, search_pattern=None):
    return {
        "id": key,
        "name": name,
        "pattern": pattern,
        "search_pattern": search_pattern or pattern,
        "positive": positive,
        "negative": negative,
        "note": note,
    }


TEMPLATES = [
    template(
        "phone",
        "手机号：1开头的11位数字",
        r"1[0-9]{10}",
        ["13812345678", "10000000000"],
        ["23812345678", "1381234567", "138123456789", "1381234567a", "１３８１２３４５６７８"],
        "只检查这三条格式要求，不限制真实运营商号段。",
        r"(?<!\d)1[0-9]{10}(?!\d)",
    ),
    template(
        "identity",
        "身份证：18位格式",
        r"[0-9]{17}[0-9Xx]",
        ["11010519491231002X"],
        ["11010519491231002", "11010519491231002A"],
        "仅检查长度与字符；日期、校验码和性别请接身份证校验节点。",
        r"(?<![0-9A-Za-z])[0-9]{17}[0-9Xx](?![0-9A-Za-z])",
    ),
    template(
        "integer",
        "无符号整数",
        r"[0-9]+",
        ["0", "0001", "12345"],
        ["abc", "1.2", "-1"],
        "保留前导零；仅匹配非负整数的文本格式。",
        r"(?<![0-9.+-])[0-9]+(?![0-9.])",
    ),
    template(
        "decimal",
        "金额：最多两位小数",
        r"[0-9]+(?:\.[0-9]{1,2})?",
        ["0", "12.3", "12.34"],
        ["12.345", "-12.34", "12."],
        "不接受负数、千位分隔符或科学计数法，可按题意修改。",
        r"(?<![0-9.+-])[0-9]+(?:\.[0-9]{1,2})?(?![0-9.])",
    ),
    template(
        "email",
        "邮箱：常见ASCII格式",
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
        ["ctf@example.test", "a+b@example.com"],
        ["ctfexample.com", "ctf@local", "@example.com"],
        "常见格式模板，不覆盖所有邮件地址标准。",
    ),
    template(
        "ipv4",
        "IPv4：四段0～255",
        rf"(?:{OCTET}\.){{3}}{OCTET}",
        ["192.168.1.1", "0.0.0.0", "255.255.255.255"],
        ["256.1.1.1", "1.2.3", "01.2.3.4"],
        "不接受前导零；提取时检查数字和点的边界。",
        rf"(?<![0-9.])(?:{OCTET}\.){{3}}{OCTET}(?![0-9.])",
    ),
    template(
        "date",
        "日期：YYYY-MM-DD",
        DATE,
        ["2024-01-31", "2000-12-01"],
        ["2024-13-01", "2024-00-10", "2024/01/01"],
        "只检查格式与月日范围，不判断闰年或2月30日；真实日期请用有效日期校验。",
        rf"(?<!\d){DATE}(?!\d)",
    ),
    template(
        "datetime",
        "时间：YYYY-MM-DD HH:MM:SS",
        DATE + r"[ T](?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]",
        ["2024-01-31 09:30:00", "2024-01-31T23:59:59"],
        ["2024-01-31 24:00:00", "2024-01-31 09:60:00"],
        "不含毫秒或时区；日期有效性和时间先后仍需日期节点。",
    ),
    template(
        "hex",
        "十六进制字符串",
        r"[0-9A-Fa-f]+",
        ["00ff", "A1B2", "123"],
        ["0x12", "xyz", "12-34"],
        "不含0x前缀与分隔符。",
        r"(?<![0-9A-Za-z-])[0-9A-Fa-f]+(?![0-9A-Za-z-])",
    ),
]


def compose(payload: dict) -> dict:
    allowed = {
        "prefix",
        "suffix",
        "characters",
        "custom",
        "min_length",
        "max_length",
        "allow_empty",
        "ignore_case",
    }
    if set(payload) - allowed:
        raise ValueError("规则组合含未知参数")
    prefix, suffix = payload.get("prefix", ""), payload.get("suffix", "")
    custom = payload.get("custom", "")
    if any(not isinstance(value, str) or len(value) > 120 for value in (prefix, suffix, custom)):
        raise ValueError("前缀、后缀、自定义字符应为不超过120字符的文本")
    choices = {
        "digits": "[0-9]",
        "letters": "[A-Za-z]",
        "lower": "[a-z]",
        "upper": "[A-Z]",
        "alnum": "[A-Za-z0-9]",
        "han": r"[\u4e00-\u9fff]",
    }
    kind = payload.get("characters", "digits")
    if kind == "custom":
        if not custom:
            raise ValueError("请逐字填写允许的字符，不要填写正则表达式")
        character = "[" + re.escape("".join(dict.fromkeys(custom))) + "]"
    elif isinstance(kind, str) and kind in choices:
        character = choices[kind]
    else:
        raise ValueError("请选择支持的字符类型")
    minimum, maximum = payload.get("min_length", 10), payload.get("max_length", 10)
    if type(minimum) is not int or type(maximum) is not int or not 0 <= minimum <= maximum <= 1000:
        raise ValueError("中间长度需要满足 0 ≤ 最小值 ≤ 最大值 ≤ 1000")
    for key in ("allow_empty", "ignore_case"):
        if type(payload.get(key, False)) is not bool:
            raise ValueError(f"{key} 必须是布尔值")
    repetition = f"{{{minimum}}}" if minimum == maximum else f"{{{minimum},{maximum}}}"
    pattern = re.escape(prefix) + character + repetition + re.escape(suffix)
    if payload.get("allow_empty"):
        pattern = "(?:" + pattern + ")?"
    if payload.get("ignore_case"):
        pattern = "(?ai)" + pattern
    explanation = [
        f"固定前缀：{prefix!r}；固定后缀：{suffix!r}（均按原文匹配）",
        f"中间部分：{character}，{minimum}～{maximum}个字符",
        (
            "允许空字符串"
            if payload.get("allow_empty") or not prefix and not suffix and minimum == 0
            else "不允许空字符串"
        ),
    ]
    return {"pattern": pattern, "explanation": explanation}


def validate_request(payload: dict) -> dict:
    allowed = {
        "pattern",
        "mode",
        "positive",
        "negative",
        "group",
        "occurrence",
        "replacement",
        "count",
    }
    if set(payload) - allowed:
        raise ValueError("正则测试含未知参数")
    pattern = payload.get("pattern")
    if not isinstance(pattern, str) or len(pattern) > 2048:
        raise ValueError("正则应为不超过2048字符的文本")
    mode = payload.get("mode", "fullmatch")
    if not isinstance(mode, str) or mode not in MODES:
        raise ValueError("不支持的匹配方式")
    if mode == "replace" and not pattern or mode == "find_all" and not pattern.strip():
        raise ValueError("当前操作的正则不能为空")
    positive, negative = payload.get("positive", []), payload.get("negative", [])
    if any(
        not isinstance(rows, list) or any(not isinstance(value, str) for value in rows)
        for rows in (positive, negative)
    ):
        raise ValueError("正反例必须是字符串数组，空字符串可作为一个样例")
    samples = positive + negative
    if (
        not 1 <= len(samples) <= 100
        or any(len(value) > 2048 for value in samples)
        or sum(map(len, samples)) > 16384
    ):
        raise ValueError("需1～100个样例，每例最多2048字符，总计最多16384字符")
    group, count = payload.get("group", 0), payload.get("count", 0)
    if (
        type(group) is not int
        or not 0 <= group <= 1000
        or type(count) is not int
        or not 0 <= count <= 1000000
    ):
        raise ValueError("捕获组或替换次数无效")
    occurrence = payload.get("occurrence", "first")
    replacement = payload.get("replacement", "")
    if (
        occurrence not in ("first", "last")
        or not isinstance(replacement, str)
        or len(replacement) > 256
    ):
        raise ValueError("提取顺序无效，或替换文本超过256字符")
    return {
        "pattern": pattern,
        "mode": mode,
        "positive": positive,
        "negative": negative,
        "group": group,
        "count": count,
        "occurrence": occurrence,
        "replacement": replacement,
    }


class RegexBusyError(RuntimeError):
    pass


def test_pattern(payload: dict) -> dict:
    request = validate_request(payload)
    if not WORKERS.acquire(blocking=False):
        raise RegexBusyError("已有2个正则测试，请稍后重试")
    process = None
    try:
        options = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
        process = subprocess.Popen(
            [sys.executable, "-I", "-S", str(Path(__file__).with_name("_regex_worker.py"))],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **options,
        )
        try:
            stdout, _ = process.communicate(
                json.dumps(request, ensure_ascii=False).encode("utf-8"), timeout=TEST_TIMEOUT
            )
        except subprocess.TimeoutExpired as exc:
            process.kill()
            process.communicate()
            raise ValueError("正则测试超过2秒，已终止；请简化表达式或缩短样例") from exc
        if process.returncode != 0 or len(stdout) > 1024 * 1024:
            raise ValueError("正则测试进程异常退出，或结果过大")
        result = json.loads(stdout)
        if not result.get("ok"):
            raise ValueError(result.get("error", "正则测试失败"))
        return result
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.communicate()
        WORKERS.release()
