import csv
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent
DATABASE_DIR = BASE_DIR / "database"
DB_PATH = DATABASE_DIR / "pin_system.db"
CSV_DIR = DATABASE_DIR


def normalize_date(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    for fmt in ("%Y/%m/%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    return value


def read_csv_rows(filename: str) -> list[dict[str, str]]:
    with (CSV_DIR / filename).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        PRAGMA foreign_keys = ON;

        CREATE TABLE part (
            part_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            stock INTEGER NOT NULL DEFAULT 0 CHECK (stock >= 0),
            description TEXT
        );

        CREATE TABLE product (
            product_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL
        );

        CREATE TABLE product_part (
            product_id INTEGER NOT NULL,
            part_id INTEGER NOT NULL,
            component TEXT NOT NULL,
            quantity INTEGER NOT NULL CHECK (quantity > 0),
            effective_from TEXT NOT NULL,
            effective_to TEXT NOT NULL,
            PRIMARY KEY (product_id, part_id, effective_from, effective_to),
            FOREIGN KEY (product_id) REFERENCES product(product_id),
            FOREIGN KEY (part_id) REFERENCES part(part_id)
        );

        CREATE TABLE supplier (
            supplier_id INTEGER PRIMARY KEY,
            supplier_name TEXT NOT NULL,
            contact_email TEXT,
            link TEXT,
            lead_time INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE part_supplier (
            part_id INTEGER NOT NULL,
            supplier_id INTEGER NOT NULL,
            price REAL NOT NULL,
            preferred_order INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (part_id, supplier_id),
            FOREIGN KEY (part_id) REFERENCES part(part_id),
            FOREIGN KEY (supplier_id) REFERENCES supplier(supplier_id)
        );

        CREATE TABLE current_order (
            product_id INTEGER NOT NULL,
            customer_id INTEGER NOT NULL,
            order_date TEXT NOT NULL,
            PRIMARY KEY (product_id, customer_id, order_date),
            FOREIGN KEY (product_id) REFERENCES product(product_id)
        );

        CREATE TABLE IF NOT EXISTS production_progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            component TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Pending',
            photo_path TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (product_id) REFERENCES product(product_id)
        );
        """
    )


def load_data(connection: sqlite3.Connection) -> None:
    part_rows = read_csv_rows("Part.csv")
    connection.executemany(
        "INSERT INTO part (part_id, name, type, stock, description) VALUES (?, ?, ?, ?, ?)",
        [
            (
                int(row["part_id"]),
                row["name"],
                row["type"],
                int(row.get("stock", 0)),
                row.get("description", ""),
            )
            for row in part_rows
        ],
    )

    product_rows = read_csv_rows("Product.csv")
    connection.executemany(
        "INSERT INTO product (product_id, name) VALUES (?, ?)",
        [(int(row["product_id"]), row["name"]) for row in product_rows],
    )

    product_part_rows = read_csv_rows("Product_Part.csv")
    connection.executemany(
        "INSERT INTO product_part (product_id, part_id, component, quantity, effective_from, effective_to) VALUES (?, ?, ?, ?, ?, ?)",
        [
            (
                int(row["product_id"]),
                int(row["part_id"]),
                row["component"],
                int(row["quantity"]),
                normalize_date(row["effective_from"]),
                normalize_date(row["effective_to"]),
            )
            for row in product_part_rows
        ],
    )

    supplier_rows = read_csv_rows("Supplier.csv")
    connection.executemany(
        "INSERT INTO supplier (supplier_id, supplier_name, contact_email, link, lead_time) VALUES (?, ?, ?, ?, ?)",
        [
            (
                int(row["supplier_id"]),
                row["supplier_name"],
                row.get("contact_email", ""),
                row.get("link", ""),
                int(row.get("lead_time", 0)),
            )
            for row in supplier_rows
        ],
    )

    part_supplier_rows = read_csv_rows("Part_Supplier.csv")
    connection.executemany(
        "INSERT INTO part_supplier (part_id, supplier_id, price, preferred_order) VALUES (?, ?, ?, ?)",
        [
            (
                int(row["part_id"]),
                int(row["supplier_id"]),
                float(row["price"]),
                int(row["preferred_order"]),
            )
            for row in part_supplier_rows
        ],
    )

    current_order_rows = read_csv_rows("Current_Order.csv")
    connection.executemany(
        "INSERT INTO current_order (product_id, customer_id, order_date) VALUES (?, ?, ?)",
        [
            (
                int(row["product_id"]),
                int(row["customer_id"]),
                normalize_date(row["order_date"]),
            )
            for row in current_order_rows
        ],
    )


def main() -> None:
    DATABASE_DIR.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()

    connection = sqlite3.connect(DB_PATH)
    try:
        create_schema(connection)
        load_data(connection)
        connection.commit()
        print(f"Initialized SQLite database at {DB_PATH}")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
