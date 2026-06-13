from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs" / "user_action_queue"
LATEST_PATH = OUTPUT_DIR / "latest.json"
TASK_HEALTH_PATH = ROOT / "outputs" / "task_health" / "latest.json"
ANDROID_CONFIG_PATH = ROOT / "outputs" / "android_execution_config" / "latest.json"
FINANCE_CENTER_PATH = ROOT / "outputs" / "finance_center_status" / "latest.json"
TOOL_WAREHOUSE_PATH = ROOT / "outputs" / "tool_warehouse_status" / "latest.json"
PROMO_BID_QUEUE_PATH = ROOT / "outputs" / "promo_bid_approval_queue" / "latest.json"
PROMO_BALANCE_STATUS_PATH = ROOT / "outputs" / "promo_balance_status" / "latest.json"
REVIEW_ACTION_STATUS_PATH = ROOT / "outputs" / "review_action_status" / "latest.json"
ORDER_SUGGESTIONS_PATH = ROOT / "outputs" / "inventory_order_suggestions" / "latest.json"
ORDER_LISTS_PATH = ROOT / "outputs" / "inventory_order_lists" / "latest.json"


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def read_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def action_item(
    *,
    item_id: str,
    title: str,
    center: str,
    priority: str,
    reason: str,
    action: str,
    source: str,
    evidence: str,
    owner: str = "用户",
    environment: str = "",
) -> dict[str, Any]:
    return {
        "id": item_id,
        "title": title,
        "center": center,
        "priority": priority,
        "owner": owner,
        "environment": environment,
        "reason": reason,
        "action": action,
        "source": source,
        "evidence": evidence,
    }


def build_payload() -> dict[str, Any]:
    task_health = read_json(TASK_HEALTH_PATH, {})
    android_config = read_json(ANDROID_CONFIG_PATH, {})
    finance = read_json(FINANCE_CENTER_PATH, {})
    tools = read_json(TOOL_WAREHOUSE_PATH, {})
    bid_queue = read_json(PROMO_BID_QUEUE_PATH, {})
    promo_balance_status = read_json(PROMO_BALANCE_STATUS_PATH, {})
    review_actions = read_json(REVIEW_ACTION_STATUS_PATH, {})
    order_suggestions = read_json(ORDER_SUGGESTIONS_PATH, {})
    order_lists = read_json(ORDER_LISTS_PATH, {})

    items: list[dict[str, Any]] = []
    environment = (task_health.get("environment") or {}).get("role") or "development"
    tasks_by_id = {item.get("id"): item for item in task_health.get("tasks") or []}
    promo_balance = tasks_by_id.get("growth.promo_balance") or {}
    promo_next = promo_balance.get("next_step") or ""
    if "Mac mini" in promo_next and "冒烟" in promo_next:
        items.append(
            action_item(
                item_id="macmini.smoke_check",
                title="Mac mini 冒烟检查待回传",
                center="系统交接",
                priority="high",
                reason="证据上传和上午定时流程已经接入，需要生产机只读冒烟输出确认。",
                action='在 Mac mini 项目目录运行 `/bin/zsh scripts/run_macmini_ai_center_smoke.zsh`，把完整输出发给 Codex。',
                source="growth.promo_balance",
                evidence="scripts/run_macmini_ai_center_smoke.zsh",
                environment="Mac mini 生产环境",
            )
        )

    android_summary = android_config.get("summary") or {}
    if android_config.get("status") == "missing_config":
        missing = "、".join(android_config.get("missing") or []) or f"{android_summary.get('missing_count', 0)} 项配置"
        android_action = android_config.get("next_action") or "在 Mac mini 确认 adb 设备号、操作员、付款确认人和供应渠道后，用 init_android_execution_config.py 向导生成配置。"
        items.append(
            action_item(
                item_id="flow.android_config",
                title="远控安卓真实设备配置待补齐",
                center="货流中心",
                priority="high",
                reason=f"订货自动化真实执行前缺少：{missing}。",
                action=android_action,
                source="flow.auto_ordering",
                evidence="outputs/android_execution_config/latest.json",
                environment="Mac mini 生产环境",
            )
        )

    order_summary = order_suggestions.get("summary") or {}
    order_confirmation = order_suggestions.get("confirmation") or {}
    suggestion_count = int(order_summary.get("suggestion_count") or 0)
    if (
        order_suggestions.get("status") == "ready"
        and suggestion_count > 0
        and order_confirmation.get("status") == "pending"
        and order_lists.get("status") != "ready"
    ):
        checklist = "；".join(order_confirmation.get("checklist") or [])
        command = order_confirmation.get("confirm_command") or 'python3 scripts/build_inventory_order_lists.py --confirmed-by "确认人"'
        items.append(
            action_item(
                item_id="flow.order_confirmation",
                title="订货建议待人工确认",
                center="货流中心",
                priority="medium",
                reason=f"当前有 {suggestion_count} 项订货建议，分布在 {order_summary.get('channel_count', 0)} 个供应渠道，预估 {float(order_summary.get('estimated_cost') or 0):.2f} 元。",
                action=f"{checklist or '先核对品项、数量和供应渠道。'} 确认后运行 `{command}`。",
                source="flow.inventory",
                evidence="outputs/inventory_order_suggestions/latest.json",
            )
        )

    recharge_plan = promo_balance_status.get("recharge_plan") or {}
    recharge_count = int(recharge_plan.get("item_count") or 0)
    if recharge_count:
        items.append(
            action_item(
                item_id="growth.promo_balance_recharge",
                title="推广余额充值待处理",
                center="商业化推广中心",
                priority="medium",
                reason=recharge_plan.get("message") or f"当前有 {recharge_count} 个推广余额低于阈值。",
                action=recharge_plan.get("next_action") or "先充值低余额门店，再执行预算或出价自动化。",
                source="growth.promo_balance",
                evidence="outputs/promo_balance_status/latest.json",
            )
        )

    reply_plan = review_actions.get("reply_plan") or {}
    reply_count = int(reply_plan.get("item_count") or 0)
    if review_actions.get("status") == "waiting_reply" and reply_count:
        items.append(
            action_item(
                item_id="ops.review_reply",
                title="评价差评待回复",
                center="运营数据中心",
                priority="medium",
                reason=review_actions.get("message") or f"当前有 {reply_count} 家门店评价待回复。",
                action=reply_plan.get("next_action") or review_actions.get("human_action") or "先在对应平台查看评价和订单，再回复顾客。",
                source="ops.review_dashboard",
                evidence="outputs/review_action_status/latest.json",
            )
        )

    evidence_plan = review_actions.get("evidence_plan") or {}
    missing_evidence_count = int(evidence_plan.get("missing_count") or 0)
    if missing_evidence_count:
        items.append(
            action_item(
                item_id="ops.review_reply_evidence",
                title="评价回复证据待补",
                center="运营数据中心",
                priority="medium",
                reason=evidence_plan.get("message") or f"已回复评价中有 {missing_evidence_count} 条缺平台截图或链接证据。",
                action=evidence_plan.get("next_action") or "补录平台回复截图、评价链接或工单链接。",
                source="ops.review_dashboard",
                evidence="outputs/review_action_status/latest.json",
            )
        )

    recap_plan = review_actions.get("recap_plan") or {}
    recap_pending_count = int(recap_plan.get("pending_count") or 0)
    if recap_pending_count:
        items.append(
            action_item(
                item_id="ops.review_recap",
                title="评价复盘结果待记录",
                center="运营数据中心",
                priority="medium",
                reason=recap_plan.get("message") or f"当前有 {recap_pending_count} 条评价复盘建议待记录结果。",
                action=recap_plan.get("next_action") or "记录门店复盘结论和 7 天观察安排。",
                source="ops.review_recap",
                evidence="outputs/review_action_status/latest.json",
            )
        )

    followup_plan = review_actions.get("followup_plan") or {}
    recurred_count = int(followup_plan.get("recurred_count") or 0)
    if recurred_count:
        items.append(
            action_item(
                item_id="ops.review_followup_recurred",
                title="评价复盘后同类差评复发",
                center="运营数据中心",
                priority="medium",
                reason=followup_plan.get("message") or f"当前有 {recurred_count} 条评价复盘后出现同类差评复发。",
                action=followup_plan.get("next_action") or "复查门店 SOP、出品和打包流程，必要时升级为专项整改。",
                source="ops.review_followup",
                evidence="outputs/review_action_status/latest.json",
            )
        )

    sop_plan = review_actions.get("sop_plan") or {}
    sop_waiting_count = int(sop_plan.get("waiting_count") or 0)
    sop_open_count = int(sop_plan.get("open_count") or 0)
    if sop_waiting_count or sop_open_count:
        items.append(
            action_item(
                item_id="ops.review_sop",
                title="评价复发 SOP 整改待推进",
                center="运营数据中心",
                priority="medium",
                reason=sop_plan.get("message") or "评价复盘复发项需要 SOP 整改。",
                action=sop_plan.get("next_action") or "开 SOP 整改记录并跟踪复查结果。",
                source="ops.review_sop",
                evidence="outputs/review_action_status/latest.json",
            )
        )

    sop_closure_plan = review_actions.get("sop_closure_plan") or {}
    sop_reopen_count = int(sop_closure_plan.get("reopen_count") or 0)
    if sop_reopen_count:
        items.append(
            action_item(
                item_id="ops.review_sop_reopen",
                title="已关闭评价 SOP 整改复发",
                center="运营数据中心",
                priority="medium",
                reason=sop_closure_plan.get("message") or f"当前有 {sop_reopen_count} 条已关闭 SOP 整改后再次复发。",
                action=sop_closure_plan.get("next_action") or "重新打开 SOP 整改并升级门店检查。",
                source="ops.review_sop",
                evidence="outputs/review_action_status/latest.json",
            )
        )

    if finance.get("status") == "waiting_samples":
        missing = "、".join(finance.get("missing") or []) or "银行账单和平台账单样例"
        intake_messages = [
            item.get("message", "")
            for item in finance.get("intake_checklist") or []
            if item.get("message")
        ]
        items.append(
            action_item(
                item_id="finance.samples",
                title="财务账单样例待提供",
                center="财务中心",
                priority="medium",
                reason=f"财务字段字典已建立，当前缺少：{missing}。",
                action="；".join(intake_messages) or "提供银行账单、美团账单、饿了么账单样例后，再进入字段映射和利润表生成。",
                source="finance.bill_analysis",
                evidence="outputs/finance_center_status/latest.json",
            )
        )

    contract = tools.get("franchise_contract") or {}
    if contract.get("status") == "waiting_template":
        contract_messages = [
            item.get("message", "")
            for item in contract.get("intake_checklist") or []
            if item.get("message")
        ]
        items.append(
            action_item(
                item_id="tools.franchise_template",
                title="加盟合同模板待提供",
                center="小工具仓库",
                priority="medium",
                reason=contract.get("message") or "合同生成器等待现用模板和关键字段。",
                action="；".join(contract_messages) or "提供现用加盟合同模板，并确认加盟费、保证金、期限、授权范围等关键字段。",
                source="tools.franchise_contract",
                evidence="outputs/tool_warehouse_status/latest.json",
            )
        )

    bid_summary = bid_queue.get("summary") or {}
    queue_count = int(bid_summary.get("queue_count") or bid_summary.get("approval_required_count") or 0)
    if bid_queue.get("status") == "waiting_approval" and queue_count:
        bid_digest = bid_queue.get("approval_digest") or {}
        digest_lines = (bid_digest.get("warnings") or []) + (bid_digest.get("top_items") or [])[:3]
        bid_action = "；".join(digest_lines) or "打开推广出价审批队列，核对预算消耗、预期消耗和门店状态后再决定是否执行。"
        items.append(
            action_item(
                item_id="growth.promo_bid_approval",
                title="推广出价审批队列待确认",
                center="商业化推广中心",
                priority="medium",
                reason=f"当前有 {queue_count} 项出价建议等待确认，确认前系统不会自动提交。",
                action=bid_action,
                source="growth.promo_bid",
                evidence="outputs/promo_bid_approval_queue/latest.json",
            )
        )

    priority_order = {"high": 0, "medium": 1, "low": 2}
    items = sorted(items, key=lambda item: (priority_order.get(item["priority"], 9), item["center"], item["title"]))
    return {
        "generated_at": now_text(),
        "status": "waiting_user" if items else "clear",
        "environment": environment,
        "summary": {
            "action_count": len(items),
            "high_count": sum(1 for item in items if item["priority"] == "high"),
            "medium_count": sum(1 for item in items if item["priority"] == "medium"),
            "low_count": sum(1 for item in items if item["priority"] == "low"),
        },
        "items": items,
        "message": f"当前有 {len(items)} 项需要用户参与。"
        if items
        else "当前没有需要用户立即参与的事项。",
    }


def main() -> int:
    payload = build_payload()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    LATEST_PATH.chmod(0o644)
    print(payload["message"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
