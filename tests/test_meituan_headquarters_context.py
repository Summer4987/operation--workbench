from unittest.mock import Mock
from scripts.meituan_headquarters_context import ensure_headquarters_scope


def test_already_all_stores_does_not_switch_or_write():
    page=Mock()
    selector=page.locator.return_value.first
    selector.inner_text.return_value='全部门店'
    ensure_headquarters_scope(page)
    selector.click.assert_not_called()
    page.wait_for_function.assert_not_called()


def test_selected_store_is_restored_and_verified():
    page=Mock()
    selector=page.locator.return_value.first
    selector.inner_text.return_value='熊小小（万松园店）'
    page.get_by_text.return_value.count.return_value=0
    ensure_headquarters_scope(page)
    selector.click.assert_called_once()
    page.get_by_text.return_value.first.click.assert_called_once()
    page.wait_for_function.assert_called_once()


def test_missing_login_never_clicks_store_or_proceeds():
    page=Mock()
    selector=page.locator.return_value.first
    selector.wait_for.side_effect=TimeoutError('login')
    try:
        ensure_headquarters_scope(page)
    except RuntimeError as error:
        assert '登录或安全验证' in str(error)
    else:
        raise AssertionError('missing login accepted')
    selector.click.assert_not_called()
