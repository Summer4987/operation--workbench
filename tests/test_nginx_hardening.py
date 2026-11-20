import importlib.util
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('hardening',ROOT/'security/nginx_hardening.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
HTTP='''server {
 listen 80;
 server_name _;
 client_max_body_size 30m;
 include /etc/nginx/snippets/qiwei-acme-challenge.conf;
 location = /_operation_auth { proxy_pass http://127.0.0.1:8020/api/access/check; }
 location /api/access/ { proxy_pass http://127.0.0.1:8020; }
 location /operation-workbench/ { auth_request /_operation_auth; }
 location /beijing-order/ { proxy_pass http://127.0.0.1:8010; }
}'''
TLS='''server {
 listen 443 ssl;
 client_max_body_size 1m;
 location ^~ /avatar/ { proxy_pass http://127.0.0.1:28965; }
 location / { return 404; }
}'''
def test_preserves_backend_auth_and_avatar_while_redirecting_users():
    http,tls,routes=m.configurations(HTTP,TLS)
    assert 'return 308 https://139.155.148.169$request_uri' in http
    assert '/.well-known' not in http # ACME is preserved via its unchanged include.
    assert 'include /etc/nginx/snippets/qiwei-acme-challenge.conf;' in http
    assert 'location = /agent-wecom/callback' in http
    assert 'auth_request /_operation_auth' in routes
    assert '127.0.0.1:8020/api/access/check' in routes
    assert 'listen ' not in routes
    assert 'location ^~ /avatar/' in tls and m.INCLUDE in tls
    assert m.configurations(HTTP,tls)[1]==tls

def test_refuses_ambiguous_gateway():
    with pytest.raises(ValueError):m.configurations(HTTP+HTTP,TLS)
    with pytest.raises(ValueError):m.configurations(HTTP,TLS.replace('location / { return 404; }',''))
