"""One-shot Python re worker. Standard library only; receives one bounded JSON request."""

import json
import re
import sys
from time import perf_counter


def evaluate(request):
    started = perf_counter()
    pattern = re.compile(request["pattern"])
    mode, group = request["mode"], request["group"]
    if mode in {"extract", "find_all"} and group > pattern.groups:
        raise ValueError(f"捕获组{group}不存在，当前有{pattern.groups}组；0代表完整匹配")
    if mode == "replace":
        pattern.sub(request["replacement"], "")  # Validate replacement even without a match.
    rows = []
    for expected, samples in ((True, request["positive"]), (False, request["negative"])):
        for sample in samples:
            hits, truncated = [], False
            if mode == "fullmatch":
                match = pattern.fullmatch(sample)
                candidates = [match] if match else []
            elif mode == "search" or mode == "extract" and request["occurrence"] == "first":
                match = pattern.search(sample)
                candidates = [match] if match else []
            elif mode == "extract":
                last = None
                for match in pattern.finditer(sample):
                    last = match
                candidates = [last] if last else []
            else:
                candidates = pattern.finditer(sample)
            for match in candidates:
                selected = group if mode in {"extract", "find_all"} else 0
                start, end = match.span(selected)
                if mode == "find_all" and (start < 0 or start == end):
                    continue
                if len(hits) == 20:
                    truncated = True
                    break
                hits.append({"value": match.group(selected) or "", "start": start, "end": end})
            output = None
            if mode == "replace":
                output = pattern.sub(request["replacement"], sample, count=request["count"])
                if len(output) > 8192:
                    raise ValueError("替换后的单条样例超过8192字符，请缩短样例或替换内容")
            rows.append(
                {
                    "sample": sample,
                    "expected": expected,
                    "matched": bool(hits),
                    "passed": bool(hits) == expected,
                    "matches": hits,
                    "output": output,
                    "truncated": truncated,
                }
            )
    passed = sum(row["passed"] for row in rows)
    return {
        "ok": True,
        "rows": rows,
        "total": len(rows),
        "passed": passed,
        "false_positive": sum(row["matched"] and not row["expected"] for row in rows),
        "false_negative": sum(not row["matched"] and row["expected"] for row in rows),
        "groups": pattern.groups,
        "group_names": pattern.groupindex,
        "seconds": round(perf_counter() - started, 6),
    }


if __name__ == "__main__":
    try:
        request = json.loads(sys.stdin.buffer.read(256 * 1024))
        result = evaluate(request)
    except re.error as exc:
        result = {"ok": False, "error": f"正则或替换表达式无效：{exc}"}
    except Exception as exc:
        result = {"ok": False, "error": str(exc)}
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False).encode("utf-8"))
