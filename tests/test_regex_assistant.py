"""Exercise the local helper against Python re and actual processing nodes."""

import re
import tempfile
from pathlib import Path
from time import monotonic
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from datasecurity import RunContext, Table
from datasecurity.builtin import create_registry
from datasecurity.web import regex_assistant as assistant
from datasecurity.web.app import create_app


class RegexAssistantTests(unittest.TestCase):
    def test_all_templates_and_operations(self):
        for template in assistant.TEMPLATES:
            for mode in assistant.MODES:
                with self.subTest(template=template["id"], mode=mode):
                    result = assistant.test_pattern(
                        {
                            "pattern": (
                                template["pattern"]
                                if mode == "fullmatch"
                                else template["search_pattern"]
                            ),
                            "mode": mode,
                            "positive": template["positive"],
                            "negative": template["negative"] + [""],
                        }
                    )
                    self.assertEqual(result["passed"], result["total"], result)

    def test_composer_literals_lengths_ascii_case_and_empty(self):
        built = assistant.compose(
            {"prefix": "1", "characters": "digits", "min_length": 10, "max_length": 10}
        )
        self.assertEqual(built["pattern"], r"1[0-9]{10}")
        self.assertIsNotNone(re.fullmatch(built["pattern"], "13812345678"))
        self.assertIsNone(re.fullmatch(built["pattern"], "１3812345678"))
        escaped = assistant.compose(
            {
                "prefix": "a.+[",
                "suffix": "]$",
                "characters": "custom",
                "custom": "-]^\\",
                "min_length": 1,
                "max_length": 3,
            }
        )
        self.assertIsNotNone(re.fullmatch(escaped["pattern"], "a.+[-]$"))
        self.assertIsNone(re.fullmatch(escaped["pattern"], "abc[-]$"))
        optional = assistant.compose(
            {
                "characters": "lower",
                "min_length": 1,
                "max_length": 2,
                "allow_empty": True,
                "ignore_case": True,
            }
        )
        self.assertIsNotNone(re.fullmatch(optional["pattern"], ""))
        self.assertIsNotNone(re.fullmatch(optional["pattern"], "AB"))
        self.assertIsNone(re.fullmatch(optional["pattern"], "İ"))

    def test_fullmatch_search_and_extraction_match_nodes(self):
        pattern = r"id=([0-9]+)"
        text = "label id=12 id=34"
        registry = create_registry()
        context = RunContext(Path.cwd(), node_id="test")
        table = Table.from_rows(("value",), [{"value": text}])
        for full in (True, False):
            plugin = registry.get("validate.regex")
            node = plugin.run(
                {"data": table},
                plugin.prepare_config({"field": "value", "pattern": pattern, "full_match": full}),
                context,
            )
            tested = assistant.test_pattern(
                {"pattern": pattern, "mode": "fullmatch" if full else "search", "positive": [text]}
            )
            self.assertEqual(tested["rows"][0]["matched"], bool(len(node["valid"])))
        for occurrence, expected in (("first", "12"), ("last", "34")):
            tested = assistant.test_pattern(
                {
                    "pattern": pattern,
                    "mode": "extract",
                    "group": 1,
                    "occurrence": occurrence,
                    "positive": [text],
                }
            )
            plugin = registry.get("text.extract")
            result = plugin.run(
                {"data": table},
                plugin.prepare_config(
                    {"field": "value", "pattern": pattern, "group": 1, "occurrence": occurrence}
                ),
                context,
            )
            self.assertEqual(tested["rows"][0]["matches"][0]["value"], expected)
            self.assertEqual(result["data"].records[0].values["提取结果"], expected)

    def test_replacements_use_python_references_and_count(self):
        pattern, replacement, sample = r"([a-z]+)([0-9]+)", r"\g<2>-\g<1>", "ab12 cd34"
        for count, expected in ((0, "12-ab 34-cd"), (1, "12-ab cd34")):
            result = assistant.test_pattern(
                {
                    "pattern": pattern,
                    "mode": "replace",
                    "replacement": replacement,
                    "count": count,
                    "positive": [sample],
                    "negative": ["nothing"],
                }
            )
            self.assertEqual(result["rows"][0]["output"], expected)
            self.assertEqual(result["rows"][1]["output"], "nothing")
        with self.assertRaisesRegex(ValueError, "无效"):
            assistant.test_pattern(
                {"pattern": "(a)", "mode": "replace", "replacement": r"\g<3>", "positive": ["none"]}
            )

    def test_all_matches_empty_groups_and_truncation(self):
        pattern = r"id=([0-9]+)"
        result = assistant.test_pattern(
            {
                "pattern": pattern,
                "mode": "find_all",
                "group": 1,
                "positive": ["id=12 id=34"],
                "negative": ["id=abc"],
            }
        )
        self.assertEqual([hit["value"] for hit in result["rows"][0]["matches"]], ["12", "34"])
        empty = assistant.test_pattern({"pattern": "a*", "mode": "find_all", "negative": ["bbb"]})
        self.assertEqual(empty["passed"], 1)
        bounded = assistant.test_pattern(
            {"pattern": "[0-9]", "mode": "find_all", "positive": ["1" * 60]}
        )
        self.assertTrue(bounded["rows"][0]["truncated"])
        self.assertEqual(len(bounded["rows"][0]["matches"]), 20)
        with self.assertRaisesRegex(ValueError, "捕获组"):
            assistant.test_pattern(
                {"pattern": "[0-9]+", "mode": "extract", "group": 1, "positive": ["12"]}
            )

    def test_malformed_and_bounded_requests(self):
        for request in (
            {"pattern": []},
            {"pattern": "a", "positive": [1]},
            {"pattern": "a", "positive": ["a"] * 101},
            {"pattern": "a", "positive": ["a" * 2049]},
            {"pattern": "a", "positive": ["a" * 2048] * 9},
            {"pattern": "a", "positive": ["a"], "group": True},
            {"pattern": "a", "positive": ["a"], "extra": 1},
        ):
            with self.subTest(request=str(request)[:100]), self.assertRaises(ValueError):
                assistant.test_pattern(request)
        for request in (
            {"min_length": -1},
            {"min_length": 20, "max_length": 1},
            {"min_length": True},
            {"characters": "custom", "custom": ""},
            {"allow_empty": 1},
        ):
            with self.assertRaises(ValueError):
                assistant.compose(request)
        with self.assertRaisesRegex(ValueError, "无效"):
            assistant.test_pattern({"pattern": "(", "positive": ["abc"]})

    def test_timeout_kills_worker_and_releases_capacity(self):
        started = monotonic()
        with patch.object(assistant, "TEST_TIMEOUT", 0.25):
            with self.assertRaisesRegex(ValueError, "已终止"):
                assistant.test_pattern({"pattern": r"(a+)+$", "positive": ["a" * 60 + "!"]})
        self.assertLess(monotonic() - started, 5)
        self.assertEqual(assistant.test_pattern({"pattern": "a", "positive": ["a"]})["passed"], 1)
        assistant.WORKERS.acquire()
        assistant.WORKERS.acquire()
        try:
            with self.assertRaises(assistant.RegexBusyError):
                assistant.test_pattern({"pattern": "a", "positive": ["a"]})
        finally:
            assistant.WORKERS.release()
            assistant.WORKERS.release()

    def test_routes_auth_errors_and_no_pipeline_tasks(self):
        with tempfile.TemporaryDirectory() as root:
            app = create_app(root)
            with TestClient(app) as client:
                headers = {"X-Workspace-Token": client.get("/api/bootstrap").json()["token"]}
                templates = client.get("/api/regex/templates")
                self.assertEqual(len(templates.json()["templates"]), 9)
                self.assertEqual(client.post("/api/regex/test", json={}).status_code, 403)
                response = client.post(
                    "/api/regex/build",
                    headers=headers,
                    json={"prefix": "1", "min_length": 10, "max_length": 10},
                )
                pattern = response.json()["pattern"]
                tested = client.post(
                    "/api/regex/test",
                    headers=headers,
                    json={
                        "pattern": pattern,
                        "positive": ["13812345678"],
                        "negative": ["23812345678", "138123456789", ""],
                    },
                )
                self.assertEqual(tested.status_code, 200, tested.text)
                self.assertEqual(tested.json()["passed"], 4)
                self.assertEqual(
                    client.post(
                        "/api/regex/test", headers=headers, json={"pattern": "(", "positive": ["a"]}
                    ).status_code,
                    422,
                )
                self.assertEqual(client.get("/api/health").status_code, 200)
                self.assertEqual(len(app.state.jobs._jobs), 0)
