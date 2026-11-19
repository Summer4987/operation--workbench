"""Surgical, idempotent update of the existing nginx config; keep unrelated routes."""
from pathlib import Path
import re
import sys


def patch(text):
 if 'location = /_operation_auth {' not in text: raise ValueError('Missing existing authorization block')
 text=text.replace('proxy_pass http://127.0.0.1:8000/api/auth/check;', 'proxy_pass http://127.0.0.1:8020/api/access/check;')
 start=text.index('    location = /_operation_auth {');end=text.index('\n    }',start)
 block=text[start:end]
 if 'X-Original-URI' not in block:
  block+='\n        proxy_set_header X-Original-URI $request_uri;\n        proxy_set_header X-Original-Method $request_method;'
 text=text[:start]+block+text[end:]
 for location in ['/login','/api/auth/login']:
  start=text.index('    location = '+location+' {');end=text.index('\n    }',start)
  block=text[start:end].replace('proxy_pass http://127.0.0.1:8000;','proxy_pass http://127.0.0.1:8020;')
  text=text[:start]+block+text[end:]
 if 'location /api/access/ {' not in text:
  location='''    location /api/access/ {
        proxy_pass http://127.0.0.1:8020;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        client_max_body_size 64k;
    }

'''
  position=text.index('    location = /login {')
  text=text[:position]+location+text[position:]
 return text

if __name__=='__main__':
 path=Path(sys.argv[1]);path.write_text(patch(path.read_text()))
