"""Public search terms only. No memory, files, credentials or browser session supplied."""
import json
import re
import sys
import html
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET


def parse_feed(raw):
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise ValueError('搜索结果格式异常')
    root = ET.fromstring(raw)
    results = []
    for item in root.findall('./channel/item'):
        url = item.findtext('link') or ''
        p = urllib.parse.urlsplit(url)
        if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password:
            continue
        clean = lambda s: re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]*>', '', s or ''))).strip()
        title = clean(item.findtext('title'))[:160]
        if title and url not in [r['url'] for r in results]:
            results.append({'title':title,'url':url,'snippet':clean(item.findtext('description'))[:300]})
    return results[:5]


def search(query):
    if not isinstance(query, str) or not 2 <= len(query) <= 300:
        raise ValueError('搜索词请写2至300字')
    url = 'https://www.bing.com/search?' + urllib.parse.urlencode({'q':query,'format':'rss','count':5})
    req = urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0','Accept':'application/rss+xml,application/xml'})
    with urllib.request.urlopen(req,timeout=12) as response:
        host = urllib.parse.urlsplit(response.geturl()).hostname or ''
        if host != 'bing.com' and not host.endswith('.bing.com'):
            raise ValueError('搜索入口跳转异常')
        raw = response.read(512001)
    if len(raw)>512000:
        raise ValueError('搜索结果过大，请换用更短的关键词')
    try:
        results=parse_feed(raw)
    except (ET.ParseError,ValueError):
        raise ValueError('搜索入口暂不可用或需要验证，请稍后重试')
    if not results:
        raise ValueError('没有可用搜索结果；可以换一组关键词，不能据此判断事实不存在')
    return {'provider':'Bing 公开搜索','query':query,'results':results,'scope':'仅搜索结果标题、链接和摘要；未读取网页正文'}


if __name__=='__main__':
    try:
        print(json.dumps(search(json.load(sys.stdin)['query']),ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({'error':str(exc) if isinstance(exc,ValueError) else '联网搜索失败或超时，请稍后重试'},ensure_ascii=False))
        sys.exit(1)
