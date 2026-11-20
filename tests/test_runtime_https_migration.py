import importlib.util
from pathlib import Path
spec=importlib.util.spec_from_file_location('https_migrate',Path(__file__).resolve().parents[1]/'security/migrate_runtime_https.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
def test_only_exact_public_origin_is_upgraded():
    old=b'ROOT="http://139.155.148.169"\nAPI=http://139.155.148.169/api/x?token=local-secret\nLOCAL=http://127.0.0.1:8000\nOTHER=http://example.com\nLEGACY=http://139.155.148.169:8088/api/latest\n'
    new=m.upgraded(old)
    assert b'ROOT="https://139.155.148.169"' in new
    assert b'https://139.155.148.169/api/x?token=local-secret' in new
    assert b'http://127.0.0.1:8000' in new and b'http://example.com' in new
    assert b'http://139.155.148.169:8088/api/latest' in new
    assert m.upgraded(new)==new
