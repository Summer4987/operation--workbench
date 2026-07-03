from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts import agent_pipeline


class AgentPipelineTests(unittest.TestCase):
    def test_execution_agent_is_skipped_by_default(self) -> None:
        record = agent_pipeline.run_stage(
            {"id": "execute", "agent": "execution", "name": "执行 Agent", "command": ["echo", "risk"]},
            allow_execution=False,
            dry_run=False,
        )

        self.assertEqual(record["status"], "skipped")
        self.assertIn("--allow-execution", record["message"])

    def test_required_json_output_must_exist_and_parse(self) -> None:
        original_root = agent_pipeline.ROOT
        try:
            import tempfile

            with tempfile.TemporaryDirectory() as temp_dir:
                tmp_path = Path(temp_dir)
                agent_pipeline.ROOT = tmp_path
                stage = {
                    "id": "validate",
                    "agent": "validate",
                    "required_outputs": ["outputs/example/latest.json"],
                    "json_required": [{"path": "outputs/example/latest.json", "keys": ["generated_at"]}],
                }

                missing_issues = agent_pipeline.validate_required_outputs(stage)
                self.assertIn("缺少产物：outputs/example/latest.json", missing_issues)

                output = tmp_path / "outputs" / "example" / "latest.json"
                output.parent.mkdir(parents=True)
                output.write_text(json.dumps({"generated_at": "2026-07-03 10:00:00"}), encoding="utf-8")

                self.assertEqual(agent_pipeline.validate_required_outputs(stage), [])
        finally:
            agent_pipeline.ROOT = original_root

    def test_notify_text_reports_failed_stage(self) -> None:
        text = agent_pipeline.build_notify_text(
            {"id": "daily_automation_guard", "name": "每日自动化多 Agent 守护"},
            [
                {"status": "success", "name": "采集 Agent"},
                {"status": "failed", "name": "校验 Agent", "message": "缺少产物：outputs/task_runs/latest.json"},
            ],
        )

        self.assertIn("有 1 个 agent 失败", text)
        self.assertIn("校验 Agent", text)

    def test_notify_text_reports_enabled_execution_agent(self) -> None:
        text = agent_pipeline.build_notify_text(
            {"id": "daily_automation_guard", "name": "每日自动化多 Agent 守护"},
            [
                {"status": "success", "name": "采集 Agent", "agent": "collect"},
                {"status": "success", "name": "执行 Agent", "agent": "execution"},
            ],
        )

        self.assertIn("执行 Agent 已参与非订货任务", text)

    def test_pipeline_notify_on_failure_dry_run(self) -> None:
        import argparse
        import tempfile

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            config_path = temp_path / "pipelines.json"
            config_path.write_text(
                json.dumps(
                    {
                        "pipelines": [
                            {
                                "id": "sample",
                                "name": "样例 Agent",
                                "stages": [
                                    {
                                        "id": "bad",
                                        "agent": "validate",
                                        "name": "失败 Agent",
                                        "command": ["{python}", "-c", "import sys; sys.exit(2)"],
                                    }
                                ],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            args = argparse.Namespace(
                pipeline="sample",
                config=str(config_path),
                output_dir=str(temp_path / "outputs"),
                allow_execution=False,
                dry_run=False,
                notify=False,
                notify_on_failure=True,
                notify_dry_run=True,
            )

            payload = agent_pipeline.run_pipeline(args)

            self.assertEqual(payload["summary"]["failed"], 1)
            self.assertEqual(payload["notification"]["delivery_output"], "dry-run")


if __name__ == "__main__":
    unittest.main()
