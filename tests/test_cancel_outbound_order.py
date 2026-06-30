from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_cancel_module():
    script_path = ROOT / "inventory-board" / "scripts" / "cancel_outbound_order.py"
    spec = importlib.util.spec_from_file_location("cancel_outbound_order_for_tests", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def init_schema(conn):
    conn.executescript(
        """
        CREATE TABLE import_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_hash TEXT NOT NULL UNIQUE,
            filename TEXT NOT NULL,
            movement_type TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'manual_upload',
            status TEXT NOT NULL,
            line_count INTEGER DEFAULT 0,
            message TEXT DEFAULT '',
            created_at TEXT NOT NULL
        );

        CREATE TABLE movements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            import_file_id INTEGER NOT NULL,
            row_key TEXT NOT NULL UNIQUE,
            movement_type TEXT NOT NULL,
            sku TEXT NOT NULL,
            name TEXT NOT NULL,
            spec TEXT DEFAULT '',
            unit TEXT DEFAULT '',
            warehouse TEXT DEFAULT '',
            address TEXT DEFAULT '',
            store_name TEXT DEFAULT '',
            quantity REAL NOT NULL,
            signed_quantity REAL NOT NULL,
            document_date TEXT DEFAULT '',
            source_row INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        );
        """
    )


def seed_outbound(conn):
    cursor = conn.execute(
        """
        INSERT INTO import_files (file_hash, filename, movement_type, source, status, line_count, created_at)
        VALUES ('original-hash', '熊小小牛排饭订单模板_20260628_190149.xlsx', 'outbound', 'cloud_order', 'success', 2, '2026-06-28T19:01:49+08:00')
        """
    )
    import_id = cursor.lastrowid
    rows = [
        ("row-1", "CWXXX0001", "熊小小牛排饭-拌饭汁", "10kg/箱", "件", 2, -2, 2),
        ("row-2", "LDXXX0001", "熊小小牛排饭-牛五花牛排（冻）", "20kg/箱", "件", 3, -3, 3),
    ]
    for row_key, sku, name, spec, unit, quantity, signed_quantity, source_row in rows:
        conn.execute(
            """
            INSERT INTO movements (
                import_file_id, row_key, movement_type, sku, name, spec, unit, warehouse, address, store_name,
                quantity, signed_quantity, document_date, source_row, created_at
            )
            VALUES (?, ?, 'outbound', ?, ?, ?, ?, '', '金融城地址', '金融城店', ?, ?, '2026-06-28', ?, '2026-06-28T19:01:49+08:00')
            """,
            (import_id, row_key, sku, name, spec, unit, quantity, signed_quantity, source_row),
        )
    conn.commit()


def test_cancel_outbound_order_restores_once(tmp_path):
    module = load_cancel_module()
    db_path = tmp_path / "inventory.sqlite3"
    with module.connect(db_path) as conn:
        init_schema(conn)
        seed_outbound(conn)

    result = module.cancel_order(
        db_path=db_path,
        filename="熊小小牛排饭订单模板_20260628_190149.xlsx",
    )

    assert result["status"] == "restored"
    assert result["restore"]["line_count"] == 2
    assert result["total_quantity"] == 5

    with module.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT movement_type, sku, quantity, signed_quantity
            FROM movements
            WHERE movement_type = 'inbound'
            ORDER BY source_row
            """
        ).fetchall()
        assert [(row["sku"], row["quantity"], row["signed_quantity"]) for row in rows] == [
            ("CWXXX0001", 2, 2),
            ("LDXXX0001", 3, 3),
        ]

    second = module.cancel_order(
        db_path=db_path,
        filename="熊小小牛排饭订单模板_20260628_190149.xlsx",
    )
    assert second["status"] == "already_restored"

    with module.connect(db_path) as conn:
        inbound_count = conn.execute("SELECT COUNT(*) FROM movements WHERE movement_type = 'inbound'").fetchone()[0]
        assert inbound_count == 2
