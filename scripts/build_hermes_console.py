#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import os
import platform
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "ai-business-center" / "dashboard" / "hermes.html"
DEFAULT_JSON_OUTPUT = ROOT / "ai-business-center" / "dashboard" / "hermes-status.json"
HERMES_HOME = Path.home() / ".hermes"
HERMES_LOG = HERMES_HOME / "logs" / "gateway.log"
HERMES_ERROR_LOG = HERMES_HOME / "logs" / "gateway.error.log"
MEMORY_PATH = ROOT / "ai-business-center" / "config" / "hermes_business_memory.md"
TASK_REPORT_PATH = ROOT / "outputs" / "agent_task_monitor" / "latest.json"
TASK_REPORT_TEXT_PATH = ROOT / "outputs" / "agent_task_monitor" / "latest.txt"
NOTIFIER_LOG_PATH = ROOT / "outputs" / "agent_task_notifications" / "latest.log"
PRIVATE_OUTBOX = Path.home() / "HermesPrivate" / "outbox"
LAUNCHD_LABELS = {
    "Hermes 网关": "ai.hermes.gateway",
    "自动化任务通知器": "com.summer.operation.agent-task-notifier",
}


def now_text() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def read_json(path: Path, fallback: Any) -> Any:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback
    return payload if payload is not None else fallback


def read_tail(path: Path, *, limit: int = 80) -> list[str]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []
    return lines[-limit:]


def run_command(command: list[str], *, timeout: int = 8) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            command,
            cwd=str(ROOT),
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
    except Exception as exc:
        return 1, str(exc)
    return completed.returncode, (completed.stdout or "").strip()


def launchd_status(label: str) -> dict[str, Any]:
    if platform.system() != "Darwin":
        return {"label": label, "state": "unknown", "detail": "launchctl 仅在 macOS 可用"}
    rc, output = run_command(["launchctl", "print", f"gui/{os.getuid()}/{label}"])
    if rc != 0:
        return {"label": label, "state": "not_loaded", "detail": output}
    state = "unknown"
    pid = ""
    last_exit = ""
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("state =") and state == "unknown":
            state = stripped.split("=", 1)[1].strip()
        elif stripped.startswith("pid =") and not pid:
            pid = stripped.split("=", 1)[1].strip()
        elif stripped.startswith("last exit code =") and not last_exit:
            last_exit = stripped.split("=", 1)[1].strip()
    return {"label": label, "state": state, "pid": pid, "last_exit_code": last_exit, "detail": output[:1200]}


def memory_summary() -> dict[str, Any]:
    text = ""
    try:
        text = MEMORY_PATH.read_text(encoding="utf-8")
    except Exception:
        pass
    headings = [
        line.strip("# ").strip()
        for line in text.splitlines()
        if line.startswith("## ")
    ]
    return {
        "path": str(MEMORY_PATH),
        "exists": MEMORY_PATH.exists(),
        "headings": headings,
        "updated_at": file_mtime(MEMORY_PATH),
    }


def file_mtime(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec="seconds")
    except Exception:
        return ""


def newest_files(root: Path, *, limit: int = 12) -> list[dict[str, str]]:
    if not root.exists():
        return []
    files: list[Path] = []
    for path in root.rglob("*"):
        if path.is_file():
            files.append(path)
    files.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    rows = []
    for path in files[:limit]:
        rows.append(
            {
                "name": path.name,
                "path": str(path),
                "updated_at": file_mtime(path),
                "size": f"{path.stat().st_size / 1024:.1f} KB",
            }
        )
    return rows


def build_task_report() -> dict[str, Any]:
    if not TASK_REPORT_PATH.exists():
        run_command(["python3", "scripts/agent_task_monitor.py"], timeout=20)
    payload = read_json(TASK_REPORT_PATH, {})
    if not payload:
        return {"summary": {}, "tasks": [], "rerun_plan": [], "wechat_text": ""}
    return payload


def build_payload() -> dict[str, Any]:
    task_report = build_task_report()
    gateway_tail = read_tail(HERMES_LOG, limit=80)
    error_tail = read_tail(HERMES_ERROR_LOG, limit=80)
    statuses = {
        name: launchd_status(label)
        for name, label in LAUNCHD_LABELS.items()
    }
    return {
        "generated_at": now_text(),
        "host": platform.node(),
        "root": str(ROOT),
        "services": statuses,
        "memory": memory_summary(),
        "task_report": task_report,
        "logs": {
            "gateway": gateway_tail,
            "gateway_error": error_tail,
            "notifier": read_tail(NOTIFIER_LOG_PATH, limit=50),
        },
        "files": {
            "private_outbox": newest_files(PRIVATE_OUTBOX),
        },
        "repair_policy": {
            "can_handle_simple_repairs": True,
            "safe_auto_scope": [
                "只读状态检查",
                "低风险/幂等采集的 dry-run 补跑",
                "日志定位和失败原因归类",
                "生成新文件但不覆盖原文件",
                "重启 Hermes 网关或通知器",
            ],
            "requires_confirmation": [
                "推广预算或出价真实修改",
                "订货提交、付款或改收货地址",
                "财务正式入账、飞书 --execute 同步",
                "云端发布和生产代码部署",
            ],
        },
    }


def esc(value: Any) -> str:
    return html.escape(str(value or ""))


def status_badge(status: str) -> str:
    lowered = (status or "").lower()
    if lowered in {"running", "active", "ok", "completed", "success"}:
        return "ok"
    if lowered in {"failed", "error", "danger", "not_loaded"}:
        return "bad"
    if lowered in {"attention", "warn", "warning", "missing", "stale", "not running"}:
        return "warn"
    return "neutral"


def render_service_cards(payload: dict[str, Any]) -> str:
    cards = []
    for name, item in payload["services"].items():
        state = item.get("state", "unknown")
        cards.append(
            f"""
            <article class="card">
              <div class="card-title">{esc(name)}</div>
              <div class="metric {status_badge(state)}">{esc(state)}</div>
              <p>PID {esc(item.get('pid') or '-')}｜last exit {esc(item.get('last_exit_code') or '-')}</p>
            </article>
            """
        )
    return "\n".join(cards)


def render_summary_cards(payload: dict[str, Any]) -> str:
    summary = payload.get("task_report", {}).get("summary") or {}
    values = [
        ("任务总数", summary.get("total", 0), "neutral"),
        ("失败", summary.get("failed", 0), "bad" if summary.get("failed", 0) else "ok"),
        ("需关注", summary.get("attention", 0), "warn" if summary.get("attention", 0) else "ok"),
        ("可 dry-run 补跑", summary.get("auto_rerun_allowed", 0), "warn" if summary.get("auto_rerun_allowed", 0) else "neutral"),
    ]
    return "\n".join(
        f"""
        <article class="card">
          <div class="card-title">{esc(label)}</div>
          <div class="metric {tone}">{esc(value)}</div>
        </article>
        """
        for label, value, tone in values
    )


def render_tasks(payload: dict[str, Any]) -> str:
    tasks = payload.get("task_report", {}).get("tasks") or []
    if not tasks:
        return "<p class=\"empty\">还没有任务报告。运行 scripts/agent_task_monitor.py 后会显示。</p>"
    rows = []
    for item in tasks:
        rerun = item.get("rerun") or {}
        repair = "可 dry-run" if rerun.get("suggested") and rerun.get("auto_allowed") else "只报告" if rerun.get("suggested") else "-"
        reason = item.get("failure_reason") or item.get("human_action") or rerun.get("reason") or ""
        rows.append(
            f"""
            <tr>
              <td>{esc(item.get('name'))}<span>{esc(item.get('id'))}</span></td>
              <td><b class="pill {status_badge(item.get('status'))}">{esc(item.get('status_text') or item.get('status'))}</b></td>
              <td>{esc(item.get('risk'))}</td>
              <td>{esc(repair)}</td>
              <td>{esc(reason)}</td>
              <td>{esc(item.get('last_run_at'))}</td>
            </tr>
            """
        )
    return f"""
    <div class="table-wrap">
      <table>
        <thead><tr><th>任务</th><th>状态</th><th>风险</th><th>修复</th><th>原因/建议</th><th>最近运行</th></tr></thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
    </div>
    """


def render_files(payload: dict[str, Any]) -> str:
    files = payload.get("files", {}).get("private_outbox") or []
    if not files:
        return "<p class=\"empty\">暂无私人文件产物。</p>"
    return "\n".join(
        f"""
        <div class="file-row">
          <strong>{esc(item['name'])}</strong>
          <span>{esc(item['updated_at'])}｜{esc(item['size'])}</span>
          <code>{esc(item['path'])}</code>
        </div>
        """
        for item in files
    )


def render_logs(payload: dict[str, Any]) -> str:
    merged = []
    for label, lines in payload.get("logs", {}).items():
        if not lines:
            continue
        merged.append(f"== {label} ==")
        merged.extend(lines[-30:])
    return esc("\n".join(merged[-120:]) or "暂无日志")


def render_html(payload: dict[str, Any]) -> str:
    memory = payload["memory"]
    policy = payload["repair_policy"]
    safe_scope = "".join(f"<li>{esc(item)}</li>" for item in policy["safe_auto_scope"])
    confirm_scope = "".join(f"<li>{esc(item)}</li>" for item in policy["requires_confirmation"])
    headings = "、".join(memory.get("headings") or [])
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Hermes 工作台</title>
  <style>
    :root {{
      --bg: #f6f7f8;
      --ink: #1d252c;
      --muted: #64717d;
      --line: #d9dee3;
      --panel: #ffffff;
      --ok: #16784b;
      --warn: #9a6a00;
      --bad: #b42318;
      --blue: #22577a;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: var(--ink); background: var(--bg); }}
    header {{ padding: 22px 28px 14px; border-bottom: 1px solid var(--line); background: var(--panel); }}
    h1 {{ margin: 0 0 6px; font-size: 24px; }}
    h2 {{ margin: 0 0 14px; font-size: 17px; }}
    p {{ margin: 0; color: var(--muted); line-height: 1.55; }}
    main {{ padding: 20px 28px 36px; display: grid; gap: 18px; }}
    section {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 18px; }}
    .grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }}
    .card {{ border: 1px solid var(--line); border-radius: 8px; padding: 14px; background: #fbfcfd; min-height: 96px; }}
    .card-title {{ color: var(--muted); font-size: 13px; margin-bottom: 10px; }}
    .metric {{ font-size: 28px; font-weight: 700; line-height: 1; }}
    .ok {{ color: var(--ok); }}
    .warn {{ color: var(--warn); }}
    .bad {{ color: var(--bad); }}
    .neutral {{ color: var(--blue); }}
    .pill {{ display: inline-block; min-width: 64px; border-radius: 999px; padding: 4px 8px; background: #eef2f5; font-size: 12px; text-align: center; }}
    .pill.ok {{ background: #e6f4ee; }}
    .pill.warn {{ background: #fff4d7; }}
    .pill.bad {{ background: #fde8e7; }}
    .table-wrap {{ overflow-x: auto; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ padding: 10px 8px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }}
    th {{ color: var(--muted); font-weight: 600; }}
    td span {{ display: block; color: var(--muted); font-size: 12px; margin-top: 4px; }}
    .two {{ display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }}
    ul {{ margin: 8px 0 0; padding-left: 18px; color: var(--muted); line-height: 1.6; }}
    code {{ display: block; color: #334; overflow-wrap: anywhere; margin-top: 4px; }}
    .file-row {{ padding: 10px 0; border-bottom: 1px solid var(--line); }}
    .file-row span {{ display: block; color: var(--muted); font-size: 12px; margin-top: 4px; }}
    pre {{ margin: 0; max-height: 420px; overflow: auto; white-space: pre-wrap; font-size: 12px; line-height: 1.5; background: #111820; color: #dce7ef; padding: 14px; border-radius: 8px; }}
    .empty {{ color: var(--muted); }}
    @media (max-width: 900px) {{ .grid, .two {{ grid-template-columns: 1fr; }} main, header {{ padding-left: 16px; padding-right: 16px; }} }}
  </style>
</head>
<body>
  <header>
    <h1>Hermes 工作台</h1>
    <p>生成时间：{esc(payload['generated_at'])}｜主机：{esc(payload['host'])}｜项目：{esc(payload['root'])}</p>
  </header>
  <main>
    <section>
      <h2>服务状态</h2>
      <div class="grid">{render_service_cards(payload)}</div>
    </section>
    <section>
      <h2>自动化摘要</h2>
      <div class="grid">{render_summary_cards(payload)}</div>
    </section>
    <section>
      <h2>任务与修复边界</h2>
      {render_tasks(payload)}
    </section>
    <section class="two">
      <div>
        <h2>Hermes 记忆</h2>
        <p>路径：{esc(memory.get('path'))}</p>
        <p>章节：{esc(headings or '未读取')}</p>
      </div>
      <div>
        <h2>简单修复能力</h2>
        <p>可以做：</p>
        <ul>{safe_scope}</ul>
        <p style="margin-top:10px">必须确认：</p>
        <ul>{confirm_scope}</ul>
      </div>
    </section>
    <section>
      <h2>最近私人文件产物</h2>
      {render_files(payload)}
    </section>
    <section>
      <h2>最近日志</h2>
      <pre>{render_logs(payload)}</pre>
    </section>
  </main>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 Hermes 本地工作台静态页")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--json-output", default=str(DEFAULT_JSON_OUTPUT))
    args = parser.parse_args()
    payload = build_payload()
    output = Path(args.output).expanduser()
    json_output = Path(args.json_output).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    json_output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_html(payload), encoding="utf-8")
    json_output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Hermes 工作台已生成：{output}")
    print(f"Hermes 状态 JSON 已生成：{json_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
