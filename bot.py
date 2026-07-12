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
from config import BOT_TOKEN, MAIN_ADMIN_CHAT_ID

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)


# =======================================================================
# Umumiy klaviaturalar
# =======================================================================
def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("💰 To'lov", callback_data="menu_payment")],
            [InlineKeyboardButton("🎧 Support", callback_data="menu_support")],
            [InlineKeyboardButton("🎟 Promo kod", callback_data="menu_promo")],
        ]
    )


def admin_panel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("📢 Barchaga xabar yuborish", callback_data="admin_broadcast")]]
    )


def contact_request_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton("📱 Raqamni yuborish", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def payment_admin_keyboard(payment_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"approve_payment_{payment_id}"),
                InlineKeyboardButton("❌ Rad etish", callback_data=f"reject_payment_{payment_id}"),
            ]
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
            "/admins -- adminlar ro'yxati\n"
            + ("/addadmin CHAT_ID -- yordamchi admin qo'shish\n"
               "/removeadmin CHAT_ID -- adminlikdan olib tashlash\n"
               if chat_id == MAIN_ADMIN_CHAT_ID else ""),
            reply_markup=admin_panel_keyboard(),
        )
        return

    user = db.create_user_if_not_exists(chat_id, username)

    if user["is_registered"] == 1:
        await update.message.reply_text(
            f"Xush kelibsiz, {user['full_name']}! 👋\n\nQuyidagi bo'limlardan birini tanlang:",
            reply_markup=main_menu_keyboard(),
        )
        return

    db.set_state(chat_id, "waiting_name")
    await update.message.reply_text(
        "Assalomu alaykum! Botimizga xush kelibsiz. 🙌\n\n"
        "Ro'yxatdan o'tish uchun avval to'liq ismingizni yozib yuboring:",
        reply_markup=ReplyKeyboardRemove(),
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
        if admin_user["state"] == "waiting_broadcast_message":
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
    if state == "waiting_payment_photo":
        await handle_payment_photo(update, context)
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
    # 5) Hech qanday state yo'q -- asosiy menyu
    # ---------------------------------------------------------
    await message.reply_text(
        "Quyidagi bo'limlardan birini tanlang 👇", reply_markup=main_menu_keyboard()
    )


async def handle_waiting_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat_id = update.effective_chat.id
    text = (message.text or "").strip()

    if len(text) < 2:
        await message.reply_text("Iltimos, to'g'ri ism kiriting (kamida 2 ta harf):")
        return

    db.save_name(chat_id, text)
    await message.reply_text(
        f"Rahmat, {text}! Endi telefon raqamingizni pastdagi tugma orqali yuboring:",
        reply_markup=contact_request_keyboard(),
    )


async def handle_waiting_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat_id = update.effective_chat.id
    contact = message.contact

    if contact is None:
        await message.reply_text(
            'Iltimos, telefon raqamingizni faqat pastdagi "📱 Raqamni yuborish" tugmasi orqali yuboring.',
            reply_markup=contact_request_keyboard(),
        )
        return

    if contact.user_id != chat_id:
        await message.reply_text(
            "Iltimos, faqat o'zingizning raqamingizni yuboring.",
            reply_markup=contact_request_keyboard(),
        )
        return

    db.save_phone_and_finish_registration(chat_id, contact.phone_number)
    await message.reply_text(
        "🎉 Ro'yxatdan muvaffaqiyatli o'tdingiz!\n\nQuyidagi bo'limlardan birini tanlang:",
        reply_markup=main_menu_keyboard(),
    )


async def handle_payment_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat_id = update.effective_chat.id

    if not message.photo:
        await message.reply_text("Iltimos, chekingizni RASM ko'rinishida yuboring (fayl emas).")
        return

    file_id = message.photo[-1].file_id  # eng katta o'lchamdagi rasm
    payment_id = db.insert_payment(chat_id, file_id)

    user = db.get_user(chat_id)
    caption = (
        "🧾 Yangi to'lov cheki!\n\n"
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
                reply_markup=payment_admin_keyboard(payment_id),
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

    if data == "menu_payment":
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
        await context.bot.send_message(chat_id=chat_id, text="Promo kodni kiriting: 🎟")

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

    user_text = (
        "✅ To'lovingiz qabul qilindi. Rahmat!"
        if is_approve
        else "❌ Afsuski, to'lovingiz rad etildi. Savolingiz bo'lsa, Support bo'limiga murojaat qiling."
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
    application.add_handler(CallbackQueryHandler(handle_callback_query))
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))

    logger.info("Bot ishga tushdi (polling)...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
