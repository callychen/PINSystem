from pathlib import Path
import sqlite3
from typing import Optional

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "database" / "pin_system.db"
ROLES = ["Engineer", "Purchaser", "Production", "Client", "Manager"]

app = FastAPI(title="PINSystem", version="0.1.0")
app.mount("/static", StaticFiles(directory=BASE_DIR / "app" / "static"), name="static")

templates = Jinja2Templates(directory=BASE_DIR / "app" / "templates")


def get_db():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def get_role(request: Request):
    role = request.query_params.get("role", "Engineer")
    if role not in ROLES:
        return "Engineer"
    return role


def get_counts(connection: sqlite3.Connection):
    return {
        "parts": connection.execute("SELECT COUNT(*) AS count FROM part").fetchone()["count"],
        "products": connection.execute("SELECT COUNT(*) AS count FROM product").fetchone()["count"],
        "orders": connection.execute("SELECT COUNT(*) AS count FROM current_order").fetchone()["count"],
    }


def build_engineer_context(connection: sqlite3.Connection):
    return {
        "parts": connection.execute("SELECT * FROM part ORDER BY part_id").fetchall(),
        "products": connection.execute("SELECT * FROM product ORDER BY product_id").fetchall(),
        "product_parts": connection.execute("SELECT * FROM product_part ORDER BY product_id, part_id").fetchall(),
        "suppliers": connection.execute("SELECT * FROM supplier ORDER BY supplier_id").fetchall(),
        "part_suppliers": connection.execute("SELECT * FROM part_supplier ORDER BY part_id, supplier_id").fetchall(),
    }


def build_purchaser_context(connection: sqlite3.Connection, selected_product_id=None, message=None, modal_actions=None):
    orders = connection.execute(
        """
        SELECT co.product_id, co.customer_id, co.order_date, p.name AS product_name
        FROM current_order co
        JOIN product p ON p.product_id = co.product_id
        ORDER BY co.order_date DESC, co.product_id
        """
    ).fetchall()

    selected_order = None
    bom_items = []
    if selected_product_id is not None:
        selected_order = connection.execute(
            """
            SELECT co.product_id, co.customer_id, co.order_date, p.name AS product_name
            FROM current_order co
            JOIN product p ON p.product_id = co.product_id
            WHERE co.product_id = ?
            """,
            (selected_product_id,),
        ).fetchone()

        if selected_order is not None:
            # Only include product_part rows that were effective at the time of the order
            order_date = selected_order["order_date"]
            bom_rows = connection.execute(
                """
                SELECT pp.product_id, pp.part_id, pp.component, pp.quantity, p.name AS part_name, p.type AS part_type, p.stock
                FROM product_part pp
                JOIN part p ON p.part_id = pp.part_id
                WHERE pp.product_id = ? AND ? BETWEEN pp.effective_from AND pp.effective_to
                ORDER BY pp.component, pp.part_id
                """,
                (selected_product_id, order_date),
            ).fetchall()

            for row in bom_rows:
                supplier_rows = connection.execute(
                    """
                    SELECT ps.part_id, ps.supplier_id, s.supplier_name, ps.price, ps.preferred_order, s.contact_email, s.link
                    FROM part_supplier ps
                    JOIN supplier s ON s.supplier_id = ps.supplier_id
                    WHERE ps.part_id = ?
                    ORDER BY ps.preferred_order, ps.price
                    """,
                    (row["part_id"],),
                ).fetchall()

                mapped_suppliers = []
                for supplier_row in supplier_rows:
                    mapped_suppliers.append(
                        {
                            "supplier_id": supplier_row["supplier_id"],
                            "supplier_name": supplier_row["supplier_name"],
                            "price": supplier_row["price"],
                            "preferred_order": supplier_row["preferred_order"],
                            "contact_email": supplier_row["contact_email"],
                            "link": supplier_row["link"],
                            "selected": False,
                        }
                    )

                if mapped_suppliers:
                    mapped_suppliers[0]["selected"] = True

                bom_items.append(
                    {
                        "part_id": row["part_id"],
                        "component": row["component"],
                        "quantity": row["quantity"],
                        "part_name": row["part_name"],
                        "part_type": row["part_type"],
                        "stock": row["stock"],
                        "suppliers": mapped_suppliers,
                    }
                )

    return {
        "orders": orders,
        "selected_order": selected_order,
        "bom_items": bom_items,
        "message": message,
        "modal_actions": modal_actions or [],
    }


@app.get("/")
def index(request: Request):
    role = get_role(request)
    connection = get_db()
    try:
        if role == "Engineer":
            context = build_engineer_context(connection)
            return templates.TemplateResponse(
                "engineer.html",
                {"request": request, "role": role, "roles": ROLES, **context},
            )

        if role == "Purchaser":
            selected_product_id = request.query_params.get("product_id")
            selected_product_id = int(selected_product_id) if selected_product_id else None
            context = build_purchaser_context(connection, selected_product_id=selected_product_id)
            return templates.TemplateResponse(
                "purchaser.html",
                {"request": request, "role": role, "roles": ROLES, **context},
            )

        if role == "Production":
            selected_product_id = request.query_params.get("product_id")
            selected_product_id = int(selected_product_id) if selected_product_id else None
            orders = connection.execute(
                "SELECT co.product_id, co.customer_id, co.order_date, p.name AS product_name FROM current_order co JOIN product p ON p.product_id = co.product_id ORDER BY co.order_date DESC"
            ).fetchall()
            selected_order = None
            component_groups = []
            if selected_product_id is not None:
                selected_order = connection.execute(
                    "SELECT co.product_id, p.name AS product_name, co.customer_id, co.order_date FROM current_order co JOIN product p ON p.product_id = co.product_id WHERE co.product_id = ?",
                    (selected_product_id,),
                ).fetchone()
                if selected_order is not None:
                    # Only include product_part rows effective at the order date
                    order_date = selected_order["order_date"]
                    grouped_rows = connection.execute(
                        "SELECT pp.component, pp.quantity, pp.part_id, p.name AS part_name, p.stock FROM product_part pp JOIN part p ON p.part_id = pp.part_id WHERE pp.product_id = ? AND ? BETWEEN pp.effective_from AND pp.effective_to ORDER BY pp.component, pp.part_id",
                        (selected_product_id, order_date),
                    ).fetchall()
                    grouped = {}
                    for row in grouped_rows:
                        grouped.setdefault(row["component"], []).append({
                            "part_id": row["part_id"],
                            "part_name": row["part_name"],
                            "quantity": row["quantity"],
                            "stock": row["stock"],
                        })
                    component_groups = [{"component": key, "items": value} for key, value in grouped.items()]
            return templates.TemplateResponse(
                "production.html",
                {
                    "request": request,
                    "role": role,
                    "roles": ROLES,
                    "orders": orders,
                    "selected_order": selected_order,
                    "component_groups": component_groups,
                },
            )

        if role == "Client":
            products = connection.execute("SELECT * FROM product ORDER BY product_id").fetchall()
            return templates.TemplateResponse(
                "client.html",
                {"request": request, "role": role, "roles": ROLES, "products": products},
            )

        if role == "Manager":
            progress_entries = connection.execute(
                "SELECT * FROM production_progress ORDER BY created_at DESC"
            ).fetchall()
            low_stock_parts = connection.execute(
                "SELECT * FROM part WHERE stock <= 10 ORDER BY stock ASC"
            ).fetchall()
            return templates.TemplateResponse(
                "manager.html",
                {
                    "request": request,
                    "role": role,
                    "roles": ROLES,
                    "progress_entries": progress_entries,
                    "low_stock_parts": low_stock_parts,
                },
            )

        counts = get_counts(connection)
        return templates.TemplateResponse(
            "index.html",
            {"request": request, "role": role, "roles": ROLES, "counts": counts},
        )
    finally:
        connection.close()


@app.get("/purchaser/order/{product_id}")
def purchaser_order(request: Request, product_id: int):
    role = get_role(request)
    connection = get_db()
    try:
        context = build_purchaser_context(connection, selected_product_id=product_id)
        return templates.TemplateResponse(
            "purchaser.html",
            {"request": request, "role": role, "roles": ROLES, **context},
        )
    finally:
        connection.close()


@app.post("/engineer/part")
def add_part(request: Request, part_id: int = Form(...), name: str = Form(...), type: str = Form(...), stock: int = Form(...), description: str = Form(default="")):
    connection = get_db()
    try:
        connection.execute(
            """
            INSERT INTO part (part_id, name, type, stock, description)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(part_id) DO UPDATE SET
                name = excluded.name,
                type = excluded.type,
                stock = excluded.stock,
                description = excluded.description
            """,
            (part_id, name, type, stock, description),
        )
        connection.commit()
    finally:
        connection.close()
    return RedirectResponse(url="/?role=Engineer", status_code=303)


@app.post("/engineer/product")
def add_product(request: Request, product_id: int = Form(...), name: str = Form(...)):
    connection = get_db()
    try:
        connection.execute(
            """
            INSERT INTO product (product_id, name)
            VALUES (?, ?)
            ON CONFLICT(product_id) DO UPDATE SET name = excluded.name
            """,
            (product_id, name),
        )
        connection.commit()
    finally:
        connection.close()
    return RedirectResponse(url="/?role=Engineer", status_code=303)


@app.post("/engineer/product-part")
def add_product_part(
    request: Request,
    product_id: int = Form(...),
    part_id: int = Form(...),
    component: str = Form(...),
    quantity: int = Form(...),
    effective_from: str = Form(...),
    effective_to: str = Form(...),
):
    connection = get_db()
    try:
        connection.execute(
            """
            INSERT INTO product_part (product_id, part_id, component, quantity, effective_from, effective_to)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(product_id, part_id, effective_from, effective_to) DO UPDATE SET
                component = excluded.component,
                quantity = excluded.quantity,
                effective_to = excluded.effective_to
            """,
            (product_id, part_id, component, quantity, effective_from, effective_to),
        )
        connection.commit()
    finally:
        connection.close()
    return RedirectResponse(url="/?role=Engineer", status_code=303)


@app.post("/engineer/supplier")
def add_supplier(
    request: Request,
    supplier_id: int = Form(...),
    supplier_name: str = Form(...),
    contact_email: str = Form(default=""),
    link: str = Form(default=""),
    lead_time: int = Form(...),
):
    connection = get_db()
    try:
        connection.execute(
            """
            INSERT INTO supplier (supplier_id, supplier_name, contact_email, link, lead_time)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(supplier_id) DO UPDATE SET
                supplier_name = excluded.supplier_name,
                contact_email = excluded.contact_email,
                link = excluded.link,
                lead_time = excluded.lead_time
            """,
            (supplier_id, supplier_name, contact_email, link, lead_time),
        )
        connection.commit()
    finally:
        connection.close()
    return RedirectResponse(url="/?role=Engineer", status_code=303)


@app.post("/engineer/part-supplier")
def add_part_supplier(
    request: Request,
    part_id: int = Form(...),
    supplier_id: int = Form(...),
    price: float = Form(...),
    preferred_order: int = Form(...),
):
    connection = get_db()
    try:
        connection.execute(
            """
            INSERT INTO part_supplier (part_id, supplier_id, price, preferred_order)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(part_id, supplier_id) DO UPDATE SET
                price = excluded.price,
                preferred_order = excluded.preferred_order
            """,
            (part_id, supplier_id, price, preferred_order),
        )
        connection.commit()
    finally:
        connection.close()
    return RedirectResponse(url="/?role=Engineer", status_code=303)


@app.post("/purchaser/place-order")
async def place_order(request: Request):
    form = await request.form()
    product_id = int(form.get("product_id", 0))
    customer_id = int(form.get("customer_id", 0))
    order_date = form.get("order_date", "")

    selected_parts = []
    for key in form.keys():
        if key.startswith("part_id_"):
            # keys like 'part_id_1000101' -> extract trailing numeric id
            try:
                part_id = int(key.rsplit("_", 1)[1])
            except Exception:
                continue
            quantity = int(form.get(f"quantity_{part_id}", 0))
            supplier_id = int(form.get(f"supplier_{part_id}", 0) or 0)
            if quantity > 0 and supplier_id > 0:
                selected_parts.append((part_id, quantity, supplier_id))

    connection = get_db()
    try:
        connection.execute("BEGIN")
        modal_actions = []
        for part_id, quantity, supplier_id in selected_parts:
            part_row = connection.execute("SELECT * FROM part WHERE part_id = ?", (part_id,)).fetchone()
            supplier_row = connection.execute("SELECT * FROM supplier WHERE supplier_id = ?", (supplier_id,)).fetchone()
            if part_row is None:
                continue
            connection.execute("UPDATE part SET stock = stock + ? WHERE part_id = ?", (quantity, part_id))
            if part_row["type"] == "Standard":
                link = supplier_row["link"] if supplier_row is not None else ""
                modal_actions.append(
                    f"Standard part ordered: {part_row['name']} — supplier link: {link or 'No link available'}"
                )
            else:
                email = supplier_row["contact_email"] if supplier_row is not None else "supplier"
                modal_actions.append(
                    f"Purchase Order Email successfully generated and sent to {email} for {part_row['name']}"
                )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    context = {
        "product_id": product_id,
        "customer_id": customer_id,
        "order_date": order_date,
        "message": "Order placed successfully.",
        "modal_actions": modal_actions,
    }

    connection = get_db()
    try:
        purchaser_context = build_purchaser_context(
            connection,
            selected_product_id=product_id,
            message=context["message"],
            modal_actions=context["modal_actions"],
        )
        return templates.TemplateResponse(
            "purchaser.html",
            {
                "request": request,
                "role": "Purchaser",
                "roles": ROLES,
                **purchaser_context,
            },
        )
    finally:
        connection.close()


@app.post("/production/complete")
async def complete_component(
    request: Request,
    product_id: int = Form(...),
    component: str = Form(...),
    finished: Optional[str] = Form(None),
    photo: Optional[UploadFile] = File(None),
):
    connection = get_db()
    try:
        if finished == "1":
            # Determine order_date for this product's current order (use latest)
            order_row = connection.execute(
                "SELECT order_date FROM current_order WHERE product_id = ? ORDER BY order_date DESC LIMIT 1",
                (product_id,),
            ).fetchone()
            if order_row is not None:
                order_date = order_row["order_date"]
                rows = connection.execute(
                    "SELECT pp.part_id, pp.quantity, p.stock FROM product_part pp JOIN part p ON p.part_id = pp.part_id WHERE pp.product_id = ? AND pp.component = ? AND ? BETWEEN pp.effective_from AND pp.effective_to",
                    (product_id, component, order_date),
                ).fetchall()
            else:
                # fallback: no order found, do not deduct
                rows = []
            for row in rows:
                connection.execute(
                    "UPDATE part SET stock = stock - ? WHERE part_id = ?",
                    (row["quantity"], row["part_id"]),
                )

        photo_path = None
        if photo is not None and photo.filename:
            safe_name = f"{product_id}_{component}_{photo.filename}"
            photo_path = f"uploads/{safe_name}"
            Path(BASE_DIR / "app" / "static" / "uploads").mkdir(parents=True, exist_ok=True)
            with (BASE_DIR / "app" / "static" / "uploads" / safe_name).open("wb") as handle:
                handle.write(await photo.read())

        connection.execute(
            "INSERT INTO production_progress (product_id, component, status, photo_path) VALUES (?, ?, ?, ?)",
            (product_id, component, "Finished" if finished == "1" else "Updated", photo_path),
        )
        connection.commit()
    finally:
        connection.close()

    return RedirectResponse(url="/?role=Production&product_id=" + str(product_id), status_code=303)


@app.post("/client/order")
def create_client_order(
    request: Request,
    product_id: int = Form(...),
    customer_id: int = Form(...),
    order_date: str = Form(...),
):
    connection = get_db()
    try:
        connection.execute(
            "INSERT INTO current_order (product_id, customer_id, order_date) VALUES (?, ?, ?)",
            (product_id, customer_id, order_date),
        )
        connection.commit()
    finally:
        connection.close()
    return RedirectResponse(url="/?role=Client", status_code=303)


@app.post("/client/replacement")
def replacement_lookup(
    request: Request,
    product_name: str = Form(...),
    part_name: str = Form(...),
    order_date: str = Form(...),
):
    connection = get_db()
    try:
        row = connection.execute(
            """
            SELECT pp.product_id, p.name AS product_name, pt.name AS part_name, pp.part_id, pp.effective_from, pp.effective_to
            FROM product_part pp
            JOIN product p ON p.product_id = pp.product_id
            JOIN part pt ON pt.part_id = pp.part_id
            WHERE p.name = ? AND pt.name = ? AND ? BETWEEN pp.effective_from AND pp.effective_to
            ORDER BY pp.effective_from DESC
            LIMIT 1
            """,
            (product_name, part_name, order_date),
        ).fetchone()
    finally:
        connection.close()

    replacement_result = None
    if row is not None:
        replacement_result = {
            "product_name": row["product_name"],
            "part_name": row["part_name"],
            "part_id": row["part_id"],
            "order_date": order_date,
            "effective_from": row["effective_from"],
            "effective_to": row["effective_to"],
        }

    connection = get_db()
    try:
        products = connection.execute("SELECT * FROM product ORDER BY product_id").fetchall()
        return templates.TemplateResponse(
            "client.html",
            {
                "request": request,
                "role": "Client",
                "roles": ROLES,
                "products": products,
                "message": "Replacement lookup completed." if replacement_result else "No historical version matched the provided criteria.",
                "replacement_result": replacement_result,
            },
        )
    finally:
        connection.close()


@app.get("/health")
def health():
    return {"status": "ok"}
