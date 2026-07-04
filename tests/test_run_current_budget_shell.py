from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_current_budget.zsh"
REALTIME_SCRIPT = ROOT / "scripts" / "run_realtime_order_income.zsh"
INSTALL_SCRIPT = ROOT / "scripts" / "install_macmini_operation_launchd.zsh"
DEPLOY_SCRIPT = ROOT / "scripts" / "deploy_workbench_to_cloud.zsh"
MORNING_SCRIPT = ROOT / "morning-ops" / "run_morning_ops.py"
LOGIN_PREFLIGHT_SCRIPT = ROOT / "scripts" / "check_platform_login_preflight.py"
OPS_NOTIFY_SCRIPT = ROOT / "scripts" / "ops_notify.py"


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
    assert "NOTIFY_RUNNER=\"$ROOT/scripts/ops_notify.py\"" in text
    assert "notify_realtime_failure_once \"$failure_message\"" in text
    assert "last_notify_signature.txt" in text


def test_macmini_installer_emits_realtime_runner_rc_handling():
    text = INSTALL_SCRIPT.read_text(encoding="utf-8")

    assert "if run_with_timeout \"\\$seconds\" \"\\$@\"; then" not in text
    assert "run_with_timeout \"\\$seconds\" \"\\$@\"\n  local rc=\\$?" in text
    assert "if [[ \"\\$FINAL_RC\" -eq 0 ]]; then\n    FINAL_RC=\"\\$rc\"\n  fi" in text
    assert "[[ ! -f \"\\$ensure_script\" || ! -x \"\\$ensure_script\" ]]" in text
    assert "python_has_playwright" in text
    assert "已用当前 Python 直接确认 Playwright 可用，继续采集" in text
    assert "NOTIFY_RUNNER=\"\\$ROOT/scripts/ops_notify.py\"" in text
    assert "notify_realtime_failure_once \"\\$failure_message\"" in text
    assert "last_notify_signature.txt" in text


def test_data_only_deploy_verifies_direct_latest_from_stage_dir():
    text = DEPLOY_SCRIPT.read_text(encoding="utf-8")

    assert 'verify_remote_file "business-report-dashboard/data/direct-latest.json" "$STAGE_DIR/business-report-dashboard/data/direct-latest.json"' in text
    assert 'verify_remote_file "business-report-dashboard/data/direct-latest.json"\n' not in text


def test_production_entrypoints_run_login_preflight_before_platform_work():
    budget_text = SCRIPT.read_text(encoding="utf-8")
    morning_text = MORNING_SCRIPT.read_text(encoding="utf-8")
    realtime_text = REALTIME_SCRIPT.read_text(encoding="utf-8")

    assert "$REPORT_PYTHON\" \"$LOGIN_PREFLIGHT_RUNNER\" --scope budget --notify" in budget_text
    assert "[sys.executable, str(LOGIN_PREFLIGHT_RUNNER), \"--scope\", \"morning\", \"--notify\"]" in morning_text
    assert "\"$PYTHON\" \"$LOGIN_PREFLIGHT_RUNNER\" --scope realtime --notify" in realtime_text
    assert "PREFLIGHT_RC=$?" in realtime_text


def test_login_preflight_notifies_and_uses_auth_exit_code():
    text = LOGIN_PREFLIGHT_SCRIPT.read_text(encoding="utf-8")

    assert "【运营自动化开跑前预检失败】" in text
    assert "return 66" in text
    assert "notify(notice)" in text


def test_ops_notify_marks_legacy_channels_unused_by_default():
    text = OPS_NOTIFY_SCRIPT.read_text(encoding="utf-8")

    assert "WorkBuddy/Hermes 已标记为 legacy" in text
    assert "legacy_fallback_enabled(config)" in text
    assert "OPS_NOTIFY_ALLOW_LEGACY_FALLBACK" in text
    assert "workbuddy_hermes_send_compat.zsh" in text
    assert "[hermes_bin, \"send\", \"--to\", target, text]" in text
    assert "[workbuddy_bin, \"send\", \"--to\", target, text]" in text
    assert ".hermes\" / \"hermes-agent\" / \"venv\" / \"bin\" / \"hermes" in text
