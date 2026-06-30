from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_DB = Path(__file__).resolve().parents[1] / "data" / "inventory.sqlite3"


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def cancellation_hash(original_hash: str) -> str:
    return hashlib.sha256(f"cancel-outbound-order:{original_hash}".encode("utf-8")).hexdigest()


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def find_original_import(
    conn: sqlite3.Connection,
    *,
    filename: str = "",
    file_hash: str = "",
) -> sqlite3.Row:
    if file_hash:
        row = conn.execute(
            """
            SELECT id, file_hash, filename, movement_type, source, status, line_count, created_at
            FROM import_files
            WHERE file_hash = ?
            """,
            (file_hash,),
        ).fetchone()
    elif filename:
        row = conn.execute(
            """
            SELECT id, file_hash, filename, movement_type, source, status, line_count, created_at
            FROM import_files
            WHERE filename = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (filename,),
        ).fetchone()
    else:
        raise ValueError("必须提供 --order-file、--file-hash 或 --filename")

    if row is None:
        target = file_hash or filename
        raise ValueError(f"没有找到已登记的出库单：{target}")
    if row["movement_type"] != "outbound":
        raise ValueError(f"目标导入记录不是出库单：{row['movement_type']}")
    if row["status"] != "success":
        raise ValueError(f"目标导入记录状态不是 success：{row['status']}")
    return row


def original_movements(conn: sqlite3.Connection, import_id: int) -> list[sqlite3.Row]:
    rows = conn.execute(
        """
        SELECT
            id, row_key, movement_type, sku, name, spec, unit, warehouse, address, store_name,
            quantity, signed_quantity, document_date, source_row, created_at
        FROM movements
        WHERE import_file_id = ?
          AND movement_type = 'outbound'
          AND signed_quantity < 0
        ORDER BY source_row, id
        """,
        (import_id,),
    ).fetchall()
    if not rows:
        raise ValueError("目标出库单没有可恢复的出库流水")
    return rows


def backup_db(db_path: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = backup_dir / f"{db_path.name}.backup-before-cancel-{stamp}"
    shutil.copy2(db_path, backup_path)
    return backup_path


def cancel_order(
    *,
    db_path: Path,
    order_file: Path | None = None,
    filename: str = "",
    file_hash: str = "",
    dry_run: bool = False,
    backup: bool = False,
    backup_dir: Path | None = None,
) -> dict:
    if order_file:
        if not order_file.exists():
            raise ValueError(f"订单文件不存在：{order_file}")
        file_hash = sha256_file(order_file)
        filename = filename or order_file.name

    backup_path = None
    with connect(db_path) as conn:
        original = find_original_import(conn, filename=filename, file_hash=file_hash)
        movements = original_movements(conn, int(original["id"]))
        restore_hash = cancellation_hash(str(original["file_hash"]))
        existing_restore = conn.execute(
            """
            SELECT id, filename, status, line_count, created_at
            FROM import_files
            WHERE file_hash = ?
            """,
            (restore_hash,),
        ).fetchone()

        items = [
            {
                "sku": row["sku"],
                "name": row["name"],
                "quantity": float(row["quantity"]),
                "unit": row["unit"],
                "store_name": row["store_name"],
                "source_row": int(row["source_row"] or 0),
            }
            for row in movements
        ]
        payload = {
            "status": "already_restored" if existing_restore else "dry_run" if dry_run else "restored",
            "db_path": str(db_path),
            "original": {
                "id": int(original["id"]),
                "filename": original["filename"],
                "file_hash": original["file_hash"],
                "source": original["source"],
                "created_at": original["created_at"],
            },
            "restore": dict(existing_restore) if existing_restore else None,
            "items": items,
            "total_quantity": sum(item["quantity"] for item in items),
            "backup_path": str(backup_path) if backup_path else "",
        }
        if dry_run or existing_restore:
            return payload

        if backup:
            backup_path = backup_db(db_path, backup_dir or db_path.parent)
            payload["backup_path"] = str(backup_path)

        created_at = now_iso()
        restore_filename = f"取消恢复-{original['filename']}"
        cursor = conn.execute(
            """
            INSERT INTO import_files (file_hash, filename, movement_type, source, status, line_count, message, created_at)
            VALUES (?, ?, 'inbound', 'order_cancellation', 'processing', 0, ?, ?)
            """,
            (
                restore_hash,
                restore_filename,
                f"恢复取消出库单：{original['filename']}；原导入ID：{original['id']}",
                created_at,
            ),
        )
        restore_id = int(cursor.lastrowid)
        inserted = 0
        for row in movements:
            quantity = abs(float(row["quantity"]))
            conn.execute(
                """
                INSERT INTO movements (
                    import_file_id, row_key, movement_type, sku, name, spec, unit, warehouse, address, store_name,
                    quantity, signed_quantity, document_date, source_row, created_at
                )
                VALUES (?, ?, 'inbound', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    restore_id,
                    f"{restore_hash}:restore:{row['id']}",
                    row["sku"],
                    row["name"],
                    row["spec"],
                    row["unit"],
                    row["warehouse"],
                    row["address"],
                    row["store_name"],
                    quantity,
                    quantity,
                    row["document_date"],
                    row["source_row"],
                    created_at,
                ),
            )
            inserted += 1
        conn.execute(
            """
            UPDATE import_files
            SET status = 'success', line_count = ?, message = ?
            WHERE id = ?
            """,
            (
                inserted,
                f"已恢复取消出库单：{original['filename']}；原导入ID：{original['id']}",
                restore_id,
            ),
        )
        conn.commit()
        payload["restore"] = {
            "id": restore_id,
            "filename": restore_filename,
            "status": "success",
            "line_count": inserted,
            "created_at": created_at,
        }
        return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="按已登记出库单插入反向恢复流水，用于订单取消后恢复库存。")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="库存 SQLite 数据库路径")
    parser.add_argument("--order-file", type=Path, help="原出库 Excel 文件，用于按 SHA256 精确匹配")
    parser.add_argument("--filename", default="", help="原出库单文件名；未提供 order-file/file-hash 时使用")
    parser.add_argument("--file-hash", default="", help="原出库单 SHA256；优先于 filename")
    parser.add_argument("--dry-run", action="store_true", help="只核对将恢复的流水，不写数据库")
    parser.add_argument("--backup", action="store_true", help="写入前备份数据库")
    parser.add_argument("--backup-dir", type=Path, help="数据库备份目录，默认与数据库同目录")
    args = parser.parse_args()

    result = cancel_order(
        db_path=args.db,
        order_file=args.order_file,
        filename=args.filename,
        file_hash=args.file_hash,
        dry_run=args.dry_run,
        backup=args.backup,
        backup_dir=args.backup_dir,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
