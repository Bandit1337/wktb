
import logging
from aiogram import Bot, Dispatcher, executor, types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from datetime import datetime, timedelta, date
import sqlite3
import os

API_TOKEN = os.getenv("API_TOKEN")
AUTHORIZED_USERS = list(map(int, os.getenv("AUTHORIZED_IDS", "").split(",")))

WORK_START = datetime.strptime("08:30:00", "%H:%M:%S").time()
WORK_DURATION = timedelta(hours=8, minutes=30)
MAX_OVERTIME = timedelta(hours=4)

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
keyboard.add(KeyboardButton("✅ Я на предприятии"))
keyboard.add(KeyboardButton("🏖️ Сегодня отпуск"))

def is_authorized(user_id):
    return user_id in AUTHORIZED_USERS

def init_db():
    conn = sqlite3.connect("data.sqlite")
    cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        username TEXT,
        date TEXT,
        entry_time TEXT,
        vacation INTEGER DEFAULT 0
    )''')
    conn.commit()
    conn.close()

init_db()

@dp.message_handler(commands=['start'])
async def send_welcome(message: types.Message):
    if not is_authorized(message.from_user.id):
        await message.answer("⛔ У вас нет доступа к этому боту.")
        return
    await message.answer("Привет! Нажми кнопку, когда зайдёшь на предприятие.", reply_markup=keyboard)

@dp.message_handler(lambda m: m.text == "✅ Я на предприятии")
async def handle_entry(message: types.Message):
    if not is_authorized(message.from_user.id):
        await message.answer("⛔ У вас нет доступа к этому боту.")
        return

    now = datetime.now()
    entry_time = now.time()
    today = now.date()

    delay = datetime.combine(today, entry_time) - datetime.combine(today, WORK_START)
    if delay.total_seconds() < 0:
        delay = timedelta(0)
    end_time = datetime.combine(today, entry_time) + WORK_DURATION + delay
    max_end_time = datetime.combine(today, entry_time) + WORK_DURATION + MAX_OVERTIME
    if end_time > max_end_time:
        end_time = max_end_time

    conn = sqlite3.connect("data.sqlite")
    cur = conn.cursor()
    cur.execute("INSERT INTO records (user_id, username, date, entry_time) VALUES (?, ?, ?, ?)",
                (message.from_user.id, message.from_user.username, today.isoformat(), entry_time.strftime("%H:%M:%S")))
    conn.commit()
    conn.close()

    await message.answer(
        "👋 Добро пожаловать, {}!
"
        "⏰ Вход зафиксирован: <b>{}</b>
"
        "🕔 Планируемый выход: <b>{}</b>".format(
            message.from_user.first_name,
            entry_time.strftime('%H:%M:%S'),
            end_time.strftime('%H:%M:%S')
        ),
        parse_mode="HTML"
    )

@dp.message_handler(lambda m: m.text == "🏖️ Сегодня отпуск")
async def handle_vacation(message: types.Message):
    if not is_authorized(message.from_user.id):
        await message.answer("⛔ У вас нет доступа к этому боту.")
        return

    today = datetime.now().date()
    conn = sqlite3.connect("data.sqlite")
    cur = conn.cursor()
    cur.execute("INSERT INTO records (user_id, username, date, vacation) VALUES (?, ?, ?, 1)",
                (message.from_user.id, message.from_user.username, today.isoformat()))
    conn.commit()
    conn.close()
    await message.answer(f"🏖️ Отпуск на {today.strftime('%d.%m.%Y')} зарегистрирован!")

@dp.message_handler(commands=['месяц'])
async def handle_month(message: types.Message):
    if not is_authorized(message.from_user.id):
        await message.answer("⛔ У вас нет доступа к этому боту.")
        return

    now = datetime.now()
    month_start = now.replace(day=1).date()

    conn = sqlite3.connect("data.sqlite")
    cur = conn.cursor()
    cur.execute("SELECT date, entry_time, vacation FROM records WHERE user_id = ? AND date >= ? ORDER BY date",
                (message.from_user.id, month_start.isoformat()))
    rows = cur.fetchall()
    conn.close()

    if not rows:
        await message.answer("Нет записей за текущий месяц.")
        return

    report = "📅 Отчёт за {}
".format(now.strftime("%B %Y"))
    total_days = 0
    total_vac = 0

    for row in rows:
        day = date.fromisoformat(row[0]).strftime("%d.%m")
        if row[2] == 1:
            report += f"{day} — 🏖️ Отпуск
"
            total_vac += 1
        else:
            report += f"{day} — 🔘 Вход: {row[1]}
"
            total_days += 1

    report += f"\n📊 Рабочих дней: {total_days} | Отпускных: {total_vac}"
    await message.answer(report)

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
