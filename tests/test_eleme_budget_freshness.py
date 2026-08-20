from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_budget_state_must_come_from_current_run_and_reject_rate_limit_page():
    adapter = (ROOT / "scripts" / "eleme_dianjin_adapter.mjs").read_text(encoding="utf-8")
    runner = (ROOT / "scripts" / "run_eleme_automation.zsh").read_text(encoding="utf-8")

    assert '--since "$RUN_STARTED_EPOCH"' in runner
    assert "系统被限流" in adapter
    assert "禁止使用历史快照" in adapter


def test_zero_action_commit_requires_verified_no_changes():
    adapter = (ROOT / "scripts" / "eleme_dianjin_adapter.mjs").read_text(encoding="utf-8")
    runner = (ROOT / "scripts" / "run_eleme_automation.zsh").read_text(encoding="utf-8")

    assert "verifiedNoChanges" in adapter
    assert 'payload.get("total") == 0 and not payload.get("verifiedNoChanges")' in runner


def test_direct_read_can_reuse_latest_historical_probe_with_matching_api():
    adapter = (ROOT / "scripts" / "eleme_dianjin_adapter.mjs").read_text(encoding="utf-8")

    assert 'latestProbeWithApi("method=queryBranchSolutions")' in adapter
    assert 'latestProbeFiles("eleme_store_probe_", 200)' in adapter


def test_rate_limited_direct_read_fails_and_budget_does_not_immediately_retry():
    adapter = (ROOT / "scripts" / "eleme_dianjin_adapter.mjs").read_text(encoding="utf-8")
    current_runner = (ROOT / "scripts" / "run_current_budget.zsh").read_text(encoding="utf-8")

    assert "饿了么推广计划接口失败" in adapter
    assert '"${ELEME_BUDGET_RETRIES:-1}"' in current_runner
