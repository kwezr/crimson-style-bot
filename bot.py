"""
Sensei AI — Yapon tili o'quv guruhi uchun Telegram bot.

Xususiyatlar:
- Ro'yxatdan o'tish (Ism + Nomer), SQLite bazasida saqlash
- Pastki tugmalar (Reply Keyboard): 📝 Test | 📊 Reyting | ℹ️ Yordam
- /test — Claude AI yordamida JLPT N5/N4 darajasida 5 ta savol, inline tugmali javoblar (a/b/c/d)
- Har to'g'ri javob uchun +10 ball, xato javobda tushuntirish (AI orqali)
- /stat — Top 5 reyting jadvali
- Har 500 ballda guruhga avtomatik tabrik xabari
- Admin (Davron) uchun: /reset [ID], /gifted [ID], /broadcast [xabar]
- Erkin xabarlarga botning o'zi INTJ uslubida (qisqa, aniq) AI orqali javob beradi

O'RNATISH:
    pip install python-telegram-bot==21.* anthropic

ISHGA TUSHIRISH:
    export TELEGRAM_BOT_TOKEN="..."
    export ANTHROPIC_API_KEY="..."
    export ADMIN_TELEGRAM_ID="123456789"   # Davronning Telegram user_id raqami
    python bot.py
"""

import os
import json
import sqlite3
import logging
import re
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()  # loyiha papkasidagi .env faylini o'qiydi

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    filters,
)

from anthropic import Anthropic

# ---------------------------------------------------------------------------
# SOZLAMALAR
# ---------------------------------------------------------------------------

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ADMIN_TELEGRAM_ID = int(os.environ.get("ADMIN_TELEGRAM_ID", "0"))
DB_PATH = os.path.join(os.path.dirname(__file__), "sensei.db")

# Tez va arzon model — savol generatsiya va qisqa suhbat uchun yetarli
AI_MODEL = "claude-haiku-4-5-20251001"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("sensei_ai")

client = Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None

# Ro'yxatdan o'tish bosqichlari
ASK_NAME, ASK_PHONE, CONFIRM = range(3)

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [["📝 Test", "📊 Reyting"], ["ℹ️ Yordam"]],
    resize_keyboard=True,
)

SYSTEM_PROMPT = (
    "Sen 'Sensei AI'san — yapon tili o'quv guruhi boshqaruvchisi va o'qituvchisi. "
    "INTJ uslubida gapir: qisqa, aniq, mantiqiy, keraksiz gaplarsiz. "
    "Har doim professional yapon tili o'qituvchisi sifatida javob ber."
)

# ---------------------------------------------------------------------------
# BAZA
# ---------------------------------------------------------------------------

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS students (
            user_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            score INTEGER NOT NULL DEFAULT 0,
            gifts INTEGER NOT NULL DEFAULT 0,
            last_milestone INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


def get_student(user_id: int):
    conn = db()
    row = conn.execute("SELECT * FROM students WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return row


def upsert_student(user_id: int, name: str, phone: str):
    conn = db()
    conn.execute(
        "INSERT OR REPLACE INTO students (user_id, name, phone, score, gifts, last_milestone, created_at) "
        "VALUES (?, ?, ?, COALESCE((SELECT score FROM students WHERE user_id=?), 0), "
        "COALESCE((SELECT gifts FROM students WHERE user_id=?), 0), "
        "COALESCE((SELECT last_milestone FROM students WHERE user_id=?), 0), ?)",
        (user_id, name, phone, user_id, user_id, user_id, datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()


def add_score(user_id: int, delta: int):
    conn = db()
    conn.execute("UPDATE students SET score = score + ? WHERE user_id=?", (delta, user_id))
    conn.commit()
    row = conn.execute("SELECT score, last_milestone FROM students WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return row


def set_milestone(user_id: int, milestone: int):
    conn = db()
    conn.execute("UPDATE students SET last_milestone=? WHERE user_id=?", (milestone, user_id))
    conn.commit()
    conn.close()


def reset_score(user_id: int):
    conn = db()
    conn.execute("UPDATE students SET score=0, last_milestone=0 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()


def add_gift(user_id: int):
    conn = db()
    conn.execute("UPDATE students SET gifts = gifts + 1 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()


def top_students(limit=5):
    conn = db()
    rows = conn.execute(
        "SELECT name, score, gifts FROM students ORDER BY score DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return rows


def all_user_ids():
    conn = db()
    rows = conn.execute("SELECT user_id FROM students").fetchall()
    conn.close()
    return [r["user_id"] for r in rows]


# ---------------------------------------------------------------------------
# AI YORDAMCHI FUNKSIYALAR
# ---------------------------------------------------------------------------

def ai_generate_quiz():
    """Claude orqali 5 ta JLPT N5/N4 savol JSON formatida generatsiya qiladi."""
    prompt = (
        "JLPT N5/N4 darajasida yapon tili bo'yicha 5 ta test savoli tuz. "
        "FAQAT quyidagi JSON massiv formatida javob ber, boshqa hech qanday matn qo'shma:\n"
        '[{"question": "...", "options": {"a": "...", "b": "...", "c": "...", "d": "..."}, '
        '"correct": "a", "explanation": "qisqa tushuntirish"}, ...]\n'
        "Savollar grammatika, so'z boyligi yoki kanji/hiragana bilishga oid bo'lsin."
    )
    resp = client.messages.create(
        model=AI_MODEL,
        max_tokens=1500,
        system="Sen faqat JSON qaytaruvchi yapon tili test generatorisan.",
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in resp.content if hasattr(b, "text"))
    text = re.sub(r"```json|```", "", text).strip()
    return json.loads(text)


def ai_reply(user_text: str, student_name: str = None):
    """Erkin xabarlarga INTJ uslubida qisqa javob."""
    prefix = f"[{student_name}] " if student_name else ""
    resp = client.messages.create(
        model=AI_MODEL,
        max_tokens=400,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"{prefix}{user_text}"}],
    )
    return "".join(b.text for b in resp.content if hasattr(b, "text"))


# ---------------------------------------------------------------------------
# RO'YXATDAN O'TISH
# ---------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    student = get_student(user_id)
    if student:
        await update.message.reply_text(
            f"Qaytib kelding, {student['name']}. Ball: {student['score']}.",
            reply_markup=MAIN_KEYBOARD,
        )
        return ConversationHandler.END

    await update.message.reply_text("Sensei AI faollashtirildi.\n\nIsmingizni kiriting.")
    return ASK_NAME


async def ask_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text.strip()
    await update.message.reply_text("Nomeringizni kiriting.")
    return ASK_PHONE


async def ask_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    if not re.match(r"^\+?\d{7,15}$", phone):
        await update.message.reply_text("Nomer noto'g'ri formatda. Qayta kiriting.")
        return ASK_PHONE
    context.user_data["phone"] = phone
    name = context.user_data["name"]
    await update.message.reply_text(
        f"Ism: {name}\nNomer: {phone}\n\nTasdiqlaysizmi? (Ha/Yo'q)"
    )
    return CONFIRM


async def confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()
    if text in ("ha", "xa", "yes", "ha."):
        user_id = update.effective_user.id
        name = context.user_data["name"]
        phone = context.user_data["phone"]
        upsert_student(user_id, name, phone)
        await update.message.reply_text(
            f"Bazaga kiritildi.\n\n{name}, 0 ball, 0 sovg'a.\n\n"
            "Tugmalardan foydalaning yoki savol bering.",
            reply_markup=MAIN_KEYBOARD,
        )
        return ConversationHandler.END
    else:
        await update.message.reply_text("Bekor qilindi. Ismingizni qayta kiriting.")
        return ASK_NAME


# ---------------------------------------------------------------------------
# TEST
# ---------------------------------------------------------------------------

async def cmd_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    student = get_student(user_id)
    if not student:
        await update.message.reply_text("Avval ro'yxatdan o'ting: /start")
        return

    await update.message.reply_text("Savollar tayyorlanmoqda...")
    try:
        quiz = ai_generate_quiz()
    except Exception as e:
        logger.exception("Quiz generation failed")
        await update.message.reply_text("Xatolik yuz berdi. Qayta urinib ko'ring.")
        return

    context.user_data["quiz"] = quiz
    context.user_data["quiz_index"] = 0
    context.user_data["quiz_score"] = 0
    await send_quiz_question(update.message.chat_id, context)


async def send_quiz_question(chat_id, context: ContextTypes.DEFAULT_TYPE):
    quiz = context.user_data["quiz"]
    idx = context.user_data["quiz_index"]
    if idx >= len(quiz):
        score_gained = context.user_data["quiz_score"]
        user_id = context.user_data["_active_user_id"]
        row = add_score(user_id, score_gained)
        await context.bot.send_message(
            chat_id,
            f"Test tugadi. Natija: {score_gained} ball.\nJami ball: {row['score']}.",
            reply_markup=MAIN_KEYBOARD,
        )
        await check_milestone(chat_id, context, user_id, row["score"], row["last_milestone"])
        return

    q = quiz[idx]
    buttons = [
        [InlineKeyboardButton(f"{k.upper()}) {v}", callback_data=f"quiz:{idx}:{k}")]
        for k, v in q["options"].items()
    ]
    await context.bot.send_message(
        chat_id,
        f"{idx + 1}-savol: {q['question']}",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def quiz_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    context.user_data["_active_user_id"] = user_id

    _, idx_str, chosen = query.data.split(":")
    idx = int(idx_str)
    quiz = context.user_data.get("quiz")
    if not quiz or idx != context.user_data.get("quiz_index"):
        return  # eski tugma bosilgan

    q = quiz[idx]
    correct = q["correct"]
    if chosen == correct:
        context.user_data["quiz_score"] += 10
        await query.edit_message_text(
            f"{idx + 1}-savol: {q['question']}\n\n✅ To'g'ri! +10 ball."
        )
    else:
        await query.edit_message_text(
            f"{idx + 1}-savol: {q['question']}\n\n"
            f"❌ Xato. To'g'ri javob: {correct.upper()}) {q['options'][correct]}\n"
            f"Izoh: {q.get('explanation', '-')}"
        )

    context.user_data["quiz_index"] += 1
    await send_quiz_question(query.message.chat_id, context)


async def check_milestone(chat_id, context, user_id, score, last_milestone):
    milestone = (score // 500) * 500
    if milestone > 0 and milestone > last_milestone:
        student = get_student(user_id)
        set_milestone(user_id, milestone)
        await context.bot.send_message(
            chat_id,
            f"Tabriklayman {student['name']}, sen {milestone} ball yig'ding va "
            f"Admin Davrondan 'Stars' sovg'asini olishga haqlisan!",
        )


# ---------------------------------------------------------------------------
# STATISTIKA
# ---------------------------------------------------------------------------

async def cmd_stat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = top_students(5)
    if not rows:
        await update.message.reply_text("Hozircha statistika yo'q.")
        return
    lines = ["📊 Reyting (Top 5):\n"]
    for i, r in enumerate(rows, start=1):
        lines.append(f"{i}. {r['name']} - {r['score']} ball - {r['gifts']} sovg'a")
    await update.message.reply_text("\n".join(lines))


# ---------------------------------------------------------------------------
# ADMIN PANEL
# ---------------------------------------------------------------------------

def is_admin(user_id: int) -> bool:
    return ADMIN_TELEGRAM_ID != 0 and user_id == ADMIN_TELEGRAM_ID


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Ruxsat yo'q.")
        return
    if not context.args:
        await update.message.reply_text("Foydalanish: /reset [ID]")
        return
    target_id = int(context.args[0])
    reset_score(target_id)
    await update.message.reply_text(f"{target_id} ball nolga tushirildi.")


async def cmd_gifted(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Ruxsat yo'q.")
        return
    if not context.args:
        await update.message.reply_text("Foydalanish: /gifted [ID]")
        return
    target_id = int(context.args[0])
    add_gift(target_id)
    await update.message.reply_text(f"{target_id} uchun sovg'a soni +1 qilindi.")


async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Ruxsat yo'q.")
        return
    message = " ".join(context.args)
    if not message:
        await update.message.reply_text("Foydalanish: /broadcast [xabar]")
        return
    count = 0
    for uid in all_user_ids():
        try:
            await context.bot.send_message(uid, f"📢 E'lon: {message}")
            count += 1
        except Exception:
            continue
    await update.message.reply_text(f"Xabar {count} ta o'quvchiga yuborildi.")


# ---------------------------------------------------------------------------
# TUGMALAR VA ERKIN XABARLAR
# ---------------------------------------------------------------------------

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user_id = update.effective_user.id
    student = get_student(user_id)

    if text == "📝 Test":
        await cmd_test(update, context)
        return
    if text == "📊 Reyting":
        await cmd_stat(update, context)
        return
    if text == "ℹ️ Yordam":
        await update.message.reply_text(
            "Buyruqlar:\n/test — bilim tekshiruvi\n/stat — reyting\n"
            "Savolingiz bo'lsa, shunchaki yozing."
        )
        return

    if not student:
        await update.message.reply_text("Avval ro'yxatdan o'ting: /start")
        return

    if client is None:
        await update.message.reply_text("AI ulanmagan. ANTHROPIC_API_KEY sozlanmagan.")
        return

    reply = ai_reply(text, student["name"])
    await update.message.reply_text(reply, reply_markup=MAIN_KEYBOARD)


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    init_db()
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    reg_conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_name)],
            ASK_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_phone)],
            CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm)],
        },
        fallbacks=[],
    )

    app.add_handler(reg_conv)
    app.add_handler(CommandHandler("test", cmd_test))
    app.add_handler(CommandHandler("stat", cmd_stat))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CommandHandler("gifted", cmd_gifted))
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))
    app.add_handler(CallbackQueryHandler(quiz_answer, pattern=r"^quiz:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("Sensei AI ishga tushdi.")
    app.run_polling()


if __name__ == "__main__":
    main()
