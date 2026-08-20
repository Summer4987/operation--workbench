from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_current_budget.zsh"
REALTIME_SCRIPT = ROOT / "scripts" / "run_realtime_order_income.zsh"
INSTALL_SCRIPT = ROOT / "scripts" / "install_macmini_operation_launchd.zsh"
DEPLOY_SCRIPT = ROOT / "scripts" / "deploy_workbench_to_cloud.zsh"
MORNING_SCRIPT = ROOT / "morning-ops" / "run_morning_ops.py"
LOGIN_PREFLIGHT_SCRIPT = ROOT / "scripts" / "check_platform_login_preflight.py"
OPS_NOTIFY_SCRIPT = ROOT / "scripts" / "ops_notify.py"
TAKEOVER_SCRIPT = ROOT / "scripts" / "macmini_takeover_clean_checkout.zsh"
PROMO_BALANCE_REFRESH_SCRIPT = ROOT / "scripts" / "run_promo_balance_refresh.zsh"
PROMO_BALANCE_INSTALL_SCRIPT = ROOT / "scripts" / "install_promo_balance_refresh_launchd.zsh"


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


def test_meituan_budget_isolates_failed_preflight_stores():
    text = SCRIPT.read_text(encoding="utf-8")

    assert '--preflight-result-output "$MEITUAN_PREFLIGHT_RESULT"' in text
    assert '--mode commit --stores "$MEITUAN_PASSED_STORES"' in text
    assert "单店预检失败，已隔离跳过" in text
    assert "没有任何门店通过预检，已跳过真实提交" in text


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
    assert "恢复平台登录/验证码" in text
    assert "确认已切到连锁/全部门店视图" in text
    assert "恢复美团登录/验证码" not in text
    assert "REALTIME_COLLECT_RETRY_ATTEMPTS" in text
    assert "首次实时采集未通过完整性校验" in text
    assert text.count('"$ROOT/scripts/realtime_order_income.py"') == 2


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
    assert "恢复平台登录/验证码" in text
    assert "确认已切到连锁/全部门店视图" in text
    assert "恢复美团登录/验证码" not in text
    assert "REALTIME_COLLECT_RETRY_ATTEMPTS" in text
    assert "首次实时采集未通过完整性校验" in text
    assert text.count('"\\$ROOT/scripts/realtime_order_income.py"') == 2
    assert '"$SOURCE_ROOT/config/ops_notify.json" != "$ROOT/config/ops_notify.json"' in text


def test_data_only_deploy_verifies_direct_latest_from_stage_dir():
    text = DEPLOY_SCRIPT.read_text(encoding="utf-8")

    assert 'verify_remote_file "business-report-dashboard/data/direct-latest.json" "$STAGE_DIR/business-report-dashboard/data/direct-latest.json"' in text
    assert 'verify_remote_file "business-report-dashboard/data/direct-latest.json"\n' not in text


def test_deploy_rejects_realtime_history_regression_and_verifies_upload():
    text = DEPLOY_SCRIPT.read_text(encoding="utf-8")

    assert "validate_realtime_history_deploy" in text
    assert "local_latest < remote_latest" in text
    assert "local_latest == remote_latest and local_count < remote_count" in text
    assert "history_regressed" in text
    assert "ALLOW_REALTIME_HISTORY_SHRINK" in text
    assert "PUBLISH_REALTIME_HISTORY=0" in text
    assert "本次保留线上实时历史，继续发布其它工作台数据" in text
    assert text.count(
        'verify_remote_file "data/realtime-history.json" "$STAGE_DIR/data/realtime-history.json"'
    ) == 2


def test_deploy_preserves_newer_cloud_franchise_daily_data():
    text = DEPLOY_SCRIPT.read_text(encoding="utf-8")

    assert "validate_franchise_daily_deploy" in text
    assert "local_latest < remote_latest" in text
    assert "ALLOW_FRANCHISE_DAILY_REGRESSION" in text
    assert "PUBLISH_FRANCHISE_DAILY=0" in text
    assert "本次保留线上日报，继续发布其它工作台数据" in text
    assert 'if [[ "$PUBLISH_FRANCHISE_DAILY" == "1" ]]; then' in text


def test_production_entrypoints_run_login_preflight_before_platform_work():
    budget_text = SCRIPT.read_text(encoding="utf-8")
    morning_text = MORNING_SCRIPT.read_text(encoding="utf-8")
    realtime_text = REALTIME_SCRIPT.read_text(encoding="utf-8")

    assert "--scope budget --platform eleme --notify" in budget_text
    assert "--scope budget --platform meituan --notify" in budget_text
    assert "饿了么预检失败，已隔离跳过；继续执行美团" in budget_text
    assert 'if [[ "$MODE" != "commit" || "$ELEME_LOGIN_OK" -eq 1 ]]; then' in budget_text
    assert 'budget_preflight_args = [sys.executable, str(LOGIN_PREFLIGHT_RUNNER), "--scope", "budget", "--notify"]' in morning_text
    assert "\"$PYTHON\" \"$LOGIN_PREFLIGHT_RUNNER\" --scope realtime --notify" in realtime_text
    assert "PREFLIGHT_RC=$?" in realtime_text


def test_scheduled_morning_skips_only_eleme_budget():
    morning_text = MORNING_SCRIPT.read_text(encoding="utf-8")
    installer_text = INSTALL_SCRIPT.read_text(encoding="utf-8")

    assert 'skip_eleme_budget = env_flag("MORNING_SKIP_ELEME_BUDGET")' in morning_text
    assert 'budget_preflight_args.extend(["--platform", "meituan"])' in morning_text
    assert "按临时运营设置跳过饿了么" in morning_text
    assert "美团预算及其它采集、看板任务照常执行" in morning_text
    assert "export MORNING_SKIP_ELEME_BUDGET=1" in installer_text


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


def test_macmini_takeover_defaults_outside_documents():
    text = TAKEOVER_SCRIPT.read_text(encoding="utf-8")

    assert "$HOME/Library/Application Support/xiong-operation/production" in text
    assert 'CLEAN_DIR="${MACMINI_TAKEOVER_DIR:-$HOME/Documents/' not in text


def test_promo_balance_refresh_collects_builds_and_deploys_data_only():
    text = PROMO_BALANCE_REFRESH_SCRIPT.read_text(encoding="utf-8")
    installer = PROMO_BALANCE_INSTALL_SCRIPT.read_text(encoding="utf-8")

    assert "store-inspection/run_all_balances.py" in text
    assert "scripts/build_promo_balance_status.py" in text
    assert "scripts/build_task_health.py" in text
    assert "scripts/build_workbench_data.py" in text
    assert "OPERATION_CLOUD_DEPLOY_MODE=data-only" in text
    assert "promo_balance_refresh.lock" in text
    assert 'for hour in {9..20}' in installer
    assert "<integer>15</integer>" in installer


def test_low_balance_notifications_only_follow_morning_and_afternoon_budget_runs():
    budget_text = SCRIPT.read_text(encoding="utf-8")
    morning_text = MORNING_SCRIPT.read_text(encoding="utf-8")
    notifier_text = (ROOT / "scripts" / "agent_task_notifier.py").read_text(encoding="utf-8")

    assert '--promo-balance-period "$BALANCE_NOTIFY_PERIOD"' in budget_text
    assert '"--promo-balance-period", "上午"' in morning_text
    assert 'task_candidates.update(load_promo_balance_alert_tasks())' not in notifier_text
    assert 'choices=("上午", "下午")' in notifier_text


def test_budget_support_failures_do_not_report_budget_setting_failed():
    text = SCRIPT.read_text(encoding="utf-8")

    assert "run_support_step()" in text
    assert 'run_support_step "运营总看板发布"' in text
    assert 'run_support_step "推广预算重试策略刷新"' in text
    assert "附属步骤失败（不代表预算设置失败）" in text
    assert "预算设置成功；附属步骤失败" in text


def test_inventory_warning_is_installed_as_separate_4pm_notification():
    installer = INSTALL_SCRIPT.read_text(encoding="utf-8")

    assert 'run_inventory_warning_daily.zsh' in installer
    assert 'write_plist "com.summer.operation.inventory-warning-daily" 16 0' in installer
    assert 'scripts/send_inventory_warning_daily.py' in installer
