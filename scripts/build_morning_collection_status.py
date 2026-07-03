from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from task_run_state import classify_failure_text


ROOT = Path(__file__).resolve().parents[1]
TASK_RUNS_PATH = ROOT / "outputs" / "task_runs" / "latest.json"
OUTPUT_DIR = ROOT / "outputs" / "morning_collection_status"
LATEST_PATH = OUTPUT_DIR / "latest.json"
TASK_ID = "ops.morning_collection"

EXPECTED_STEPS = [
    "初始化",
    "启动/检查后台 Chrome",
    "双平台评价下载",
    "门店日报采集并发布",
    "直营美团日报下载",
    "推广余额总巡检",
    "巡检证据清单生成",
    "巡检证据上传云端",
    "同步云端预算配置",
    "推广预算初始化预览",
    "饿了么午餐预算真实提交",
    "美团午餐预算真实提交",
    "运营总看板数据更新",
    "运营总看板发布腾讯云",
    "汇总",
]

REPAIR_GUIDES = {
    "auth_block": {
        "title": "登录或验证码恢复向导",
        "checklist": [
            "在 Mac mini 的 Chrome 打开对应平台后台。",
            "确认门店账号已登录，处理验证码或安全验证。",
            "刷新页面后重新运行上午运营一键采集。",
        ],
    },
    "permission": {
        "title": "Mac mini 权限恢复向导",
        "checklist": [
            "打开系统设置，检查终端、Chrome、Python 的屏幕录制和文件访问权限。",
            "补齐权限后重启 Chrome 或终端会话。",
            "先运行只读检查，再重跑上午运营一键采集。",
        ],
    },
    "manual_browser_setup": {
        "title": "浏览器准备向导",
        "checklist": [
            "在 Mac mini 的 Chrome 手动打开对应后台页面。",
            "确认页面能看到目标门店和操作入口。",
            "保持浏览器打开，再重跑自动化脚本。",
        ],
    },
    "page_structure": {
        "title": "平台页面改版排查向导",
        "checklist": [
            "人工打开失败页面，确认按钮、表格或弹窗名称是否变化。",
            "保存失败截图或页面提示，定位对应采集/预算脚本选择器。",
            "在 MacBook 修复脚本并提交后，再同步到 Mac mini。",
        ],
    },
    "timeout": {
        "title": "超时和网络恢复向导",
        "checklist": [
            "确认 Mac mini 网络和平台后台访问正常。",
            "关闭卡住的页面或重启 Chrome/CDP。",
            "连续两次超时后先只跑失败子步骤，不直接继续高风险提交。",
        ],
    },
    "store_mapping": {
        "title": "门店映射修复向导",
        "checklist": [
            "核对平台后台门店名称是否改名、停业或新增。",
            "更新对应配置中的门店映射。",
            "先运行只读采集确认覆盖，再恢复定时任务。",
        ],
    },
}


def platform_for_step(step: str, message: str = "") -> str:
    text = f"{step} {message}"
    if "饿了么" in text:
        return "饿了么"
    if "美团" in text:
        return "美团"
    if "双平台" in text:
        return "双平台"
    return ""


def module_for_step(step: str) -> str:
    if "评价" in step:
        return "评价下载"
    if "日报" in step:
        return "日报采集"
    if "余额" in step:
        return "推广余额"
    if "证据" in step:
        return "巡检证据"
    if "预算" in step:
        return "推广预算"
    if "云端" in step or "发布" in step:
        return "云端同步"
    if "Chrome" in step:
        return "浏览器准备"
    if "总看板" in step:
        return "总看板"
    return "上午采集"


def human_action_for(step: str, failure_type: str, platform: str) -> str:
    target = platform or module_for_step(step)
    if failure_type == "auth_block":
        return f"在 Mac mini 的 Chrome 恢复{target}登录或验证码，再重跑上午一键采集。"
    if failure_type == "permission":
        return f"在 Mac mini 系统设置补齐{target}需要的屏幕录制/文件访问权限，再重跑上午一键采集。"
    if failure_type == "manual_browser_setup":
        return f"先在 Mac mini 的 Chrome 打开{target}后台页面并确认登录，再重跑上午一键采集。"
    if failure_type == "page_structure":
        return f"先人工核对{target}后台页面是否改版，再调整对应采集或预算脚本。"
    if failure_type == "timeout":
        return f"先确认{target}后台页面和网络可用；连续超时则重启 Chrome/CDP 后重跑上午一键采集。"
    if failure_type == "store_mapping":
        return f"检查{target}门店映射或门店名称是否变更，再重跑相关子步骤。"
    if "预算" in step:
        return f"先暂停真实预算提交，核对{target}预算页面、门店映射和目标预算后再重跑。"
    if "证据" in step and "云端" in step:
        return "先在 Mac mini 检查云端 SSH 密钥、网络和证据清单，再运行 scripts/upload_store_inspection_evidence.zsh --dry-run。"
    if "发布" in step or "云端" in step:
        return "先检查网络和云端发布权限，再重新发布运营总看板。"
    return f"查看{step}日志，确认登录、权限、页面结构和输入数据后重跑。"


def repair_guide_for(step: dict[str, Any]) -> dict[str, Any]:
    failure_type = step.get("failure_type") or "unknown"
    platform = step.get("platform") or ""
    module = step.get("module") or module_for_step(step.get("name", ""))
    guide = REPAIR_GUIDES.get(failure_type)
    if not guide:
        if "预算" in str(step.get("name") or ""):
            guide = {
                "title": "推广预算失败安全处理向导",
                "checklist": [
                    "先暂停真实预算提交，避免重复提交或误调预算。",
                    "核对平台页面、门店映射和目标预算。",
                    "确认无风险后，只重跑对应平台和时段的预算步骤。",
                ],
            }
        elif "证据" in str(step.get("name") or "") and "云端" in str(step.get("name") or ""):
            guide = {
                "title": "证据上传恢复向导",
                "checklist": [
                    "检查 Mac mini 到云端的网络和 SSH 权限。",
                    "确认证据清单文件存在且日期正确。",
                    "先运行上传 dry-run，再恢复正式上传。",
                ],
            }
        else:
            guide = {
                "title": "通用失败排查向导",
                "checklist": [
                    "查看失败子步骤日志和页面提示。",
                    "确认登录、权限、页面结构、门店映射和输入数据。",
                    "先做只读复查，再重跑上午运营一键采集。",
                ],
            }
    target = " · ".join(part for part in (platform, module) if part) or module
    checklist = list(guide["checklist"])
    human_action = step.get("human_action") or ""
    if human_action and human_action not in checklist:
        checklist.append(human_action)
    return {
        "id": f"{failure_type}.{module}.{platform or 'all'}",
        "title": guide["title"],
        "priority": "high" if failure_type in {"auth_block", "permission", "page_structure"} or "预算" in str(step.get("name") or "") else "medium",
        "target": target,
        "step": step.get("name", ""),
        "module": module,
        "platform": platform,
        "failure_type": failure_type,
        "checklist": checklist,
        "rerun_command": "/bin/zsh morning-ops/上午运营一键采集.command",
        "evidence": step.get("log_path") or "outputs/morning_collection_status/latest.json",
    }


def build_repair_guides(failed_steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    guides: dict[str, dict[str, Any]] = {}
    for step in failed_steps:
        guide = repair_guide_for(step)
        existing = guides.get(guide["id"])
        if not existing:
            guides[guide["id"]] = guide
            continue
        existing["step"] = "、".join(
            sorted({part for part in [existing.get("step", ""), guide.get("step", "")] if part})
        )
        existing["evidence"] = existing.get("evidence") or guide.get("evidence", "")
    return sorted(guides.values(), key=lambda item: (0 if item["priority"] == "high" else 1, item["target"], item["title"]))


def repair_templates() -> list[dict[str, Any]]:
    labels = {
        "auth_block": "平台登录/验证码",
        "permission": "Mac mini 系统权限",
        "manual_browser_setup": "浏览器后台准备",
        "page_structure": "平台页面改版",
        "timeout": "网络或页面超时",
        "store_mapping": "门店映射变化",
    }
    return [
        {
            "failure_type": failure_type,
            "title": guide["title"],
            "trigger": labels.get(failure_type, failure_type),
            "checklist": guide["checklist"],
        }
        for failure_type, guide in sorted(REPAIR_GUIDES.items())
    ]


def normalize_failure_type(message: str, returncode: int | None, fallback: str = "") -> str:
    if "屏幕录制" in str(message or "") or "could not create image from display" in str(message or ""):
        return "permission"
    return fallback or classify_failure_text(message, returncode)


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def read_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def write_latest(payload: dict[str, Any]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    LATEST_PATH.chmod(0o644)


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip().replace("Z", "")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text[:26] if "." in text else text[:19], fmt)
        except ValueError:
            continue
    return None


def latest_start_index(events: list[dict[str, Any]]) -> int:
    for index in range(len(events) - 1, -1, -1):
        event = events[index]
        if event.get("task_id") != TASK_ID:
            continue
        step = str(event.get("step") or "")
        message = str(event.get("message") or "")
        if event.get("status") == "running" and (step in {"start", "初始化"} or "开始" in message):
            return index
    for index in range(len(events) - 1, -1, -1):
        if events[index].get("task_id") == TASK_ID:
            return index
    return -1


def event_step_status(event: dict[str, Any]) -> str:
    if event.get("status") == "failed":
        return "failed"
    message = str(event.get("message") or "")
    if "完成" in message:
        return "success"
    if event.get("status") == "success":
        return "success"
    if event.get("status") == "skipped":
        return "skipped"
    return "running"


def summarize_steps(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_step: dict[str, dict[str, Any]] = {}
    for event in events:
        step = str(event.get("step") or "")
        if not step or step in {"start", "finish", "exception"}:
            continue
        if step not in EXPECTED_STEPS and not any(step.startswith(prefix) for prefix in ("饿了么", "美团")):
            continue
        message = event.get("message") or ""
        failure_type = event.get("failure_type") or ""
        if event.get("status") == "failed" and not failure_type:
            failure_type = normalize_failure_type(message, event.get("returncode"))
        platform = platform_for_step(step, message)
        status = event_step_status(event)
        by_step[step] = {
            "name": step,
            "status": status,
            "module": module_for_step(step),
            "platform": platform,
            "message": message,
            "failure_type": failure_type,
            "human_action": human_action_for(step, failure_type, platform) if status == "failed" else "",
            "returncode": event.get("returncode"),
            "log_path": event.get("log_path") or "",
            "updated_at": event.get("created_at") or "",
        }
    return sorted(by_step.values(), key=lambda item: parse_time(item.get("updated_at")) or datetime.min)


def fallback_steps_from_task(task: dict[str, Any]) -> list[dict[str, Any]]:
    if not task or task.get("status") != "failed":
        return []
    extra = task.get("extra") if isinstance(task.get("extra"), dict) else {}
    failures = [
        part.strip()
        for part in str(extra.get("failures") or "").replace("，", ",").replace("、", ",").split(",")
        if part.strip()
    ]
    if not failures:
        failures = [str(task.get("step") or "上午运营一键采集")]
    steps: list[dict[str, Any]] = []
    for name in failures:
        message = str(task.get("message") or f"{name}失败。")
        failure_type = str(task.get("failure_type") or normalize_failure_type(message, task.get("returncode")))
        platform = platform_for_step(name, message)
        steps.append(
            {
                "name": name,
                "status": "failed",
                "module": module_for_step(name),
                "platform": platform,
                "message": message,
                "failure_type": failure_type,
                "human_action": human_action_for(name, failure_type, platform),
                "returncode": task.get("returncode"),
                "log_path": task.get("log_path") or "",
                "updated_at": task.get("updated_at") or task.get("finished_at") or "",
            }
        )
    return steps


def build_payload() -> dict[str, Any]:
    run_state = read_json(TASK_RUNS_PATH, {"tasks": {}, "events": []})
    all_events = [event for event in run_state.get("events", []) if event.get("task_id") == TASK_ID]
    start_index = latest_start_index(run_state.get("events", []))
    session_events = []
    if start_index >= 0:
        session_events = [
            event
            for event in run_state.get("events", [])[start_index:]
            if event.get("task_id") == TASK_ID
        ]
    task = (run_state.get("tasks") or {}).get(TASK_ID) or {}
    steps = summarize_steps(session_events)
    if not steps:
        steps = fallback_steps_from_task(task)
    failed_steps = [step for step in steps if step["status"] == "failed"]
    recovery_actions = [
        {
            "step": step["name"],
            "module": step.get("module", ""),
            "platform": step.get("platform", ""),
            "failure_type": step.get("failure_type", ""),
            "message": step.get("message", ""),
            "human_action": step.get("human_action", ""),
            "log_path": step.get("log_path", ""),
        }
        for step in failed_steps
    ]
    repair_guides = build_repair_guides(failed_steps)
    completed_steps = [step for step in steps if step["status"] == "success"]
    running_steps = [step for step in steps if step["status"] == "running"]
    if failed_steps or task.get("status") == "failed":
        status = "failed"
        message = f"上午运营一键采集有 {len(failed_steps)} 个子步骤失败。"
    elif not all_events:
        status = "missing_run"
        message = "尚未找到上午运营一键采集运行记录。"
    elif task.get("status") == "success" and completed_steps:
        status = "success"
        message = f"上午运营一键采集完成，{len(completed_steps)} 个子步骤有完成记录。"
    elif task.get("status") == "success":
        status = "partial"
        message = "上午运营一键采集总状态为成功，但没有子步骤完成记录，不能判定早间任务完整完成。"
    else:
        status = "running" if running_steps else "partial"
        message = f"上午运营一键采集已有 {len(steps)} 个子步骤记录。"
    return {
        "generated_at": now_text(),
        "status": status,
        "task_status": task.get("status", ""),
        "task_message": task.get("message", ""),
        "started_at": task.get("started_at", ""),
        "finished_at": task.get("finished_at", ""),
        "updated_at": task.get("updated_at", ""),
        "summary": {
            "step_count": len(steps),
            "completed_count": len(completed_steps),
            "failed_count": len(failed_steps),
            "running_count": len(running_steps),
            "event_count": len(all_events),
            "repair_guide_count": len(repair_guides),
        },
        "steps": steps,
        "failed_steps": failed_steps,
        "recovery_actions": recovery_actions,
        "repair_guides": repair_guides,
        "repair_templates": repair_templates(),
        "human_action": "；".join(item["human_action"] for item in recovery_actions[:2] if item.get("human_action")),
        "message": message,
    }


def main() -> int:
    payload = build_payload()
    write_latest(payload)
    print(payload["message"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
