from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_pac_only_routes_eleme_domains() -> None:
    pac = (ROOT / "config/eleme-proxy.pac").read_text(encoding="utf-8")
    assert 'dnsDomainIs(normalizedHost, ".ele.me")' in pac
    assert 'dnsDomainIs(normalizedHost, ".elemecdn.com")' in pac
    assert 'return "SOCKS5 127.0.0.1:18888"' in pac
    assert 'return "DIRECT"' in pac
    assert "meituan" not in pac.lower()


def test_installer_has_reversible_launchd_services() -> None:
    install = (ROOT / "scripts/install_eleme_proxy_route.zsh").read_text(encoding="utf-8")
    uninstall = (ROOT / "scripts/uninstall_eleme_proxy_route.zsh").read_text(encoding="utf-8")
    assert "com.summer.operation.eleme-proxy-tunnel" in install
    assert "com.summer.operation.eleme-proxy-pac" in install
    assert "-setautoproxyurl" in install
    assert "-setautoproxystate" in install
    assert "-setautoproxystate" in uninstall
    assert "off" in uninstall
