# database.py
# ------------------------------------------------------------------
# Ushbu fayl butun loyihaning ma'lumotlar bazasi qatlami (SQLite).
# Bot.py va boshqa qismlar mahsulot, foydalanuvchi, buyurtma va
# promokodlar bilan ishlashda faqat shu fayldagi funksiyalarni chaqiradi.
# Bu orqali SQL so'rovlari bir joyda jamlanadi va kodni boshqarish osonlashadi.
# ------------------------------------------------------------------

import sqlite3
from contextlib import contextmanager
from typing import Optional

DB_NAME = "shop.db"


@contextmanager
def get_connection():
    """
    Har bir DB amali uchun yangi ulanish ochib, oxirida avtomatik yopadi.
    'with get_connection() as conn:' shaklida ishlatiladi.
    """
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row  # natijalarni dict kabi olish uchun
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    """
    Bot birinchi marta ishga tushganda chaqiriladi.
    Kerakli jadvallar mavjud bo'lmasa - yaratadi.
    """
    with get_connection() as conn:
        cur = conn.cursor()

        # --- Mahsulotlar jadvali ---
        cur.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                price REAL NOT NULL,
                photo_url TEXT DEFAULT '',
                sizes TEXT DEFAULT '',          -- razmerlar, vergul bilan: "S,M,L,XL" yoki "40,41,42"
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Eski bazalarda "sizes" ustuni bo'lmasligi mumkin - shu yerda qo'shib qo'yamiz
        cur.execute("PRAGMA table_info(products)")
        existing_columns = [row[1] for row in cur.fetchall()]
        if "sizes" not in existing_columns:
            cur.execute("ALTER TABLE products ADD COLUMN sizes TEXT DEFAULT ''")

        # --- Foydalanuvchilar jadvali ---
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # --- Promokodlar jadvali ---
        cur.execute("""
            CREATE TABLE IF NOT EXISTS promocodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                discount_percent INTEGER NOT NULL,
                is_active INTEGER DEFAULT 1
            )
        """)

        # --- Adminlar jadvali (dinamik qo'shiladigan adminlar) ---
        # Eslatma: bot.py ichidagi SUPER_ADMIN_IDS doim admin hisoblanadi
        # va bu jadvaldan mustaqil ishlaydi (kod orqali belgilanadi).
        # Shu jadval orqali qo'shilgan adminlarni esa super-admin
        # /add_admin va /remove_admin buyruqlari bilan boshqaradi.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY,
                username TEXT DEFAULT '',
                added_by INTEGER,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # --- Buyurtmalar jadvali ---
        cur.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                items_json TEXT NOT NULL,      -- savatdagi mahsulotlar JSON ko'rinishida
                total_price REAL NOT NULL,
                promo_code TEXT DEFAULT NULL,
                discount_percent INTEGER DEFAULT 0,
                final_price REAL NOT NULL,
                status TEXT DEFAULT 'new',     -- new / confirmed / cancelled
                delivery_price REAL DEFAULT 0,
                latitude REAL,
                longitude REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Eski bazalarda yetkazib berish ustunlari bo'lmasligi mumkin
        cur.execute("PRAGMA table_info(orders)")
        order_columns = [row[1] for row in cur.fetchall()]
        if "delivery_price" not in order_columns:
            cur.execute("ALTER TABLE orders ADD COLUMN delivery_price REAL DEFAULT 0")
        if "latitude" not in order_columns:
            cur.execute("ALTER TABLE orders ADD COLUMN latitude REAL")
        if "longitude" not in order_columns:
            cur.execute("ALTER TABLE orders ADD COLUMN longitude REAL")

        # --- Sozlamalar jadvali (kalit-qiymat) - do'kon joylashuvi,
        #     km narxi va boshqa sozlamalar shu yerda saqlanadi ---
        cur.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)

        # --- To'lov kartalari jadvali (admin qo'shadi, xaridorga buyurtma
        #     qabul qilingandan keyin to'lov qilish uchun ko'rsatiladi) ---
        cur.execute("""
            CREATE TABLE IF NOT EXISTS payment_cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                card_number TEXT NOT NULL,     -- faqat raqamlar, masalan 8600123456789012
                holder_name TEXT DEFAULT '',
                bank_name TEXT DEFAULT '',
                is_active INTEGER DEFAULT 1,
                added_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)


# ------------------------------------------------------------------
# MAHSULOTLAR bilan ishlash funksiyalari
# ------------------------------------------------------------------

def add_product(name: str, price: float, description: str = "", photo_url: str = "", sizes: str = "") -> int:
    """
    sizes - vergul bilan ajratilgan razmerlar matni, masalan:
      Kiyim uchun: "S,M,L,XL"
      Oyoq kiyim uchun: "40,41,42,43,44"
      Agar mahsulotda razmer bo'lmasa - bo'sh qoldiriladi ("")
    """
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO products (name, description, price, photo_url, sizes) VALUES (?, ?, ?, ?, ?)",
            (name, description, price, photo_url, sizes),
        )
        return cur.lastrowid


def delete_product(product_id: int) -> bool:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM products WHERE id = ?", (product_id,))
        return cur.rowcount > 0


def update_product_price(product_id: int, new_price: float) -> bool:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE products SET price = ? WHERE id = ?", (new_price, product_id))
        return cur.rowcount > 0


def get_all_products(only_active: bool = True):
    with get_connection() as conn:
        cur = conn.cursor()
        if only_active:
            cur.execute("SELECT * FROM products WHERE is_active = 1 ORDER BY id DESC")
        else:
            cur.execute("SELECT * FROM products ORDER BY id DESC")
        return [dict(row) for row in cur.fetchall()]


def get_product_by_id(product_id: int) -> Optional[dict]:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM products WHERE id = ?", (product_id,))
        row = cur.fetchone()
        return dict(row) if row else None


# ------------------------------------------------------------------
# FOYDALANUVCHILAR bilan ishlash funksiyalari
# ------------------------------------------------------------------

def add_or_update_user(user_id: int, username: str, full_name: str):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO users (user_id, username, full_name)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET username = excluded.username,
                                                full_name = excluded.full_name
            """,
            (user_id, username, full_name),
        )


# ------------------------------------------------------------------
# ADMINLAR bilan ishlash funksiyalari (dinamik qo'shiladigan adminlar)
# ------------------------------------------------------------------

def add_admin(user_id: int, username: str, added_by: int) -> bool:
    """Yangi adminni bazaga qo'shadi. Agar allaqachon mavjud bo'lsa False qaytaradi."""
    with get_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO admins (user_id, username, added_by) VALUES (?, ?, ?)",
                (user_id, username, added_by),
            )
            return True
        except sqlite3.IntegrityError:
            return False


def remove_admin(user_id: int) -> bool:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM admins WHERE user_id = ?", (user_id,))
        return cur.rowcount > 0


def is_admin_in_db(user_id: int) -> bool:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM admins WHERE user_id = ?", (user_id,))
        return cur.fetchone() is not None


def get_all_admins():
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM admins ORDER BY added_at DESC")
        return [dict(row) for row in cur.fetchall()]


# ------------------------------------------------------------------
# PROMOKODLAR bilan ishlash funksiyalari
# ------------------------------------------------------------------

def add_promocode(code: str, discount_percent: int) -> bool:
    with get_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO promocodes (code, discount_percent) VALUES (?, ?)",
                (code.upper(), discount_percent),
            )
            return True
        except sqlite3.IntegrityError:
            return False  # bunday promokod allaqachon mavjud


def delete_promocode(code: str) -> bool:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM promocodes WHERE code = ?", (code.upper(),))
        return cur.rowcount > 0


def get_promocode(code: str) -> Optional[dict]:
    """Promokodni tekshiradi, mavjud va faol bo'lsa qaytaradi."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM promocodes WHERE code = ? AND is_active = 1",
            (code.upper(),),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def get_all_promocodes():
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM promocodes ORDER BY id DESC")
        return [dict(row) for row in cur.fetchall()]


# ------------------------------------------------------------------
# BUYURTMALAR bilan ishlash funksiyalari
# ------------------------------------------------------------------

def create_order(user_id: int, items_json: str, total_price: float,
                  promo_code: Optional[str], discount_percent: int,
                  final_price: float) -> int:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO orders (user_id, items_json, total_price, promo_code,
                                 discount_percent, final_price)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, items_json, total_price, promo_code, discount_percent, final_price),
        )
        return cur.lastrowid


def get_order(order_id: int) -> Optional[dict]:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM orders WHERE id = ?", (order_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def update_order_status(order_id: int, status: str) -> bool:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
        return cur.rowcount > 0


def get_all_orders(limit: int = 50):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM orders ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(row) for row in cur.fetchall()]


# ------------------------------------------------------------------
# TO'LOV KARTALARI bilan ishlash funksiyalari
# ------------------------------------------------------------------

def add_card(card_number: str, holder_name: str, bank_name: str, added_by: int) -> int:
    """Faqat raqamlarni saqlaymiz, ko'rsatishda formatlaymiz (format_card_number)."""
    digits = "".join(ch for ch in card_number if ch.isdigit())
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO payment_cards (card_number, holder_name, bank_name, added_by) VALUES (?, ?, ?, ?)",
            (digits, holder_name, bank_name, added_by),
        )
        return cur.lastrowid


def delete_card(card_id: int) -> bool:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM payment_cards WHERE id = ?", (card_id,))
        return cur.rowcount > 0


def get_all_cards(only_active: bool = True):
    with get_connection() as conn:
        cur = conn.cursor()
        if only_active:
            cur.execute("SELECT * FROM payment_cards WHERE is_active = 1 ORDER BY id DESC")
        else:
            cur.execute("SELECT * FROM payment_cards ORDER BY id DESC")
        return [dict(row) for row in cur.fetchall()]


# ------------------------------------------------------------------
# SOZLAMALAR (kalit-qiymat) - do'kon joylashuvi, km narxi va h.k.
# ------------------------------------------------------------------

def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cur.fetchone()
        return row["value"] if row else default


def set_setting(key: str, value: str):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, str(value)),
        )


# ------------------------------------------------------------------
# YETKAZIB BERISH - buyurtmaga manzil/narx yozish
# ------------------------------------------------------------------

def update_order_delivery(order_id: int, latitude: Optional[float], longitude: Optional[float], delivery_price: float) -> bool:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE orders SET latitude = ?, longitude = ?, delivery_price = ? WHERE id = ?",
            (latitude, longitude, delivery_price, order_id),
        )
        return cur.rowcount > 0
