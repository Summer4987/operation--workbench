from __future__ import annotations

import base64
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "inventory-board"))

from app import agent_wecom  # noqa: E402

try:
    import cryptography  # noqa: F401

    HAS_CRYPTOGRAPHY = True
except Exception:
    HAS_CRYPTOGRAPHY = False


def sample_key() -> str:
    return base64.b64encode(b"0123456789abcdef0123456789abcdef").decode("utf-8").rstrip("=")


class AgentWecomCallbackTests(unittest.TestCase):
    @unittest.skipUnless(HAS_CRYPTOGRAPHY, "cryptography is required for WeCom AES callback tests")
    def test_encrypt_decrypt_roundtrip(self) -> None:
        key = sample_key()
        xml = "<xml><ToUserName><![CDATA[corp]]></ToUserName><Content><![CDATA[任务正常吗]]></Content></xml>"

        encrypted = agent_wecom.encrypt_message(xml, key, "corp-id")
        decrypted, receive_id = agent_wecom.decrypt_message(encrypted, key, "corp-id")

        self.assertEqual(decrypted, xml)
        self.assertEqual(receive_id, "corp-id")

    @unittest.skipUnless(HAS_CRYPTOGRAPHY, "cryptography is required for WeCom AES callback tests")
    def test_handle_callback_post_replies_with_status_answer(self) -> None:
        key = sample_key()
        token = "token123"
        settings = {"token": token, "encoding_aes_key": key, "corp_id": "corp-id"}
        inbound = (
            "<xml>"
            "<ToUserName><![CDATA[corp-id]]></ToUserName>"
            "<FromUserName><![CDATA[summer]]></FromUserName>"
            "<MsgType><![CDATA[text]]></MsgType>"
            "<Content><![CDATA[任务正常吗]]></Content>"
            "</xml>"
        )
        encrypted = agent_wecom.encrypt_message(inbound, key, "corp-id")
        timestamp = "1780000000"
        nonce = "abc"
        signature = agent_wecom._sha1_signature(token, timestamp, nonce, encrypted)
        body = f"<xml><Encrypt><![CDATA[{encrypted}]]></Encrypt></xml>"

        response_xml = agent_wecom.handle_callback_post(
            body=body,
            msg_signature=signature,
            timestamp=timestamp,
            nonce=nonce,
            settings=settings,
            status={
                "generated_at": "2026-07-04 12:00:00",
                "answers": [{"intent": "status", "answer": "Agent 正常，失败 0 个。"}],
            },
        )
        response = agent_wecom.parse_xml(response_xml)
        decrypted, _receive_id = agent_wecom.decrypt_message(response["Encrypt"], key, "corp-id")

        self.assertIn("Agent 正常", decrypted)
        self.assertIn("<ToUserName><![CDATA[summer]]></ToUserName>", decrypted)

    def test_ordering_request_is_blocked(self) -> None:
        answer = agent_wecom.answer_agent_text("帮我补跑订货", {"answers": []})

        self.assertIn("不参与执行", answer)
        self.assertIn("订货", answer)


if __name__ == "__main__":
    unittest.main()
