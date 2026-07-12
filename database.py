"""
database.py
-----------------------------------------------------------------
SQLite bilan ishlash uchun barcha funksiyalar shu yerda.
SQLite -- bitta oddiy fayl (bot.db), alohida server kerak emas.
-----------------------------------------------------------------
"""

import sqlite3
from contextlib import closing

from config import DB_PATH, MAIN_ADMIN_CHAT_ID


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """Bot birinchi marta ishga tushganda barcha jadvallarni yaratadi."""
    with closing(get_connection()) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER UNIQUE NOT NULL,
                username TEXT,
                full_name TEXT,
                phone_number TEXT,
                balance REAL NOT NULL DEFAULT 0,
                state TEXT,
                is_registered INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS admins (
                chat_id INTEGER PRIMARY KEY,
                added_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_chat_id INTEGER NOT NULL,
                photo_file_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                product_key TEXT,
                product_label TEXT,
                product_price REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS products (
                key TEXT PRIMARY KEY,
                category TEXT NOT NULL,
                label TEXT NOT NULL,
                price REAL NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS payment_notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                payment_id INTEGER NOT NULL,
                admin_chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS support_threads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_chat_id INTEGER NOT NULL,
                user_message_id INTEGER NOT NULL,
                message_text TEXT,
                is_answered INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS support_notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                support_id INTEGER NOT NULL,
                admin_chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS promo_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                amount REAL NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS promo_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                promo_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(promo_id, chat_id)
            );
            CREATE TABLE IF NOT EXISTS shipments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tracking_code TEXT UNIQUE NOT NULL,
                user_chat_id INTEGER NOT NULL,
                description TEXT,
                status TEXT NOT NULL DEFAULT 'accepted',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        conn.commit()


# ---------------------------------------------------------------------
# Foydalanuvchilar
# ---------------------------------------------------------------------
def get_user(chat_id: int) -> sqlite3.Row | None:
    with closing(get_connection()) as conn:
        return conn.execute("SELECT * FROM users WHERE chat_id = ?", (chat_id,)).fetchone()


def create_user_if_not_exists(chat_id: int, username: str | None) -> sqlite3.Row:
    user = get_user(chat_id)
    if user is not None:
        return user

    with closing(get_connection()) as conn:
        conn.execute(
            "INSERT INTO users (chat_id, username, state, is_registered) VALUES (?, ?, 'waiting_name', 0)",
            (chat_id, username),
        )
        conn.commit()

    return get_user(chat_id)


def set_state(chat_id: int, state: str | None) -> None:
    with closing(get_connection()) as conn:
        conn.execute("UPDATE users SET state = ? WHERE chat_id = ?", (state, chat_id))
        conn.commit()


def save_name(chat_id: int, full_name: str) -> None:
    with closing(get_connection()) as conn:
        conn.execute(
            "UPDATE users SET full_name = ?, state = 'waiting_phone' WHERE chat_id = ?",
            (full_name, chat_id),
        )
        conn.commit()


def save_phone_and_finish_registration(chat_id: int, phone: str) -> None:
    with closing(get_connection()) as conn:
        conn.execute(
            "UPDATE users SET phone_number = ?, is_registered = 1, state = NULL WHERE chat_id = ?",
            (phone, chat_id),
        )
        conn.commit()


def is_registered(chat_id: int) -> bool:
    user = get_user(chat_id)
    return user is not None and user["is_registered"] == 1


def add_balance(chat_id: int, amount: float) -> None:
    with closing(get_connection()) as conn:
        conn.execute("UPDATE users SET balance = balance + ? WHERE chat_id = ?", (amount, chat_id))
        conn.commit()


def get_balance(chat_id: int) -> float:
    user = get_user(chat_id)
    return user["balance"] if user else 0.0


def get_all_registered_chat_ids() -> list[int]:
    with closing(get_connection()) as conn:
        rows = conn.execute("SELECT chat_id FROM users WHERE is_registered = 1").fetchall()
        return [row["chat_id"] for row in rows]


# ---------------------------------------------------------------------
# Adminlar (asosiy admin config.py'dan, yordamchilar shu jadvalda)
# ---------------------------------------------------------------------
def is_admin(chat_id: int) -> bool:
    if chat_id == MAIN_ADMIN_CHAT_ID:
        return True
    with closing(get_connection()) as conn:
        row = conn.execute("SELECT chat_id FROM admins WHERE chat_id = ?", (chat_id,)).fetchone()
        return row is not None


def add_admin(chat_id: int, added_by: int) -> None:
    with closing(get_connection()) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO admins (chat_id, added_by) VALUES (?, ?)", (chat_id, added_by)
        )
        conn.commit()


def remove_admin(chat_id: int) -> None:
    with closing(get_connection()) as conn:
        conn.execute("DELETE FROM admins WHERE chat_id = ?", (chat_id,))
        conn.commit()


def get_all_admin_ids() -> list[int]:
    """Asosiy admin + barcha yordamchi adminlar, takrorlanmaydigan ro'yxat."""
    with closing(get_connection()) as conn:
        rows = conn.execute("SELECT chat_id FROM admins").fetchall()
        ids = {row["chat_id"] for row in rows}
        ids.add(MAIN_ADMIN_CHAT_ID)
        return list(ids)


def get_helper_admin_ids() -> list[int]:
    """Faqat yordamchi adminlar (asosiy admin bundan mustasno)."""
    with closing(get_connection()) as conn:
        rows = conn.execute("SELECT chat_id FROM admins").fetchall()
        return [row["chat_id"] for row in rows]


# ---------------------------------------------------------------------
# To'lovlar (bir nechta adminga yuboriladi, har biriga alohida xabar ID)
# ---------------------------------------------------------------------
def insert_payment(
    user_chat_id: int,
    photo_file_id: str,
    product_key: str | None = None,
    product_label: str | None = None,
    product_price: float | None = None,
) -> int:
    with closing(get_connection()) as conn:
        cur = conn.execute(
            """INSERT INTO payments
               (user_chat_id, photo_file_id, status, product_key, product_label, product_price)
               VALUES (?, ?, 'pending', ?, ?, ?)""",
            (user_chat_id, photo_file_id, product_key, product_label, product_price),
        )
        conn.commit()
        return cur.lastrowid


def add_payment_notification(payment_id: int, admin_chat_id: int, message_id: int) -> None:
    with closing(get_connection()) as conn:
        conn.execute(
            "INSERT INTO payment_notifications (payment_id, admin_chat_id, message_id) VALUES (?, ?, ?)",
            (payment_id, admin_chat_id, message_id),
        )
        conn.commit()


def get_payment_notifications(payment_id: int) -> list[sqlite3.Row]:
    with closing(get_connection()) as conn:
        return conn.execute(
            "SELECT * FROM payment_notifications WHERE payment_id = ?", (payment_id,)
        ).fetchall()


def get_payment(payment_id: int) -> sqlite3.Row | None:
    with closing(get_connection()) as conn:
        return conn.execute("SELECT * FROM payments WHERE id = ?", (payment_id,)).fetchone()


def update_payment_status(payment_id: int, status: str) -> None:
    with closing(get_connection()) as conn:
        conn.execute("UPDATE payments SET status = ? WHERE id = ?", (status, payment_id))
        conn.commit()


# ---------------------------------------------------------------------
# Support (bir nechta adminga yuboriladi, qaysi admin reply qilsa o'sha javob beradi)
# ---------------------------------------------------------------------
def insert_support_thread(user_chat_id: int, user_message_id: int, text: str) -> int:
    with closing(get_connection()) as conn:
        cur = conn.execute(
            """INSERT INTO support_threads (user_chat_id, user_message_id, message_text)
               VALUES (?, ?, ?)""",
            (user_chat_id, user_message_id, text),
        )
        conn.commit()
        return cur.lastrowid


def add_support_notification(support_id: int, admin_chat_id: int, message_id: int) -> None:
    with closing(get_connection()) as conn:
        conn.execute(
            "INSERT INTO support_notifications (support_id, admin_chat_id, message_id) VALUES (?, ?, ?)",
            (support_id, admin_chat_id, message_id),
        )
        conn.commit()


def get_support_notification(admin_chat_id: int, message_id: int) -> sqlite3.Row | None:
    with closing(get_connection()) as conn:
        return conn.execute(
            """SELECT * FROM support_notifications
               WHERE admin_chat_id = ? AND message_id = ?
               ORDER BY id DESC LIMIT 1""",
            (admin_chat_id, message_id),
        ).fetchone()


def get_support_thread(support_id: int) -> sqlite3.Row | None:
    with closing(get_connection()) as conn:
        return conn.execute("SELECT * FROM support_threads WHERE id = ?", (support_id,)).fetchone()


def mark_support_answered(support_id: int) -> None:
    with closing(get_connection()) as conn:
        conn.execute("UPDATE support_threads SET is_answered = 1 WHERE id = ?", (support_id,))
        conn.commit()


# ---------------------------------------------------------------------
# Promo kodlar
# ---------------------------------------------------------------------
def get_active_promo(code: str) -> sqlite3.Row | None:
    with closing(get_connection()) as conn:
        return conn.execute(
            "SELECT * FROM promo_codes WHERE code = ? AND is_active = 1", (code,)
        ).fetchone()


def has_used_promo(promo_id: int, chat_id: int) -> bool:
    with closing(get_connection()) as conn:
        row = conn.execute(
            "SELECT id FROM promo_usage WHERE promo_id = ? AND chat_id = ?", (promo_id, chat_id)
        ).fetchone()
        return row is not None


def redeem_promo(promo_id: int, chat_id: int, amount: float) -> None:
    with closing(get_connection()) as conn:
        conn.execute("UPDATE users SET balance = balance + ? WHERE chat_id = ?", (amount, chat_id))
        conn.execute(
            "INSERT INTO promo_usage (promo_id, chat_id) VALUES (?, ?)", (promo_id, chat_id)
        )
        conn.commit()


def upsert_promo_code(code: str, amount: float) -> None:
    with closing(get_connection()) as conn:
        conn.execute(
            """INSERT INTO promo_codes (code, amount, is_active) VALUES (?, ?, 1)
               ON CONFLICT(code) DO UPDATE SET amount = excluded.amount, is_active = 1""",
            (code, amount),
        )
        conn.commit()


# ---------------------------------------------------------------------
# Mahsulotlar (Telegram Premium / Stars) -- narxlarni admin o'zi boshqaradi
# ---------------------------------------------------------------------
def upsert_product(key: str, category: str, label: str, price: float) -> None:
    with closing(get_connection()) as conn:
        conn.execute(
            """INSERT INTO products (key, category, label, price, is_active)
               VALUES (?, ?, ?, ?, 1)
               ON CONFLICT(key) DO UPDATE SET
                   category = excluded.category,
                   label = excluded.label,
                   price = excluded.price,
                   is_active = 1""",
            (key, category, label, price),
        )
        conn.commit()


def deactivate_product(key: str) -> bool:
    with closing(get_connection()) as conn:
        cur = conn.execute("UPDATE products SET is_active = 0 WHERE key = ?", (key,))
        conn.commit()
        return cur.rowcount > 0


def get_product(key: str) -> sqlite3.Row | None:
    with closing(get_connection()) as conn:
        return conn.execute("SELECT * FROM products WHERE key = ?", (key,)).fetchone()


def get_active_products(category: str) -> list[sqlite3.Row]:
    with closing(get_connection()) as conn:
        return conn.execute(
            "SELECT * FROM products WHERE category = ? AND is_active = 1 ORDER BY price ASC",
            (category,),
        ).fetchall()


def get_all_products() -> list[sqlite3.Row]:
    with closing(get_connection()) as conn:
        return conn.execute(
            "SELECT * FROM products WHERE is_active = 1 ORDER BY category, price ASC"
        ).fetchall()


# ---------------------------------------------------------------------
# Yuk kuzatish (shipments)
# ---------------------------------------------------------------------
def create_shipment(tracking_code: str, user_chat_id: int, description: str) -> int | None:
    with closing(get_connection()) as conn:
        try:
            cur = conn.execute(
                """INSERT INTO shipments (tracking_code, user_chat_id, description, status)
                   VALUES (?, ?, ?, 'accepted')""",
                (tracking_code, user_chat_id, description),
            )
            conn.commit()
            return cur.lastrowid
        except sqlite3.IntegrityError:
            return None  # bu kod allaqachon band


def get_shipment_by_code(tracking_code: str) -> sqlite3.Row | None:
    with closing(get_connection()) as conn:
        return conn.execute(
            "SELECT * FROM shipments WHERE tracking_code = ?", (tracking_code,)
        ).fetchone()


def get_shipment(shipment_id: int) -> sqlite3.Row | None:
    with closing(get_connection()) as conn:
        return conn.execute("SELECT * FROM shipments WHERE id = ?", (shipment_id,)).fetchone()


def update_shipment_status(shipment_id: int, status: str) -> None:
    with closing(get_connection()) as conn:
        conn.execute(
            "UPDATE shipments SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (status, shipment_id),
        )
        conn.commit()