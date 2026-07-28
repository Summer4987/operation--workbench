#!/usr/bin/env python3
"""Build sanitized text templates from the approved DOCX contracts."""

from __future__ import annotations

import argparse
import html
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "franchise-contract-generator" / "templates"


def paragraphs(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
    result: list[str] = []
    for paragraph in root.iter(f"{W}p"):
        text = "".join(node.text or "" for node in paragraph.iter(f"{W}t"))
        text = html.unescape(text).strip()
        if text:
            result.append(text)
    return result


def build_brand(source: Path) -> str:
    output = []
    for line in paragraphs(source):
        if line.startswith("乙方："):
            line = re.sub(r"(?<=乙方：).*", "{{party_name}}", line)
        elif line.startswith("统一社会信用代码/身份证号：420203"):
            line = "统一社会信用代码/身份证号：{{party_id}}"
        elif line.startswith("地址：湖北省"):
            line = "地址：{{party_address}}"
        elif line.startswith("联系方式：185728"):
            line = "联系方式：{{party_phone}}"
        elif line.startswith("收件人：余宇霆"):
            line = "收件人：{{notice_contact}}"
        elif line.startswith("联系电话：185728"):
            line = "联系电话：{{notice_phone}}"
        elif line.startswith("电子邮箱：258944"):
            line = "电子邮箱：{{party_email}}"
        elif line.startswith("邮寄地址：湖北省"):
            line = "邮寄地址：{{notice_address}}"
        line = line.replace("_武汉_市", "{{license_city}}")
        line = line.replace("_3_年", "_{{term_years}}_年")
        line = line.replace("2026年7月28日", "{{sign_date}}")
        output.append(line)
    return "\n\n".join(output) + "\n"


def build_service(source: Path) -> str:
    output = []
    in_party_notice = False
    for line in paragraphs(source):
        if line.startswith("甲方送达地址："):
            in_party_notice = True
        elif line.startswith("乙方送达地址："):
            in_party_notice = False
        if line.startswith("甲方（委托方）："):
            line = "甲方（委托方）：{{party_name}}"
        elif line.startswith("统一社会信用代码/身份证号：420203"):
            line = "统一社会信用代码/身份证号：{{party_id}}"
        elif line.startswith("地址：湖北省"):
            line = "地址：{{party_address}}"
        elif line.startswith("联系方式: 185728"):
            line = "联系方式：{{party_phone}}"
        elif line.startswith("法定代表人/授权代表："):
            line = "法定代表人/授权代表：{{legal_representative}}"
        elif line.startswith("联系地址：湖北省"):
            line = "联系地址：{{party_address}}"
        elif line.startswith("联系电话：185728") or line.startswith("联系电话： 185728"):
            line = "联系电话：{{notice_phone}}" if in_party_notice else "联系电话：{{party_phone}}"
        elif line.startswith("甲方：") and "余宇霆" in line:
            line = "甲方：{{party_name}}"
        elif line.startswith("甲方送达地址："):
            line = "甲方送达地址：{{notice_address}}"
        elif line.startswith("联系人：余宇霆"):
            line = "联系人：{{notice_contact}}"
        elif line.startswith("邮箱：258944"):
            line = "邮箱：{{party_email}}"
        elif line.startswith("致xxx公司"):
            line = "致{{party_name}}："

        line = line.replace("万松园店", "{{store_short_name}}")
        line = line.replace("暂未确定", "{{store_address}}")
        line = line.replace("2026年7月28日", "{{start_date}}")
        line = line.replace("2029年7月28日", "{{end_date}}")
        if line.startswith("签订日期："):
            line = "签订日期：{{sign_date}}"
        if line.startswith("甲方（盖章）：法定代表人（或委托代理人）签字："):
            line = "甲方（盖章）：法定代表人（或委托代理人）签字：{{sign_date}}"
        if line.startswith("乙方（盖章）：法定代表人（或委托代理人）签字："):
            line = "乙方（盖章）：法定代表人（或委托代理人）签字：{{sign_date}}"
        if line.startswith("（甲方盖章或授权负责人签字）日期："):
            line = "（甲方盖章或授权负责人签字）日期：{{sign_date}}"
        if "甲方指定签收人员：" in line:
            line = re.sub(r"甲方指定签收人员：[^）]+", "甲方指定签收人员：{{receiver_name}}", line)
            line += " 指定收货电话：{{receiver_phone}}；指定收货地址：{{receiver_address}}。"
        output.append(line)
    return "\n\n".join(output) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("brand_docx", type=Path)
    parser.add_argument("service_docx", type=Path)
    args = parser.parse_args()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "brand-authorization.txt").write_text(build_brand(args.brand_docx), encoding="utf-8")
    (OUTPUT_DIR / "service-purchase.txt").write_text(build_service(args.service_docx), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
