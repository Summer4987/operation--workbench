from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from atomic_io import atomic_write_text


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "agent_llm.json"
ENV_PATH = Path.home() / ".xiong-agent-env"
OUTPUT_DIR = ROOT / "outputs" / "agent_llm"
LATEST_PATH = OUTPUT_DIR / "latest.json"

ALLOWED_INTENTS = {
    "status",
    "problems",
    "refresh_status",
    "rerun_plan",
    "execution_status",
    "execute_non_ordering",
    "budget_preview",
    "budget_commit",
    "publish_mobile",
    "chat",
    "help",
}

SYSTEM_PROMPT = """你是熊小小运营自动化的意图识别助手。
只输出 JSON，不要输出 Markdown。
你只能做理解、分类和总结建议，不能决定真实生产执行。
订货、下单、采购、快驴相关动作必须归类为 blocked_ordering，但这类硬拦截通常由外层规则先处理。
真实预算提交只有用户明确说“确认执行预算重跑/确认提交预算”等确认语时才是 budget_commit；普通“重跑预算/预算有问题”只能是 budget_preview。
非订货恢复、执行其他自动化、处理非订货问题归类为 execute_non_ordering。
查询任务是否正常、怎么样、情况如何归类为 status。
询问哪里失败、哪里异常、有什么问题归类为 problems。
刷新、更新状态归类为 refresh_status。
询问哪些能补跑归类为 rerun_plan。
询问执行 Agent 是谁或执行 Agent 状态归类为 execution_status。
发布手机入口、同步工作台到云端归类为 publish_mobile。
无法确定时归类为 chat。
输出格式：
{"intent":"status","confidence":0.0,"reason":"一句很短的中文理由"}
"""

ANSWER_SYSTEM_PROMPT = """你是熊小小运营自动化的对话助手。
只输出 JSON，不要输出 Markdown。
你只能根据用户问题、本地状态草稿和结构化上下文回答，不能编造没有出现在上下文里的任务结果。
订货、下单、采购、快驴相关动作不能建议自动执行，只能说明当前系统不参与。
预算真实提交、平台执行、发布类动作必须说明需要显式执行确认；普通询问只能报告状态或给出安全建议。
回答要像在企业微信里和老板汇报：短、清楚、直接说结论，再说原因和下一步。
输出格式：
{"answer":"一段中文回答","confidence":0.0,"reason":"一句很短的中文理由"}
"""


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def read_json(path: Path, fallback: Any) -> Any:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if payload is not None else fallback
    except Exception:
        return fallback


def parse_env_value(value: str) -> str:
    clean = value.strip()
    if (clean.startswith("'") and clean.endswith("'")) or (clean.startswith('"') and clean.endswith('"')):
        clean = clean[1:-1]
    return clean


def load_env_file(path: Path = ENV_PATH) -> dict[str, str]:
    if not path.exists():
        return {}
    env: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            env[key] = parse_env_value(value)
    return env


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    config = read_json(path, {})
    return config if isinstance(config, dict) else {}


def resolve_settings(config_path: Path = CONFIG_PATH, env_path: Path = ENV_PATH) -> dict[str, Any]:
    config = load_config(config_path)
    file_env = load_env_file(env_path)
    merged_env = {**file_env, **os.environ}
    api_key_env = str(config.get("api_key_env") or "AGENT_LLM_API_KEY")
    base_url_env = str(config.get("base_url_env") or "AGENT_LLM_BASE_URL")
    model_env = str(config.get("model_env") or "AGENT_LLM_MODEL")
    return {
        "enabled": bool(config.get("enabled")),
        "provider": str(config.get("provider") or merged_env.get("AGENT_LLM_PROVIDER") or "deepseek"),
        "api_key": str(merged_env.get(api_key_env) or ""),
        "base_url": str(merged_env.get(base_url_env) or "https://api.deepseek.com").rstrip("/"),
        "model": str(merged_env.get(model_env) or "deepseek-chat"),
        "mode": str(config.get("mode") or "advisory_only"),
        "allow_production_actions": bool(config.get("allow_production_actions")),
        "allow_ordering_actions": bool(config.get("allow_ordering_actions")),
        "allow_budget_commit": bool(config.get("allow_budget_commit")),
        "timeout_seconds": int(config.get("timeout_seconds") or 15),
        "max_tokens": int(config.get("max_tokens") or 160),
    }


def extract_json_object(text: str) -> dict[str, Any]:
    clean = (text or "").strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?", "", clean).strip()
        clean = re.sub(r"```$", "", clean).strip()
    try:
        payload = json.loads(clean)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", clean, flags=re.S)
        if not match:
            raise
        payload = json.loads(match.group(0))
    if not isinstance(payload, dict):
        raise ValueError("LLM response is not a JSON object")
    return payload


def call_chat_completion(settings: dict[str, Any], user_text: str) -> dict[str, Any]:
    payload = {
        "model": settings["model"],
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_text[:1000]},
        ],
        "temperature": 0,
        "max_tokens": settings["max_tokens"],
        "response_format": {"type": "json_object"},
    }
    req = urllib.request.Request(
        settings["base_url"] + "/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + settings["api_key"],
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=settings["timeout_seconds"]) as response:
        data = json.loads(response.read().decode("utf-8"))
    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    parsed = extract_json_object(str(content))
    return {
        "raw": parsed,
        "usage": data.get("usage") if isinstance(data.get("usage"), dict) else {},
    }


def call_answer_completion(settings: dict[str, Any], *, question: str, draft_answer: str, context: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "model": settings["model"],
        "messages": [
            {"role": "system", "content": ANSWER_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "question": question[:800],
                        "draft_answer": draft_answer[:1800],
                        "context": context,
                    },
                    ensure_ascii=False,
                )[:5000],
            },
        ],
        "temperature": 0.2,
        "max_tokens": max(settings["max_tokens"], 260),
        "response_format": {"type": "json_object"},
    }
    req = urllib.request.Request(
        settings["base_url"] + "/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + settings["api_key"],
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=settings["timeout_seconds"]) as response:
        data = json.loads(response.read().decode("utf-8"))
    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    parsed = extract_json_object(str(content))
    return {
        "raw": parsed,
        "usage": data.get("usage") if isinstance(data.get("usage"), dict) else {},
    }


def classify(text: str, *, config_path: Path = CONFIG_PATH, env_path: Path = ENV_PATH) -> dict[str, Any]:
    settings = resolve_settings(config_path, env_path)
    record: dict[str, Any] = {
        "generated_at": now_text(),
        "host": socket.gethostname(),
        "provider": settings["provider"],
        "model": settings["model"],
        "enabled": settings["enabled"],
        "used": False,
        "intent": "",
        "confidence": 0.0,
        "reason": "",
        "error": "",
        "mode": settings["mode"],
    }
    if not settings["enabled"]:
        record["error"] = "llm-disabled"
        return record
    if settings["mode"] != "advisory_only":
        record["error"] = "llm-mode-not-advisory"
        return record
    if not settings["api_key"]:
        record["error"] = "missing-api-key"
        return record
    if not settings["base_url"]:
        record["error"] = "missing-base-url"
        return record

    try:
        response = call_chat_completion(settings, text)
        raw = response["raw"]
        intent = str(raw.get("intent") or "").strip()
        confidence = float(raw.get("confidence") or 0)
        if intent not in ALLOWED_INTENTS:
            raise ValueError(f"unsupported-intent:{intent}")
        if intent == "budget_commit" and not settings["allow_budget_commit"]:
            intent = "budget_preview"
        if intent == "execute_non_ordering" and not settings["allow_production_actions"]:
            # The outer command layer still requires --execute. Keep the intent so it can ask for confirmation.
            pass
        record.update(
            {
                "used": True,
                "intent": intent,
                "confidence": confidence,
                "reason": str(raw.get("reason") or "")[:300],
                "usage": response["usage"],
            }
        )
    except urllib.error.HTTPError as exc:
        record["error"] = f"http-{exc.code}"
    except Exception as exc:
        record["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
    return record


def generate_answer(
    *,
    question: str,
    draft_answer: str,
    context: dict[str, Any],
    config_path: Path = CONFIG_PATH,
    env_path: Path = ENV_PATH,
) -> dict[str, Any]:
    settings = resolve_settings(config_path, env_path)
    record: dict[str, Any] = {
        "generated_at": now_text(),
        "host": socket.gethostname(),
        "provider": settings["provider"],
        "model": settings["model"],
        "enabled": settings["enabled"],
        "used": False,
        "answer": "",
        "confidence": 0.0,
        "reason": "",
        "error": "",
        "mode": settings["mode"],
    }
    if not settings["enabled"]:
        record["error"] = "llm-disabled"
        return record
    if settings["mode"] != "advisory_only":
        record["error"] = "llm-mode-not-advisory"
        return record
    if not settings["api_key"]:
        record["error"] = "missing-api-key"
        return record

    try:
        response = call_answer_completion(settings, question=question, draft_answer=draft_answer, context=context)
        raw = response["raw"]
        answer = str(raw.get("answer") or "").strip()
        confidence = float(raw.get("confidence") or 0)
        if not answer:
            raise ValueError("empty-answer")
        record.update(
            {
                "used": True,
                "answer": answer[:1200],
                "confidence": confidence,
                "reason": str(raw.get("reason") or "")[:300],
                "usage": response["usage"],
            }
        )
    except urllib.error.HTTPError as exc:
        record["error"] = f"http-{exc.code}"
    except Exception as exc:
        record["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description="只读 advisory 模式的大模型意图识别。")
    parser.add_argument("text", nargs="*", help="要识别的自然语言命令")
    parser.add_argument("--output", default=str(LATEST_PATH), help="输出 JSON 路径")
    args = parser.parse_args()

    payload = classify(" ".join(args.text).strip())
    write_json(Path(args.output).expanduser(), payload)
    if payload.get("used"):
        print(f"{payload['intent']} confidence={payload['confidence']}")
        return 0
    print(f"LLM 未使用：{payload.get('error') or 'unknown'}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
