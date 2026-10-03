import os
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
from contextlib import contextmanager

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "warkop-pos-secret-key-change-me-in-production")

# Database setup
DATABASE = os.path.join(os.path.dirname(__file__), "instance", "warkop.db")

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"
login_manager.login_message = "Silakan login terlebih dahulu."

@contextmanager
def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    os.makedirs(os.path.dirname(DATABASE), exist_ok=True)
    with get_db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            full_name TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'kasir',  -- admin / kasir
            is_active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category_id INTEGER,
            price REAL NOT NULL,
            cost REAL DEFAULT 0,
            stock REAL DEFAULT 0,
            unit TEXT DEFAULT 'pcs',
            is_active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (category_id) REFERENCES categories(id)
        );

        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_no TEXT UNIQUE NOT NULL,
            user_id INTEGER,
            customer_name TEXT,
            total REAL NOT NULL,
            discount REAL DEFAULT 0,
            tax REAL DEFAULT 0,
            grand_total REAL NOT NULL,
            payment_method TEXT DEFAULT 'tunai',  -- tunai / non_tunai / qris / transfer
            paid_amount REAL,
            change_amount REAL DEFAULT 0,
            note TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS transaction_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transaction_id INTEGER NOT NULL,
            product_id INTEGER,
            product_name TEXT NOT NULL,
            qty REAL NOT NULL,
            price REAL NOT NULL,
            cost REAL DEFAULT 0,
            subtotal REAL NOT NULL,
            FOREIGN KEY (transaction_id) REFERENCES transactions(id) ON DELETE CASCADE,
            FOREIGN KEY (product_id) REFERENCES products(id)
        );

        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            description TEXT NOT NULL,
            amount REAL NOT NULL,
            category TEXT,
            user_id INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        """)

        # Default admin
        cur = conn.execute("SELECT COUNT(*) as c FROM users")
        if cur.fetchone()["c"] == 0:
            conn.execute(
                "INSERT INTO users (username, password_hash, full_name, role) VALUES (?, ?, ?, ?)",
                ("admin", generate_password_hash("admin123"), "Administrator", "admin")
            )
            conn.execute(
                "INSERT INTO users (username, password_hash, full_name, role) VALUES (?, ?, ?, ?)",
                ("kasir", generate_password_hash("kasir123"), "Kasir", "kasir")
            )

        # Default settings
        defaults = {
            "store_name": "Warkop Bahenol",
            "store_address": "Jl. Contoh No. 1",
            "store_phone": "08123456789",
            "currency": "Rp",
            "tax_percent": "0",
        }
        for k, v in defaults.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                (k, v)
            )

        # Sample categories & products for cafe
        cur = conn.execute("SELECT COUNT(*) as c FROM categories")
        if cur.fetchone()["c"] == 0:
            cats = ["Kopi", "Non-Kopi", "Makanan", "Snack", "Lainnya"]
            for c in cats:
                conn.execute("INSERT INTO categories (name) VALUES (?)", (c,))

            products = [
                ("Espresso", 1, 15000, 5000, 100),
                ("Americano", 1, 18000, 6000, 100),
                ("Caffe Latte", 1, 22000, 8000, 100),
                ("Cappuccino", 1, 22000, 8000, 100),
                ("Manual Brew", 1, 25000, 9000, 50),
                ("Es Teh Manis", 2, 8000, 2000, 100),
                ("Es Jeruk", 2, 10000, 3000, 80),
                ("Air Mineral", 2, 5000, 2000, 100),
                ("Nasi Goreng", 3, 20000, 10000, 30),
                ("Mie Goreng", 3, 18000, 9000, 30),
                ("Roti Bakar", 4, 12000, 5000, 40),
                ("Kentang Goreng", 4, 15000, 6000, 40),
            ]
            for name, cat_id, price, cost, stock in products:
                conn.execute(
                    "INSERT INTO products (name, category_id, price, cost, stock) VALUES (?, ?, ?, ?, ?)",
                    (name, cat_id, price, cost, stock)
                )

class User(UserMixin):
    def __init__(self, id, username, full_name, role):
        self.id = id
        self.username = username
        self.full_name = full_name
        self.role = role

@login_manager.user_loader
def load_user(user_id):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ? AND is_active = 1", (user_id,)).fetchone()
        if row:
            return User(row["id"], row["username"], row["full_name"], row["role"])
    return None

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != "admin":
            flash("Akses hanya untuk Admin.", "danger")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return decorated

def get_setting(key, default=""):
    with get_db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

def generate_invoice():
    now = datetime.now()
    prefix = now.strftime("%Y%m%d")
    with get_db() as conn:
        last = conn.execute(
            "SELECT invoice_no FROM transactions WHERE invoice_no LIKE ? ORDER BY id DESC LIMIT 1",
            (f"{prefix}%",)
        ).fetchone()
        if last:
            seq = int(last["invoice_no"][-4:]) + 1
        else:
            seq = 1
        return f"{prefix}{seq:04d}"

# ============== ROUTES ==============

@app.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        with get_db() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE username = ? AND is_active = 1", (username,)
            ).fetchone()
            if row and check_password_hash(row["password_hash"], password):
                user = User(row["id"], row["username"], row["full_name"], row["role"])
                login_user(user)
                flash(f"Selamat datang, {user.full_name}!", "success")
                return redirect(url_for("dashboard"))
        flash("Username atau password salah.", "danger")
    store_name = get_setting("store_name", "Warkop Bahenol")
    return render_template("login.html", store_name=store_name)

@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Anda telah logout.", "info")
    return redirect(url_for("login"))

@app.route("/dashboard")
@login_required
def dashboard():
    today = datetime.now().strftime("%Y-%m-%d")
    with get_db() as conn:
        # Sales today
        sales = conn.execute("""
            SELECT COUNT(*) as trx_count, COALESCE(SUM(grand_total), 0) as total_sales,
                   COALESCE(SUM(discount), 0) as total_discount
            FROM transactions WHERE date(created_at) = ?
        """, (today,)).fetchone()

        # Cost of goods sold today
        cogs = conn.execute("""
            SELECT COALESCE(SUM(ti.cost * ti.qty), 0) as total_cogs
            FROM transaction_items ti
            JOIN transactions t ON t.id = ti.transaction_id
            WHERE date(t.created_at) = ?
        """, (today,)).fetchone()

        # Expenses today
        exp = conn.execute("""
            SELECT COALESCE(SUM(amount), 0) as total_exp
            FROM expenses WHERE date(created_at) = ?
        """, (today,)).fetchone()

        profit_today = sales["total_sales"] - cogs["total_cogs"] - exp["total_exp"]

        # Top products (7 days)
        top_products = conn.execute("""
            SELECT ti.product_name, SUM(ti.qty) as qty, SUM(ti.subtotal) as revenue
            FROM transaction_items ti
            JOIN transactions t ON t.id = ti.transaction_id
            WHERE t.created_at >= date('now', '-7 days')
            GROUP BY ti.product_name
            ORDER BY qty DESC LIMIT 5
        """).fetchall()

        # Recent transactions
        recent = conn.execute("""
            SELECT t.*, u.full_name as kasir
            FROM transactions t
            LEFT JOIN users u ON u.id = t.user_id
            ORDER BY t.id DESC LIMIT 8
        """).fetchall()

        # Sales last 7 days for chart
        chart_data = conn.execute("""
            SELECT date(created_at) as tgl, SUM(grand_total) as total
            FROM transactions
            WHERE created_at >= date('now', '-6 days')
            GROUP BY date(created_at)
            ORDER BY tgl
        """).fetchall()

    store_name = get_setting("store_name")
    return render_template(
        "dashboard.html",
        store_name=store_name,
        sales=sales,
        cogs=cogs["total_cogs"],
        expenses=exp["total_exp"],
        profit=profit_today,
        top_products=top_products,
        recent=recent,
        chart_data=chart_data,
        today=today,
    )

@app.route("/pos")
@login_required
def pos():
    with get_db() as conn:
        categories = conn.execute("SELECT * FROM categories ORDER BY name").fetchall()
        products = conn.execute("""
            SELECT p.*, c.name as category_name
            FROM products p
            LEFT JOIN categories c ON c.id = p.category_id
            WHERE p.is_active = 1
            ORDER BY p.name
        """).fetchall()
    store_name = get_setting("store_name")
    return render_template("pos.html", store_name=store_name, categories=categories, products=products)

@app.route("/api/checkout", methods=["POST"])
@login_required
def api_checkout():
    data = request.get_json()
    items = data.get("items", [])
    if not items:
        return jsonify({"ok": False, "msg": "Keranjang kosong"}), 400

    discount = float(data.get("discount", 0) or 0)
    payment_method = data.get("payment_method", "tunai")
    paid_amount = float(data.get("paid_amount", 0) or 0)
    customer_name = data.get("customer_name", "")
    note = data.get("note", "")

    with get_db() as conn:
        total = 0
        item_details = []
        for it in items:
            prod = conn.execute("SELECT * FROM products WHERE id = ?", (it["id"],)).fetchone()
            if not prod:
                return jsonify({"ok": False, "msg": f"Produk tidak ditemukan"}), 400
            qty = float(it["qty"])
            if prod["stock"] < qty:
                return jsonify({"ok": False, "msg": f"Stok {prod['name']} tidak cukup"}), 400
            subtotal = prod["price"] * qty
            total += subtotal
            item_details.append({
                "product_id": prod["id"],
                "name": prod["name"],
                "qty": qty,
                "price": prod["price"],
                "cost": prod["cost"],
                "subtotal": subtotal,
            })

        tax_percent = float(get_setting("tax_percent", "0") or 0)
        tax = total * tax_percent / 100
        grand_total = total - discount + tax
        change = max(0, paid_amount - grand_total) if payment_method == "tunai" else 0

        invoice = generate_invoice()
        cur = conn.execute("""
            INSERT INTO transactions
            (invoice_no, user_id, customer_name, total, discount, tax, grand_total,
             payment_method, paid_amount, change_amount, note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            invoice, current_user.id, customer_name, total, discount, tax, grand_total,
            payment_method, paid_amount, change, note
        ))
        trx_id = cur.lastrowid

        for it in item_details:
            conn.execute("""
                INSERT INTO transaction_items
                (transaction_id, product_id, product_name, qty, price, cost, subtotal)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (trx_id, it["product_id"], it["name"], it["qty"], it["price"], it["cost"], it["subtotal"]))
            # Update stock
            conn.execute("UPDATE products SET stock = stock - ? WHERE id = ?", (it["qty"], it["product_id"]))

    return jsonify({
        "ok": True,
        "invoice": invoice,
        "grand_total": grand_total,
        "change": change,
        "msg": "Transaksi berhasil"
    })

@app.route("/products")
@login_required
def products():
    with get_db() as conn:
        products = conn.execute("""
            SELECT p.*, c.name as category_name
            FROM products p
            LEFT JOIN categories c ON c.id = p.category_id
            ORDER BY p.name
        """).fetchall()
        categories = conn.execute("SELECT * FROM categories ORDER BY name").fetchall()
    return render_template("products.html", products=products, categories=categories, store_name=get_setting("store_name"))

@app.route("/products/add", methods=["POST"])
@login_required
@admin_required
def product_add():
    name = request.form.get("name", "").strip()
    category_id = request.form.get("category_id") or None
    price = float(request.form.get("price", 0) or 0)
    cost = float(request.form.get("cost", 0) or 0)
    stock = float(request.form.get("stock", 0) or 0)
    unit = request.form.get("unit", "pcs")
    if not name or price <= 0:
        flash("Nama dan harga wajib diisi.", "danger")
        return redirect(url_for("products"))
    with get_db() as conn:
        conn.execute(
            "INSERT INTO products (name, category_id, price, cost, stock, unit) VALUES (?, ?, ?, ?, ?, ?)",
            (name, category_id, price, cost, stock, unit)
        )
    flash("Produk berhasil ditambahkan.", "success")
    return redirect(url_for("products"))

@app.route("/products/edit/<int:pid>", methods=["POST"])
@login_required
@admin_required
def product_edit(pid):
    name = request.form.get("name", "").strip()
    category_id = request.form.get("category_id") or None
    price = float(request.form.get("price", 0) or 0)
    cost = float(request.form.get("cost", 0) or 0)
    stock = float(request.form.get("stock", 0) or 0)
    unit = request.form.get("unit", "pcs")
    is_active = 1 if request.form.get("is_active") else 0
    with get_db() as conn:
        conn.execute("""
            UPDATE products SET name=?, category_id=?, price=?, cost=?, stock=?, unit=?, is_active=?
            WHERE id=?
        """, (name, category_id, price, cost, stock, unit, is_active, pid))
    flash("Produk berhasil diupdate.", "success")
    return redirect(url_for("products"))

@app.route("/transactions")
@login_required
def transactions():
    date_from = request.args.get("from", (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d"))
    date_to = request.args.get("to", datetime.now().strftime("%Y-%m-%d"))
    with get_db() as conn:
        rows = conn.execute("""
            SELECT t.*, u.full_name as kasir
            FROM transactions t
            LEFT JOIN users u ON u.id = t.user_id
            WHERE date(t.created_at) BETWEEN ? AND ?
            ORDER BY t.id DESC
        """, (date_from, date_to)).fetchall()
    return render_template("transactions.html", transactions=rows, date_from=date_from, date_to=date_to, store_name=get_setting("store_name"))

@app.route("/transactions/<int:tid>")
@login_required
def transaction_detail(tid):
    with get_db() as conn:
        trx = conn.execute("""
            SELECT t.*, u.full_name as kasir FROM transactions t
            LEFT JOIN users u ON u.id = t.user_id WHERE t.id = ?
        """, (tid,)).fetchone()
        items = conn.execute("SELECT * FROM transaction_items WHERE transaction_id = ?", (tid,)).fetchall()
    if not trx:
        flash("Transaksi tidak ditemukan.", "danger")
        return redirect(url_for("transactions"))
    return render_template("transaction_detail.html", trx=trx, items=items, store_name=get_setting("store_name"))

@app.route("/expenses")
@login_required
def expenses():
    date_from = request.args.get("from", (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d"))
    date_to = request.args.get("to", datetime.now().strftime("%Y-%m-%d"))
    with get_db() as conn:
        rows = conn.execute("""
            SELECT e.*, u.full_name as input_by FROM expenses e
            LEFT JOIN users u ON u.id = e.user_id
            WHERE date(e.created_at) BETWEEN ? AND ?
            ORDER BY e.id DESC
        """, (date_from, date_to)).fetchall()
    return render_template("expenses.html", expenses=rows, date_from=date_from, date_to=date_to, store_name=get_setting("store_name"))

@app.route("/expenses/add", methods=["POST"])
@login_required
def expense_add():
    desc = request.form.get("description", "").strip()
    amount = float(request.form.get("amount", 0) or 0)
    category = request.form.get("category", "")
    if not desc or amount <= 0:
        flash("Deskripsi dan jumlah wajib diisi.", "danger")
        return redirect(url_for("expenses"))
    with get_db() as conn:
        conn.execute(
            "INSERT INTO expenses (description, amount, category, user_id) VALUES (?, ?, ?, ?)",
            (desc, amount, category, current_user.id)
        )
    flash("Pengeluaran berhasil dicatat.", "success")
    return redirect(url_for("expenses"))

@app.route("/reports")
@login_required
def reports():
    date_from = request.args.get("from", (datetime.now().replace(day=1)).strftime("%Y-%m-%d"))
    date_to = request.args.get("to", datetime.now().strftime("%Y-%m-%d"))

    with get_db() as conn:
        # Summary
        sales = conn.execute("""
            SELECT COUNT(*) as trx, COALESCE(SUM(grand_total),0) as revenue,
                   COALESCE(SUM(discount),0) as discount, COALESCE(SUM(tax),0) as tax
            FROM transactions WHERE date(created_at) BETWEEN ? AND ?
        """, (date_from, date_to)).fetchone()

        cogs = conn.execute("""
            SELECT COALESCE(SUM(ti.cost * ti.qty), 0) as cogs
            FROM transaction_items ti
            JOIN transactions t ON t.id = ti.transaction_id
            WHERE date(t.created_at) BETWEEN ? AND ?
        """, (date_from, date_to)).fetchone()

        exp = conn.execute("""
            SELECT COALESCE(SUM(amount), 0) as total FROM expenses
            WHERE date(created_at) BETWEEN ? AND ?
        """, (date_from, date_to)).fetchone()

        gross_profit = sales["revenue"] - cogs["cogs"]
        net_profit = gross_profit - exp["total"]

        # By payment method
        by_payment = conn.execute("""
            SELECT payment_method, COUNT(*) as cnt, SUM(grand_total) as total
            FROM transactions WHERE date(created_at) BETWEEN ? AND ?
            GROUP BY payment_method
        """, (date_from, date_to)).fetchall()

        # Top products
        top = conn.execute("""
            SELECT ti.product_name, SUM(ti.qty) as qty, SUM(ti.subtotal) as revenue,
                   SUM(ti.cost * ti.qty) as cost
            FROM transaction_items ti
            JOIN transactions t ON t.id = ti.transaction_id
            WHERE date(t.created_at) BETWEEN ? AND ?
            GROUP BY ti.product_name ORDER BY qty DESC LIMIT 10
        """, (date_from, date_to)).fetchall()

        # Daily sales
        daily = conn.execute("""
            SELECT date(created_at) as tgl, COUNT(*) as trx, SUM(grand_total) as total
            FROM transactions WHERE date(created_at) BETWEEN ? AND ?
            GROUP BY date(created_at) ORDER BY tgl
        """, (date_from, date_to)).fetchall()

    return render_template(
        "reports.html",
        store_name=get_setting("store_name"),
        date_from=date_from,
        date_to=date_to,
        sales=sales,
        cogs=cogs["cogs"],
        expenses=exp["total"],
        gross_profit=gross_profit,
        net_profit=net_profit,
        by_payment=by_payment,
        top=top,
        daily=daily,
    )

@app.route("/settings", methods=["GET", "POST"])
@login_required
@admin_required
def settings():
    if request.method == "POST":
        keys = ["store_name", "store_address", "store_phone", "tax_percent"]
        with get_db() as conn:
            for k in keys:
                v = request.form.get(k, "")
                conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (k, v))
        flash("Pengaturan berhasil disimpan.", "success")
        return redirect(url_for("settings"))
    settings_data = {k: get_setting(k) for k in ["store_name", "store_address", "store_phone", "tax_percent"]}
    return render_template("settings.html", settings=settings_data, store_name=get_setting("store_name"))

@app.route("/users")
@login_required
@admin_required
def users():
    with get_db() as conn:
        users = conn.execute("SELECT * FROM users ORDER BY id").fetchall()
    return render_template("users.html", users=users, store_name=get_setting("store_name"))

@app.route("/users/add", methods=["POST"])
@login_required
@admin_required
def user_add():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    full_name = request.form.get("full_name", "").strip()
    role = request.form.get("role", "kasir")
    if not username or not password or not full_name:
        flash("Semua field wajib diisi.", "danger")
        return redirect(url_for("users"))
    try:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO users (username, password_hash, full_name, role) VALUES (?, ?, ?, ?)",
                (username, generate_password_hash(password), full_name, role)
            )
        flash("User berhasil ditambahkan.", "success")
    except sqlite3.IntegrityError:
        flash("Username sudah dipakai.", "danger")
    return redirect(url_for("users"))

# Init on startup
with app.app_context():
    init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
