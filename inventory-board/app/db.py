from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path


DB_PATH = Path(__file__).resolve().parents[1] / "data" / "inventory.sqlite3"


@contextmanager
def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS products (
                sku TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                spec TEXT DEFAULT '',
                unit TEXT DEFAULT '',
                warehouse TEXT DEFAULT '',
                unit_cost REAL DEFAULT 0,
                warning_threshold REAL DEFAULT 10,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS import_files (
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

            CREATE TABLE IF NOT EXISTS movements (
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
                created_at TEXT NOT NULL,
                FOREIGN KEY(import_file_id) REFERENCES import_files(id)
            );
            """
        )
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(products)").fetchall()}
        if "unit_cost" not in columns:
            conn.execute("ALTER TABLE products ADD COLUMN unit_cost REAL DEFAULT 0")
        import_columns = {row["name"] for row in conn.execute("PRAGMA table_info(import_files)").fetchall()}
        if "source" not in import_columns:
            conn.execute("ALTER TABLE import_files ADD COLUMN source TEXT NOT NULL DEFAULT 'manual_upload'")
        movement_columns = {row["name"] for row in conn.execute("PRAGMA table_info(movements)").fetchall()}
        if "address" not in movement_columns:
            conn.execute("ALTER TABLE movements ADD COLUMN address TEXT DEFAULT ''")
        if "store_name" not in movement_columns:
            conn.execute("ALTER TABLE movements ADD COLUMN store_name TEXT DEFAULT ''")


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def upsert_product(
    conn: sqlite3.Connection,
    *,
    sku: str,
    name: str,
    spec: str = "",
    unit: str = "",
    warehouse: str = "",
    unit_cost: float | int | str = 0,
) -> None:
    existing = conn.execute("SELECT sku, name, spec, unit, warehouse, unit_cost FROM products WHERE sku = ?", (sku,)).fetchone()
    parsed_cost = _to_float(unit_cost)
    if existing:
        conn.execute(
            """
            UPDATE products
            SET name = CASE WHEN name = '' OR name = sku THEN COALESCE(NULLIF(?, ''), name) ELSE name END,
                spec = CASE WHEN spec = '' THEN COALESCE(NULLIF(?, ''), spec) ELSE spec END,
                unit = CASE WHEN unit = '' THEN COALESCE(NULLIF(?, ''), unit) ELSE unit END,
                warehouse = CASE WHEN warehouse = '' THEN COALESCE(NULLIF(?, ''), warehouse) ELSE warehouse END,
                unit_cost = CASE WHEN ? > 0 THEN ? ELSE unit_cost END,
                updated_at = ?
            WHERE sku = ?
            """,
            (name, spec, unit, warehouse, parsed_cost, parsed_cost, now_iso(), sku),
        )
        return

    conn.execute(
        """
        INSERT INTO products (sku, name, spec, unit, warehouse, unit_cost, warning_threshold, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, 10, ?)
        """,
        (sku, name or sku, spec, unit, warehouse, parsed_cost, now_iso()),
    )


def create_import(
    conn: sqlite3.Connection,
    *,
    file_hash: str,
    filename: str,
    movement_type: str,
    source: str = "manual_upload",
) -> int | None:
    if conn.execute("SELECT 1 FROM import_files WHERE file_hash = ?", (file_hash,)).fetchone():
        return None
    cursor = conn.execute(
        """
        INSERT INTO import_files (file_hash, filename, movement_type, source, status, created_at)
        VALUES (?, ?, ?, ?, 'processing', ?)
        """,
        (file_hash, filename, movement_type, source, now_iso()),
    )
    return int(cursor.lastrowid)


def finish_import(conn: sqlite3.Connection, import_id: int, *, status: str, line_count: int, message: str = "") -> None:
    conn.execute(
        "UPDATE import_files SET status = ?, line_count = ?, message = ? WHERE id = ?",
        (status, line_count, message, import_id),
    )


def inventory_summary() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT
                p.sku,
                p.name,
                p.spec,
                p.unit,
                p.warehouse,
                p.unit_cost,
                p.warning_threshold,
                COALESCE(SUM(m.signed_quantity), 0) AS balance,
                COALESCE(SUM(m.signed_quantity), 0) * COALESCE(p.unit_cost, 0) AS inventory_value,
                MAX(CASE WHEN m.movement_type = 'inbound' THEN m.created_at END) AS last_inbound_at,
                MAX(CASE WHEN m.movement_type = 'outbound' THEN m.created_at END) AS last_outbound_at
            FROM products p
            LEFT JOIN movements m ON m.sku = p.sku
            GROUP BY p.sku
            ORDER BY
                CASE
                    WHEN p.sku LIKE 'LD%' THEN 0
                    WHEN p.sku LIKE 'CW%' THEN 1
                    ELSE 2
                END,
                CAST(substr(p.sku, -4) AS INTEGER),
                p.sku
            """
        ).fetchall()
    return [dict(row) for row in rows]


def inventory_warning_items(skus: list[str] | set[str] | tuple[str, ...]) -> list[dict]:
    clean_skus = sorted({str(sku).strip() for sku in skus if str(sku).strip()})
    if not clean_skus:
        return []
    placeholders = ",".join("?" for _ in clean_skus)
    with connect() as conn:
        rows = conn.execute(
            f"""
            SELECT
                p.sku,
                p.name,
                p.spec,
                p.unit,
                p.warehouse,
                p.warning_threshold,
                COALESCE(SUM(m.signed_quantity), 0) AS balance
            FROM products p
            LEFT JOIN movements m ON m.sku = p.sku
            WHERE p.sku IN ({placeholders})
            GROUP BY p.sku
            HAVING balance <= p.warning_threshold
            ORDER BY balance ASC, p.sku
            """,
            clean_skus,
        ).fetchall()
    return [dict(row) for row in rows]


def recent_imports(limit: int = 20) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, filename, movement_type, source, status, line_count, message, created_at
            FROM import_files
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def recent_movements(limit: int = 50) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT
                movements.movement_type,
                movements.sku,
                movements.name,
                movements.quantity,
                movements.unit,
                movements.store_name,
                movements.document_date,
                import_files.filename,
                movements.created_at
            FROM movements
            JOIN import_files ON import_files.id = movements.import_file_id
            ORDER BY movements.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def delivery_months() -> list[str]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT substr(created_at, 1, 7) AS month
            FROM movements
            WHERE movement_type = 'outbound' AND created_at != ''
            ORDER BY month DESC
            """
        ).fetchall()
    return [row["month"] for row in rows if row["month"]]


def store_delivery_summary(month: str | None = None) -> list[dict]:
    params = []
    month_filter = ""
    if month:
        month_filter = "AND substr(m.created_at, 1, 7) = ?"
        params.append(month)

    with connect() as conn:
        rows = conn.execute(
            f"""
            SELECT
                COALESCE(NULLIF(m.store_name, ''), '未识别门店') AS store_name,
                COALESCE(NULLIF(m.document_date, ''), substr(m.created_at, 1, 10)) AS delivery_date,
                m.sku,
                p.name AS product_name,
                p.unit,
                SUM(m.quantity) AS quantity
            FROM movements m
            LEFT JOIN products p ON p.sku = m.sku
            WHERE m.movement_type = 'outbound'
            {month_filter}
            GROUP BY store_name, delivery_date, m.sku
            ORDER BY
                CASE store_name
                    WHEN '银泰城店' THEN 1
                    WHEN '万象城店' THEN 2
                    WHEN '金融城店' THEN 3
                    WHEN '保利中心店' THEN 4
                    ELSE 9
                END,
                delivery_date DESC,
                CASE
                    WHEN m.sku LIKE 'LD%' THEN 0
                    WHEN m.sku LIKE 'CW%' THEN 1
                    ELSE 2
                END,
                CAST(substr(m.sku, -4) AS INTEGER),
                m.sku
            """,
            params,
        ).fetchall()

    stores: dict[str, dict] = {}
    for row in rows:
        item = dict(row)
        store_name = item.pop("store_name")
        delivery_date = item.pop("delivery_date") or "未注明日期"
        store = stores.setdefault(store_name, {"items": {}, "dates": {}})
        sku = item["sku"]
        existing = store["items"].setdefault(
            sku,
            {
                "sku": sku,
                "product_name": item["product_name"],
                "unit": item["unit"],
                "quantity": 0,
            },
        )
        existing["quantity"] += item["quantity"] or 0
        store["dates"][delivery_date] = store["dates"].get(delivery_date, 0) + (item["quantity"] or 0)

    result = []
    for store_name, payload in stores.items():
        dates = [
            {"date": date, "quantity": quantity}
            for date, quantity in sorted(payload["dates"].items(), reverse=True)
        ]
        result.append({"store_name": store_name, "items": list(payload["items"].values()), "dates": dates})
    return result


def inventory_flow_summary(month: str | None = None, limit: int = 80) -> dict:
    params: list[str] = []
    movement_filter = ""
    if month:
        movement_filter = "AND substr(m.created_at, 1, 7) = ?"
        params.append(month)

    with connect() as conn:
        product_rows = conn.execute(
            f"""
            SELECT
                p.sku,
                p.name,
                p.spec,
                p.unit,
                p.warehouse,
                p.unit_cost,
                COALESCE(SUM(CASE WHEN m.movement_type = 'inbound' {movement_filter} THEN m.quantity ELSE 0 END), 0) AS inbound_quantity,
                COALESCE(SUM(CASE WHEN m.movement_type = 'outbound' {movement_filter} THEN m.quantity ELSE 0 END), 0) AS outbound_quantity,
                COALESCE(SUM(m.signed_quantity), 0) AS current_balance,
                COALESCE(SUM(m.signed_quantity), 0) * COALESCE(p.unit_cost, 0) AS current_value,
                MAX(CASE WHEN m.movement_type = 'inbound' THEN m.created_at END) AS last_inbound_at,
                MAX(CASE WHEN m.movement_type = 'outbound' THEN m.created_at END) AS last_outbound_at
            FROM products p
            LEFT JOIN movements m ON m.sku = p.sku
            GROUP BY p.sku
            HAVING inbound_quantity > 0 OR outbound_quantity > 0 OR current_balance != 0
            ORDER BY outbound_quantity DESC, inbound_quantity DESC, current_value DESC, p.sku
            LIMIT ?
            """,
            [*params, *params, limit],
        ).fetchall()

        store_rows = conn.execute(
            f"""
            SELECT
                m.sku,
                COALESCE(NULLIF(m.store_name, ''), '未识别去向') AS destination,
                SUM(m.quantity) AS quantity
            FROM movements m
            WHERE m.movement_type = 'outbound'
            {movement_filter}
            GROUP BY m.sku, destination
            ORDER BY m.sku, quantity DESC
            """,
            params,
        ).fetchall()

        recent_rows = conn.execute(
            f"""
            SELECT
                m.movement_type,
                m.sku,
                m.name,
                m.quantity,
                m.unit,
                COALESCE(NULLIF(m.store_name, ''), NULLIF(m.address, ''), '未识别去向') AS destination,
                m.document_date,
                m.created_at,
                f.filename,
                f.source
            FROM movements m
            JOIN import_files f ON f.id = m.import_file_id
            WHERE 1 = 1
            {movement_filter}
            ORDER BY m.id DESC
            LIMIT 40
            """,
            params,
        ).fetchall()

    destinations: dict[str, list[dict]] = {}
    for row in store_rows:
        item = dict(row)
        destinations.setdefault(item["sku"], []).append(
            {
                "destination": item["destination"],
                "quantity": item["quantity"] or 0,
            }
        )

    items = []
    for row in product_rows:
        item = dict(row)
        item["destinations"] = destinations.get(item["sku"], [])[:8]
        items.append(item)

    totals = {
        "inbound_quantity": sum(float(item["inbound_quantity"] or 0) for item in items),
        "outbound_quantity": sum(float(item["outbound_quantity"] or 0) for item in items),
        "current_value": sum(float(item["current_value"] or 0) for item in items),
        "sku_count": len(items),
    }
    return {
        "month": month or "",
        "items": items,
        "recent_movements": [dict(row) for row in recent_rows],
        "totals": totals,
    }


def set_warning_threshold(sku: str, threshold: Decimal) -> bool:
    with connect() as conn:
        cursor = conn.execute(
            "UPDATE products SET warning_threshold = ?, updated_at = ? WHERE sku = ?",
            (float(threshold), now_iso(), sku),
        )
        return cursor.rowcount > 0


def _to_float(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0
