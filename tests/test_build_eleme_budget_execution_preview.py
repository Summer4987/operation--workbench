import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NODE = "/Users/summer/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"


def test_builds_oldbranch_budget_preview_without_api_state(tmp_path: Path) -> None:
    source = tmp_path / "source.json"
    output = tmp_path / "preview.json"
    source.write_text(
        json.dumps(
            {
                "eleme_lunch": [
                    {"store": "保利中心店", "shopId": 540966345, "targetBudget": 80}
                ],
                "eleme_dinner": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    subprocess.run(
        [
            NODE,
            str(ROOT / "scripts/build_eleme_budget_execution_preview.mjs"),
            "--time",
            "10:30",
            "--source",
            str(source),
            "--output",
            str(output),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["summary"]["sourceMode"] == "oldBranch-visible-table"
    assert payload["summary"]["missing"] == 0
    assert payload["rows"] == [
        {
            "taskId": "lunch-budget-保利中心店",
            "platform": "饿了么",
            "period": "午餐",
            "time": "10:30",
            "type": "budget",
            "store": "保利中心店",
            "shopId": 540966345,
            "elemeFullName": "",
            "found": True,
            "currentBid": None,
            "bidAssistantStatus": "",
            "currentBudget": None,
            "currentSpend": None,
            "minBid": None,
            "budgetUsage": "",
            "switchStatus": "",
            "targetBudget": 80,
            "expectedSpend": None,
            "bidDelta": 0,
            "targetBid": None,
            "action": "批量页设置午餐预算 80 元",
            "risk": "",
            "canExecute": True,
        }
    ]


def test_budget_wrapper_uses_oldbranch_preview_builder() -> None:
    text = (ROOT / "scripts/run_eleme_automation.zsh").read_text(encoding="utf-8")
    assert "单店斗金计划批量处理（原分店资金）" in text
    assert "build_eleme_budget_execution_preview.mjs" in text
    assert "预算任务改走单店逐家提交路径" not in text


def test_batch_executor_reports_missing_headquarters_context() -> None:
    text = (ROOT / "scripts/eleme_dianjin_adapter.mjs").read_text(encoding="utf-8")
    assert "旧版批量页当前账号未返回任何门店" in text
    assert "Mac mini Chrome 是否登录总部组织账号" in text


def test_budget_wrapper_uses_dedicated_eleme_chrome() -> None:
    text = (ROOT / "scripts/run_eleme_automation.zsh").read_text(encoding="utf-8")
    adapter = (ROOT / "scripts/eleme_dianjin_adapter.mjs").read_text(encoding="utf-8")
    launcher = (ROOT / "scripts/start_eleme_chrome.zsh").read_text(encoding="utf-8")
    assert "ELEME_CDP_DEBUG_URL" in text
    assert "http://127.0.0.1:9223" in text
    assert "start_eleme_chrome.zsh" in text
    assert "ELEME_CDP_DEBUG_URL" in adapter
    assert "eleme-chrome-profile" in launcher
    assert "__path__=eleCpcChain/oldBranch" in launcher
