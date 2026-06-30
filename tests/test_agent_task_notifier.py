#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "agent_task_notifier.py"


def load_notifier():
    scripts_dir = str(SCRIPT_PATH.parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location("agent_task_notifier_for_test", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class AgentTaskNotifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.notifier = load_notifier()

    def test_build_failure_message_includes_reason_and_log(self) -> None:
        message = self.notifier.build_message(
            "ops.example",
            {
                "status": "failed",
                "message": "页面结构变化",
                "step": "采集",
                "log_path": "/tmp/example.log",
                "failure_type": "page_structure",
                "finished_at": "2026-06-30 17:00:00",
            },
            {"name": "示例任务", "rerun": {"suggested": True, "auto_allowed": False, "reason": "只报告。"}},
        )

        self.assertIn("[失败] Mac mini 自动化任务：示例任务", message)
        self.assertIn("失败原因：页面结构变化", message)
        self.assertIn("日志/证据：/tmp/example.log", message)
        self.assertIn("处理建议：只报告。", message)

    def test_notify_deduplicates_terminal_task_signatures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            runs_path = tmp_path / "runs.json"
            state_path = tmp_path / "state.json"
            log_path = tmp_path / "log.json"
            runs_path.write_text(
                json.dumps(
                    {
                        "tasks": {
                            "ops.example": {
                                "status": "success",
                                "message": "完成",
                                "step": "汇总",
                                "finished_at": "2026-06-30 17:00:00",
                            }
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            args = type(
                "Args",
                (),
                {
                    "runs": str(runs_path),
                    "state": str(state_path),
                    "log": str(log_path),
                    "target": "weixin",
                    "hermes_bin": "hermes",
                    "seed": False,
                    "dry_run": True,
                    "no_write": False,
                },
            )()

            first = self.notifier.notify(args)
            second = self.notifier.notify(args)

            self.assertEqual(first["notification_count"], 1)
            self.assertEqual(second["notification_count"], 0)


if __name__ == "__main__":
    unittest.main()
