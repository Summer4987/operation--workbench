from types import SimpleNamespace
from unittest import mock

import pytest

from scripts import platform_auth_guard as guard


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setattr(guard, "STATE_DIR", tmp_path)


def test_block_is_platform_specific_persistent_and_requires_confirmation():
    guard.block("美团", "美团安全验证", "https://verify.meituan.com/v2/app/general_page?requestCode=secret")
    with pytest.raises(guard.PlatformAuthBlocked):
        guard.require_access("美团")
    guard.require_access("饿了么")
    assert "requestCode" not in guard.state_path("美团").read_text()
    with pytest.raises(ValueError):
        guard.release("美团", confirmed=False)
    guard.release("美团", confirmed=True)
    guard.require_access("美团")


def test_repeated_block_does_not_refresh_or_duplicate_waiting_state():
    first = guard.block("美团", "安全验证")
    assert guard.block("美团", "重复的安全验证") == first


def test_old_verification_tab_does_not_block_a_new_attempt_but_new_popup_does():
    old = SimpleNamespace(url="https://verify.meituan.com/old")
    page = SimpleNamespace(url="https://e.waimai.meituan.com/")
    page.context = SimpleNamespace(pages=[old, page])
    guard.begin_page_attempt(page)
    assert guard.current_meituan_challenge(page) is None
    current = SimpleNamespace(url="https://verify.meituan.com/new")
    page.context.pages.append(current)
    assert guard.current_meituan_challenge(page) is current


def test_existing_tab_redirected_during_this_attempt_is_a_current_challenge():
    page = SimpleNamespace(url="https://e.waimai.meituan.com/")
    popup = SimpleNamespace(url="about:blank")
    page.context = SimpleNamespace(pages=[page, popup])
    guard.begin_page_attempt(page)
    popup.url = "https://verify.meituan.com/new"
    assert guard.current_meituan_challenge(page) is popup
    page.url = "https://verify.meituan.com/direct"
    assert guard.current_meituan_challenge(page) is page


def test_only_current_auth_failure_suppresses_retry(tmp_path):
    import json
    import os
    path = tmp_path / "failed.json"
    path.write_text(json.dumps({"errors": ["美团安全验证等待人工处理"]}))
    assert guard.failure_needs_human(path, 0)
    os.utime(path, (1, 1))
    assert not guard.failure_needs_human(path, 2)
    path.write_text(json.dumps({"errors": ["Chrome/CDP 接入超时"]}))
    assert not guard.failure_needs_human(path, 0)
