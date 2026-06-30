from __future__ import annotations

import argparse
import html
import json
import sys
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import finance_inbox  # noqa: E402


CSS = """
:root {
  color-scheme: light;
  --ink: #1f2933;
  --muted: #64748b;
  --line: #d9e2ec;
  --soft: #f6f8fb;
  --panel: #ffffff;
  --accent: #0f766e;
  --danger: #b42318;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  color: var(--ink);
  background: #eef2f6;
}
header {
  padding: 18px 28px;
  background: var(--panel);
  border-bottom: 1px solid var(--line);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
h1 { margin: 0; font-size: 22px; font-weight: 700; }
main { max-width: 1180px; margin: 0 auto; padding: 24px; }
.layout { display: grid; grid-template-columns: minmax(360px, 0.9fr) minmax(460px, 1.1fr); gap: 20px; align-items: start; }
section { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 18px; }
h2 { margin: 0 0 14px; font-size: 17px; }
label { display: block; font-weight: 600; margin: 14px 0 7px; }
textarea, input {
  width: 100%;
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 10px 12px;
  font: inherit;
  background: white;
}
textarea { min-height: 132px; resize: vertical; }
.row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
button {
  margin-top: 14px;
  border: 0;
  border-radius: 6px;
  padding: 10px 14px;
  background: var(--accent);
  color: white;
  font-weight: 700;
  cursor: pointer;
}
.secondary { background: #334155; }
.muted { color: var(--muted); font-size: 13px; line-height: 1.45; }
.notice { padding: 10px 12px; border-radius: 6px; margin-bottom: 14px; background: #ecfdf5; border: 1px solid #a7f3d0; }
.error { background: #fff1f2; border-color: #fecdd3; color: var(--danger); }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { border-bottom: 1px solid var(--line); padding: 9px 8px; text-align: left; vertical-align: top; }
th { color: var(--muted); font-weight: 700; background: var(--soft); }
.pill { display: inline-block; border-radius: 999px; padding: 2px 8px; background: #e2e8f0; white-space: nowrap; }
.toolbar { display: flex; gap: 10px; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.empty { padding: 24px; text-align: center; color: var(--muted); background: var(--soft); border-radius: 6px; }
@media (max-width: 900px) {
  .layout { grid-template-columns: 1fr; }
  main { padding: 14px; }
  header { padding: 14px; align-items: flex-start; flex-direction: column; }
}
"""


def page(title: str, body: str) -> bytes:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>{CSS}</style>
</head>
<body>
  <header>
    <div>
      <h1>熊小小财务系统</h1>
      <div class="muted">录入只生成待确认草稿；人工确认后才进入账本，显式同步后才写飞书。</div>
    </div>
    <div class="muted">数据目录：{html.escape(str(finance_inbox.DATA_DIR))}</div>
  </header>
  <main>{body}</main>
</body>
</html>""".encode("utf-8")


def pending_drafts() -> list[dict[str, Any]]:
    confirmed_ids = finance_inbox.ledger_draft_ids()
    return [
        draft
        for draft in finance_inbox.latest_draft_states().values()
        if draft.get("status") == finance_inbox.DRAFT_PENDING and draft.get("draft_id") not in confirmed_ids
    ]


def render_drafts() -> str:
    drafts = pending_drafts()
    if not drafts:
        return '<div class="empty">当前没有待确认财务草稿</div>'
    rows = []
    for draft in drafts:
        warnings = draft.get("parse_warnings") or []
        amount_value = draft.get("parsed_amount")
        amount_text = "" if amount_value is None else f"{float(amount_value):.2f}"
        rows.append(
            "<tr>"
            f"<td><code>{html.escape(str(draft.get('draft_id') or ''))}</code></td>"
            f"<td>{html.escape(str(draft.get('parsed_transaction_date') or ''))}</td>"
            f"<td><span class=\"pill\">{html.escape(str(draft.get('parsed_direction') or ''))}</span></td>"
            f"<td>{html.escape(amount_text)}</td>"
            f"<td>{html.escape(str(draft.get('parsed_category') or ''))}</td>"
            f"<td>{html.escape(str(draft.get('parsed_store') or ''))}</td>"
            f"<td>{html.escape(str(draft.get('raw_text') or ''))}<div class=\"muted\">提醒：{html.escape('；'.join(warnings) if warnings else '无')}</div></td>"
            "</tr>"
        )
    return (
        "<table><thead><tr>"
        "<th>草稿ID</th><th>日期</th><th>方向</th><th>金额</th><th>分类</th><th>门店</th><th>原始文本</th>"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def render_home(message: str = "", error: str = "") -> bytes:
    notice = ""
    if message:
        notice = f'<div class="notice">{html.escape(message)}</div>'
    if error:
        notice = f'<div class="notice error">{html.escape(error)}</div>'
    body = f"""
{notice}
<div class="layout">
  <section>
    <h2>录入财务记录</h2>
    <form method="post" action="/intake">
      <label for="raw_text">财务文本</label>
      <textarea id="raw_text" name="raw_text" required placeholder="例如：今天 熊小小万象城 微信支付采购原料 128.50 元 供应商:张三冻品"></textarea>
      <div class="row">
        <div>
          <label for="operator">录入人</label>
          <input id="operator" name="operator" value="finance-web">
        </div>
        <div>
          <label for="hint">状态</label>
          <input id="hint" value="只生成待确认草稿" disabled>
        </div>
      </div>
      <button type="submit">录入草稿</button>
    </form>
    <p class="muted">录入后请在右侧复制草稿 ID，用后台确认命令或后续确认界面人工确认。系统不会从网页录入直接入账。</p>
  </section>
  <section>
    <div class="toolbar">
      <h2>待确认草稿</h2>
      <form method="get" action="/"><button class="secondary" type="submit">刷新</button></form>
    </div>
    {render_drafts()}
  </section>
</div>
"""
    return page("熊小小财务系统", body)


class FinanceHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path not in {"/", "/index.html"}:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self.respond(render_home())

    def do_POST(self) -> None:
        if self.path != "/intake":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_length = int(self.headers.get("Content-Length", "0"))
        payload = self.rfile.read(content_length).decode("utf-8")
        form = urllib.parse.parse_qs(payload)
        raw_text = (form.get("raw_text") or [""])[0].strip()
        operator = (form.get("operator") or ["finance-web"])[0].strip() or "finance-web"
        if not raw_text:
            self.respond(render_home(error="请输入财务文本。"))
            return
        parsed = finance_inbox.parse_wechat_text(raw_text)
        draft = {
            "draft_id": finance_inbox.short_id("fin-draft"),
            "created_at": finance_inbox.now_text(),
            "created_by": operator,
            "status": finance_inbox.DRAFT_PENDING,
            "source_channel": "manual",
            "raw_text": raw_text,
            **parsed,
            "safety_notice": "本记录来自网页录入口，只是待确认草稿，不会自动写入账本或飞书。",
        }
        finance_inbox.append_jsonl(finance_inbox.DRAFTS_PATH, draft)
        warnings = draft.get("parse_warnings") or []
        message = f"已录入待确认草稿：{draft['draft_id']}。"
        if warnings:
            message += " 解析提醒：" + "；".join(str(item) for item in warnings)
        self.respond(render_home(message=message))

    def respond(self, body: bytes) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        print(f"[finance-web] {self.address_string()} - {format % args}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="熊小小财务系统网页录入口。")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-open", action="store_true", help="不自动打开浏览器。")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    server = ThreadingHTTPServer((args.host, args.port), FinanceHandler)
    url = f"http://{args.host}:{args.port}/"
    print(f"熊小小财务系统网页录入口：{url}")
    print("按 Ctrl+C 停止。")
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止财务系统网页录入口。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
