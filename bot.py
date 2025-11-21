"""
ShxudjA_bot - Telegram bot (polling) for career suggestions and Kaspi payment auto-confirmation.

IMPORTANT:
 - Replace "YOUR_TELEGRAM_TOKEN_HERE" with your bot token (do NOT share it publicly).
 - This bot expects a payment webhook server (payment_server.py) to run on Render (or any public host).
 - The payment server, when it sees a successful payment, will mark the user as paid in database.json
   and will send a Telegram message to the user. The bot itself will also provide a "Check payment"
   button for manual poll if needed.

Run:
    python bot.py

Dependencies:
    python-telegram-bot==20.3
"""

import json
import os
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

DB_PATH = "database.json"
UNIS_PATH = "universities.json"
COLL_PATH = "colleges.json"
SUBJ_PATH = "subject_rules.json"

TELEGRAM_TOKEN = "YOUR_TELEGRAM_TOKEN_HERE"  # <-- REPLACE before running

def load_db():
    if not os.path.exists(DB_PATH):
        with open(DB_PATH, "w", encoding="utf-8") as f:
            json.dump({}, f)
    with open(DB_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def save_db(db):
    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

# helper: calculate careers from subject ratings
def recommend_careers(ratings):
    rules = load_json(SUBJ_PATH)
    scores = {}
    for career, rule in rules.items():
        s = 0
        for subj, weight in rule["weights"].items():
            s += ratings.get(subj, 0) * weight
        scores[career] = s
    # return top 3 careers sorted by score
    sorted_c = sorted(scores.items(), key=lambda x: -x[1])
    return [c for c,_ in sorted_c[:3]]

# building subject keyboard for ratings 0..10
def subject_rating_keyboard(subj):
    kb = []
    row = []
    for i in range(0,11):
        row.append(InlineKeyboardButton(str(i), callback_data=f"rate|{subj}|{i}"))
        if len(row) == 6:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    return InlineKeyboardMarkup(kb)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = str(user.id)
    db = load_db()
    if user_id not in db:
        db[user_id] = {"paid": False, "phone": None, "stage": "phone", "ratings": {}, "grade": None}
        save_db(db)
    kb = ReplyKeyboardMarkup([[KeyboardButton("Жіберу телефоның (мыс: 8702...)", request_contact=False)]], resize_keyboard=True)
    await update.message.reply_text(
        "Сәлем! Бұл бот сенің сүйікті пәндерің бойынша мамандық пен оқу орындарын ұсынады.\n\n"
        "Бірінші қадам — телефон нөміріңді жазыңыз (мыс: 87021234567). Бұл төлемді сәйкестендіру үшін қажет.",
        reply_markup=kb
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = str(user.id)
    text = update.message.text.strip()
    db = load_db()
    if user_id not in db:
        db[user_id] = {"paid": False, "phone": None, "stage": "phone", "ratings": {}, "grade": None}
    user_rec = db[user_id]

    # If waiting for phone
    if user_rec.get("stage") == "phone":
        phone = "".join([c for c in text if c.isdigit()])
        if len(phone) < 9:
            await update.message.reply_text("Телефон нөмірін толық және цифрмен жазыңыз (мыс: 87021234567).")
            return
        user_rec["phone"] = phone
        user_rec["stage"] = "after_phone"
        save_db(db)

        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Мен төледім / Тексеру", callback_data="check_paid")]])
        await update.message.reply_text(
            f"Төлем жасау нұсқаулық:\n\n"
            f"💳 Kaspi Gold: 8702 *** ****\n"
            f"📝 Комментарийге мынаны міндетті түрде жазыңыз:\n➡ {phone}\n\n"
            "Kaspi-ден төлем түскен соң жүйе автоматты түрде сізді келесі қадамға өткізеді.\n"
            "Егер төлем автоматты түрде расталмаса, «Мен төледім / Тексеру» батырмасын басыңыз.",
            reply_markup=kb
        )
        return

    # if after all steps, allow restart
    if text.lower() in ["бастау", "/start", "restart", "қайта"]:
        await start(update, context)
        return

    await update.message.reply_text("Мен тек батырмалар арқылы жүруге ұсынамын. Телефоныңды бастаудан кейін батырмалар шығады.")

async def check_paid_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = str(query.from_user.id)
    db = load_db()
    await query.answer()
    user_rec = db.get(user_id, {})
    if user_rec.get("paid"):
        # move to grade selection
        keyboard = [
            [InlineKeyboardButton("9 сынып", callback_data="grade|9"), InlineKeyboardButton("11 сынып", callback_data="grade|11")]
        ]
        await query.edit_message_text("✅ Төлем расталды! Қайсы сыныпсың?", reply_markup=InlineKeyboardMarkup(keyboard))
        user_rec["stage"] = "choose_grade"
        save_db(db)
    else:
        await query.edit_message_text("❗ Төлем әлі расталған жоқ. Kaspi арқылы төлеңіз және бірнеше секунд ішінде жүйе автоматты түрде растайды. Немесе «Төледім / Тексеру» батырмасын қайтадан басыңыз.")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = str(query.from_user.id)
    db = load_db()
    user_rec = db.get(user_id, {"paid": False, "phone": None, "stage": "phone", "ratings": {}, "grade": None})
    await query.answer()

    if data.startswith("grade|"):
        grade = data.split("|")[1]
        user_rec["grade"] = int(grade)
        user_rec["stage"] = "rating_subjects"
        save_db(db)
        # start subject ratings sequence
        subjects = list(load_json("subject_rules.json").get("subjects_order"))
        # store order in db so we can proceed
        user_rec["subject_order"] = subjects
        user_rec["current_subject_index"] = 0
        user_rec["ratings"] = {}
        save_db(db)
        subj = subjects[0]
        await query.edit_message_text(f"Әр пәнге 0-ден 10-ға дейін баға беріңіз.\n\n{subj} үшін баға таңдаңыз:", reply_markup=subject_rating_keyboard(subj))
        return

    if data.startswith("rate|"):
        # format: rate|<subject>|<score>
        _, subj, score = data.split("|")
        score = int(score)
        user_rec["ratings"][subj] = score
        idx = user_rec.get("current_subject_index", 0) + 1
        subjects = user_rec.get("subject_order", list(load_json("subject_rules.json").get("subjects_order")))
        user_rec["current_subject_index"] = idx
        save_db(db)
        if idx >= len(subjects):
            # finished ratings
            # compute careers
            careers = recommend_careers(user_rec["ratings"])
            msg = "✅ Сенің ұнататын пәндерің бойынша ұсынылатын мамандықтар:\n\n"
            for i,c in enumerate(careers, start=1):
                msg += f"{i}. {c}\\n"
            # depending on grade, choose colleges or unis for the top career
            top = careers[0]
            if user_rec.get("grade") == 9:
                # show colleges
                colleges = load_json(COLL_PATH).get(top, [])
                if not colleges:
                    msg += "\\nКолледждер табылмады."
                else:
                    msg += "\\nҰсынылатын колледждер:\\n"
                    for col in colleges[:3]:
                        msg += f"• {col['name']} — Ақша: {col['price']} тг — Грант бар ма: {col['grant']}\\n"
            else:
                # show universities
                unis = load_json(UNIS_PATH).get(top, [])
                if not unis:
                    msg += "\\nУниверситеттер табылмады."
                else:
                    msg += "\\nҰсынылатын университеттер:\\n"
                    for u in unis[:3]:
                        msg += f"• {u['name']} — Грант: {u.get('grant_score','—')} балл — Платный: {u.get('price','—')} тг\\n"
            msg += "\\n🔄 Қайта бастау үшін /start жіберіңіз."
            await query.edit_message_text(msg)
            user_rec["stage"] = "finished"
            save_db(db)
            return
        else:
            next_subj = subjects[idx]
            await query.edit_message_text(f"{next_subj} үшін баға таңдаңыз:", reply_markup=subject_rating_keyboard(next_subj))
            return

    await query.edit_message_text("Басқа батырмаға қатысты операция әлі қосылмаған.")

def subject_rating_keyboard(subj):
    # local helper duplicate to ensure function exists in bot context
    kb = []
    row = []
    for i in range(0,11):
        row.append(InlineKeyboardButton(str(i), callback_data=f"rate|{subj}|{i}"))
        if len(row) == 6:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    return InlineKeyboardMarkup(kb)

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(callback_handler))
    print("Bot started. Press Ctrl+C to stop.")
    app.run_polling()

if __name__ == "__main__":
    main()