from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_current_budget.zsh"
REALTIME_SCRIPT = ROOT / "scripts" / "run_realtime_order_income.zsh"
INSTALL_SCRIPT = ROOT / "scripts" / "install_macmini_operation_launchd.zsh"


def test_current_budget_does_not_read_step_rc_after_fi():
    text = SCRIPT.read_text(encoding="utf-8")

    assert "if run_with_timeout \"$seconds\" \"$@\"; then" not in text
    assert "if run_with_retry \"$step\" \"$seconds\" \"$attempts\" \"$@\"; then" not in text

    assert "run_with_timeout \"$seconds\" \"$@\"\n    exit_status=$?" in text
    assert "run_with_retry \"$step\" \"$seconds\" \"$attempts\" \"$@\"\n  rc=$?" in text
    assert "run_with_timeout \"$seconds\" \"$@\"\n  rc=$?" in text


def test_direct_meituan_accounts_sync_skips_identical_runtime_file():
    text = SCRIPT.read_text(encoding="utf-8")

    assert "/usr/bin/cmp -s \"$direct_accounts_source\" \"$direct_accounts_target\"" in text
    assert "美团直营账号配置已是最新，跳过重复复制" in text
    assert "/bin/cp \"$ROOT/config/direct_meituan_accounts.json\" \"$NODE_RUNTIME_ROOT/config/direct_meituan_accounts.json\"" not in text


def test_realtime_runner_preserves_collect_failure_after_followup_failure():
    text = REALTIME_SCRIPT.read_text(encoding="utf-8")

    assert "if run_with_timeout \"$seconds\" \"$@\"; then" not in text
    assert "run_with_timeout \"$seconds\" \"$@\"\n  local rc=$?" in text
    assert "if [[ \"$FINAL_RC\" -eq 0 ]]; then\n    FINAL_RC=\"$rc\"\n  fi" in text
    assert "[[ ! -f \"$ensure_script\" || ! -x \"$ensure_script\" ]]" in text
    assert "python_has_playwright" in text
    assert "已用当前 Python 直接确认 Playwright 可用，继续采集" in text


def test_macmini_installer_emits_realtime_runner_rc_handling():
    text = INSTALL_SCRIPT.read_text(encoding="utf-8")

    assert "if run_with_timeout \"\\$seconds\" \"\\$@\"; then" not in text
    assert "run_with_timeout \"\\$seconds\" \"\\$@\"\n  local rc=\\$?" in text
    assert "if [[ \"\\$FINAL_RC\" -eq 0 ]]; then\n    FINAL_RC=\"\\$rc\"\n  fi" in text
    assert "[[ ! -f \"\\$ensure_script\" || ! -x \"\\$ensure_script\" ]]" in text
    assert "python_has_playwright" in text
    assert "已用当前 Python 直接确认 Playwright 可用，继续采集" in text
