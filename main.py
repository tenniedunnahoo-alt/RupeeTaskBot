import os
import json
import uuid
import telebot
from telebot import types
import firebase_admin
from firebase_admin import credentials, firestore

# ======================
# ENV SETUP REQUIRED:
# ======================
# TELEGRAM_BOT_TOKEN = your bot token
# FIREBASE_CREDENTIALS = full service account json

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
FIREBASE_JSON = os.getenv("FIREBASE_CREDENTIALS")

if not TOKEN or not FIREBASE_JSON:
    raise Exception("Please set TELEGRAM_BOT_TOKEN and FIREBASE_CREDENTIALS")

cred_dict = json.loads(FIREBASE_JSON)
cred = credentials.Certificate(cred_dict)
firebase_admin.initialize_app(cred)
db = firestore.client()

bot = telebot.TeleBot(TOKEN)

# ======================
# HELPERS
# ======================

def get_user(user):
    ref = db.collection("users").document(str(user.id))
    doc = ref.get()
    if not doc.exists:
        ref.set({
            "username": user.username or "",
            "balance": 0,
            "total_done": 0,
            "total_pending": 0
        })
    return ref

def main_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("📋 View Tasks", "📤 My Submissions")
    markup.add("💰 Wallet", "💸 Withdraw")
    return markup

# ======================
# START
# ======================

@bot.message_handler(commands=["start"])
def start(message):
    get_user(message.from_user)
    bot.send_message(message.chat.id, "Welcome to RupeeTasksBot ✅\nComplete tasks & earn money.", reply_markup=main_menu())

# ======================
# VIEW TASKS
# ======================

@bot.message_handler(func=lambda m: m.text == "📋 View Tasks")
def view_tasks(message):
    tasks = db.collection("tasks").stream()
    found = False
    for t in tasks:
        found = True
        data = t.to_dict()
        text = f"📝 {data['title']}\n💰 Reward: ₹{data['reward']}\n\n{data['description']}"
        btn = types.InlineKeyboardMarkup()
        btn.add(types.InlineKeyboardButton("✅ Submit Proof", callback_data=f"submit_{t.id}"))
        bot.send_message(message.chat.id, text, reply_markup=btn)
    if not found:
        bot.send_message(message.chat.id, "No tasks available right now.")

# ======================
# SUBMIT PROOF
# ======================

user_states = {}

@bot.callback_query_handler(func=lambda c: c.data.startswith("submit_"))
def submit_task(call):
    task_id = call.data.split("_")[1]
    user_states[call.from_user.id] = {"task_id": task_id}
    bot.send_message(call.message.chat.id, "Send your proof (text or screenshot).")

@bot.message_handler(content_types=["text", "photo"])
def receive_proof(message):
    uid = message.from_user.id
    if uid not in user_states:
        return

    task_id = user_states[uid]["task_id"]
    proof = ""

    if message.content_type == "text":
        proof = message.text
    else:
        proof = message.photo[-1].file_id

    sub_id = str(uuid.uuid4())

    db.collection("submissions").document(sub_id).set({
        "user_id": str(uid),
        "task_id": task_id,
        "proof": proof,
        "status": "pending"
    })

    user_ref = db.collection("users").document(str(uid))
    user_ref.update({
        "total_pending": firestore.Increment(1)
    })

    del user_states[uid]
    bot.send_message(message.chat.id, "✅ Proof submitted! Status: Pending review.")

# ======================
# MY SUBMISSIONS
# ======================

@bot.message_handler(func=lambda m: m.text == "📤 My Submissions")
def my_subs(message):
    uid = str(message.from_user.id)
    subs = db.collection("submissions").where("user_id", "==", uid).stream()
    msg = "📊 Your Submissions:\n\n"
    found = False
    for s in subs:
        found = True
        d = s.to_dict()
        msg += f"Task: {d['task_id']} | Status: {d['status']}\n"
    if not found:
        msg += "No submissions yet."
    bot.send_message(message.chat.id, msg)

# ======================
# WALLET
# ======================

@bot.message_handler(func=lambda m: m.text == "💰 Wallet")
def wallet(message):
    user = db.collection("users").document(str(message.from_user.id)).get().to_dict()
    msg = f"""
💰 Your Wallet

Balance: ₹{user['balance']}
✅ Completed: {user['total_done']}
⏳ Pending: {user['total_pending']}
"""
    bot.send_message(message.chat.id, msg)

# ======================
# WITHDRAW
# ======================

withdraw_states = {}

@bot.message_handler(func=lambda m: m.text == "💸 Withdraw")
def withdraw(message):
    bot.send_message(message.chat.id, "Enter amount to withdraw:")
    withdraw_states[message.from_user.id] = {}

@bot.message_handler(func=lambda m: m.from_user.id in withdraw_states and "amount" not in withdraw_states[m.from_user.id])
def get_amount(message):
    try:
        amt = int(message.text)
    except:
        bot.send_message(message.chat.id, "Enter valid number.")
        return

    user = db.collection("users").document(str(message.from_user.id)).get().to_dict()
    if amt < 50:
        bot.send_message(message.chat.id, "Minimum withdraw is ₹50")
        withdraw_states.pop(message.from_user.id)
        return

    if user["balance"] < amt:
        bot.send_message(message.chat.id, "Not enough balance.")
        withdraw_states.pop(message.from_user.id)
        return

    withdraw_states[message.from_user.id]["amount"] = amt
    bot.send_message(message.chat.id, "Enter your UPI ID:")

@bot.message_handler(func=lambda m: m.from_user.id in withdraw_states and "amount" in withdraw_states[m.from_user.id])
def get_upi(message):
    uid = message.from_user.id
    upi = message.text
    amt = withdraw_states[uid]["amount"]

    rid = str(uuid.uuid4())

    db.collection("withdraw_requests").document(rid).set({
        "user_id": str(uid),
        "amount": amt,
        "upi": upi,
        "status": "pending"
    })

    bot.send_message(message.chat.id, "✅ Withdraw request submitted. It will be processed after review.")
    withdraw_states.pop(uid)

# ======================
# RUN
# ======================

print("User bot is running...")
bot.infinity_polling()
