from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import struct
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from . import agent_inbox

DEFAULT_AGENT_STATUS_PATH = Path("/var/www/html/operation-workbench/outputs/agent_mobile/latest.json")


class WeComCallbackError(Exception):
    pass


def _sha1_signature(token: str, timestamp: str, nonce: str, encrypted: str) -> str:
    raw = "".join(sorted([token, timestamp, nonce, encrypted]))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def verify_signature(token: str, msg_signature: str, timestamp: str, nonce: str, encrypted: str) -> None:
    expected = _sha1_signature(token, timestamp, nonce, encrypted)
    if not secrets.compare_digest(expected, msg_signature):
        raise WeComCallbackError("invalid-msg-signature")


def _aes_key(encoding_aes_key: str) -> bytes:
    key_text = encoding_aes_key.strip()
    if len(key_text) != 43:
        raise WeComCallbackError("invalid-encoding-aes-key")
    try:
        return base64.b64decode(key_text + "=")
    except Exception as exc:
        raise WeComCallbackError("invalid-encoding-aes-key") from exc


def _pkcs7_unpad(data: bytes) -> bytes:
    if not data:
        raise WeComCallbackError("empty-cipher-plain")
    pad = data[-1]
    if pad < 1 or pad > 32:
        raise WeComCallbackError("invalid-padding")
    if data[-pad:] != bytes([pad]) * pad:
        raise WeComCallbackError("invalid-padding")
    return data[:-pad]


def _pkcs7_pad(data: bytes) -> bytes:
    block_size = 32
    pad = block_size - (len(data) % block_size)
    if pad == 0:
        pad = block_size
    return data + bytes([pad]) * pad


def decrypt_message(encrypted: str, encoding_aes_key: str, expected_receive_id: str = "") -> tuple[str, str]:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    key = _aes_key(encoding_aes_key)
    try:
        cipher_bytes = base64.b64decode(encrypted)
    except Exception as exc:
        raise WeComCallbackError("invalid-encrypt-base64") from exc
    cipher = Cipher(algorithms.AES(key), modes.CBC(key[:16]))
    decryptor = cipher.decryptor()
    plain = _pkcs7_unpad(decryptor.update(cipher_bytes) + decryptor.finalize())
    if len(plain) < 20:
        raise WeComCallbackError("invalid-plain-length")
    msg_len = struct.unpack("!I", plain[16:20])[0]
    msg = plain[20 : 20 + msg_len].decode("utf-8")
    receive_id = plain[20 + msg_len :].decode("utf-8")
    if expected_receive_id and receive_id and not secrets.compare_digest(receive_id, expected_receive_id):
        raise WeComCallbackError("receive-id-mismatch")
    return msg, receive_id


def encrypt_message(xml_text: str, encoding_aes_key: str, receive_id: str) -> str:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    key = _aes_key(encoding_aes_key)
    xml_bytes = xml_text.encode("utf-8")
    random16 = secrets.token_bytes(16)
    plain = random16 + struct.pack("!I", len(xml_bytes)) + xml_bytes + receive_id.encode("utf-8")
    cipher = Cipher(algorithms.AES(key), modes.CBC(key[:16]))
    encryptor = cipher.encryptor()
    encrypted = encryptor.update(_pkcs7_pad(plain)) + encryptor.finalize()
    return base64.b64encode(encrypted).decode("utf-8")


def parse_xml(text: str) -> dict[str, str]:
    try:
        root = ET.fromstring(text)
    except Exception as exc:
        raise WeComCallbackError("invalid-xml") from exc
    return {child.tag: child.text or "" for child in root}


def extract_encrypt(xml_text: str) -> str:
    payload = parse_xml(xml_text)
    encrypted = payload.get("Encrypt", "").strip()
    if not encrypted:
        raise WeComCallbackError("missing-encrypt")
    return encrypted


def cdata(value: str) -> str:
    return "<![CDATA[" + value.replace("]]>", "]]]]><![CDATA[>") + "]]>"


def build_plain_text_reply(inbound: dict[str, str], content: str, now: int | None = None) -> str:
    to_user = inbound.get("FromUserName", "")
    from_user = inbound.get("ToUserName", "")
    return (
        "<xml>"
        f"<ToUserName>{cdata(to_user)}</ToUserName>"
        f"<FromUserName>{cdata(from_user)}</FromUserName>"
        f"<CreateTime>{int(now or time.time())}</CreateTime>"
        f"<MsgType>{cdata('text')}</MsgType>"
        f"<Content>{cdata(content[:1800])}</Content>"
        "</xml>"
    )


def build_encrypted_response(
    *,
    reply_plain_xml: str,
    token: str,
    encoding_aes_key: str,
    receive_id: str,
    timestamp: str | None = None,
    nonce: str | None = None,
) -> str:
    ts = timestamp or str(int(time.time()))
    nonce_value = nonce or secrets.token_hex(8)
    encrypted = encrypt_message(reply_plain_xml, encoding_aes_key, receive_id)
    signature = _sha1_signature(token, ts, nonce_value, encrypted)
    return (
        "<xml>"
        f"<Encrypt>{cdata(encrypted)}</Encrypt>"
        f"<MsgSignature>{cdata(signature)}</MsgSignature>"
        f"<TimeStamp>{ts}</TimeStamp>"
        f"<Nonce>{cdata(nonce_value)}</Nonce>"
        "</xml>"
    )


def read_agent_status(path: Path | None = None) -> dict[str, Any]:
    status_path = path or Path(os.environ.get("WECOM_AGENT_STATUS_PATH", str(DEFAULT_AGENT_STATUS_PATH))).expanduser()
    try:
        payload = json.loads(status_path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _match_answer(text: str, answers: list[dict[str, Any]], intent: str) -> str:
    for item in answers:
        if isinstance(item, dict) and item.get("intent") == intent and item.get("answer"):
            return str(item["answer"])
    return ""


def answer_agent_text(text: str, status: dict[str, Any] | None = None) -> str:
    clean = " ".join(str(text or "").split())
    payload = status if isinstance(status, dict) else read_agent_status()
    answers = payload.get("answers") if isinstance(payload.get("answers"), list) else []
    generated_at = str(payload.get("generated_at") or "未知时间")
    lower = clean.lower()

    if not clean:
        return "我在。你可以问：任务正常吗、今天哪里失败、哪些能补跑、执行 Agent 是谁。"
    if any(word in clean for word in ("订货", "下单", "采购", "快驴")) or any(word in lower for word in ("order", "purchase")):
        return "这个属于订货/下单/采购范围，当前 Agent 不参与执行。我可以帮你报告状态，但不会在企微里触发订货动作。"
    if any(word in clean for word in ("补跑", "重跑", "恢复")):
        if any(word in clean for word in ("预算", "推广", "执行", "发布", "上线")):
            return "这类动作需要 Mac mini 显式执行确认，企微回调入口当前只做只读回答，不会直接触发生产动作。"
        answer = _match_answer(clean, answers, "rerun")
        return answer or "当前没有读到补跑计划。"
    if any(word in clean for word in ("失败", "异常", "问题", "报错", "没完成")):
        answer = _match_answer(clean, answers, "problems")
        return answer or "我没读到明确失败项。"
    if "执行" in clean or "4号" in clean or "4 号" in clean:
        answer = _match_answer(clean, answers, "execution_agent")
        return answer or "执行 Agent 默认不启用；订货/下单/采购仍排除。"
    if any(word in clean for word in ("状态", "正常", "怎么样", "情况", "稳", "完成")):
        answer = _match_answer(clean, answers, "status")
        if answer:
            return answer
        summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
        return (
            f"最近一次 Agent 状态来自 {generated_at}：成功 {summary.get('agent_success', 0)} 个，"
            f"失败 {summary.get('agent_failed', 0)} 个，跳过 {summary.get('agent_skipped', 0)} 个。"
        )
    if "help" in lower or "帮助" in clean or "怎么问" in clean:
        return "你可以问：任务正常吗、今天哪里失败、哪些能补跑、执行 Agent 是谁。企微入口当前只读，不直接执行生产动作。"
    answer = _match_answer(clean, answers, "status")
    return answer or "我收到了，但云端暂时没有可用 Agent 状态。请稍后再问，或在 Mac mini 刷新 Agent 状态。"


def answer_or_enqueue(text: str, *, sender: str = "", status: dict[str, Any] | None = None) -> str:
    policy = agent_inbox.command_policy(text)
    if policy.get("intent") == "blocked_ordering":
        return answer_agent_text(text, status=status)
    if not policy.get("enqueue"):
        return answer_agent_text(text, status=status)
    item = agent_inbox.append_task(
        text=text,
        intent=str(policy.get("intent") or ""),
        execute=bool(policy.get("execute")),
        source="wecom-agent",
        sender=sender,
    )
    if item["intent"] == "budget_commit":
        action = "真实预算提交流程"
    elif item["intent"] == "budget_preview":
        action = "预算预览/安全计划，不会直接提交预算"
    elif item["intent"] == "meituan_spend_inspection":
        action = "美团推广余量/实时消耗只读巡检，不会修改预算或出价"
    elif item["intent"] == "refresh_status":
        action = "刷新 Agent 状态和手机入口数据"
    elif item["intent"] == "publish_mobile":
        action = "发布手机入口和工作台数据"
    elif item["intent"] == "rerun_plan":
        action = "执行安全补跑清单，只跑低风险允许项"
    else:
        action = "执行允许的非订货动作"
    return f"已收到，已加入 Mac mini 队列：{action}。队列编号：{item['id'][:8]}。完成后会通过企业微信通知结果。"


def callback_settings() -> dict[str, str]:
    return {
        "token": os.environ.get("WECOM_AGENT_CALLBACK_TOKEN", "").strip(),
        "encoding_aes_key": os.environ.get("WECOM_AGENT_ENCODING_AES_KEY", "").strip(),
        "corp_id": os.environ.get("WECOM_AGENT_CORP_ID", "").strip(),
    }


def verify_url(*, msg_signature: str, timestamp: str, nonce: str, echostr: str, settings: dict[str, str]) -> str:
    verify_signature(settings["token"], msg_signature, timestamp, nonce, echostr)
    plain, _receive_id = decrypt_message(echostr, settings["encoding_aes_key"], settings.get("corp_id", ""))
    return plain


def handle_callback_post(
    *,
    body: str,
    msg_signature: str,
    timestamp: str,
    nonce: str,
    settings: dict[str, str],
    status: dict[str, Any] | None = None,
) -> str:
    encrypted = extract_encrypt(body)
    verify_signature(settings["token"], msg_signature, timestamp, nonce, encrypted)
    plain_xml, receive_id = decrypt_message(encrypted, settings["encoding_aes_key"], settings.get("corp_id", ""))
    inbound = parse_xml(plain_xml)
    msg_type = inbound.get("MsgType", "")
    if msg_type != "text":
        answer = "我收到了，但当前企微 Agent 入口只处理文字消息。"
    else:
        answer = answer_or_enqueue(inbound.get("Content", ""), sender=inbound.get("FromUserName", ""), status=status)
    reply_plain = build_plain_text_reply(inbound, answer)
    return build_encrypted_response(
        reply_plain_xml=reply_plain,
        token=settings["token"],
        encoding_aes_key=settings["encoding_aes_key"],
        receive_id=settings.get("corp_id") or receive_id,
    )


def configured(settings: dict[str, str] | None = None) -> bool:
    values = settings or callback_settings()
    return bool(values.get("token") and values.get("encoding_aes_key"))
