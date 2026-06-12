#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import html
import json
import os
import re
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CENTER_ROOT = Path(__file__).resolve().parent
DEFAULT_ROOT = Path(__file__).resolve().parents[1]
ROOT = Path(os.environ.get("OPERATION_CENTER_ROOT", str(DEFAULT_ROOT))).expanduser().resolve()
CONFIG_PATH = CENTER_ROOT / "config" / "tasks.json"
STATE_DIR = CENTER_ROOT / "state"
RUN_DIR = STATE_DIR / "runs"
DASHBOARD_PATH = CENTER_ROOT / "dashboard" / "index.html"
NODE = Path("/Users/summer/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node")


AUTH_PATTERNS = ["验证码", "安全验证", "未登录", "登录", "风控", "UNAUTHORIZED", "Permission denied"]
DOWNLOAD_PATTERNS = ["下载失败", "没有下载", "download", "报表", "文件不存在"]
TIMEOUT_PATTERNS = ["timeout", "超时", "Timed out"]
PUBLISH_PATTERNS = ["发布失败", "deploy", "ssh", "rsync", "remote", "云服务器"]


@dataclass
class EvidenceStatus:
    path: str
    status: str
    message: str
    updated_at: str | None
    age_hours: float | None


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_config() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def format_time(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts).astimezone().isoformat(timespec="seconds")


def newest_mtime(path: Path) -> float | None:
    if not path.exists():
        return None
    if path.is_file():
        return path.stat().st_mtime
    newest = path.stat().st_mtime
    for current_root, dirnames, filenames in os.walk(path):
        for name in filenames:
            candidate = Path(current_root) / name
            try:
                newest = max(newest, candidate.stat().st_mtime)
            except OSError:
                continue
        dirnames[:] = [name for name in dirnames if name not in {"__pycache__", ".git", ".venv", "node_modules"}]
    return newest


def json_summary(payload: Any) -> str:
    if isinstance(payload, dict):
        pieces = []
        for key in ("generated_at", "status", "message"):
            value = payload.get(key)
            if value:
                pieces.append(f"{key}: {value}")
        for key in ("store_summary", "items", "stores", "tasks"):
            value = payload.get(key)
            if isinstance(value, list):
                pieces.append(f"{key}: {len(value)} 条")
        return "；".join(pieces) or "JSON 可解析"
    if isinstance(payload, list):
        return f"JSON 可解析，{len(payload)} 条"
    return "JSON 可解析"


def validate_json(path: Path) -> tuple[str, str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        return "invalid", f"JSON 解析失败：{exc}"

    if isinstance(payload, dict):
        status = str(payload.get("status", "")).lower()
        if status in {"failed", "error", "blocked"}:
            message = payload.get("message") or payload.get("error") or "产物声明失败"
            return "invalid", f"JSON 状态异常：{message}"
        if "store_summary" in payload and not payload.get("store_summary"):
            return "invalid", "经营日报没有门店汇总数据"
        if "items" in payload and status == "ok" and not payload.get("items"):
            return "invalid", "JSON 状态为 ok，但明细为空"
    elif isinstance(payload, list) and not payload:
        return "invalid", "JSON 列表为空"

    return "ok", json_summary(payload)


def validate_csv(path: Path) -> tuple[str, str]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fieldnames = reader.fieldnames or []
            row_count = 0
            for row_count, _row in enumerate(reader, start=1):
                if row_count >= 100000:
                    break
    except Exception as exc:
        return "invalid", f"CSV 解析失败：{exc}"
    if not fieldnames:
        return "invalid", "CSV 缺少表头"
    if row_count == 0:
        return "invalid", "CSV 没有数据行"
    return "ok", f"CSV 可解析，{len(fieldnames)} 列，至少 {row_count} 行"


def validate_sqlite(path: Path) -> tuple[str, str]:
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
            integrity = conn.execute("pragma integrity_check").fetchone()
            if not integrity or integrity[0] != "ok":
                return "invalid", f"SQLite 完整性异常：{integrity[0] if integrity else '无结果'}"
            table_count = conn.execute(
                "select count(*) from sqlite_master where type = 'table'"
            ).fetchone()[0]
    except Exception as exc:
        return "invalid", f"SQLite 打开失败：{exc}"
    if table_count == 0:
        return "invalid", "SQLite 没有数据表"
    return "ok", f"SQLite 可打开，{table_count} 个数据表"


def validate_html(path: Path) -> tuple[str, str]:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception as exc:
        return "invalid", f"HTML 读取失败：{exc}"
    if len(text.strip()) < 100:
        return "invalid", "HTML 内容过短"
    lowered = text.lower()
    if "<html" not in lowered and "<!doctype" not in lowered:
        return "invalid", "HTML 缺少页面结构"
    return "ok", "HTML 页面结构可读"


def validate_javascript_data(path: Path) -> tuple[str, str]:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore").strip()
    except Exception as exc:
        return "invalid", f"JS 数据读取失败：{exc}"
    if len(text) < 20:
        return "invalid", "JS 数据内容过短"
    match = re.match(r"window\.[A-Z0-9_]+\s*=\s*(.*?);?\s*$", text, flags=re.S)
    if not match:
        return "ok", "JS 数据文件存在且非空"
    try:
        payload = json.loads(match.group(1))
    except Exception as exc:
        return "invalid", f"JS 内嵌 JSON 解析失败：{exc}"
    if isinstance(payload, dict) and str(payload.get("status", "")).lower() in {"failed", "error", "blocked"}:
        return "invalid", f"JS 数据状态异常：{payload.get('message') or payload.get('status')}"
    return "ok", json_summary(payload)


def validate_content(path: Path, expected_type: str) -> tuple[str, str]:
    if expected_type == "directory":
        try:
            has_child = any(path.iterdir())
        except Exception as exc:
            return "invalid", f"目录读取失败：{exc}"
        return ("ok", "目录存在且非空") if has_child else ("invalid", "目录为空")

    if path.stat().st_size == 0:
        return "invalid", "文件为空"
    suffix = path.suffix.lower()
    if suffix == ".json":
        return validate_json(path)
    if suffix == ".csv":
        return validate_csv(path)
    if suffix in {".sqlite", ".sqlite3", ".db"}:
        return validate_sqlite(path)
    if suffix == ".html":
        return validate_html(path)
    if suffix == ".js":
        return validate_javascript_data(path)
    return "ok", "文件存在且非空"


def check_evidence(item: dict[str, Any]) -> EvidenceStatus:
    rel_path = item["path"]
    expected_type = item.get("type", "file")
    freshness_hours = item.get("freshness_hours")
    path = ROOT / rel_path
    if not path.exists():
        return EvidenceStatus(rel_path, "missing", "未找到产物", None, None)
    if expected_type == "file" and not path.is_file():
        return EvidenceStatus(rel_path, "wrong_type", "存在但不是文件", None, None)
    if expected_type == "directory" and not path.is_dir():
        return EvidenceStatus(rel_path, "wrong_type", "存在但不是目录", None, None)

    mtime = newest_mtime(path)
    if mtime is None:
        return EvidenceStatus(rel_path, "empty", "没有可用更新时间", None, None)

    content_status, content_message = validate_content(path, expected_type)
    if content_status != "ok":
        return EvidenceStatus(rel_path, "invalid", content_message, format_time(mtime), None)

    age_hours = (datetime.now().timestamp() - mtime) / 3600
    if freshness_hours is not None and age_hours > float(freshness_hours):
        return EvidenceStatus(
            rel_path,
            "stale",
            f"产物过旧：{age_hours:.1f} 小时前更新，阈值 {freshness_hours} 小时",
            format_time(mtime),
            round(age_hours, 2),
        )
    return EvidenceStatus(
        rel_path,
        "ok",
        f"产物可信：{content_message}；更新时间在阈值内",
        format_time(mtime),
        round(age_hours, 2),
    )


def task_health(task: dict[str, Any]) -> dict[str, Any]:
    evidence = [check_evidence(item) for item in task.get("evidence", [])]
    command = task.get("command") or []
    command_status = "ready" if command else "planned"
    if command:
        command_path = command[1] if command[0] in {"/bin/zsh", "{python}", "{node}"} and len(command) > 1 else command[0]
        if command_path and not command_path.startswith("{") and command_path.startswith(".") is False:
            candidate = ROOT / command_path
            if "/" in command_path and not candidate.exists():
                command_status = "missing_command"

    if task.get("mode") == "planned":
        status = "planned"
    elif command_status == "missing_command":
        status = "broken"
    elif any(item.status in {"missing", "wrong_type", "empty"} for item in evidence):
        status = "missing_evidence"
    elif any(item.status == "invalid" for item in evidence):
        status = "invalid_evidence"
    elif any(item.status == "stale" for item in evidence):
        status = "stale"
    else:
        status = "ok"

    return {
        "id": task["id"],
        "center": task["center"],
        "name": task["name"],
        "risk": task.get("risk", "unknown"),
        "mode": task.get("mode", "manual_run"),
        "status": status,
        "command_status": command_status,
        "description": task.get("description", ""),
        "evidence": [item.__dict__ for item in evidence],
        "blockers": task.get("blockers", []),
    }


def build_health() -> dict[str, Any]:
    config = load_config()
    tasks = [task_health(task) for task in config["tasks"]]
    by_center: dict[str, dict[str, Any]] = {}
    for center in config["centers"]:
        center_tasks = [task for task in tasks if task["center"] == center["id"]]
        counts: dict[str, int] = {}
        for task in center_tasks:
            counts[task["status"]] = counts.get(task["status"], 0) + 1
        by_center[center["id"]] = {
            **center,
            "counts": counts,
            "task_count": len(center_tasks),
        }
    payload = {
        "generated_at": now_iso(),
        "root": str(ROOT),
        "centers": by_center,
        "tasks": tasks,
    }
    write_json(STATE_DIR / "health.json", payload)
    return payload


def expand_command(command: list[str]) -> list[str]:
    python = sys.executable
    node = str(NODE if NODE.exists() else "node")
    expanded = []
    for part in command:
        expanded.append(part.replace("{python}", python).replace("{node}", node))
    return expanded


def classify_failure(text: str, returncode: int) -> list[str]:
    labels: list[str] = []
    lowered = text.lower()
    if any(pattern in text for pattern in AUTH_PATTERNS):
        labels.append("登录/验证码/平台验证阻塞")
    if any(pattern in text or pattern in lowered for pattern in DOWNLOAD_PATTERNS):
        labels.append("平台下载或页面产物失败")
    if any(pattern in text or pattern in lowered for pattern in TIMEOUT_PATTERNS):
        labels.append("脚本超时")
    if any(pattern in text or pattern in lowered for pattern in PUBLISH_PATTERNS):
        labels.append("发布或远端同步失败")
    if returncode != 0 and not labels:
        labels.append("脚本非零退出，待查看日志")
    return labels


def run_task(task_id: str, *, timeout_seconds: int | None = None) -> int:
    config = load_config()
    task = next((item for item in config["tasks"] if item["id"] == task_id), None)
    if task is None:
        print(f"没有找到任务：{task_id}", file=sys.stderr)
        return 2
    command = task.get("command") or []
    if not command:
        print(f"任务还没有接入执行命令：{task['name']}")
        return 2

    RUN_DIR.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = RUN_DIR / f"{run_id}-{task_id.replace('.', '_')}.log"
    status_path = RUN_DIR / f"{run_id}-{task_id.replace('.', '_')}.json"
    expanded = expand_command(command)
    started_at = now_iso()
    print(f"开始执行：{task['name']}")
    print("命令：" + " ".join(expanded))

    result = subprocess.run(
        expanded,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout_seconds,
    )
    output = result.stdout or ""
    log_path.write_text(output, encoding="utf-8")
    labels = classify_failure(output, result.returncode)
    payload = {
        "task_id": task_id,
        "task_name": task["name"],
        "started_at": started_at,
        "finished_at": now_iso(),
        "returncode": result.returncode,
        "status": "success" if result.returncode == 0 else "failed",
        "failure_labels": labels,
        "log_path": str(log_path),
    }
    write_json(status_path, payload)
    build_health()
    print(f"执行结束：{'成功' if result.returncode == 0 else '失败'}，日志：{log_path}")
    if labels:
        print("失败分类：" + "、".join(labels))
    return result.returncode


def status_badge(status: str) -> str:
    labels = {
        "ok": "正常",
        "stale": "过旧",
        "missing_evidence": "缺产物",
        "invalid_evidence": "产物异常",
        "broken": "命令缺失",
        "planned": "待接入",
    }
    return labels.get(status, status)


def render_dashboard(health: dict[str, Any]) -> None:
    DASHBOARD_PATH.parent.mkdir(parents=True, exist_ok=True)
    center_cards = []
    for center in health["centers"].values():
        counts = center["counts"]
        count_text = " / ".join(f"{status_badge(key)} {value}" for key, value in sorted(counts.items())) or "暂无任务"
        center_cards.append(
            f"""
            <section class="center-card">
              <h2>{html.escape(center['name'])}</h2>
              <p>{html.escape(center['description'])}</p>
              <div class="count">{html.escape(count_text)}</div>
            </section>
            """
        )

    rows = []
    for task in health["tasks"]:
        evidence_lines = []
        for item in task["evidence"]:
            evidence_lines.append(
                f"<li><strong>{html.escape(status_badge(item['status']))}</strong> "
                f"{html.escape(item['path'])}<span>{html.escape(item['message'])}</span></li>"
            )
        blockers = "、".join(task["blockers"]) if task["blockers"] else "无"
        rows.append(
            f"""
            <article class="task {html.escape(task['status'])}">
              <div>
                <div class="task-title">{html.escape(task['name'])}</div>
                <div class="task-meta">{html.escape(task['id'])} · 风险 {html.escape(task['risk'])} · {html.escape(status_badge(task['status']))}</div>
                <p>{html.escape(task['description'])}</p>
                <p class="blockers">可能阻塞：{html.escape(blockers)}</p>
              </div>
              <ul>{''.join(evidence_lines) or '<li>待接入产物验证</li>'}</ul>
            </article>
            """
        )

    html_text = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AI 业务中心</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f7f8;
      --text: #172026;
      --muted: #66737f;
      --line: #d9dee3;
      --ok: #147a50;
      --warn: #a15c00;
      --bad: #b42318;
      --planned: #52677a;
      --panel: #ffffff;
    }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    header {{
      padding: 28px 32px 18px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
    }}
    h1 {{ margin: 0 0 8px; font-size: 28px; letter-spacing: 0; }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 24px; }}
    .sub {{ color: var(--muted); margin: 0; }}
    .centers {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
      gap: 12px;
      margin-bottom: 22px;
    }}
    .center-card, .task {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
    }}
    .center-card {{ padding: 16px; }}
    .center-card h2 {{ margin: 0 0 8px; font-size: 17px; }}
    .center-card p {{ margin: 0 0 12px; color: var(--muted); min-height: 42px; }}
    .count {{ font-weight: 700; }}
    .task {{
      display: grid;
      grid-template-columns: minmax(260px, 0.9fr) minmax(320px, 1.1fr);
      gap: 18px;
      padding: 16px;
      margin-bottom: 10px;
      border-left-width: 5px;
    }}
    .task.ok {{ border-left-color: var(--ok); }}
    .task.stale, .task.missing_evidence, .task.invalid_evidence {{ border-left-color: var(--warn); }}
    .task.broken {{ border-left-color: var(--bad); }}
    .task.planned {{ border-left-color: var(--planned); }}
    .task-title {{ font-size: 16px; font-weight: 750; margin-bottom: 4px; }}
    .task-meta, .blockers, .task p {{ color: var(--muted); margin: 6px 0 0; }}
    ul {{ margin: 0; padding-left: 18px; }}
    li {{ margin: 0 0 8px; }}
    li span {{ display: block; color: var(--muted); }}
    @media (max-width: 760px) {{
      header {{ padding: 22px 18px 14px; }}
      main {{ padding: 16px; }}
      .task {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>AI 业务中心</h1>
    <p class="sub">生成时间：{html.escape(health['generated_at'])} · 工程：{html.escape(health['root'])}</p>
  </header>
  <main>
    <section class="centers">{''.join(center_cards)}</section>
    <section>{''.join(rows)}</section>
  </main>
</body>
</html>
"""
    DASHBOARD_PATH.write_text(html_text, encoding="utf-8")


def print_task_list(health: dict[str, Any]) -> None:
    for task in health["tasks"]:
        print(f"{task['id']:<34} {status_badge(task['status']):<8} {task['name']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="AI 业务中心控制入口")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="列出已登记任务")
    sub.add_parser("health", help="检查任务产物和状态")
    sub.add_parser("dashboard", help="生成本地状态页")
    run_parser = sub.add_parser("run", help="手动执行一个已登记任务")
    run_parser.add_argument("task_id")
    run_parser.add_argument("--timeout", type=int, default=None, help="超时时间，单位秒")
    args = parser.parse_args()

    if args.command == "run":
        return run_task(args.task_id, timeout_seconds=args.timeout)

    health = build_health()
    if args.command == "dashboard":
        render_dashboard(health)
        print(f"已生成状态页：{DASHBOARD_PATH}")
    else:
        print_task_list(health)
        print(f"\n状态文件：{STATE_DIR / 'health.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
