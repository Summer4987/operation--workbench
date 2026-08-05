from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
PROCESSOR = ROOT / "business-report-dashboard" / "process_reports.py"
DEPLOY_SCRIPT = ROOT / "scripts" / "deploy_workbench_to_cloud.zsh"


def load_processor():
    spec = importlib.util.spec_from_file_location("franchise_process_reports_for_test", PROCESSOR)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FranchiseDashboardPublishTests(unittest.TestCase):
    def test_existing_latest_payload_can_be_rendered_without_platform_collection(self):
        module = load_processor()
        with tempfile.TemporaryDirectory() as directory:
            payload_path = Path(directory) / "latest.json"
            payload_path.write_text(
                json.dumps({"generated_at": "2026-08-05 08:09:21", "source_dates": ["2026-08-04"]}),
                encoding="utf-8",
            )
            with mock.patch.object(module, "write_dashboard", return_value=Path(directory) / "index.html") as dashboard:
                with mock.patch.object(module, "write_store_reports", return_value=[]) as stores:
                    result = module.render_existing_payload(payload_path)

        self.assertEqual(result["payload"]["source_dates"], ["2026-08-04"])
        dashboard.assert_called_once()
        stores.assert_called_once()

    def test_workbench_publish_regenerates_and_verifies_franchise_dashboard(self):
        script = DEPLOY_SCRIPT.read_text(encoding="utf-8")

        self.assertIn("process_reports.py --render-existing", script)
        self.assertIn('verify_remote_file "business-report-dashboard/index.html"', script)
        self.assertIn('verify_remote_file "business-report-dashboard/data/latest.json"', script)


if __name__ == "__main__":
    unittest.main()
