# bot.py
# ------------------------------------------------------------------
# LOYIHA HAQIDA:
# Bu fayl botning "miyasi". U 2 ta vazifani bajaradi:
#   1) Telegram bot (aiogram 3.x) - foydalanuvchiga WebApp tugmasini
#      ko'rsatadi, admin buyruqlarini boshqaradi (mahsulot qo'shish/
#      o'chirish, narx o'zgartirish, promokod qo'shish/o'chirish).
#   2) Kichik HTTP server (aiohttp) - webapp/ papkasidagi HTML/JS/CSS
#      fayllarni brauzerga xizmat qiladi VA webapp/script.js dan
#      fetch() orqali kelayotgan so'rovlarni (mahsulotlar ro'yxati,
#      yangi buyurtma) qabul qiladi.
#
# Ikkalasi bitta asyncio jarayonida BIRGA ishlaydi (dp.start_polling
# va aiohttp serveri asyncio.gather() bilan parallel ishga tushiriladi).
# ------------------------------------------------------------------

import asyncio
import hashlib
import hmac
import json
import logging
import math
import os
import time
import urllib.parse
from pathlib import Path

from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.base import StorageKey
from aiogram.types import (
    Message,
    WebAppInfo,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from aiohttp import web

import database as db

# ------------------------------------------------------------------
# SOZLAMALAR
# Haqiqiy qiymatlar endi kod ichida emas, balki loyiha papkasidagi
# `.env` faylida saqlanadi (bu fayl git/arxivga qo'shilmasligi kerak).
# Namuna uchun `.env.example` faylga qarang.
# ------------------------------------------------------------------
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN topilmadi! `.env` faylini yarating (namuna: .env.example) "
        "va ichiga BOT_TOKEN=... qatorini yozing."
    )

# SUPER_ADMIN_IDS - kod ichida qo'lda belgilanadigan "bosh adminlar".
# Ular hech qachon botdan o'chirilmaydi va boshqa (oddiy) adminlarni
# /add_admin va /remove_admin buyruqlari orqali qo'sha/o'chira oladi.
# Oddiy adminlar esa database.py dagi "admins" jadvalida saqlanadi
# va dinamik ravishda boshqariladi (bot qayta ishga tushirilmasa ham).
SUPER_ADMIN_IDS = [
    int(x) for x in os.getenv("SUPER_ADMIN_IDS", "2002780745").split(",") if x.strip()
]

# Bot ishlaydigan serverning ochiq (https) manzili.
# Telegram WebApp FAQAT https bo'lgan manzillarni qabul qiladi.
# Lokal test uchun ngrok/cloudflared kabi tunnel ishlatishingiz kerak, masalan:
#   ngrok http 8080
# va natijada olingan https havolani `.env` faylidagi PUBLIC_BASE_URL ga yozing.
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "https://your-domain-or-ngrok-url.example")
WEBAPP_URL = f"{PUBLIC_BASE_URL}/app"          # do'kon sahifasi manzili
ADMIN_WEBAPP_URL = f"{PUBLIC_BASE_URL}/app/admin.html"   # veb admin panel manzili

HTTP_HOST = os.getenv("HTTP_HOST", "0.0.0.0")
HTTP_PORT = int(os.getenv("HTTP_PORT", "8080"))

WEBAPP_DIR = Path(__file__).parent

# Yetkazib berish narxini hisoblashda ishlatiladigan standart qiymatlar
# (admin /admin panelidan "📍 Yetkazib berish sozlamalari" orqali o'zgartira oladi).
DEFAULT_PRICE_PER_KM = 3000     # 1 km uchun necha so'm
DEFAULT_BASE_DELIVERY_FEE = 5000  # boshlang'ich (bazaviy) yetkazib berish narxi

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("shop-bot")

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)


def is_super_admin(user_id: int) -> bool:
    """Faqat kod ichida belgilangan bosh adminlar uchun True qaytaradi."""
    return user_id in SUPER_ADMIN_IDS


def is_admin(user_id: int) -> bool:
    """Bosh admin YOKI bazada ro'yxatdan o'tgan oddiy admin bo'lsa True."""
    return is_super_admin(user_id) or db.is_admin_in_db(user_id)


def get_all_admin_ids() -> list:
    """Adminlarga xabar yuborish uchun barcha admin ID larini qaytaradi
    (super adminlar + bazadagi adminlar, takrorlanmasdan)."""
    db_admin_ids = [a["user_id"] for a in db.get_all_admins()]
    return list(set(SUPER_ADMIN_IDS + db_admin_ids))


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Ikki geografik nuqta orasidagi masofani km da hisoblaydi (to'g'ri chiziq bo'yicha)."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(d_lambda / 2) ** 2
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def get_shop_location():
    """Do'kon joylashuvini sozlamalardan o'qiydi. Sozlanmagan bo'lsa None qaytaradi."""
    lat = db.get_setting("shop_lat")
    lon = db.get_setting("shop_lon")
    if lat is None or lon is None:
        return None
    return float(lat), float(lon)


def compute_delivery_price(distance_km: float) -> float:
    price_per_km = float(db.get_setting("price_per_km", DEFAULT_PRICE_PER_KM))
    base_fee = float(db.get_setting("base_delivery_fee", DEFAULT_BASE_DELIVERY_FEE))
    return base_fee + distance_km * price_per_km


async def get_user_fsm_context(user_id: int) -> FSMContext:
    """
    Odatda FSMContext faqat handler ichida (masalan callback/message orqali)
    olinadi. Bu yerda esa buyurtma process_order() ichida (ya'ni HTTP so'rov
    yoki boshqa handlerdan) yaratilgani uchun, xaridorning shaxsiy holatini
    (state) qo'lda, uning user_id si orqali ochamiz.
    """
    key = StorageKey(bot_id=bot.id, chat_id=user_id, user_id=user_id)
    return FSMContext(storage=dp.storage, key=key)


def validate_init_data(init_data: str, bot_token: str, max_age_seconds: int = 86400):
    """
    Telegram WebApp yuborgan `initData` satrini tekshiradi (HMAC-SHA256).
    Bu orqali foydalanuvchi ID sini brauzerdan emas, faqat Telegram
    tomonidan imzolangan ma'lumotdan olamiz - shu bilan soxta user_id
    yuborib buyurtma "urlash" imkoniyati yopiladi.
    Muvaffaqiyatli bo'lsa {"user": {...}} qaytaradi, aks holda None.
    """
    if not init_data:
        return None
    try:
        parsed = dict(urllib.parse.parse_qsl(init_data, strict_parsing=True))
    except ValueError:
        return None

    received_hash = parsed.pop("hash", None)
    if not received_hash:
        return None

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(computed_hash, received_hash):
        return None

    auth_date = parsed.get("auth_date")
    if auth_date:
        try:
            if time.time() - int(auth_date) > max_age_seconds:
                return None  # eskirgan initData (masalan ilgari saqlab qolingan)
        except ValueError:
            pass

    user = None
    if parsed.get("user"):
        try:
            user = json.loads(parsed["user"])
        except json.JSONDecodeError:
            return None

    return {"user": user}


# ------------------------------------------------------------------
# FSM HOLATLARI - admin ko'p bosqichli amallarni bajarganda
# (masalan mahsulot qo'shish: avval nomini so'raymiz, keyin narxini...)
# ------------------------------------------------------------------
class AddProduct(StatesGroup):
    name = State()
    price = State()
    sizes = State()
    description = State()


class DeleteProduct(StatesGroup):
    product_id = State()


class ChangePrice(StatesGroup):
    product_id = State()
    new_price = State()


class AddPromo(StatesGroup):
    code = State()
    percent = State()


class DeletePromo(StatesGroup):
    code = State()


class AddAdmin(StatesGroup):
    user_id = State()


class RemoveAdmin(StatesGroup):
    user_id = State()


class AddCard(StatesGroup):
    card_number = State()
    holder_name = State()
    bank_name = State()


class DeleteCard(StatesGroup):
    card_id = State()


class WaitingDeliveryLocation(StatesGroup):
    """Xaridor 'Sotib olish'dan keyin manzilini yuborishini kutamiz."""
    order_id = State()


class SetShopLocation(StatesGroup):
    """Admin do'konning joylashuvi va yetkazib berish narxlarini sozlaydi."""
    location = State()
    price_per_km = State()
    base_fee = State()


def format_card_number(digits: str) -> str:
    """8600123456789012 -> 8600 1234 5678 9012"""
    digits = "".join(ch for ch in str(digits) if ch.isdigit())
    return " ".join(digits[i:i + 4] for i in range(0, len(digits), 4))


# ------------------------------------------------------------------
# ODDIY FOYDALANUVCHI BUYRUQLARI
# ------------------------------------------------------------------

@router.message(CommandStart())
async def cmd_start(message: Message):
    """
    /start bosilganda foydalanuvchini bazaga yozamiz va
    do'konni ochadigan WebApp tugmasini ko'rsatamiz.
    """
    db.add_or_update_user(
        user_id=message.from_user.id,
        username=message.from_user.username or "",
        full_name=message.from_user.full_name or "",
    )

    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🛍 Do'konni ochish", web_app=WebAppInfo(url=WEBAPP_URL))]
        ],
        resize_keyboard=True,
    )

    await message.answer(
        "Assalomu alaykum! 👋\n\n"
        "Bizning onlayn do'konimizga xush kelibsiz.\n"
        "Quyidagi tugma orqali mahsulotlarni ko'rib, buyurtma bering.",
        reply_markup=keyboard,
    )


@router.message(Command("help"))
async def cmd_help(message: Message):
    text = (
        "ℹ️ <b>Yordam</b>\n\n"
        "/start - do'konni ochish\n"
    )
    if is_admin(message.from_user.id):
        text += (
            "\n<b>Admin buyruqlari:</b>\n"
            "/admin - admin panelni ochish\n"
            "/products - barcha mahsulotlar ro'yxati\n"
            "/orders - so'nggi buyurtmalar\n"
            "/promos - promokodlar ro'yxati\n"
            "/cards - to'lov kartalari ro'yxati\n"
            "/delivery - yetkazib berish sozlamalari\n"
            "/admins - adminlar ro'yxati\n"
        )
        if is_super_admin(message.from_user.id):
            text += (
                "\n<b>Bosh admin buyruqlari:</b>\n"
                "/add_admin USER_ID - yangi admin qo'shish\n"
                "/remove_admin USER_ID - adminni o'chirish\n"
            )
    await message.answer(text)


# ------------------------------------------------------------------
# ADMIN PANEL - asosiy menyu (inline tugmalar)
# ------------------------------------------------------------------

def admin_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Mahsulot qo'shish", callback_data="adm_add_product")],
            [InlineKeyboardButton(text="🗑 Mahsulot o'chirish", callback_data="adm_del_product")],
            [InlineKeyboardButton(text="💰 Narxni o'zgartirish", callback_data="adm_price")],
            [InlineKeyboardButton(text="🏷 Promokod qo'shish", callback_data="adm_add_promo")],
            [InlineKeyboardButton(text="❌ Promokod o'chirish", callback_data="adm_del_promo")],
            [InlineKeyboardButton(text="💳 Karta qo'shish", callback_data="adm_add_card")],
            [InlineKeyboardButton(text="🗑 Kartani o'chirish", callback_data="adm_del_card")],
            [InlineKeyboardButton(text="📍 Yetkazib berish sozlamalari", callback_data="adm_delivery_settings")],
            [InlineKeyboardButton(text="📋 Mahsulotlar ro'yxati", callback_data="adm_list_products")],
            [InlineKeyboardButton(text="📦 Buyurtmalar", callback_data="adm_list_orders")],
            [InlineKeyboardButton(text="👤 Adminlar ro'yxati", callback_data="adm_list_admins")],
        ]
    )


def super_admin_menu_keyboard() -> InlineKeyboardMarkup:
    """Faqat bosh adminlarga ko'rinadigan qo'shimcha bo'lim."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Admin qo'shish", callback_data="adm_add_admin")],
            [InlineKeyboardButton(text="🚫 Admin o'chirish", callback_data="adm_remove_admin")],
        ]
    )


@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if not is_admin(message.from_user.id):
        return await message.answer("⛔️ Bu buyruq faqat adminlar uchun.")

    web_panel_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🌐 Veb admin panelni ochish", web_app=WebAppInfo(url=ADMIN_WEBAPP_URL))],
        ]
    )
    await message.answer(
        "🔧 <b>Admin panel</b>\nTo'liq boshqarish uchun veb-panelni oching, "
        "yoki quyidagi bo'limlardan birini tanlang:",
        reply_markup=web_panel_kb,
    )
    await message.answer("Bot ichidagi bo'limlar:", reply_markup=admin_menu_keyboard())

    if is_super_admin(message.from_user.id):
        await message.answer(
            "👑 <b>Bosh admin bo'limi</b>\nAdminlarni shu yerdan boshqaring:",
            reply_markup=super_admin_menu_keyboard(),
        )


# --- Callback: mahsulot qo'shish jarayonini boshlash ---
@router.callback_query(F.data == "adm_add_product")
async def adm_add_product_start(callback, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return await callback.answer("⛔️ Ruxsat yo'q", show_alert=True)
    await state.set_state(AddProduct.name)
    await callback.message.answer("Yangi mahsulot nomini kiriting:")
    await callback.answer()


@router.message(StateFilter(AddProduct.name))
async def adm_add_product_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await state.set_state(AddProduct.price)
    await message.answer("Endi narxini kiriting (faqat son, masalan 150000):")


@router.message(StateFilter(AddProduct.price))
async def adm_add_product_price(message: Message, state: FSMContext):
    try:
        price = float(message.text.replace(",", ".").strip())
    except ValueError:
        return await message.answer("❗️ Narxni faqat son ko'rinishida kiriting. Qayta urinib ko'ring:")
    await state.update_data(price=price)
    await state.set_state(AddProduct.sizes)
    await message.answer(
        "Razmerlarini kiriting, vergul bilan ajratib:\n"
        "• Kiyim uchun: <code>S,M,L,XL</code>\n"
        "• Oyoq kiyim uchun: <code>40,41,42,43,44</code>\n\n"
        "Agar bu mahsulotda razmer bo'lmasa — <code>-</code> deb yozing."
    )


@router.message(StateFilter(AddProduct.sizes))
async def adm_add_product_sizes(message: Message, state: FSMContext):
    raw = message.text.strip()
    if raw == "-":
        sizes = ""
    else:
        # foydalanuvchi kiritgan qiymatlarni tozalab, vergul bilan qayta yig'amiz
        parts = [p.strip().upper() for p in raw.split(",") if p.strip()]
        sizes = ",".join(parts)

    await state.update_data(sizes=sizes)
    await state.set_state(AddProduct.description)
    await message.answer("Mahsulot haqida to'liq tavsilot (tavsif) kiriting (yoki '-' deb yozing, o'tkazib yuborish uchun):")


@router.message(StateFilter(AddProduct.description))
async def adm_add_product_description(message: Message, state: FSMContext):
    data = await state.get_data()
    description = "" if message.text.strip() == "-" else message.text.strip()

    product_id = db.add_product(
        name=data["name"],
        price=data["price"],
        description=description,
        sizes=data.get("sizes", ""),
    )
    await state.clear()

    sizes_line = f"\n📏 Razmerlar: {data['sizes']}" if data.get("sizes") else ""
    await message.answer(
        f"✅ Mahsulot qo'shildi!\n\n"
        f"🆔 ID: {product_id}\n"
        f"📦 Nomi: {data['name']}\n"
        f"💰 Narxi: {data['price']:.0f} so'm"
        f"{sizes_line}"
    )


# --- Callback: mahsulot o'chirish ---
@router.callback_query(F.data == "adm_del_product")
async def adm_del_product_start(callback, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return await callback.answer("⛔️ Ruxsat yo'q", show_alert=True)
    products = db.get_all_products(only_active=False)
    if not products:
        await callback.message.answer("Hozircha mahsulotlar mavjud emas.")
        return await callback.answer()

    text = "🗑 O'chirmoqchi bo'lgan mahsulot ID sini yuboring:\n\n"
    for p in products:
        text += f"#{p['id']} — {p['name']} — {p['price']:.0f} so'm\n"

    await state.set_state(DeleteProduct.product_id)
    await callback.message.answer(text)
    await callback.answer()


@router.message(StateFilter(DeleteProduct.product_id))
async def adm_del_product_finish(message: Message, state: FSMContext):
    try:
        product_id = int(message.text.strip())
    except ValueError:
        return await message.answer("❗️ Faqat mahsulot ID raqamini yuboring:")

    ok = db.delete_product(product_id)
    await state.clear()
    if ok:
        await message.answer(f"✅ #{product_id} mahsulot o'chirildi.")
    else:
        await message.answer("❗️ Bunday ID topilmadi.")


# --- Callback: narxni o'zgartirish ---
@router.callback_query(F.data == "adm_price")
async def adm_price_start(callback, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return await callback.answer("⛔️ Ruxsat yo'q", show_alert=True)
    products = db.get_all_products(only_active=False)
    if not products:
        await callback.message.answer("Hozircha mahsulotlar mavjud emas.")
        return await callback.answer()

    text = "💰 Narxini o'zgartirmoqchi bo'lgan mahsulot ID sini yuboring:\n\n"
    for p in products:
        text += f"#{p['id']} — {p['name']} — {p['price']:.0f} so'm\n"

    await state.set_state(ChangePrice.product_id)
    await callback.message.answer(text)
    await callback.answer()


@router.message(StateFilter(ChangePrice.product_id))
async def adm_price_get_id(message: Message, state: FSMContext):
    try:
        product_id = int(message.text.strip())
    except ValueError:
        return await message.answer("❗️ Faqat ID raqamini yuboring:")

    product = db.get_product_by_id(product_id)
    if not product:
        return await message.answer("❗️ Bunday ID topilmadi. Qayta urinib ko'ring:")

    await state.update_data(product_id=product_id)
    await state.set_state(ChangePrice.new_price)
    await message.answer(f"'{product['name']}' uchun yangi narxni kiriting:")


@router.message(StateFilter(ChangePrice.new_price))
async def adm_price_finish(message: Message, state: FSMContext):
    try:
        new_price = float(message.text.replace(",", ".").strip())
    except ValueError:
        return await message.answer("❗️ Narxni faqat son ko'rinishida kiriting:")

    data = await state.get_data()
    db.update_product_price(data["product_id"], new_price)
    await state.clear()
    await message.answer(f"✅ Narx yangilandi: {new_price:.0f} so'm")


# --- Callback: promokod qo'shish ---
@router.callback_query(F.data == "adm_add_promo")
async def adm_add_promo_start(callback, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return await callback.answer("⛔️ Ruxsat yo'q", show_alert=True)
    await state.set_state(AddPromo.code)
    await callback.message.answer("Yangi promokod matnini kiriting (masalan SALE20):")
    await callback.answer()


@router.message(StateFilter(AddPromo.code))
async def adm_add_promo_code(message: Message, state: FSMContext):
    await state.update_data(code=message.text.strip().upper())
    await state.set_state(AddPromo.percent)
    await message.answer("Chegirma foizini kiriting (masalan 20):")


@router.message(StateFilter(AddPromo.percent))
async def adm_add_promo_percent(message: Message, state: FSMContext):
    try:
        percent = int(message.text.strip())
        if not (0 < percent <= 100):
            raise ValueError
    except ValueError:
        return await message.answer("❗️ Foizni 1 dan 100 gacha son ko'rinishida kiriting:")

    data = await state.get_data()
    ok = db.add_promocode(data["code"], percent)
    await state.clear()
    if ok:
        await message.answer(f"✅ Promokod qo'shildi: {data['code']} — {percent}% chegirma")
    else:
        await message.answer("❗️ Bunday promokod allaqachon mavjud.")


# --- Callback: promokod o'chirish ---
@router.callback_query(F.data == "adm_del_promo")
async def adm_del_promo_start(callback, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return await callback.answer("⛔️ Ruxsat yo'q", show_alert=True)
    promos = db.get_all_promocodes()
    if not promos:
        await callback.message.answer("Hozircha promokodlar mavjud emas.")
        return await callback.answer()

    text = "❌ O'chirmoqchi bo'lgan promokodni yuboring:\n\n"
    for p in promos:
        text += f"{p['code']} — {p['discount_percent']}%\n"

    await state.set_state(DeletePromo.code)
    await callback.message.answer(text)
    await callback.answer()


@router.message(StateFilter(DeletePromo.code))
async def adm_del_promo_finish(message: Message, state: FSMContext):
    code = message.text.strip().upper()
    ok = db.delete_promocode(code)
    await state.clear()
    if ok:
        await message.answer(f"✅ {code} promokodi o'chirildi.")
    else:
        await message.answer("❗️ Bunday promokod topilmadi.")


# --- Callback: to'lov kartasi qo'shish ---
@router.callback_query(F.data == "adm_add_card")
async def adm_add_card_start(callback, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return await callback.answer("⛔️ Ruxsat yo'q", show_alert=True)
    await state.set_state(AddCard.card_number)
    await callback.message.answer(
        "💳 Karta raqamini kiriting (bo'sh joy yoki chiziqchalar bilan ham bo'ladi):\n"
        "masalan: <code>8600 1234 5678 9012</code>"
    )
    await callback.answer()


@router.message(StateFilter(AddCard.card_number))
async def adm_add_card_number(message: Message, state: FSMContext):
    digits = "".join(ch for ch in message.text if ch.isdigit())
    if len(digits) < 12:
        return await message.answer("❗️ Karta raqami noto'g'ri ko'rinishda. Qayta kiriting:")
    await state.update_data(card_number=digits)
    await state.set_state(AddCard.holder_name)
    await message.answer("Karta egasining F.I.Sh sini kiriting (yoki '-' deb yozing, o'tkazib yuborish uchun):")


@router.message(StateFilter(AddCard.holder_name))
async def adm_add_card_holder(message: Message, state: FSMContext):
    holder_name = "" if message.text.strip() == "-" else message.text.strip()
    await state.update_data(holder_name=holder_name)
    await state.set_state(AddCard.bank_name)
    await message.answer("Bank nomini kiriting (yoki '-' deb yozing, o'tkazib yuborish uchun):")


@router.message(StateFilter(AddCard.bank_name))
async def adm_add_card_bank(message: Message, state: FSMContext):
    bank_name = "" if message.text.strip() == "-" else message.text.strip()
    data = await state.get_data()

    card_id = db.add_card(
        card_number=data["card_number"],
        holder_name=data.get("holder_name", ""),
        bank_name=bank_name,
        added_by=message.from_user.id,
    )
    await state.clear()

    await message.answer(
        f"✅ Karta qo'shildi!\n\n"
        f"💳 <code>{format_card_number(data['card_number'])}</code>\n"
        f"{data.get('holder_name', '') or '—'}"
        f"{(' • ' + bank_name) if bank_name else ''}\n\n"
        f"Bu karta endi buyurtma qabul qilingan xaridorlarga avtomatik ko'rsatiladi."
    )


# --- Callback: to'lov kartasini o'chirish ---
@router.callback_query(F.data == "adm_del_card")
async def adm_del_card_start(callback, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return await callback.answer("⛔️ Ruxsat yo'q", show_alert=True)
    cards = db.get_all_cards(only_active=False)
    if not cards:
        await callback.message.answer("Hozircha kartalar qo'shilmagan.")
        return await callback.answer()

    text = "🗑 O'chirmoqchi bo'lgan karta ID sini yuboring:\n\n"
    for c in cards:
        label = " • ".join(filter(None, [c["holder_name"], c["bank_name"]]))
        text += f"#{c['id']} — {format_card_number(c['card_number'])}" + (f" ({label})" if label else "") + "\n"

    await state.set_state(DeleteCard.card_id)
    await callback.message.answer(text)
    await callback.answer()


@router.message(StateFilter(DeleteCard.card_id))
async def adm_del_card_finish(message: Message, state: FSMContext):
    try:
        card_id = int(message.text.strip())
    except ValueError:
        return await message.answer("❗️ Faqat karta ID raqamini yuboring:")

    ok = db.delete_card(card_id)
    await state.clear()
    if ok:
        await message.answer(f"✅ #{card_id} karta o'chirildi.")
    else:
        await message.answer("❗️ Bunday ID topilmadi.")


@router.message(Command("cards"))
async def cmd_cards(message: Message):
    if not is_admin(message.from_user.id):
        return
    cards = db.get_all_cards(only_active=False)
    if not cards:
        return await message.answer("Hozircha kartalar qo'shilmagan.")
    text = "💳 <b>To'lov kartalari:</b>\n\n"
    for c in cards:
        label = " • ".join(filter(None, [c["holder_name"], c["bank_name"]]))
        status = "faol ✅" if c["is_active"] else "faol emas ❌"
        text += f"#{c['id']} — <code>{format_card_number(c['card_number'])}</code>" + (f" ({label})" if label else "") + f" — {status}\n"
    await message.answer(text)


# ------------------------------------------------------------------
# YETKAZIB BERISH SOZLAMALARI (admin do'kon joylashuvi + km narxini kiritadi)
# ------------------------------------------------------------------

@router.callback_query(F.data == "adm_delivery_settings")
async def adm_delivery_settings_start(callback, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return await callback.answer("⛔️ Ruxsat yo'q", show_alert=True)
    await state.set_state(SetShopLocation.location)
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📍 Do'kon joylashuvini yuborish", request_location=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await callback.message.answer(
        "📍 Do'konning joylashuvini yuboring (pastdagi tugma orqali, yoki 📎 → Location):\n"
        "Shu nuqtadan xaridorgacha bo'lgan masofa shu yerdan hisoblanadi.",
        reply_markup=kb,
    )
    await callback.answer()


@router.message(StateFilter(SetShopLocation.location), F.location)
async def adm_delivery_settings_location(message: Message, state: FSMContext):
    db.set_setting("shop_lat", message.location.latitude)
    db.set_setting("shop_lon", message.location.longitude)
    await state.set_state(SetShopLocation.price_per_km)
    current = float(db.get_setting("price_per_km", DEFAULT_PRICE_PER_KM))
    await message.answer(
        f"✅ Do'kon joylashuvi saqlandi.\n\n"
        f"Endi 1 km uchun necha so'm olishni kiriting (hozirgi: {current:.0f} so'm):",
        reply_markup=ReplyKeyboardRemove(),
    )


@router.message(StateFilter(SetShopLocation.location))
async def adm_delivery_settings_location_invalid(message: Message):
    await message.answer("❗️ Iltimos, pastdagi tugma yoki 📎 → Location orqali joylashuv yuboring:")


@router.message(StateFilter(SetShopLocation.price_per_km))
async def adm_delivery_settings_price(message: Message, state: FSMContext):
    try:
        price = float(message.text.replace(",", ".").strip())
        if price < 0:
            raise ValueError
    except ValueError:
        return await message.answer("❗️ Faqat musbat son kiriting:")

    await state.update_data(price_per_km=price)
    await state.set_state(SetShopLocation.base_fee)
    current = float(db.get_setting("base_delivery_fee", DEFAULT_BASE_DELIVERY_FEE))
    await message.answer(f"Endi bazaviy (boshlang'ich) yetkazib berish narxini kiriting (hozirgi: {current:.0f} so'm):")


@router.message(StateFilter(SetShopLocation.base_fee))
async def adm_delivery_settings_base_fee(message: Message, state: FSMContext):
    try:
        base_fee = float(message.text.replace(",", ".").strip())
        if base_fee < 0:
            raise ValueError
    except ValueError:
        return await message.answer("❗️ Faqat musbat son kiriting:")

    data = await state.get_data()
    price_per_km = data["price_per_km"]
    db.set_setting("price_per_km", price_per_km)
    db.set_setting("base_delivery_fee", base_fee)
    await state.clear()

    example_5km = base_fee + price_per_km * 5
    await message.answer(
        f"✅ Yetkazib berish sozlamalari saqlandi!\n\n"
        f"📏 1 km: {price_per_km:.0f} so'm\n"
        f"🏁 Bazaviy narx: {base_fee:.0f} so'm\n\n"
        f"Masalan, 5 km masofa uchun: {example_5km:.0f} so'm"
    )


@router.message(Command("delivery"))
async def cmd_delivery(message: Message):
    if not is_admin(message.from_user.id):
        return
    shop_loc = get_shop_location()
    price_per_km = float(db.get_setting("price_per_km", DEFAULT_PRICE_PER_KM))
    base_fee = float(db.get_setting("base_delivery_fee", DEFAULT_BASE_DELIVERY_FEE))
    loc_line = f"📍 {shop_loc[0]:.5f}, {shop_loc[1]:.5f}" if shop_loc else "📍 Hali sozlanmagan"
    await message.answer(
        f"🚚 <b>Yetkazib berish sozlamalari</b>\n\n"
        f"{loc_line}\n"
        f"📏 1 km: {price_per_km:.0f} so'm\n"
        f"🏁 Bazaviy narx: {base_fee:.0f} so'm\n\n"
        f"O'zgartirish uchun: /admin → 📍 Yetkazib berish sozlamalari"
    )


# --- Callback: mahsulotlar ro'yxati / buyurtmalar ---
@router.callback_query(F.data == "adm_list_products")
async def adm_list_products(callback):
    if not is_admin(callback.from_user.id):
        return await callback.answer("⛔️ Ruxsat yo'q", show_alert=True)
    products = db.get_all_products(only_active=False)
    if not products:
        text = "Hozircha mahsulotlar yo'q."
    else:
        text = "📋 <b>Mahsulotlar:</b>\n\n"
        for p in products:
            text += f"#{p['id']} — {p['name']} — {p['price']:.0f} so'm\n"
    await callback.message.answer(text)
    await callback.answer()


@router.callback_query(F.data == "adm_list_orders")
async def adm_list_orders(callback):
    if not is_admin(callback.from_user.id):
        return await callback.answer("⛔️ Ruxsat yo'q", show_alert=True)
    orders = db.get_all_orders(limit=20)
    if not orders:
        text = "Hozircha buyurtmalar yo'q."
    else:
        text = "📦 <b>So'nggi buyurtmalar:</b>\n\n"
        for o in orders:
            delivery_line = f" +{o['delivery_price']:.0f} yetkazish" if o["delivery_price"] else ""
            text += (
                f"#{o['id']} — user {o['user_id']} — "
                f"{o['final_price']:.0f} so'm{delivery_line} ({o['status']})\n"
            )
    await callback.message.answer(text)
    await callback.answer()


# --- Callback: adminlar ro'yxatini ko'rsatish ---
@router.callback_query(F.data == "adm_list_admins")
async def adm_list_admins(callback):
    if not is_admin(callback.from_user.id):
        return await callback.answer("⛔️ Ruxsat yo'q", show_alert=True)
    await callback.message.answer(build_admins_list_text())
    await callback.answer()


def build_admins_list_text() -> str:
    text = "👑 <b>Bosh adminlar</b> (kod orqali belgilangan):\n"
    for uid in SUPER_ADMIN_IDS:
        text += f"  • <code>{uid}</code>\n"

    db_admins = db.get_all_admins()
    text += "\n👤 <b>Qo'shimcha adminlar</b>:\n"
    if not db_admins:
        text += "  (hozircha yo'q)\n"
    else:
        for a in db_admins:
            uname = f"@{a['username']}" if a["username"] else ""
            text += f"  • <code>{a['user_id']}</code> {uname}\n"
    return text


# --- Callback: yangi admin qo'shish (faqat bosh adminlar uchun) ---
@router.callback_query(F.data == "adm_add_admin")
async def adm_add_admin_start(callback, state: FSMContext):
    if not is_super_admin(callback.from_user.id):
        return await callback.answer("⛔️ Bu bo'lim faqat bosh adminlar uchun", show_alert=True)
    await state.set_state(AddAdmin.user_id)
    await callback.message.answer(
        "Yangi admin qilib tayinlamoqchi bo'lgan foydalanuvchining "
        "Telegram user_id raqamini yuboring.\n\n"
        "💡 User ID ni bilish uchun foydalanuvchi @userinfobot ga /start yuborishi mumkin."
    )
    await callback.answer()


@router.message(StateFilter(AddAdmin.user_id))
async def adm_add_admin_finish(message: Message, state: FSMContext):
    try:
        new_admin_id = int(message.text.strip())
    except ValueError:
        return await message.answer("❗️ Faqat son (user_id) yuboring:")

    await state.clear()

    if is_admin(new_admin_id):
        return await message.answer("❗️ Bu foydalanuvchi allaqachon admin.")

    ok = db.add_admin(user_id=new_admin_id, username="", added_by=message.from_user.id)
    if ok:
        await message.answer(f"✅ Yangi admin qo'shildi: <code>{new_admin_id}</code>")
        try:
            await bot.send_message(
                new_admin_id,
                "🎉 Tabriklaymiz! Sizga ushbu do'kon botida admin huquqi berildi.\n"
                "/admin buyrug'i orqali admin panelni oching.",
            )
        except Exception as e:
            logger.warning(f"Yangi adminga xabar yuborib bo'lmadi: {e}")
    else:
        await message.answer("❗️ Xatolik: bu foydalanuvchi bazada allaqachon mavjud.")


# --- Callback: adminni o'chirish (faqat bosh adminlar uchun) ---
@router.callback_query(F.data == "adm_remove_admin")
async def adm_remove_admin_start(callback, state: FSMContext):
    if not is_super_admin(callback.from_user.id):
        return await callback.answer("⛔️ Bu bo'lim faqat bosh adminlar uchun", show_alert=True)

    db_admins = db.get_all_admins()
    if not db_admins:
        await callback.message.answer("Hozircha o'chirish mumkin bo'lgan (qo'shimcha) adminlar yo'q.")
        return await callback.answer()

    text = "🚫 O'chirmoqchi bo'lgan adminning user_id sini yuboring:\n\n"
    for a in db_admins:
        uname = f"@{a['username']}" if a["username"] else ""
        text += f"  • <code>{a['user_id']}</code> {uname}\n"

    await state.set_state(RemoveAdmin.user_id)
    await callback.message.answer(text)
    await callback.answer()


@router.message(StateFilter(RemoveAdmin.user_id))
async def adm_remove_admin_finish(message: Message, state: FSMContext):
    try:
        target_id = int(message.text.strip())
    except ValueError:
        return await message.answer("❗️ Faqat son (user_id) yuboring:")

    await state.clear()

    if target_id in SUPER_ADMIN_IDS:
        return await message.answer("❗️ Bosh adminni bu yerdan o'chirib bo'lmaydi (kod orqali belgilangan).")

    ok = db.remove_admin(target_id)
    if ok:
        await message.answer(f"✅ Admin o'chirildi: <code>{target_id}</code>")
    else:
        await message.answer("❗️ Bunday admin bazada topilmadi.")


# --- Matnli buyruqlar: /add_admin, /remove_admin, /admins (bosh adminlar uchun tezkor yo'l) ---
@router.message(Command("add_admin"))
async def cmd_add_admin(message: Message):
    if not is_super_admin(message.from_user.id):
        return await message.answer("⛔️ Bu buyruq faqat bosh adminlar uchun.")

    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip().isdigit():
        return await message.answer("Foydalanish: <code>/add_admin USER_ID</code>")

    new_admin_id = int(args[1].strip())
    if is_admin(new_admin_id):
        return await message.answer("❗️ Bu foydalanuvchi allaqachon admin.")

    ok = db.add_admin(user_id=new_admin_id, username="", added_by=message.from_user.id)
    if ok:
        await message.answer(f"✅ Yangi admin qo'shildi: <code>{new_admin_id}</code>")
    else:
        await message.answer("❗️ Xatolik yuz berdi.")


@router.message(Command("remove_admin"))
async def cmd_remove_admin(message: Message):
    if not is_super_admin(message.from_user.id):
        return await message.answer("⛔️ Bu buyruq faqat bosh adminlar uchun.")

    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip().isdigit():
        return await message.answer("Foydalanish: <code>/remove_admin USER_ID</code>")

    target_id = int(args[1].strip())
    if target_id in SUPER_ADMIN_IDS:
        return await message.answer("❗️ Bosh adminni o'chirib bo'lmaydi.")

    ok = db.remove_admin(target_id)
    if ok:
        await message.answer(f"✅ Admin o'chirildi: <code>{target_id}</code>")
    else:
        await message.answer("❗️ Bunday admin topilmadi.")


@router.message(Command("admins"))
async def cmd_admins(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer(build_admins_list_text())


# Tezkor matnli buyruqlar (admin panelsiz ham ishlatish uchun)
@router.message(Command("products"))
async def cmd_products(message: Message):
    if not is_admin(message.from_user.id):
        return
    await adm_list_products_text(message)


async def adm_list_products_text(message: Message):
    products = db.get_all_products(only_active=False)
    if not products:
        return await message.answer("Hozircha mahsulotlar yo'q.")
    text = "📋 <b>Mahsulotlar:</b>\n\n"
    for p in products:
        text += f"#{p['id']} — {p['name']} — {p['price']:.0f} so'm\n"
    await message.answer(text)


@router.message(Command("orders"))
async def cmd_orders(message: Message):
    if not is_admin(message.from_user.id):
        return
    orders = db.get_all_orders(limit=20)
    if not orders:
        return await message.answer("Hozircha buyurtmalar yo'q.")
    text = "📦 <b>So'nggi buyurtmalar:</b>\n\n"
    for o in orders:
        delivery_line = f" +{o['delivery_price']:.0f} yetkazish" if o["delivery_price"] else ""
        text += f"#{o['id']} — user {o['user_id']} — {o['final_price']:.0f} so'm{delivery_line} ({o['status']})\n"
    await message.answer(text)


@router.message(Command("promos"))
async def cmd_promos(message: Message):
    if not is_admin(message.from_user.id):
        return
    promos = db.get_all_promocodes()
    if not promos:
        return await message.answer("Hozircha promokodlar yo'q.")
    text = "🏷 <b>Promokodlar:</b>\n\n"
    for p in promos:
        status = "faol ✅" if p["is_active"] else "faol emas ❌"
        text += f"{p['code']} — {p['discount_percent']}% ({status})\n"
    await message.answer(text)


# ------------------------------------------------------------------
# XARIDORDAN YETKAZIB BERISH MANZILINI QABUL QILISH
# (buyurtma qabul qilingandan keyin process_order shu holatni yoqadi)
# ------------------------------------------------------------------

@router.message(StateFilter(WaitingDeliveryLocation.order_id), F.location)
async def handle_delivery_location(message: Message, state: FSMContext):
    data = await state.get_data()
    order_id = data.get("order_id")
    await state.clear()

    order = db.get_order(order_id)
    if not order:
        return await message.answer("❗️ Buyurtma topilmadi.", reply_markup=ReplyKeyboardRemove())

    lat, lon = message.location.latitude, message.location.longitude
    shop_loc = get_shop_location()
    distance_line = ""

    if shop_loc:
        distance_km = haversine_km(shop_loc[0], shop_loc[1], lat, lon)
        delivery_price = compute_delivery_price(distance_km)
        db.update_order_delivery(order_id, lat, lon, delivery_price)
        total_with_delivery = order["final_price"] + delivery_price
        await message.answer(
            f"🚚 Yetkazib berish: <b>{delivery_price:.0f} so'm</b> (~{distance_km:.1f} km)\n"
            f"💵 Umumiy to'lov (mahsulot + yetkazish): <b>{total_with_delivery:.0f} so'm</b>",
            reply_markup=ReplyKeyboardRemove(),
        )
        distance_line = f"📏 Masofa: {distance_km:.1f} km\n🚚 Yetkazib berish: {delivery_price:.0f} so'm\n"
    else:
        db.update_order_delivery(order_id, lat, lon, 0)
        await message.answer(
            "✅ Manzilingiz qabul qilindi. Operator yetkazib berish narxini alohida aytadi.",
            reply_markup=ReplyKeyboardRemove(),
        )

    # Manzilni adminga tabiiy Telegram xaritasi + Google Maps havolasi bilan yuboramiz
    maps_link = f"https://maps.google.com/?q={lat},{lon}"
    admin_text = (
        f"📍 <b>Buyurtma #{order_id}</b> uchun manzil yuborildi\n"
        f"👤 <a href='tg://user?id={message.from_user.id}'>{message.from_user.id}</a>\n"
        f"{distance_line}"
        f"🗺 <a href='{maps_link}'>Google Maps'da ochish</a>"
    )
    for admin_id in get_all_admin_ids():
        try:
            await bot.send_location(admin_id, latitude=lat, longitude=lon)
            await bot.send_message(admin_id, admin_text)
        except Exception as e:
            logger.warning(f"Adminga manzil yuborib bo'lmadi ({admin_id}): {e}")


@router.message(StateFilter(WaitingDeliveryLocation.order_id), F.text == "🏬 O'zim olib ketaman")
async def handle_pickup_choice(message: Message, state: FSMContext):
    data = await state.get_data()
    order_id = data.get("order_id")
    await state.clear()
    db.update_order_delivery(order_id, None, None, 0)

    await message.answer(
        "🏬 Yaxshi, o'zingiz do'kondan olib ketasiz. Yetkazib berish kerak emas.",
        reply_markup=ReplyKeyboardRemove(),
    )
    for admin_id in get_all_admin_ids():
        try:
            await bot.send_message(
                admin_id,
                f"🏬 Buyurtma #{order_id}: xaridor o'zi olib ketadi (yetkazib berish shart emas).",
            )
        except Exception as e:
            logger.warning(f"Adminga xabar yuborib bo'lmadi ({admin_id}): {e}")


@router.message(StateFilter(WaitingDeliveryLocation.order_id))
async def handle_delivery_location_invalid(message: Message):
    await message.answer("❗️ Iltimos, pastdagi tugmalardan birini tanlang: manzil yuboring yoki 'O'zim olib ketaman'ni bosing.")


# ------------------------------------------------------------------
# WebApp dan keladigan "sendData" xabarlarini qabul qilish
# (script.js Telegram.WebApp.sendData() orqali ham yuborishi mumkin,
#  bu - fetch() usuliga qo'shimcha zaxira yo'l sifatida qo'shildi)
# ------------------------------------------------------------------
@router.message(F.web_app_data)
async def handle_webapp_data(message: Message):
    try:
        data = json.loads(message.web_app_data.data)
    except json.JSONDecodeError:
        return await message.answer("❗️ Buyurtma ma'lumotini o'qib bo'lmadi.")

    # Bu yerda message.from_user.id Telegram tomonidan tasdiqlangan
    # (Bot API orqali kelgan), shuning uchun initData tekshirish shart emas.
    # process_order o'zi xaridorga tasdiqlash + to'lov kartasi xabarini yuboradi.
    try:
        await process_order(user_id=message.from_user.id, order_data=data)
    except ValueError as e:
        if str(e) == "phone_required":
            await message.answer("❗️ Telefon raqamingizni kiritmagansiz. Iltimos, qaytadan urinib ko'ring.")
        else:
            await message.answer("❗️ Savat bo'sh yoki mahsulotlar topilmadi.")


def order_admin_keyboard(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"order_ok:{order_id}"),
                InlineKeyboardButton(text="❌ Bekor qilish", callback_data=f"order_no:{order_id}"),
            ]
        ]
    )


# ------------------------------------------------------------------
# TO'LOV CHEKI (screenshot) qabul qilish
# Mijoz kartaga pul o'tkazgach, shu yerga chek/screenshot rasm qilib
# yuboradi. Bot buni eng oxirgi "new" holatdagi buyurtmasiga bog'lab,
# rasmni to'g'ridan-to'g'ri barcha adminlarga (tasdiqlash/bekor qilish
# tugmalari bilan) yuboradi.
# ------------------------------------------------------------------
@router.message(F.photo)
async def handle_payment_receipt(message: Message):
    order = db.get_latest_pending_order_for_user(message.from_user.id)
    if not order:
        # Foydalanuvchida hech qanday kutilayotgan buyurtma yo'q -
        # bu rasm chekka aloqasi bo'lmasligi mumkin, shuning uchun jim turamiz.
        return

    file_id = message.photo[-1].file_id
    db.update_order_receipt(order["id"], file_id)

    caption = (
        f"🧾 <b>To'lov cheki — buyurtma #{order['id']}</b>\n"
        f"👤 Foydalanuvchi: <a href='tg://user?id={message.from_user.id}'>{message.from_user.id}</a>\n"
        f"💵 Summa: {order['final_price']:.0f} so'm"
    )
    for admin_id in get_all_admin_ids():
        try:
            await bot.send_photo(
                admin_id,
                photo=file_id,
                caption=caption,
                reply_markup=order_admin_keyboard(order["id"]),
            )
        except Exception as e:
            logger.warning(f"Chekni adminga yuborib bo'lmadi ({admin_id}): {e}")

    await message.answer("✅ Chek qabul qilindi. Operator tez orada tekshirib, buyurtmangizni tasdiqlaydi.")


async def process_order(user_id: int, order_data: dict) -> dict:
    """
    Buyurtmani bazaga yozadi va barcha adminlarga tasdiqlash tugmali
    xabar yuboradi. Bu funksiya ham web_app_data orqali, ham HTTP API
    (/api/checkout) orqali kelgan buyurtmalar uchun BIR XIL ishlatiladi.

    MUHIM: narx va mahsulot ma'lumotlari HECH QACHON clientdan (browser)
    kelgan qiymatga ishonib olinmaydi - har bir mahsulot ID va soni
    bo'yicha bazadan qayta tekshirib, narx shu yerda qayta hisoblanadi.
    Shunday qilib foydalanuvchi brauzerdan narxni "buzib" yubora olmaydi.
    """
    raw_items = order_data.get("items", [])
    promo_code = order_data.get("promo_code")
    if promo_code:
        promo_code = str(promo_code).strip().upper()

    phone = str(order_data.get("phone") or "").strip()
    if not phone:
        raise ValueError("phone_required")

    resolved_items = []
    total_price = 0.0
    for raw in raw_items:
        try:
            product_id = int(raw.get("id"))
            qty = int(raw.get("qty", 1))
        except (TypeError, ValueError, AttributeError):
            continue
        if qty <= 0:
            continue

        product = db.get_product_by_id(product_id)
        if not product or not product.get("is_active", 1):
            continue  # o'chirilgan/faol bo'lmagan mahsulotni e'tiborsiz qoldiramiz

        size = str(raw.get("size") or "")
        line_total = product["price"] * qty
        total_price += line_total
        resolved_items.append({
            "id": product_id,
            "name": product["name"],
            "price": product["price"],
            "size": size,
            "qty": qty,
        })

    if not resolved_items:
        raise ValueError("empty_or_invalid_cart")

    discount_percent = 0
    if promo_code:
        promo = db.get_promocode(promo_code)
        if promo:
            discount_percent = promo["discount_percent"]
        else:
            promo_code = None  # noto'g'ri/eskirgan promokod - hisobga olinmaydi

    final_price = total_price * (1 - discount_percent / 100)

    order_id = db.create_order(
        user_id=user_id,
        items_json=json.dumps(resolved_items, ensure_ascii=False),
        total_price=total_price,
        promo_code=promo_code,
        discount_percent=discount_percent,
        final_price=final_price,
        phone=phone,
    )

    # Xaridorga buyurtma qabul qilingani va to'lov uchun karta ma'lumotini yuboramiz
    cards = db.get_all_cards(only_active=True)
    if cards:
        card_lines = "\n".join(
            f"💳 <code>{format_card_number(c['card_number'])}</code>"
            + (f" — {c['holder_name']}" if c["holder_name"] else "")
            + (f" ({c['bank_name']})" if c["bank_name"] else "")
            for c in cards
        )
        payment_block = (
            f"\n\n💳 <b>To'lov uchun karta:</b>\n{card_lines}\n\n"
            f"To'lovni amalga oshirgach, chek/screenshot yuboring — operator tekshirib buyurtmani tasdiqlaydi."
        )
    else:
        payment_block = "\n\n⏳ Operator tez orada siz bilan bog'lanib, to'lov tafsilotlarini yuboradi."

    customer_text = (
        f"✅ <b>Buyurtmangiz qabul qilindi!</b> (#{order_id})\n\n"
        f"💵 Yakuniy summa: <b>{final_price:.0f} so'm</b>"
        f"{payment_block}"
    )
    try:
        await bot.send_message(user_id, customer_text)
    except Exception as e:
        logger.warning(f"Xaridorga xabar yuborib bo'lmadi ({user_id}): {e}")

    # Yetkazib berish narxini hisoblash uchun mijozdan manzilini so'raymiz
    try:
        location_kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📍 Manzilni yuborish", request_location=True)],
                [KeyboardButton(text="🏬 O'zim olib ketaman")],
            ],
            resize_keyboard=True,
            one_time_keyboard=True,
        )
        await bot.send_message(
            user_id,
            "🚚 Yetkazib berish narxini hisoblash uchun manzilingizni yuboring "
            "(pastdagi tugma orqali), yoki do'kondan o'zingiz olib keting:",
            reply_markup=location_kb,
        )
        buyer_state = await get_user_fsm_context(user_id)
        await buyer_state.set_state(WaitingDeliveryLocation.order_id)
        await buyer_state.update_data(order_id=order_id)
    except Exception as e:
        logger.warning(f"Manzil so'rovini yuborib bo'lmadi ({user_id}): {e}")

    # Admin(lar)ga xabar matnini tayyorlaymiz
    items_text = "\n".join(
        f"  • {i['name']}"
        + (f" [{i['size']}]" if i["size"] else "")
        + f" — {i['price']:.0f} so'm x {i['qty']}"
        for i in resolved_items
    )
    promo_line = f"\n🏷 Promokod: {promo_code} (-{discount_percent}%)" if promo_code else ""

    admin_text = (
        f"🆕 <b>Yangi buyurtma #{order_id}</b>\n\n"
        f"👤 Foydalanuvchi: <a href='tg://user?id={user_id}'>{user_id}</a>\n"
        f"📞 Telefon: <code>{phone}</code>\n"
        f"🛒 Mahsulotlar:\n{items_text}\n\n"
        f"💵 Umumiy summa: {total_price:.0f} so'm"
        f"{promo_line}\n"
        f"✅ Yakuniy summa: <b>{final_price:.0f} so'm</b>\n\n"
        f"⏳ Holat: kutilmoqda — quyidagi tugmalar orqali tasdiqlang."
    )

    for admin_id in get_all_admin_ids():
        try:
            await bot.send_message(admin_id, admin_text, reply_markup=order_admin_keyboard(order_id))
        except Exception as e:
            logger.warning(f"Adminga xabar yuborib bo'lmadi ({admin_id}): {e}")

    return {
        "order_id": order_id,
        "total_price": total_price,
        "discount_percent": discount_percent,
        "final_price": final_price,
    }


async def apply_order_decision(order_id: int, new_status: str) -> dict:
    """Buyurtma holatini ('confirmed' yoki 'cancelled') yangilaydi va
    xaridorga xabar yuboradi. Ham Telegram tugmasi (callback), ham
    veb admin panel (/api/admin/orders/{id}/confirm|cancel) shu bitta
    funksiyani ishlatadi - shunda ikkala joyda ham xatti-harakat bir xil bo'ladi."""
    order = db.get_order(order_id)
    if not order:
        raise ValueError("order_not_found")
    if order["status"] != "new":
        raise ValueError("already_handled")

    db.update_order_status(order_id, new_status)

    if new_status == "confirmed":
        text = f"✅ Buyurtmangiz <b>#{order_id}</b> tasdiqlandi!\nTez orada operator siz bilan bog'lanadi."
    else:
        text = f"❌ Buyurtmangiz <b>#{order_id}</b> bekor qilindi.\nSavollar bo'lsa, operatorga yozing."

    try:
        await bot.send_message(order["user_id"], text)
    except Exception as e:
        logger.warning(f"Foydalanuvchiga xabar yuborib bo'lmadi ({order['user_id']}): {e}")

    return order


@router.callback_query(F.data.startswith("order_ok:"))
async def adm_confirm_order(callback):
    if not is_admin(callback.from_user.id):
        return await callback.answer("⛔️ Ruxsat yo'q", show_alert=True)

    order_id = int(callback.data.split(":", 1)[1])
    try:
        await apply_order_decision(order_id, "confirmed")
    except ValueError as e:
        msg = "❗️ Buyurtma topilmadi" if str(e) == "order_not_found" else "Bu buyurtma allaqachon ko'rib chiqilgan."
        return await callback.answer(msg, show_alert=True)

    try:
        await callback.message.edit_text(
            callback.message.html_text + f"\n\n✅ <b>TASDIQLANDI</b> — {callback.from_user.full_name}",
            reply_markup=None,
        )
    except Exception:
        pass

    await callback.answer("Tasdiqlandi ✅")


@router.callback_query(F.data.startswith("order_no:"))
async def adm_cancel_order(callback):
    if not is_admin(callback.from_user.id):
        return await callback.answer("⛔️ Ruxsat yo'q", show_alert=True)

    order_id = int(callback.data.split(":", 1)[1])
    try:
        await apply_order_decision(order_id, "cancelled")
    except ValueError as e:
        msg = "❗️ Buyurtma topilmadi" if str(e) == "order_not_found" else "Bu buyurtma allaqachon ko'rib chiqilgan."
        return await callback.answer(msg, show_alert=True)

    try:
        await callback.message.edit_text(
            callback.message.html_text + f"\n\n❌ <b>BEKOR QILINDI</b> — {callback.from_user.full_name}",
            reply_markup=None,
        )
    except Exception:
        pass

    await callback.answer("Bekor qilindi ❌")


# ------------------------------------------------------------------
# HTTP API (aiohttp) - webapp/script.js shu endpointlarga fetch() qiladi
# ------------------------------------------------------------------

routes = web.RouteTableDef()


def cors_headers():
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
    }


@routes.get("/api/products")
async def api_get_products(request: web.Request):
    """WebApp ochilganda script.js shu yerdan mahsulotlar ro'yxatini oladi."""
    products = db.get_all_products(only_active=True)
    return web.json_response(products, headers=cors_headers())


@routes.get("/api/payment-cards")
async def api_get_payment_cards(request: web.Request):
    """WebApp checkout paneli to'lov kartalarini shu yerdan oladi va
    xaridorga xarid qilishdan OLDIN qaysi kartaga pul o'tkazish kerakligini
    ko'rsatadi (bot orqali xabar yuborilishini kutmasdan)."""
    cards = db.get_all_cards(only_active=True)
    result = [
        {
            "card_number": format_card_number(c["card_number"]),
            "holder_name": c["holder_name"],
            "bank_name": c["bank_name"],
        }
        for c in cards
    ]
    return web.json_response(result, headers=cors_headers())


@routes.get("/api/promocode/{code}")
async def api_check_promocode(request: web.Request):
    """script.js promokod kiritilganda shu endpointga so'rov yuboradi
    va chegirma foizini oladi (agar mavjud bo'lsa)."""
    code = request.match_info["code"]
    promo = db.get_promocode(code)
    if promo:
        return web.json_response(
            {"valid": True, "discount_percent": promo["discount_percent"]},
            headers=cors_headers(),
        )
    return web.json_response({"valid": False}, headers=cors_headers())


@routes.post("/api/checkout")
async def api_checkout(request: web.Request):
    """
    'Sotib olish' tugmasi bosilganda script.js shu endpointga
    fetch() orqali POST so'rov yuboradi.

    XAVFSIZLIK: foydalanuvchi ID si HECH QACHON body.user_id dan
    to'g'ridan-to'g'ri olinmaydi (buni istalgan kishi qalbakilashtira
    oladi). Buning o'rniga Telegram WebApp yuborgan `init_data` HMAC
    imzosi tekshiriladi va user_id shu tasdiqlangan ma'lumotdan olinadi.
    """
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "invalid_json"}, status=400, headers=cors_headers())

    validated = validate_init_data(body.get("init_data", ""), BOT_TOKEN)
    if not validated or not validated.get("user") or not validated["user"].get("id"):
        return web.json_response({"ok": False, "error": "auth_failed"}, status=401, headers=cors_headers())

    user_id = int(validated["user"]["id"])

    try:
        result = await process_order(user_id=user_id, order_data=body)
    except ValueError as e:
        error_code = "phone_required" if str(e) == "phone_required" else "empty_cart"
        return web.json_response({"ok": False, "error": error_code}, status=400, headers=cors_headers())

    return web.json_response({"ok": True, **result}, headers=cors_headers())


# ------------------------------------------------------------------
# WEB ADMIN PANEL API (/api/admin/*)
# webapp/admin.html + admin.js shu endpointlarga fetch() qiladi.
# Har bir so'rov "X-Init-Data" headerida Telegram WebApp initData sini
# yuboradi - shu orqali kim so'rov yuborayotgani tasdiqlanadi va
# faqat adminlarga ruxsat beriladi.
# ------------------------------------------------------------------

def require_admin(request: web.Request):
    """Headerdagi initData ni tekshiradi va admin bo'lmasa None qaytaradi.
    Muvaffaqiyatli bo'lsa (user_id, is_super_admin) qaytaradi."""
    init_data = request.headers.get("X-Init-Data", "")
    validated = validate_init_data(init_data, BOT_TOKEN)
    if not validated or not validated.get("user") or not validated["user"].get("id"):
        return None
    user_id = int(validated["user"]["id"])
    if not is_admin(user_id):
        return None
    return user_id, is_super_admin(user_id)


def admin_denied():
    return web.json_response({"ok": False, "error": "forbidden"}, status=403, headers=cors_headers())


@routes.get("/api/admin/check")
async def api_admin_check(request: web.Request):
    auth = require_admin(request)
    if not auth:
        return admin_denied()
    user_id, is_super = auth
    return web.json_response({"ok": True, "user_id": user_id, "is_super_admin": is_super}, headers=cors_headers())


# --- Mahsulotlar ---
@routes.get("/api/admin/products")
async def api_admin_get_products(request: web.Request):
    if not require_admin(request):
        return admin_denied()
    return web.json_response(db.get_all_products(only_active=False), headers=cors_headers())


@routes.post("/api/admin/products")
async def api_admin_add_product(request: web.Request):
    if not require_admin(request):
        return admin_denied()
    try:
        body = await request.json()
        name = str(body["name"]).strip()
        price = float(body["price"])
    except Exception:
        return web.json_response({"ok": False, "error": "invalid_data"}, status=400, headers=cors_headers())
    if not name or price <= 0:
        return web.json_response({"ok": False, "error": "invalid_data"}, status=400, headers=cors_headers())

    description = str(body.get("description", ""))
    photo_url = str(body.get("photo_url", ""))
    sizes = str(body.get("sizes", ""))
    product_id = db.add_product(name, price, description, photo_url, sizes)
    return web.json_response({"ok": True, "id": product_id}, headers=cors_headers())


@routes.patch("/api/admin/products/{id}")
async def api_admin_update_product_price(request: web.Request):
    if not require_admin(request):
        return admin_denied()
    try:
        product_id = int(request.match_info["id"])
        body = await request.json()
        new_price = float(body["price"])
    except Exception:
        return web.json_response({"ok": False, "error": "invalid_data"}, status=400, headers=cors_headers())
    if new_price <= 0:
        return web.json_response({"ok": False, "error": "invalid_data"}, status=400, headers=cors_headers())

    ok = db.update_product_price(product_id, new_price)
    return web.json_response({"ok": ok}, headers=cors_headers())


@routes.delete("/api/admin/products/{id}")
async def api_admin_delete_product(request: web.Request):
    if not require_admin(request):
        return admin_denied()
    product_id = int(request.match_info["id"])
    ok = db.delete_product(product_id)
    return web.json_response({"ok": ok}, headers=cors_headers())


# --- Promokodlar ---
@routes.get("/api/admin/promocodes")
async def api_admin_get_promocodes(request: web.Request):
    if not require_admin(request):
        return admin_denied()
    return web.json_response(db.get_all_promocodes(), headers=cors_headers())


@routes.post("/api/admin/promocodes")
async def api_admin_add_promocode(request: web.Request):
    if not require_admin(request):
        return admin_denied()
    try:
        body = await request.json()
        code = str(body["code"]).strip().upper()
        discount_percent = int(body["discount_percent"])
    except Exception:
        return web.json_response({"ok": False, "error": "invalid_data"}, status=400, headers=cors_headers())
    if not code or not (0 < discount_percent <= 100):
        return web.json_response({"ok": False, "error": "invalid_data"}, status=400, headers=cors_headers())

    ok = db.add_promocode(code, discount_percent)
    if not ok:
        return web.json_response({"ok": False, "error": "already_exists"}, status=400, headers=cors_headers())
    return web.json_response({"ok": True}, headers=cors_headers())


@routes.delete("/api/admin/promocodes/{code}")
async def api_admin_delete_promocode(request: web.Request):
    if not require_admin(request):
        return admin_denied()
    code = request.match_info["code"].strip().upper()
    ok = db.delete_promocode(code)
    return web.json_response({"ok": ok}, headers=cors_headers())


# --- To'lov kartalari ---
@routes.get("/api/admin/cards")
async def api_admin_get_cards(request: web.Request):
    if not require_admin(request):
        return admin_denied()
    cards = db.get_all_cards(only_active=False)
    for c in cards:
        c["card_number_display"] = format_card_number(c["card_number"])
    return web.json_response(cards, headers=cors_headers())


@routes.post("/api/admin/cards")
async def api_admin_add_card(request: web.Request):
    auth = require_admin(request)
    if not auth:
        return admin_denied()
    user_id, _ = auth
    try:
        body = await request.json()
        card_number = str(body["card_number"])
        holder_name = str(body.get("holder_name", ""))
        bank_name = str(body.get("bank_name", ""))
    except Exception:
        return web.json_response({"ok": False, "error": "invalid_data"}, status=400, headers=cors_headers())

    digits = "".join(ch for ch in card_number if ch.isdigit())
    if len(digits) < 12:
        return web.json_response({"ok": False, "error": "invalid_card_number"}, status=400, headers=cors_headers())

    card_id = db.add_card(card_number, holder_name, bank_name, user_id)
    return web.json_response({"ok": True, "id": card_id}, headers=cors_headers())


@routes.delete("/api/admin/cards/{id}")
async def api_admin_delete_card(request: web.Request):
    if not require_admin(request):
        return admin_denied()
    card_id = int(request.match_info["id"])
    ok = db.delete_card(card_id)
    return web.json_response({"ok": ok}, headers=cors_headers())


# --- Buyurtmalar ---
@routes.get("/api/admin/orders")
async def api_admin_get_orders(request: web.Request):
    if not require_admin(request):
        return admin_denied()
    limit = int(request.query.get("limit", 50))
    orders = db.get_all_orders(limit=limit)
    for o in orders:
        try:
            o["items"] = json.loads(o["items_json"])
        except Exception:
            o["items"] = []
    return web.json_response(orders, headers=cors_headers())


@routes.post("/api/admin/orders/{id}/confirm")
async def api_admin_confirm_order(request: web.Request):
    if not require_admin(request):
        return admin_denied()
    order_id = int(request.match_info["id"])
    try:
        await apply_order_decision(order_id, "confirmed")
    except ValueError as e:
        return web.json_response({"ok": False, "error": str(e)}, status=400, headers=cors_headers())
    return web.json_response({"ok": True}, headers=cors_headers())


@routes.post("/api/admin/orders/{id}/cancel")
async def api_admin_cancel_order(request: web.Request):
    if not require_admin(request):
        return admin_denied()
    order_id = int(request.match_info["id"])
    try:
        await apply_order_decision(order_id, "cancelled")
    except ValueError as e:
        return web.json_response({"ok": False, "error": str(e)}, status=400, headers=cors_headers())
    return web.json_response({"ok": True}, headers=cors_headers())


# --- Yetkazib berish sozlamalari ---
@routes.get("/api/admin/delivery")
async def api_admin_get_delivery(request: web.Request):
    if not require_admin(request):
        return admin_denied()
    return web.json_response({
        "shop_lat": db.get_setting("shop_lat"),
        "shop_lon": db.get_setting("shop_lon"),
        "price_per_km": float(db.get_setting("price_per_km", DEFAULT_PRICE_PER_KM)),
        "base_delivery_fee": float(db.get_setting("base_delivery_fee", DEFAULT_BASE_DELIVERY_FEE)),
    }, headers=cors_headers())


@routes.post("/api/admin/delivery")
async def api_admin_set_delivery(request: web.Request):
    if not require_admin(request):
        return admin_denied()
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "invalid_data"}, status=400, headers=cors_headers())

    if "price_per_km" in body:
        db.set_setting("price_per_km", float(body["price_per_km"]))
    if "base_delivery_fee" in body:
        db.set_setting("base_delivery_fee", float(body["base_delivery_fee"]))
    if "shop_lat" in body and "shop_lon" in body:
        db.set_setting("shop_lat", float(body["shop_lat"]))
        db.set_setting("shop_lon", float(body["shop_lon"]))
    return web.json_response({"ok": True}, headers=cors_headers())


# --- Adminlar (faqat bosh adminlar boshqara oladi) ---
@routes.get("/api/admin/admins")
async def api_admin_get_admins(request: web.Request):
    if not require_admin(request):
        return admin_denied()
    return web.json_response({
        "super_admin_ids": SUPER_ADMIN_IDS,
        "admins": db.get_all_admins(),
    }, headers=cors_headers())


@routes.post("/api/admin/admins")
async def api_admin_add_admin(request: web.Request):
    auth = require_admin(request)
    if not auth:
        return admin_denied()
    user_id, is_super = auth
    if not is_super:
        return admin_denied()
    try:
        body = await request.json()
        new_admin_id = int(body["user_id"])
    except Exception:
        return web.json_response({"ok": False, "error": "invalid_data"}, status=400, headers=cors_headers())

    ok = db.add_admin(new_admin_id, "", user_id)
    return web.json_response({"ok": ok}, headers=cors_headers())


@routes.delete("/api/admin/admins/{user_id}")
async def api_admin_remove_admin(request: web.Request):
    auth = require_admin(request)
    if not auth:
        return admin_denied()
    _, is_super = auth
    if not is_super:
        return admin_denied()
    target_id = int(request.match_info["user_id"])
    if target_id in SUPER_ADMIN_IDS:
        return web.json_response({"ok": False, "error": "cannot_remove_super_admin"}, status=400, headers=cors_headers())
    ok = db.remove_admin(target_id)
    return web.json_response({"ok": ok}, headers=cors_headers())


@routes.options("/{tail:.*}")
async def api_options(request: web.Request):
    """Brauzerning CORS preflight (OPTIONS) so'rovlariga javob."""
    return web.Response(headers=cors_headers())


def build_web_app() -> web.Application:
    app = web.Application()
    app.add_routes(routes)
    # webapp/index.html, script.js va boshqa statik fayllarni /app manzilidan xizmat qilamiz
    app.router.add_static("/app", path=str(WEBAPP_DIR), show_index=True)
    return app


# ------------------------------------------------------------------
# ISHGA TUSHIRISH: bot polling + HTTP server bir vaqtda ishlaydi
# ------------------------------------------------------------------

async def start_http_server():
    app = build_web_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, HTTP_HOST, HTTP_PORT)
    await site.start()
    logger.info(f"HTTP server ishga tushdi: http://{HTTP_HOST}:{HTTP_PORT}/app")


async def main():
    db.init_db()
    await start_http_server()
    logger.info("Bot polling boshlandi...")
    await bot.delete_webhook(drop_pending_updates=True)
await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
