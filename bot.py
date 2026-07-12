"""
bot.py
-----------------------------------------------------------------
Asosiy bot fayli. Polling rejimida ishlaydi -- hech qanday
webhook, HTTPS yoki domen kerak emas. Shunchaki shu skriptni
ishga tushirib qo'yasiz:

    python bot.py

Bot doimiy ishlab turishi uchun serverda uni background jarayon
sifatida ishga tushiring (masalan systemd, screen yoki tmux orqali).
-----------------------------------------------------------------
"""

import logging

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import database as db
from config import BOT_TOKEN, BOT_USERNAME, MAIN_ADMIN_CHAT_ID, REFERRAL_BONUS

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)


# =======================================================================
# Ko'p til qo'llab-quvvatlash (o'zbek / rus / ingliz)
# Faqat asosiy foydalanuvchi oqimi tarjima qilingan; admin panel doim
# o'zbek tilida qoladi (chunki adminlar o'zgarmaydi).
# =======================================================================
TEXTS = {
    "choose_language": {
        "uz": "Tilni tanlang / Выберите язык / Choose language:",
        "ru": "Tilni tanlang / Выберите язык / Choose language:",
        "en": "Tilni tanlang / Выберите язык / Choose language:",
    },
    "welcome_new": {
        "uz": "Assalomu alaykum! Botimizga xush kelibsiz. 🙌\n\nRo'yxatdan o'tish uchun avval to'liq ismingizni yozib yuboring:",
        "ru": "Здравствуйте! Добро пожаловать в наш бот. 🙌\n\nДля регистрации напишите, пожалуйста, ваше полное имя:",
        "en": "Hello! Welcome to our bot. 🙌\n\nTo register, please send your full name:",
    },
    "ask_name_invalid": {
        "uz": "Iltimos, to'g'ri ism kiriting (kamida 2 ta harf):",
        "ru": "Пожалуйста, введите корректное имя (минимум 2 буквы):",
        "en": "Please enter a valid name (at least 2 letters):",
    },
    "ask_phone": {
        "uz": "Rahmat, {name}! Endi telefon raqamingizni pastdagi tugma orqali yuboring:",
        "ru": "Спасибо, {name}! Теперь отправьте свой номер телефона через кнопку ниже:",
        "en": "Thanks, {name}! Now send your phone number using the button below:",
    },
    "phone_button": {
        "uz": "📱 Raqamni yuborish",
        "ru": "📱 Отправить номер",
        "en": "📱 Send phone number",
    },
    "registered_welcome": {
        "uz": "🎉 Ro'yxatdan muvaffaqiyatli o'tdingiz!\n\nQuyidagi bo'limlardan birini tanlang:",
        "ru": "🎉 Вы успешно зарегистрированы!\n\nВыберите один из разделов ниже:",
        "en": "🎉 You have registered successfully!\n\nChoose one of the sections below:",
    },
    "welcome_back": {
        "uz": "Xush kelibsiz, {name}! 👋\n\nQuyidagi bo'limlardan birini tanlang:",
        "ru": "Добро пожаловать, {name}! 👋\n\nВыберите один из разделов ниже:",
        "en": "Welcome back, {name}! 👋\n\nChoose one of the sections below:",
    },
    "main_menu_prompt": {
        "uz": "Quyidagi bo'limlardan birini tanlang 👇",
        "ru": "Выберите один из разделов ниже 👇",
        "en": "Choose one of the sections below 👇",
    },
    "btn_payment": {"uz": "💰 To'lov", "ru": "💰 Оплата", "en": "💰 Payment"},
    "btn_wallet": {"uz": "💼 Hamyon", "ru": "💼 Кошелёк", "en": "💼 Wallet"},
    "btn_support": {"uz": "🎧 Support", "ru": "🎧 Поддержка", "en": "🎧 Support"},
    "btn_promo": {"uz": "🎟 Promo kod", "ru": "🎟 Промокод", "en": "🎟 Promo code"},
    "btn_premium": {"uz": "⭐ Premium & Stars", "ru": "⭐ Premium и Stars", "en": "⭐ Premium & Stars"},
    "btn_cargo": {"uz": "📦 Yuk kuzatish", "ru": "📦 Отследить груз", "en": "📦 Track cargo"},
    "btn_referral": {"uz": "🎁 Referal", "ru": "🎁 Реферал", "en": "🎁 Referral"},
    "btn_orders": {"uz": "📜 Buyurtmalarim", "ru": "📜 Мои заказы", "en": "📜 My orders"},
    "btn_language": {"uz": "🌐 Til", "ru": "🌐 Язык", "en": "🌐 Language"},
    "wallet_text": {
        "uz": "💼 Hamyoningiz\n\nJoriy balans: {balance} so'm\n\nBalansni to'ldirish uchun \"🎟 Promo kod\" yoki \"🎁 Referal\" bo'limidan foydalaning.",
        "ru": "💼 Ваш кошелёк\n\nТекущий баланс: {balance} сум\n\nЧтобы пополнить баланс, используйте раздел «🎟 Промокод» или «🎁 Реферал».",
        "en": "💼 Your wallet\n\nCurrent balance: {balance} UZS\n\nTo top up, use \"🎟 Promo code\" or \"🎁 Referral\".",
    },
    "promo_prompt": {
        "uz": "Promo kodni kiriting: 🎟",
        "ru": "Введите промокод: 🎟",
        "en": "Enter the promo code: 🎟",
    },
    "promo_invalid": {
        "uz": "❌ Bunday promo kod topilmadi yoki u faol emas.",
        "ru": "❌ Такой промокод не найден или он неактивен.",
        "en": "❌ This promo code was not found or is inactive.",
    },
    "promo_used": {
        "uz": "⚠️ Siz bu promo koddan avval foydalangansiz.",
        "ru": "⚠️ Вы уже использовали этот промокод.",
        "en": "⚠️ You have already used this promo code.",
    },
    "promo_success": {
        "uz": "✅ Promo kod muvaffaqiyatli qo'llanildi!\n💰 Balansingizga {amount} so'm qo'shildi.\n\nJoriy balans: {balance} so'm",
        "ru": "✅ Промокод успешно применён!\n💰 На ваш баланс зачислено {amount} сум.\n\nТекущий баланс: {balance} сум",
        "en": "✅ Promo code applied successfully!\n💰 {amount} UZS added to your balance.\n\nCurrent balance: {balance} UZS",
    },
    "cancel_text": {
        "uz": "❌ Amal bekor qilindi.",
        "ru": "❌ Действие отменено.",
        "en": "❌ Action cancelled.",
    },
    "referral_text": {
        "uz": "🎁 Do'stlaringizni taklif qiling!\n\nHar bir taklif qilingan do'stingiz ro'yxatdan o'tsa, hamyoningizga {bonus} so'm qo'shiladi.\n\n🔗 Sizning havolangiz:\n{link}\n\n👥 Taklif qilingan do'stlar: {count}",
        "ru": "🎁 Приглашайте друзей!\n\nЗа каждого друга, который зарегистрируется по вашей ссылке, на ваш кошелёк начислится {bonus} сум.\n\n🔗 Ваша ссылка:\n{link}\n\n👥 Приглашено друзей: {count}",
        "en": "🎁 Invite your friends!\n\nFor every friend who registers using your link, {bonus} UZS will be added to your wallet.\n\n🔗 Your link:\n{link}\n\n👥 Friends invited: {count}",
    },
    "referral_bonus_notice": {
        "uz": "🎉 Sizning havolangiz orqali yangi do'stingiz ro'yxatdan o'tdi!\n💰 Hamyoningizga {bonus} so'm qo'shildi.",
        "ru": "🎉 По вашей ссылке зарегистрировался новый друг!\n💰 На ваш кошелёк начислено {bonus} сум.",
        "en": "🎉 A new friend registered using your link!\n💰 {bonus} UZS added to your wallet.",
    },
    "orders_header": {
        "uz": "📜 Sizning buyurtmalaringiz:",
        "ru": "📜 Ваши заказы:",
        "en": "📜 Your orders:",
    },
    "orders_empty": {
        "uz": "Sizda hali birorta ham buyurtma yo'q.",
        "ru": "У вас пока нет заказов.",
        "en": "You don't have any orders yet.",
    },
    "language_changed": {
        "uz": "✅ Til o'zbekchaga o'zgartirildi.",
        "ru": "✅ Язык изменён на русский.",
        "en": "✅ Language changed to English.",
    },
}


def t(lang: str, key: str, **kwargs) -> str:
    lang = lang if lang in ("uz", "ru", "en") else "uz"
    template = TEXTS.get(key, {}).get(lang) or TEXTS.get(key, {}).get("uz", key)
    return template.format(**kwargs) if kwargs else template


# =======================================================================
# Umumiy klaviaturalar
# =======================================================================
def main_menu_keyboard(lang: str = "uz") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t(lang, "btn_payment"), callback_data="menu_payment")],
            [InlineKeyboardButton(t(lang, "btn_wallet"), callback_data="menu_wallet")],
            [InlineKeyboardButton(t(lang, "btn_support"), callback_data="menu_support")],
            [InlineKeyboardButton(t(lang, "btn_promo"), callback_data="menu_promo")],
            [InlineKeyboardButton(t(lang, "btn_premium"), callback_data="menu_premium")],
            [InlineKeyboardButton(t(lang, "btn_cargo"), callback_data="menu_cargo")],
            [InlineKeyboardButton(t(lang, "btn_referral"), callback_data="menu_referral")],
            [InlineKeyboardButton(t(lang, "btn_orders"), callback_data="menu_orders")],
            [InlineKeyboardButton(t(lang, "btn_language"), callback_data="menu_language")],
        ]
    )


def language_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🇺🇿 O'zbekcha", callback_data="lang_uz"),
                InlineKeyboardButton("🇷🇺 Русский", callback_data="lang_ru"),
                InlineKeyboardButton("🇬🇧 English", callback_data="lang_en"),
            ]
        ]
    )


CARGO_STATUSES = {
    "accepted": "✅ Qabul qilindi",
    "shipped": "🚚 Yo'lga chiqdi",
    "in_transit": "📍 Yo'lda",
    "delivered": "📦 Yetkazib berildi",
}

CARGO_STATUS_MESSAGES = {
    "accepted": "✅ Yukingiz qabul qilindi!\n\nTez orada yo'lga chiqariladi.",
    "shipped": "🚚 Yukingiz yo'lga chiqdi!\n\nYaqin orada manzilingizga yetib boradi.",
    "in_transit": "📍 Yukingiz hozir yo'lda!",
    "delivered": "📦 Yukingiz yetkazib berildi! ✅\n\nXaridingiz uchun rahmat! 🙏",
}


def cargo_admin_keyboard(shipment_id: int, current_status: str) -> InlineKeyboardMarkup:
    rows = []
    for status_key, label in CARGO_STATUSES.items():
        prefix = "🔘 " if status_key == current_status else ""
        rows.append(
            [InlineKeyboardButton(f"{prefix}{label}", callback_data=f"cargo_status_{shipment_id}_{status_key}")]
        )
    return InlineKeyboardMarkup(rows)


def premium_category_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("💎 Telegram Premium", callback_data="premium_cat_premium")],
            [InlineKeyboardButton("⭐ Telegram Stars", callback_data="premium_cat_stars")],
            [InlineKeyboardButton("« Orqaga", callback_data="menu_back")],
        ]
    )


def product_list_keyboard(products, category: str) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                f"{p['label']} — {p['price']:,.0f} so'm".replace(",", " "),
                callback_data=f"buy_product_{p['key']}",
            )
        ]
        for p in products
    ]
    rows.append([InlineKeyboardButton("« Orqaga", callback_data="menu_premium")])
    return InlineKeyboardMarkup(rows)


def admin_panel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("📢 Barchaga xabar yuborish", callback_data="admin_broadcast")]]
    )


def contact_request_keyboard(label: str = "📱 Raqamni yuborish") -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton(label, request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def payment_admin_keyboard(payment_id: int, user_chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"approve_payment_{payment_id}"),
                InlineKeyboardButton("❌ Rad etish", callback_data=f"reject_payment_{payment_id}"),
            ],
            [
                InlineKeyboardButton("✉️ Xabar yozish", callback_data=f"message_user_{user_chat_id}"),
            ],
        ]
    )


# =======================================================================
# /start -- ro'yxatdan o'tish YOKI admin panel
# =======================================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    username = update.effective_user.username

    # Adminlar (asosiy yoki yordamchi) uchun ro'yxatdan o'tish so'ralmaydi
    if db.is_admin(chat_id):
        await update.message.reply_text(
            "🛠 Admin panelga xush kelibsiz.\n\n"
            "Buyruqlar:\n"
            "/addpromo KOD SUMMA -- promo kod qo'shish\n"
            "/balance CHAT_ID -- foydalanuvchi hamyonini ko'rish\n"
            "/addbalance CHAT_ID SUMMA -- hamyonga to'g'ridan-to'g'ri pul qo'shish\n"
            "/removebalance CHAT_ID SUMMA -- hamyondan pul ayirish\n"
            "/addpremium KEY NARX NOM -- Premium tarif qo'shish\n"
            "/addstars KEY NARX NOM -- Stars paketi qo'shish\n"
            "/removeproduct KEY -- mahsulotni o'chirish\n"
            "/products -- barcha mahsulotlar ro'yxati\n"
            "/addshipment CHAT_ID KOD TAVSIF -- yangi yuk yaratish\n"
            "/cargo KOD -- yuk holatini boshqarish panelini ochish\n"
            "/admins -- adminlar ro'yxati\n"
            + ("/addadmin CHAT_ID -- yordamchi admin qo'shish\n"
               "/removeadmin CHAT_ID -- adminlikdan olib tashlash\n"
               if chat_id == MAIN_ADMIN_CHAT_ID else ""),
            reply_markup=admin_panel_keyboard(),
        )
        return

    user = db.create_user_if_not_exists(chat_id, username)
    lang = db.get_language(chat_id)

    if user["is_registered"] == 1:
        await update.message.reply_text(
            t(lang, "welcome_back", name=user["full_name"]),
            reply_markup=main_menu_keyboard(lang),
        )
        return

    # Referal havolasi orqali kelganmi? (masalan /start ref123456)
    if context.args and context.args[0].startswith("ref") and user["referred_by"] is None:
        try:
            referrer_id = int(context.args[0][3:])
            db.set_referrer(chat_id, referrer_id)
        except ValueError:
            pass

    # Yangi foydalanuvchi -- avval tilni tanlaydi
    await update.message.reply_text(t(lang, "choose_language"), reply_markup=language_keyboard())


async def handle_language_selected(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int, lang: str) -> None:
    db.set_language(chat_id, lang)
    db.set_state(chat_id, "waiting_name")
    await context.bot.send_message(
        chat_id=chat_id, text=t(lang, "welcome_new"), reply_markup=ReplyKeyboardRemove()
    )


# =======================================================================
# /addpromo KOD SUMMA -- istalgan admin ishlata oladi
# =======================================================================
async def addpromo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id

    if not db.is_admin(chat_id):
        await update.message.reply_text("Bu buyruq faqat admin uchun.")
        return

    args = context.args
    if len(args) != 2:
        await update.message.reply_text(
            "Noto'g'ri format. To'g'ri format:\n/addpromo KOD SUMMA\n\nMisol: /addpromo YANGIYIL2026 50000"
        )
        return

    code, amount_str = args
    code = code.upper()

    try:
        amount = float(amount_str)
    except ValueError:
        await update.message.reply_text("Summa raqam bo'lishi kerak.")
        return

    if amount <= 0:
        await update.message.reply_text("Summa musbat son bo'lishi kerak.")
        return

    db.upsert_promo_code(code, amount)
    await update.message.reply_text(
        f"✅ Promo kod saqlandi:\nKod: {code}\nSumma: {amount:,.0f} so'm".replace(",", " ")
    )


# =======================================================================
# /addadmin, /removeadmin, /admins -- faqat ASOSIY admin qo'sha/o'chira oladi
# =======================================================================
async def addadmin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id

    if chat_id != MAIN_ADMIN_CHAT_ID:
        await update.message.reply_text("Bu buyruq faqat asosiy admin uchun.")
        return

    if len(context.args) != 1 or not context.args[0].lstrip("-").isdigit():
        await update.message.reply_text(
            "To'g'ri format:\n/addadmin CHAT_ID\n\nMisol: /addadmin 123456789\n\n"
            "Chat ID'ni bilish uchun o'sha odam @userinfobot'ga yozishi kerak."
        )
        return

    new_admin_id = int(context.args[0])
    db.add_admin(new_admin_id, added_by=chat_id)

    await update.message.reply_text(f"✅ {new_admin_id} endi yordamchi admin.")

    try:
        await context.bot.send_message(
            chat_id=new_admin_id,
            text="🛠 Sizga admin huquqi berildi! Admin panelni ochish uchun /start bosing.",
        )
    except Exception:
        await update.message.reply_text(
            "⚠️ Diqqat: bu foydalanuvchiga xabar yubora olmadim -- u botga hali /start bosmagan bo'lishi mumkin."
        )


async def removeadmin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id

    if chat_id != MAIN_ADMIN_CHAT_ID:
        await update.message.reply_text("Bu buyruq faqat asosiy admin uchun.")
        return

    if len(context.args) != 1 or not context.args[0].lstrip("-").isdigit():
        await update.message.reply_text("To'g'ri format:\n/removeadmin CHAT_ID")
        return

    target_id = int(context.args[0])
    db.remove_admin(target_id)
    await update.message.reply_text(f"✅ {target_id} adminlikdan olib tashlandi.")


async def list_admins(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id

    if not db.is_admin(chat_id):
        await update.message.reply_text("Bu buyruq faqat admin uchun.")
        return

    helper_ids = db.get_helper_admin_ids()
    text = f"👑 Asosiy admin: {MAIN_ADMIN_CHAT_ID}\n"
    if helper_ids:
        text += "\n🛠 Yordamchi adminlar:\n" + "\n".join(f"- {aid}" for aid in helper_ids)
    else:
        text += "\nYordamchi adminlar yo'q."

    await update.message.reply_text(text)


async def check_balance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id

    if not db.is_admin(chat_id):
        await update.message.reply_text("Bu buyruq faqat admin uchun.")
        return

    if len(context.args) != 1 or not context.args[0].lstrip("-").isdigit():
        await update.message.reply_text("To'g'ri format:\n/balance CHAT_ID")
        return

    target_id = int(context.args[0])
    user = db.get_user(target_id)

    if user is None:
        await update.message.reply_text("Bunday foydalanuvchi topilmadi.")
        return

    await update.message.reply_text(
        f"👤 {user['full_name'] or '-'} (@{user['username'] or '-'})\n"
        f"🆔 Chat ID: {target_id}\n"
        f"💼 Balans: {user['balance']:,.0f} so'm".replace(",", " ")
    )


async def add_balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id

    if not db.is_admin(chat_id):
        await update.message.reply_text("Bu buyruq faqat admin uchun.")
        return

    if len(context.args) != 2 or not context.args[0].lstrip("-").isdigit():
        await update.message.reply_text(
            "To'g'ri format:\n/addbalance CHAT_ID SUMMA\n\nMisol: /addbalance 123456789 20000"
        )
        return

    target_id = int(context.args[0])

    try:
        amount = float(context.args[1])
    except ValueError:
        await update.message.reply_text("Summa raqam bo'lishi kerak.")
        return

    user = db.get_user(target_id)
    if user is None:
        await update.message.reply_text("Bunday foydalanuvchi topilmadi (u hali botga /start bosmagan).")
        return

    db.add_balance(target_id, amount)
    new_balance = db.get_balance(target_id)

    await update.message.reply_text(
        f"✅ {amount:,.0f} so'm qo'shildi.\nYangi balans: {new_balance:,.0f} so'm".replace(",", " ")
    )

    try:
        await context.bot.send_message(
            chat_id=target_id,
            text=(
                f"💼 Hamyoningizga {amount:,.0f} so'm qo'shildi.\n"
                f"Joriy balans: {new_balance:,.0f} so'm"
            ).replace(",", " "),
        )
    except Exception as e:
        logger.warning("Foydalanuvchiga (%s) balans haqida xabar yuborilmadi: %s", target_id, e)


def _parse_add_product_args(args: list[str]) -> tuple[str, float, str] | None:
    """/addpremium KEY NARX NOM... ni ajratib beradi. NOM bo'sh joyli bo'lishi mumkin."""
    if len(args) < 3:
        return None
    key = args[0]
    try:
        price = float(args[1])
    except ValueError:
        return None
    label = " ".join(args[2:])
    return key, price, label


async def add_premium_product(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not db.is_admin(chat_id):
        await update.message.reply_text("Bu buyruq faqat admin uchun.")
        return

    parsed = _parse_add_product_args(context.args)
    if parsed is None:
        await update.message.reply_text(
            "To'g'ri format:\n/addpremium KEY NARX NOM\n\nMisol: /addpremium premium_3m 89000 Telegram Premium 3 oy"
        )
        return

    key, price, label = parsed
    db.upsert_product(key, "premium", label, price)
    await update.message.reply_text(f"✅ Qo'shildi: {label} — {price:,.0f} so'm".replace(",", " "))


async def add_stars_product(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not db.is_admin(chat_id):
        await update.message.reply_text("Bu buyruq faqat admin uchun.")
        return

    parsed = _parse_add_product_args(context.args)
    if parsed is None:
        await update.message.reply_text(
            "To'g'ri format:\n/addstars KEY NARX NOM\n\nMisol: /addstars stars_100 15000 100 ta Stars"
        )
        return

    key, price, label = parsed
    db.upsert_product(key, "stars", label, price)
    await update.message.reply_text(f"✅ Qo'shildi: {label} — {price:,.0f} so'm".replace(",", " "))


async def remove_product(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not db.is_admin(chat_id):
        await update.message.reply_text("Bu buyruq faqat admin uchun.")
        return

    if len(context.args) != 1:
        await update.message.reply_text("To'g'ri format:\n/removeproduct KEY")
        return

    removed = db.deactivate_product(context.args[0])
    await update.message.reply_text("✅ O'chirildi." if removed else "Bunday KEY topilmadi.")


async def list_products(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not db.is_admin(chat_id):
        await update.message.reply_text("Bu buyruq faqat admin uchun.")
        return

    products = db.get_all_products()
    if not products:
        await update.message.reply_text("Hozircha hech qanday mahsulot qo'shilmagan.")
        return

    lines = ["📦 Faol mahsulotlar:\n"]
    for p in products:
        cat_label = "💎 Premium" if p["category"] == "premium" else "⭐ Stars"
        lines.append(f"{cat_label} | {p['key']} | {p['label']} — {p['price']:,.0f} so'm".replace(",", " "))

    await update.message.reply_text("\n".join(lines))


async def add_shipment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not db.is_admin(chat_id):
        await update.message.reply_text("Bu buyruq faqat admin uchun.")
        return

    if len(context.args) < 3 or not context.args[0].lstrip("-").isdigit():
        await update.message.reply_text(
            "To'g'ri format:\n/addshipment CHAT_ID KOD TAVSIF\n\n"
            "Misol: /addshipment 123456789 UZ12345 iPhone 15 Pro Max"
        )
        return

    target_id = int(context.args[0])
    tracking_code = context.args[1].upper()
    description = " ".join(context.args[2:])

    user = db.get_user(target_id)
    if user is None:
        await update.message.reply_text("Bunday foydalanuvchi topilmadi (u hali botga /start bosmagan).")
        return

    shipment_id = db.create_shipment(tracking_code, target_id, description)
    if shipment_id is None:
        await update.message.reply_text(f"❌ '{tracking_code}' kodi allaqachon band. Boshqa kod tanlang.")
        return

    await update.message.reply_text(
        f"✅ Yuk yaratildi!\n\n📦 Kod: {tracking_code}\n📝 Tavsif: {description}\n\n"
        "Statusni boshqarish uchun pastdagi tugmalardan foydalaning:",
        reply_markup=cargo_admin_keyboard(shipment_id, "accepted"),
    )

    try:
        await context.bot.send_message(
            chat_id=target_id,
            text=(
                f"📦 Sizga yangi yuk biriktirildi!\n\n"
                f"🔖 Kuzatuv kodi: {tracking_code}\n"
                f"📝 Tavsif: {description}\n"
                f"📍 Holat: {CARGO_STATUSES['accepted']}\n\n"
                "Holatni istalgan vaqtda \"📦 Yuk kuzatish\" bo'limidan tekshirib turishingiz mumkin."
            ),
        )
    except Exception as e:
        logger.warning("Foydalanuvchiga (%s) yuk haqida xabar yuborilmadi: %s", target_id, e)


async def open_cargo_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not db.is_admin(chat_id):
        await update.message.reply_text("Bu buyruq faqat admin uchun.")
        return

    if len(context.args) != 1:
        await update.message.reply_text("To'g'ri format:\n/cargo KOD")
        return

    shipment = db.get_shipment_by_code(context.args[0].upper())
    if shipment is None:
        await update.message.reply_text("Bunday kuzatuv kodi topilmadi.")
        return

    await update.message.reply_text(
        f"📦 Kod: {shipment['tracking_code']}\n"
        f"📝 Tavsif: {shipment['description']}\n"
        f"🆔 Mijoz: {shipment['user_chat_id']}\n"
        f"📍 Joriy holat: {CARGO_STATUSES.get(shipment['status'], shipment['status'])}\n\n"
        "Statusni yangilash uchun tugmani bosing:",
        reply_markup=cargo_admin_keyboard(shipment["id"], shipment["status"]),
    )


async def remove_balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id

    if not db.is_admin(chat_id):
        await update.message.reply_text("Bu buyruq faqat admin uchun.")
        return

    if len(context.args) != 2 or not context.args[0].lstrip("-").isdigit():
        await update.message.reply_text(
            "To'g'ri format:\n/removebalance CHAT_ID SUMMA\n\nMisol: /removebalance 123456789 20000"
        )
        return

    target_id = int(context.args[0])

    try:
        amount = float(context.args[1])
    except ValueError:
        await update.message.reply_text("Summa raqam bo'lishi kerak.")
        return

    if amount <= 0:
        await update.message.reply_text("Summa musbat son bo'lishi kerak.")
        return

    user = db.get_user(target_id)
    if user is None:
        await update.message.reply_text("Bunday foydalanuvchi topilmadi.")
        return

    db.add_balance(target_id, -amount)
    new_balance = db.get_balance(target_id)

    await update.message.reply_text(
        f"✅ {amount:,.0f} so'm ayirildi.\nYangi balans: {new_balance:,.0f} so'm".replace(",", " ")
    )

    try:
        await context.bot.send_message(
            chat_id=target_id,
            text=(
                f"💼 Hamyoningizdan {amount:,.0f} so'm ayirildi.\n"
                f"Joriy balans: {new_balance:,.0f} so'm"
            ).replace(",", " "),
        )
    except Exception as e:
        logger.warning("Foydalanuvchiga (%s) balans haqida xabar yuborilmadi: %s", target_id, e)


# =======================================================================
# Barcha oddiy xabarlar (matn / kontakt / rasm) -- state-machine
# =======================================================================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat_id = update.effective_chat.id

    # ---------------------------------------------------------
    # 0) Admin support xabariga "Reply" qildimi?
    # ---------------------------------------------------------
    if db.is_admin(chat_id) and message.reply_to_message is not None:
        handled = await handle_admin_support_reply(update, context)
        if handled:
            return

    # ---------------------------------------------------------
    # 0.5) Admin "Barchaga xabar yuborish" tugmasidan keyin matn yozdimi?
    # ---------------------------------------------------------
    if db.is_admin(chat_id):
        admin_user = db.create_user_if_not_exists(chat_id, update.effective_user.username)
        state = admin_user["state"] or ""

        if state.startswith("waiting_direct_message:"):
            target_chat_id = int(state.split(":", 1)[1])
            await handle_direct_message(update, context, target_chat_id)
            return

        if state == "waiting_broadcast_message":
            await handle_broadcast_message(update, context)
            return

    user = db.create_user_if_not_exists(chat_id, update.effective_user.username)

    # Adminlar oddiy ro'yxatdan o'tish oqimiga tushmaydi
    if db.is_admin(chat_id):
        return

    state = user["state"]

    # ---------------------------------------------------------
    # 1) Ro'yxatdan o'tish bosqichlari
    # ---------------------------------------------------------
    if state == "waiting_name":
        await handle_waiting_name(update, context)
        return

    if state == "waiting_phone":
        await handle_waiting_phone(update, context)
        return

    if not db.is_registered(chat_id):
        await message.reply_text("Iltimos, avval ro'yxatdan o'ting: /start")
        return

    # ---------------------------------------------------------
    # 2) To'lov cheki
    # ---------------------------------------------------------
    if state == "waiting_payment_photo" or (state or "").startswith("waiting_payment_photo:"):
        product_key = state.split(":", 1)[1] if state and ":" in state else None
        await handle_payment_photo(update, context, product_key)
        return

    # ---------------------------------------------------------
    # 3) Support xabari
    # ---------------------------------------------------------
    if state == "waiting_support_message":
        await handle_support_message(update, context)
        return

    # ---------------------------------------------------------
    # 4) Promo kod
    # ---------------------------------------------------------
    if state == "waiting_promo_code":
        await handle_promo_code(update, context)
        return

    # ---------------------------------------------------------
    # 5) Yuk kuzatuv kodi
    # ---------------------------------------------------------
    if state == "waiting_cargo_code":
        await handle_cargo_code(update, context)
        return

    # ---------------------------------------------------------
    # 5) Hech qanday state yo'q -- asosiy menyu
    # ---------------------------------------------------------
    await message.reply_text(
        t(db.get_language(chat_id), "main_menu_prompt"), reply_markup=main_menu_keyboard(db.get_language(chat_id))
    )


async def handle_waiting_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat_id = update.effective_chat.id
    text = (message.text or "").strip()
    lang = db.get_language(chat_id)

    if len(text) < 2:
        await message.reply_text(t(lang, "ask_name_invalid"))
        return

    db.save_name(chat_id, text)
    await message.reply_text(
        t(lang, "ask_phone", name=text),
        reply_markup=contact_request_keyboard(t(lang, "phone_button")),
    )


async def handle_waiting_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat_id = update.effective_chat.id
    lang = db.get_language(chat_id)
    contact = message.contact

    if contact is None:
        await message.reply_text(
            'Iltimos, telefon raqamingizni faqat pastdagi "📱 Raqamni yuborish" tugmasi orqali yuboring.',
            reply_markup=contact_request_keyboard(t(lang, "phone_button")),
        )
        return

    if contact.user_id != chat_id:
        await message.reply_text(
            "Iltimos, faqat o'zingizning raqamingizni yuboring.",
            reply_markup=contact_request_keyboard(t(lang, "phone_button")),
        )
        return

    user_before = db.get_user(chat_id)
    db.save_phone_and_finish_registration(chat_id, contact.phone_number)

    # Avvalgi "Raqamni yuborish" pastki tugmasini majburan olib tashlaymiz
    # (aks holda u ekranda abadiy osilib qolaveradi)
    await message.reply_text("Rahmat! ✅", reply_markup=ReplyKeyboardRemove())

    await message.reply_text(
        t(lang, "registered_welcome"),
        reply_markup=main_menu_keyboard(lang),
    )

    # Agar referal havolasi orqali kelgan bo'lsa, taklif qilgan odamga bonus beramiz
    referrer_id = user_before["referred_by"] if user_before else None
    if referrer_id:
        db.add_balance(referrer_id, REFERRAL_BONUS)
        referrer_lang = db.get_language(referrer_id)
        try:
            await context.bot.send_message(
                chat_id=referrer_id,
                text=t(referrer_lang, "referral_bonus_notice", bonus=f"{REFERRAL_BONUS:,.0f}".replace(",", " ")),
            )
        except Exception as e:
            logger.warning("Referal bonusi haqida (%s) xabar yuborilmadi: %s", referrer_id, e)




async def handle_payment_photo(
    update: Update, context: ContextTypes.DEFAULT_TYPE, product_key: str | None = None
) -> None:
    message = update.effective_message
    chat_id = update.effective_chat.id

    if not message.photo:
        await message.reply_text("Iltimos, chekingizni RASM ko'rinishida yuboring (fayl emas).")
        return

    product = db.get_product(product_key) if product_key else None

    file_id = message.photo[-1].file_id  # eng katta o'lchamdagi rasm
    payment_id = db.insert_payment(
        chat_id,
        file_id,
        product_key=product["key"] if product else None,
        product_label=product["label"] if product else None,
        product_price=product["price"] if product else None,
    )

    user = db.get_user(chat_id)
    product_line = f"🛒 Mahsulot: {product['label']} ({product['price']:,.0f} so'm)\n".replace(",", " ") if product else ""
    caption = (
        "🧾 Yangi to'lov cheki!\n\n"
        f"{product_line}"
        f"👤 Ism: {user['full_name']}\n"
        f"📞 Tel: {user['phone_number']}\n"
        f"🆔 Chat ID: {chat_id}\n"
        f"#to'lov_{payment_id}"
    )

    # Barcha adminlarga (asosiy + yordamchi) yuboramiz
    for admin_id in db.get_all_admin_ids():
        try:
            sent = await context.bot.send_photo(
                chat_id=admin_id,
                photo=file_id,
                caption=caption,
                reply_markup=payment_admin_keyboard(payment_id, chat_id),
            )
            db.add_payment_notification(payment_id, admin_id, sent.message_id)
        except Exception as e:
            logger.warning("Adminga (%s) chek yuborilmadi: %s", admin_id, e)

    db.set_state(chat_id, None)
    await message.reply_text(
        "Chekingiz qabul qilindi ✅\nIltimos, tasdiqlanishini kuting. Natija haqida sizga xabar beramiz."
    )



async def handle_support_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat_id = update.effective_chat.id
    text = (message.text or "").strip()

    if not text:
        await message.reply_text("Iltimos, savolingizni matn ko'rinishida yozing.")
        return

    user = db.get_user(chat_id)
    caption = (
        "🆘 Yangi support xabari\n\n"
        f"👤 {user['full_name']} (@{user['username']})\n"
        f"🆔 Chat ID: {chat_id}\n\n"
        f"✉️ Xabar:\n{text}\n\n"
        "↩️ Javob berish uchun shu xabarga Reply qiling."
    )

    support_id = db.insert_support_thread(chat_id, message.message_id, text)

    # Barcha adminlarga yuboramiz -- qaysi biri birinchi Reply qilsa, o'sha javob beradi
    for admin_id in db.get_all_admin_ids():
        try:
            sent = await context.bot.send_message(chat_id=admin_id, text=caption)
            db.add_support_notification(support_id, admin_id, sent.message_id)
        except Exception as e:
            logger.warning("Adminga (%s) support xabari yuborilmadi: %s", admin_id, e)

    db.set_state(chat_id, None)
    await message.reply_text("Savolingiz qabul qilindi ✅\nTez orada operator javob beradi.")


async def handle_cargo_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat_id = update.effective_chat.id
    code = (message.text or "").strip().upper()

    db.set_state(chat_id, None)

    if not code:
        await message.reply_text("Iltimos, yuk kuzatuv kodini matn ko'rinishida kiriting.")
        return

    shipment = db.get_shipment_by_code(code)

    if shipment is None:
        await message.reply_text(
            "❌ Bunday kuzatuv kodi topilmadi. Kodni to'g'ri kiritganingizga ishonch hosil qiling."
        )
        return

    if shipment["user_chat_id"] != chat_id:
        await message.reply_text("❌ Bu kod sizga tegishli emas.")
        return

    status_label = CARGO_STATUSES.get(shipment["status"], shipment["status"])
    await message.reply_text(
        f"📦 Yuk ma'lumoti\n\n"
        f"🔖 Kod: {shipment['tracking_code']}\n"
        f"📝 Tavsif: {shipment['description']}\n"
        f"📍 Joriy holat: {status_label}"
    )


async def handle_promo_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat_id = update.effective_chat.id
    code = (message.text or "").strip().upper()

    db.set_state(chat_id, None)

    if not code:
        await message.reply_text("Iltimos, promo kodni matn ko'rinishida kiriting.")
        return

    promo = db.get_active_promo(code)
    if promo is None:
        await message.reply_text("❌ Bunday promo kod topilmadi yoki u faol emas.")
        return

    if db.has_used_promo(promo["id"], chat_id):
        await message.reply_text("⚠️ Siz bu promo koddan avval foydalangansiz.")
        return

    db.redeem_promo(promo["id"], chat_id, promo["amount"])
    new_balance = db.get_balance(chat_id)

    await message.reply_text(
        "✅ Promo kod muvaffaqiyatli qo'llanildi!\n"
        f"💰 Balansingizga {promo['amount']:,.0f} so'm qo'shildi.\n\n"
        f"Joriy balans: {new_balance:,.0f} so'm".replace(",", " ")
    )


async def handle_admin_support_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Istalgan admin support xabariga Reply qilganda javobni foydalanuvchiga yetkazadi."""
    message = update.effective_message
    admin_chat_id = update.effective_chat.id
    replied_to_id = message.reply_to_message.message_id

    notification = db.get_support_notification(admin_chat_id, replied_to_id)
    if notification is None:
        return False  # oddiy reply, support tizimiga aloqasi yo'q

    support_thread = db.get_support_thread(notification["support_id"])
    if support_thread is None:
        return False

    reply_text = (message.text or "").strip()
    if not reply_text:
        await message.reply_text("Iltimos, javobni matn ko'rinishida yuboring.")
        return True

    if support_thread["is_answered"] == 1:
        await message.reply_text("ℹ️ Bu savolga boshqa admin allaqachon javob bergan.")
        return True

    await context.bot.send_message(
        chat_id=support_thread["user_chat_id"], text=f"🎧 Support javobi:\n\n{reply_text}"
    )
    db.mark_support_answered(support_thread["id"])
    await message.reply_text("✅ Javobingiz foydalanuvchiga yuborildi.")

    return True


async def handle_direct_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE, target_chat_id: int
) -> None:
    """Admin muayyan bir mijozga (masalan chek yuborgan foydalanuvchiga) xabar yozganda ishlaydi."""
    message = update.effective_message
    admin_chat_id = update.effective_chat.id
    text = (message.text or "").strip()

    db.set_state(admin_chat_id, None)

    if not text:
        await message.reply_text("Xabar bo'sh bo'lmasligi kerak.")
        return

    try:
        await context.bot.send_message(chat_id=target_chat_id, text=f"✉️ Xabar:\n\n{text}")
        await message.reply_text("✅ Xabar yuborildi.")
    except Exception as e:
        logger.warning("Foydalanuvchiga (%s) xabar yuborilmadi: %s", target_chat_id, e)
        await message.reply_text("❌ Xabar yuborilmadi -- foydalanuvchi botni bloklagan bo'lishi mumkin.")


async def handle_broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin 'Barchaga xabar yuborish' tugmasidan keyin yozgan matnni hamma foydalanuvchiga yuboradi."""
    message = update.effective_message
    admin_chat_id = update.effective_chat.id
    text = (message.text or "").strip()

    db.set_state(admin_chat_id, None)

    if not text:
        await message.reply_text("Xabar bo'sh bo'lmasligi kerak. Qaytadan urinib ko'ring.")
        return

    chat_ids = db.get_all_registered_chat_ids()
    sent_count = 0
    failed_count = 0

    status_message = await message.reply_text(f"📢 Yuborilmoqda... (0/{len(chat_ids)})")

    for i, target_chat_id in enumerate(chat_ids, start=1):
        try:
            await context.bot.send_message(chat_id=target_chat_id, text=text)
            sent_count += 1
        except Exception as e:
            failed_count += 1
            logger.warning("Broadcast xabari %s ga yuborilmadi: %s", target_chat_id, e)

        # Har 20 ta xabardan keyin progressni yangilaymiz (juda ko'p edit chaqirmaslik uchun)
        if i % 20 == 0:
            try:
                await status_message.edit_text(f"📢 Yuborilmoqda... ({i}/{len(chat_ids)})")
            except Exception:
                pass

    await status_message.edit_text(
        f"✅ Xabar yuborish yakunlandi!\n\nYuborildi: {sent_count}\nXato: {failed_count}"
    )


# =======================================================================
# Inline tugmalar (callback_query)
# =======================================================================
async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    data = query.data
    chat_id = query.message.chat_id

    if data.startswith("message_user_"):
        if not db.is_admin(chat_id):
            await query.answer(text="Bu amal faqat admin uchun.", show_alert=True)
            return

        target_chat_id = int(data.replace("message_user_", ""))
        db.set_state(chat_id, f"waiting_direct_message:{target_chat_id}")
        await query.answer()
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"✉️ Foydalanuvchi ({target_chat_id}) ga yuboriladigan xabarni yozing:",
        )
        return

    if data.startswith("approve_payment_") or data.startswith("reject_payment_"):
        await handle_payment_decision(update, context)
        return

    if data == "admin_broadcast":
        if not db.is_admin(chat_id):
            await query.answer(text="Bu amal faqat admin uchun.", show_alert=True)
            return

        db.set_state(chat_id, "waiting_broadcast_message")
        await query.answer()
        await context.bot.send_message(
            chat_id=chat_id,
            text="📢 Barcha foydalanuvchilarga yuboriladigan xabar matnini yozing:",
        )
        return

    if data == "menu_wallet":
        lang = db.get_language(chat_id)
        await query.answer()
        balance = db.get_balance(chat_id)
        await context.bot.send_message(
            chat_id=chat_id,
            text=t(lang, "wallet_text", balance=f"{balance:,.0f}".replace(",", " ")),
        )
        return

    if data.startswith("lang_"):
        lang = data.replace("lang_", "")
        user = db.get_user(chat_id)
        await query.answer()

        if user is not None and user["is_registered"] == 1:
            # Ro'yxatdan o'tgan foydalanuvchi tilni o'zgartiryapti
            db.set_language(chat_id, lang)
            await context.bot.send_message(chat_id=chat_id, text=t(lang, "language_changed"))
            await context.bot.send_message(
                chat_id=chat_id, text=t(lang, "main_menu_prompt"), reply_markup=main_menu_keyboard(lang)
            )
        else:
            # Ro'yxatdan o'tish jarayonida birinchi marta til tanlanyapti
            await handle_language_selected(update, context, chat_id, lang)
        return

    if data == "menu_language":
        await query.answer()
        await context.bot.send_message(chat_id=chat_id, text=t(db.get_language(chat_id), "choose_language"), reply_markup=language_keyboard())
        return

    if data == "menu_referral":
        lang = db.get_language(chat_id)
        await query.answer()
        link = f"https://t.me/{BOT_USERNAME}?start=ref{chat_id}"
        count = db.get_referral_count(chat_id)
        await context.bot.send_message(
            chat_id=chat_id,
            text=t(lang, "referral_text", bonus=f"{REFERRAL_BONUS:,.0f}".replace(",", " "), link=link, count=count),
        )
        return

    if data == "menu_orders":
        lang = db.get_language(chat_id)
        await query.answer()
        payments = db.get_user_payments(chat_id)
        shipments = db.get_user_shipments(chat_id)

        if not payments and not shipments:
            await context.bot.send_message(chat_id=chat_id, text=t(lang, "orders_empty"))
            return

        lines = [t(lang, "orders_header"), ""]
        status_icons = {"pending": "⏳", "approved": "✅", "rejected": "❌"}
        for p in payments:
            product = f" — {p['product_label']}" if p["product_label"] else ""
            lines.append(f"{status_icons.get(p['status'], '•')} #{p['id']}{product} ({p['status']})")

        if shipments:
            lines.append("")
            for s in shipments:
                lines.append(f"📦 {s['tracking_code']} — {CARGO_STATUSES.get(s['status'], s['status'])}")

        await context.bot.send_message(chat_id=chat_id, text="\n".join(lines))
        return

    if data == "menu_cargo":
        db.set_state(chat_id, "waiting_cargo_code")
        await query.answer()
        await context.bot.send_message(
            chat_id=chat_id, text="📦 Yuk kuzatuv kodingizni kiriting:"
        )
        return

    if data.startswith("cargo_status_"):
        if not db.is_admin(chat_id):
            await query.answer(text="Bu amal faqat admin uchun.", show_alert=True)
            return

        _, _, shipment_id_str, status_key = data.split("_", 3)
        shipment_id = int(shipment_id_str)

        shipment = db.get_shipment(shipment_id)
        if shipment is None:
            await query.answer(text="Yuk topilmadi.", show_alert=True)
            return

        db.update_shipment_status(shipment_id, status_key)
        await query.answer(text="✅ Holat yangilandi.")

        try:
            await query.edit_message_text(
                f"📦 Kod: {shipment['tracking_code']}\n"
                f"📝 Tavsif: {shipment['description']}\n"
                f"🆔 Mijoz: {shipment['user_chat_id']}\n"
                f"📍 Joriy holat: {CARGO_STATUSES[status_key]}\n\n"
                "Statusni yangilash uchun tugmani bosing:",
                reply_markup=cargo_admin_keyboard(shipment_id, status_key),
            )
        except Exception:
            pass

        try:
            await context.bot.send_message(
                chat_id=shipment["user_chat_id"],
                text=(
                    f"{CARGO_STATUS_MESSAGES[status_key]}\n\n"
                    f"🔖 Kuzatuv kodi: {shipment['tracking_code']}\n"
                    f"📝 Tavsif: {shipment['description']}"
                ),
            )
        except Exception as e:
            logger.warning("Mijozga (%s) yuk holati haqida xabar yuborilmadi: %s", shipment["user_chat_id"], e)

        return

    if data == "menu_back":
        lang = db.get_language(chat_id)
        await query.answer()
        await context.bot.send_message(
            chat_id=chat_id, text=t(lang, "main_menu_prompt"), reply_markup=main_menu_keyboard(lang)
        )
        return

    if data == "menu_premium":
        await query.answer()
        await context.bot.send_message(
            chat_id=chat_id,
            text="⭐ Qaysi birini xohlaysiz?",
            reply_markup=premium_category_keyboard(),
        )
        return

    if data in ("premium_cat_premium", "premium_cat_stars"):
        category = "premium" if data == "premium_cat_premium" else "stars"
        products = db.get_active_products(category)
        await query.answer()

        if not products:
            await context.bot.send_message(
                chat_id=chat_id,
                text="Hozircha bu bo'limda mahsulotlar mavjud emas. Keyinroq qayta urinib ko'ring.",
                reply_markup=premium_category_keyboard(),
            )
            return

        title = "💎 Telegram Premium tariflari:" if category == "premium" else "⭐ Telegram Stars paketlari:"
        await context.bot.send_message(
            chat_id=chat_id, text=title, reply_markup=product_list_keyboard(products, category)
        )
        return

    if data.startswith("buy_product_"):
        product_key = data.replace("buy_product_", "")
        product = db.get_product(product_key)

        if product is None or product["is_active"] != 1:
            await query.answer(text="Bu mahsulot endi mavjud emas.", show_alert=True)
            return

        if db.has_pending_payment(chat_id):
            await query.answer(
                text="Sizda hali tasdiqlanmagan chek bor. Iltimos, natijani kuting.", show_alert=True
            )
            return

        db.set_state(chat_id, f"waiting_payment_photo:{product_key}")
        await query.answer()
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                f"Siz tanladingiz: {product['label']}\n"
                f"Narxi: {product['price']:,.0f} so'm\n\n"
                "Chekingizni rasm ko'rinishida yuboring va tasdiqlanishini kuting. 🧾"
            ).replace(",", " "),
        )
        return

    if data == "menu_payment":
        if db.has_pending_payment(chat_id):
            await query.answer(
                text="Sizda hali tasdiqlanmagan chek bor. Iltimos, natijani kuting.", show_alert=True
            )
            return
        db.set_state(chat_id, "waiting_payment_photo")
        await query.answer()
        await context.bot.send_message(
            chat_id=chat_id, text="Chekingizni rasm ko'rinishida yuboring va tasdiqlanishini kuting. 🧾"
        )

    elif data == "menu_support":
        db.set_state(chat_id, "waiting_support_message")
        await query.answer()
        await context.bot.send_message(
            chat_id=chat_id, text="Savolingizni yozing, operatorimiz tez orada javob beradi. ✍️"
        )

    elif data == "menu_promo":
        db.set_state(chat_id, "waiting_promo_code")
        await query.answer()
        await context.bot.send_message(chat_id=chat_id, text=t(db.get_language(chat_id), "promo_prompt"))

    else:
        await query.answer(text="Noma'lum amal.")


async def handle_payment_decision(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    data = query.data
    chat_id = query.message.chat_id

    if not db.is_admin(chat_id):
        await query.answer(text="Bu amal faqat admin uchun.", show_alert=True)
        return

    is_approve = data.startswith("approve_payment_")
    payment_id = int(data.replace("approve_payment_", "").replace("reject_payment_", ""))

    payment = db.get_payment(payment_id)
    if payment is None:
        await query.answer(text="To'lov topilmadi.", show_alert=True)
        return

    if payment["status"] != "pending":
        await query.answer(text="Bu to'lov bo'yicha qaror allaqachon qabul qilingan.", show_alert=True)
        return

    new_status = "approved" if is_approve else "rejected"
    db.update_payment_status(payment_id, new_status)

    product_note = f" ({payment['product_label']})" if payment["product_label"] else ""
    user_text = (
        f"✅ To'lovingiz qabul qilindi{product_note}. Rahmat!"
        if is_approve
        else f"❌ Afsuski, to'lovingiz{product_note} rad etildi. Savolingiz bo'lsa, Support bo'limiga murojaat qiling."
    )
    await context.bot.send_message(chat_id=payment["user_chat_id"], text=user_text)

    # Boshqa qaysi adminlarga ham shu chek yuborilgan bo'lsa, ularning xabarini ham yangilaymiz
    status_label = "✅ TASDIQLANDI" if is_approve else "❌ RAD ETILDI"
    decided_by = query.from_user.full_name if query.from_user else "Admin"

    for notif in db.get_payment_notifications(payment_id):
        try:
            old_caption = ""
            if notif["admin_chat_id"] == chat_id and query.message.caption:
                old_caption = query.message.caption
            await context.bot.edit_message_caption(
                chat_id=notif["admin_chat_id"],
                message_id=notif["message_id"],
                caption=f"#to'lov_{payment_id}\n\n{status_label}\n(qaror: {decided_by})"
                if not old_caption
                else f"{old_caption}\n\n{status_label}\n(qaror: {decided_by})",
            )
        except Exception as e:
            logger.warning("Admin xabarini yangilab bo'lmadi: %s", e)

    await query.answer(text="Qabul qilindi.")


# =======================================================================
# Ishga tushirish
# =======================================================================
def main() -> None:
    db.init_db()

    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("addpromo", addpromo))
    application.add_handler(CommandHandler("addadmin", addadmin))
    application.add_handler(CommandHandler("removeadmin", removeadmin))
    application.add_handler(CommandHandler("admins", list_admins))
    application.add_handler(CommandHandler("balance", check_balance))
    application.add_handler(CommandHandler("addbalance", add_balance_command))
    application.add_handler(CommandHandler("removebalance", remove_balance_command))
    application.add_handler(CommandHandler("addpremium", add_premium_product))
    application.add_handler(CommandHandler("addstars", add_stars_product))
    application.add_handler(CommandHandler("removeproduct", remove_product))
    application.add_handler(CommandHandler("products", list_products))
    application.add_handler(CommandHandler("addshipment", add_shipment))
    application.add_handler(CommandHandler("cargo", open_cargo_panel))
    application.add_handler(CallbackQueryHandler(handle_callback_query))
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))

    logger.info("Bot ishga tushdi (polling)...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
