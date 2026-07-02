from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_current_budget.zsh"


def test_current_budget_does_not_read_step_rc_after_fi():
    text = SCRIPT.read_text(encoding="utf-8")

    assert "if run_with_timeout \"$seconds\" \"$@\"; then" not in text
    assert "if run_with_retry \"$step\" \"$seconds\" \"$attempts\" \"$@\"; then" not in text

    assert "run_with_timeout \"$seconds\" \"$@\"\n    exit_status=$?" in text
    assert "run_with_retry \"$step\" \"$seconds\" \"$attempts\" \"$@\"\n  rc=$?" in text
    assert "run_with_timeout \"$seconds\" \"$@\"\n  rc=$?" in text
