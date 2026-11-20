"""Build shared HTTPS routes without changing existing business routing."""
import re

INCLUDE = 'include /etc/nginx/snippets/xiong-workbench-https.conf;'


def configurations(http, tls):
    if not http.lstrip().startswith('server {') or http.count('listen 80;') != 1:
        raise ValueError('Unknown HTTP server configuration')
    for required in ['location = /_operation_auth {', 'location /api/access/ {', 'location /operation-workbench/ {']:
        if http.count(required) != 1: raise ValueError('Missing or ambiguous authorization route')
    body = http[http.index('{')+1:http.rfind('}')]
    body = re.sub(r'^\s*(?:listen 80;|server_name _;|client_max_body_size 30m;|include /etc/nginx/snippets/qiwei-acme-challenge.conf;)\s*$', '', body, flags=re.M)
    if 'listen ' in body or 'ssl_certificate' in body: raise ValueError('Unexpected server directives')
    routes = '# GitHub main managed authenticated business routes\n'+body+'\n'
    if INCLUDE not in tls:
        if tls.count('location / { return 404; }') != 1: raise ValueError('Unknown TLS fallback')
        tls=tls.replace('location / { return 404; }',INCLUDE)
    tls=tls.replace('    client_max_body_size 1m;','    client_max_body_size 30m;',1)
    redirect='''# GitHub main managed: all user-facing access uses verified HTTPS.
server {
    listen 80;
    server_name _;
    include /etc/nginx/snippets/qiwei-acme-challenge.conf;
    # Keep the existing signed/encrypted provider callback at its configured URL.
    location = /agent-wecom/callback {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    location / { return 308 https://139.155.148.169$request_uri; }
}
'''
    return redirect, tls, routes
