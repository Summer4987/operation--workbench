from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from atomic_io import atomic_write_text


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import agent_llm  # noqa: E402

PIPELINE_ID = "daily_automation_guard"
PIPELINE_PATH = ROOT / "outputs" / "agent_pipeline" / PIPELINE_ID / "latest.json"
MONITOR_PATH = ROOT / "outputs" / "agent_task_monitor" / "latest.json"
TASK_RUNS_PATH = ROOT / "outputs" / "task_runs" / "latest.json"
OUTPUT_DIR = ROOT / "outputs" / "agent_chat"


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def read_json(path: Path, fallback: Any) -> Any:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if payload is not None else fallback
    except Exception:
        return fallback


def write_json(path: Path, payload: dict[str, Any]) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def run_refresh() -> dict[str, Any]:
    command = [sys.executable or "python3", str(ROOT / "scripts" / "agent_pipeline.py"), PIPELINE_ID]
    result = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return {
        "command": command,
        "returncode": result.returncode,
        "output_tail": (result.stdout or "")[-4000:],
    }


def compact_reason(value: Any, fallback: str = "没有写明原因") -> str:
    text = str(value or "").strip()
    if not text:
        return fallback
    return text.replace("\n", " ")[:180].rstrip("。.")


def skipped_execution_agents(pipeline: dict[str, Any]) -> list[dict[str, Any]]:
    stages = pipeline.get("stages") if isinstance(pipeline.get("stages"), list) else []
    return [
        stage
        for stage in stages
        if isinstance(stage, dict)
        and str(stage.get("agent") or "").lower() in {"execute", "execution"}
        and stage.get("status") == "skipped"
    ]


def successful_execution_agents(pipeline: dict[str, Any]) -> list[dict[str, Any]]:
    stages = pipeline.get("stages") if isinstance(pipeline.get("stages"), list) else []
    return [
        stage
        for stage in stages
        if isinstance(stage, dict)
        and str(stage.get("agent") or "").lower() in {"execute", "execution"}
        and stage.get("status") == "success"
    ]


def failed_pipeline_stages(pipeline: dict[str, Any]) -> list[dict[str, Any]]:
    stages = pipeline.get("stages") if isinstance(pipeline.get("stages"), list) else []
    return [stage for stage in stages if isinstance(stage, dict) and stage.get("status") == "failed"]


def attention_tasks(monitor: dict[str, Any]) -> list[dict[str, Any]]:
    rows = monitor.get("tasks") if isinstance(monitor.get("tasks"), list) else []
    return [
        row
        for row in rows
        if isinstance(row, dict) and row.get("status") in {"failed", "attention", "missing", "running"}
    ]


def failed_tasks(monitor: dict[str, Any]) -> list[dict[str, Any]]:
    rows = monitor.get("tasks") if isinstance(monitor.get("tasks"), list) else []
    return [row for row in rows if isinstance(row, dict) and row.get("status") == "failed"]


def verification_tasks(monitor: dict[str, Any]) -> list[dict[str, Any]]:
    rows = monitor.get("tasks") if isinstance(monitor.get("tasks"), list) else []
    return [row for row in rows if isinstance(row, dict) and row.get("status") in {"attention", "missing", "running"}]


def rerun_candidates(monitor: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    plan = monitor.get("rerun_plan") if isinstance(monitor.get("rerun_plan"), list) else []
    allowed = [item for item in plan if isinstance(item, dict) and item.get("auto_allowed")]
    manual = [item for item in plan if isinstance(item, dict) and not item.get("auto_allowed")]
    return allowed, manual


def build_status_answer(pipeline: dict[str, Any], monitor: dict[str, Any]) -> str:
    summary = pipeline.get("summary") if isinstance(pipeline.get("summary"), dict) else {}
    monitor_summary = monitor.get("summary") if isinstance(monitor.get("summary"), dict) else {}
    line = (
        f"现在这组 agent 最近一次运行是 {pipeline.get('generated_at') or '未知时间'}："
        f"成功 {summary.get('success', 0)} 个，失败 {summary.get('failed', 0)} 个，"
        f"跳过 {summary.get('skipped', 0)} 个。"
    )
    if monitor_summary:
        line += (
            f" 透明化报告里完成 {monitor_summary.get('completed', 0)} 个，"
            f"真正失败 {monitor_summary.get('failed', 0)} 个，需核实 {monitor_summary.get('attention', 0)} 个。"
        )
    skipped = skipped_execution_agents(pipeline)
    if skipped:
        names = "、".join(str(stage.get("name") or stage.get("id")) for stage in skipped)
        line += f" 被跳过的是：{names}。它需要显式启用，且订货任务排除在外。"
    executed = successful_execution_agents(pipeline)
    if executed:
        names = "、".join(str(stage.get("name") or stage.get("id")) for stage in executed)
        line += f" 已参与执行的是：{names}；订货/下单/采购类动作仍然排除。"
    return line


def build_problem_answer(pipeline: dict[str, Any], monitor: dict[str, Any]) -> str:
    failed_stages = failed_pipeline_stages(pipeline)
    if failed_stages:
        first = failed_stages[0]
        return f"agent 流程本身有失败：{first.get('name')}。原因：{compact_reason(first.get('message'))}。"

    failures = failed_tasks(monitor)
    checks = verification_tasks(monitor)
    if not failures and not checks:
        return "这组 agent 本身没有失败项。当前没有从透明化报告里读到需要处理或核实的任务。"

    if not failures:
        names = "、".join(str(row.get("name") or row.get("id")) for row in checks[:5])
        extra = "" if len(checks) <= 5 else f"；另外还有 {len(checks) - 5} 项"
        return (
            f"今天没有读到真正失败项。需核实 {len(checks)} 项，但这些不是失败：{names}{extra}。"
            "需核实通常表示产物存在但步骤账本缺记录，不能直接算失败。"
        )

    parts = []
    for row in failures[:5]:
        name = row.get("name") or row.get("id")
        reason = compact_reason(row.get("failure_reason") or row.get("message"))
        evidence = row.get("evidence") or ""
        evidence_text = f"，证据：{evidence}" if evidence else ""
        parts.append(f"{name}：{reason}{evidence_text}")
    extra_failures = "" if len(failures) <= 5 else f" 另外还有 {len(failures) - 5} 个失败项。"
    verify_text = f"另有 {len(checks)} 项需核实，但不算失败。" if checks else "没有其它需核实项。"
    return f"今天真正失败 {len(failures)} 项：" + "；".join(parts) + f"。{extra_failures}{verify_text}"


def build_rerun_answer(monitor: dict[str, Any]) -> str:
    allowed, manual = rerun_candidates(monitor)
    if not allowed and not manual:
        return "当前没有读到补跑计划。"
    failures = {str(row.get("id") or "") for row in failed_tasks(monitor)}
    parts = []
    if allowed:
        names = "、".join(str(item.get("task_name") or item.get("task_id")) for item in allowed[:6])
        parts.append(f"可以自动补跑的是：{names}")
    if manual:
        failed_manual = [item for item in manual if str(item.get("task_id") or "") in failures]
        other_manual = [item for item in manual if str(item.get("task_id") or "") not in failures]
        if failed_manual:
            names = "、".join(str(item.get("task_name") or item.get("task_id")) for item in failed_manual[:6])
            parts.append(f"真正失败且需要人工确认的是：{names}")
        if other_manual:
            names = "、".join(str(item.get("task_name") or item.get("task_id")) for item in other_manual[:6])
            parts.append(f"需核实但不是失败的是：{names}")
    return "；".join(parts) + "。"


def build_execution_answer(pipeline: dict[str, Any]) -> str:
    executed = successful_execution_agents(pipeline)
    if executed:
        details = []
        execution_payload = read_json(ROOT / "outputs" / "agent_execution" / "latest.json", {})
        summary = execution_payload.get("summary") if isinstance(execution_payload.get("summary"), dict) else {}
        for stage in executed:
            details.append(f"{stage.get('name') or stage.get('id')}（id: {stage.get('id')}, agent: {stage.get('agent')}）")
        return (
            "执行 Agent 已参与：" + "、".join(details) + "。"
            f"最近执行结果：成功 {summary.get('success', 0)} 个，失败 {summary.get('failed', 0)} 个，"
            f"拦截 {summary.get('blocked', 0)} 个；订货/下单/采购类动作不参与。"
        )
    skipped = skipped_execution_agents(pipeline)
    if not skipped:
        return "这次没有读到执行 Agent 的运行记录。"
    details = []
    for stage in skipped:
        details.append(
            f"{stage.get('name') or stage.get('id')}（id: {stage.get('id')}, agent: {stage.get('agent')}）："
            f"{compact_reason(stage.get('message'))}"
        )
    return "刚刚跳过的是 " + "；".join(details) + "。"


def compact_task_rows(rows: Any, *, limit: int = 8) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    compacted: list[dict[str, Any]] = []
    for row in rows[:limit]:
        if not isinstance(row, dict):
            continue
        compacted.append(
            {
                "id": row.get("id") or row.get("task_id"),
                "name": row.get("name") or row.get("task_name"),
                "status": row.get("status"),
                "status_text": row.get("status_text"),
                "message": compact_reason(row.get("failure_reason") or row.get("message"), fallback=""),
                "auto_allowed": row.get("auto_allowed"),
            }
        )
    return compacted


def build_llm_context(
    *,
    intent: str,
    pipeline: dict[str, Any],
    monitor: dict[str, Any],
    task_runs: dict[str, Any],
    refreshed: dict[str, Any] | None,
) -> dict[str, Any]:
    stages = pipeline.get("stages") if isinstance(pipeline.get("stages"), list) else []
    monitor_tasks = monitor.get("tasks") if isinstance(monitor.get("tasks"), list) else []
    rerun_plan = monitor.get("rerun_plan") if isinstance(monitor.get("rerun_plan"), list) else []
    return {
        "intent": intent,
        "generated_at": {
            "pipeline": pipeline.get("generated_at"),
            "monitor": monitor.get("generated_at"),
            "task_runs": task_runs.get("generated_at") if isinstance(task_runs, dict) else "",
        },
        "pipeline": {
            "name": (pipeline.get("pipeline") or {}).get("name") if isinstance(pipeline.get("pipeline"), dict) else "",
            "summary": pipeline.get("summary") if isinstance(pipeline.get("summary"), dict) else {},
            "safety": pipeline.get("safety") if isinstance(pipeline.get("safety"), dict) else {},
            "stages": compact_task_rows(stages, limit=8),
        },
        "monitor": {
            "summary": monitor.get("summary") if isinstance(monitor.get("summary"), dict) else {},
            "attention_tasks": compact_task_rows(attention_tasks(monitor), limit=8),
            "rerun_plan": compact_task_rows(rerun_plan, limit=8),
        },
        "refresh": refreshed or {"ran": False},
        "safety": {
            "ordering_excluded": True,
            "llm_advisory_only": True,
            "requires_execute_flag_for_mutation": True,
        },
    }


def maybe_improve_answer(
    *,
    question: str,
    draft_answer: str,
    intent: str,
    pipeline: dict[str, Any],
    monitor: dict[str, Any],
    task_runs: dict[str, Any],
    refreshed: dict[str, Any] | None,
    use_llm: bool,
) -> tuple[str, dict[str, Any]]:
    if not use_llm:
        return draft_answer, {"enabled": False, "used": False, "fallback": "llm-disabled-by-flag"}
    context = build_llm_context(
        intent=intent,
        pipeline=pipeline,
        monitor=monitor,
        task_runs=task_runs,
        refreshed=refreshed,
    )
    record = agent_llm.generate_answer(question=question, draft_answer=draft_answer, context=context)
    record["draft_answer"] = draft_answer
    if record.get("used") and float(record.get("confidence") or 0) >= 0.5:
        return str(record.get("answer") or draft_answer), record
    return draft_answer, record


def answer_question(question: str, *, refreshed: dict[str, Any] | None = None, use_llm: bool = True) -> dict[str, Any]:
    pipeline = read_json(PIPELINE_PATH, {})
    monitor = read_json(MONITOR_PATH, {})
    task_runs = read_json(TASK_RUNS_PATH, {})
    normalized = question.strip() or "现在怎么样？"
    lower = normalized.lower()

    if any(keyword in normalized for keyword in ("执行", "跳过", "4号", "4 号")):
        intent = "execution_agent"
        answer = build_execution_answer(pipeline)
    elif any(keyword in normalized for keyword in ("补跑", "重跑", "恢复")):
        intent = "rerun"
        answer = build_rerun_answer(monitor)
    elif any(keyword in normalized for keyword in ("问题", "失败", "异常", "坏", "报错")):
        intent = "problems"
        answer = build_problem_answer(pipeline, monitor)
    elif "help" in lower or "怎么问" in normalized or "帮助" in normalized:
        intent = "help"
        answer = "你可以问：今天哪里有问题、哪些任务能补跑、刚刚跳过的执行 Agent 是谁、现在 agent 状态怎么样。"
    else:
        intent = "status"
        answer = build_status_answer(pipeline, monitor)

    factual_intents = {"problems", "rerun", "execution_agent"}
    effective_use_llm = bool(use_llm and intent not in factual_intents)
    final_answer, llm_record = maybe_improve_answer(
        question=normalized,
        draft_answer=answer,
        intent=intent,
        pipeline=pipeline,
        monitor=monitor,
        task_runs=task_runs if isinstance(task_runs, dict) else {},
        refreshed=refreshed,
        use_llm=effective_use_llm,
    )

    return {
        "generated_at": now_text(),
        "host": socket.gethostname(),
        "question": normalized,
        "intent": intent,
        "answer": final_answer,
        "llm": {
            "enabled": bool(effective_use_llm),
            "used": bool(llm_record.get("used")),
            "provider": llm_record.get("provider", ""),
            "model": llm_record.get("model", ""),
            "confidence": llm_record.get("confidence", 0),
            "reason": llm_record.get("reason", ""),
            "error": llm_record.get("error", ""),
            "fallback": llm_record.get("fallback", ""),
            "draft_answer": llm_record.get("draft_answer", ""),
        },
        "sources": {
            "pipeline": str(PIPELINE_PATH.relative_to(ROOT)),
            "monitor": str(MONITOR_PATH.relative_to(ROOT)),
            "task_runs": str(TASK_RUNS_PATH.relative_to(ROOT)),
        },
        "refresh": refreshed or {"ran": False},
        "task_runs_generated_at": task_runs.get("generated_at") if isinstance(task_runs, dict) else "",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="和本地多 Agent 运行结果对话。")
    parser.add_argument("question", nargs="*", help="要问 agent 的问题")
    parser.add_argument("--refresh", action="store_true", help="回答前先安全刷新 daily_automation_guard")
    parser.add_argument("--no-llm", action="store_true", help="禁用大模型回答生成，强制使用本地规则回答")
    parser.add_argument("--json-out", default=str(OUTPUT_DIR / "latest.json"), help="JSON 回答输出路径")
    parser.add_argument("--text-out", default=str(OUTPUT_DIR / "latest.txt"), help="文本回答输出路径")
    args = parser.parse_args()

    refreshed = None
    if args.refresh:
        refresh_result = run_refresh()
        refreshed = {"ran": True, **refresh_result}

    question = " ".join(args.question).strip() or "现在 agent 状态怎么样？"
    payload = answer_question(question, refreshed=refreshed, use_llm=not args.no_llm)
    json_out = Path(args.json_out).expanduser()
    text_out = Path(args.text_out).expanduser()
    write_json(json_out, payload)
    atomic_write_text(text_out, payload["answer"] + "\n")
    print(payload["answer"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
