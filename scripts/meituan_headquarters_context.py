"""Restore the HQ all-store scope through the visible merchant UI only."""
import re

HOME = "https://e.waimai.meituan.com/"


def ensure_headquarters_scope(page):
    page.goto(HOME, wait_until="domcontentloaded", timeout=45000)
    selector = page.locator(".current-poi_31GHxd").first
    try:
        selector.wait_for(state="visible", timeout=15000)
    except Exception:
        raise RuntimeError("美团总部账号未就绪，请检查登录或安全验证") from None
    if selector.inner_text().strip() == "全部门店":
        return
    # Known informational dialogs only; never dismiss verification challenges.
    known = page.get_by_text("我知道了", exact=True)
    if known.count() and known.first.is_visible():
        known.first.click()
    selector.click()
    page.get_by_text(re.compile(r"^全部门店(?:[（(]共\d+家[）)])?$"), exact=True).first.click(timeout=10000)
    page.wait_for_function("""() => document.querySelector('.current-poi_31GHxd')?.innerText.trim() === '全部门店'""", timeout=15000)
