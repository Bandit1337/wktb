
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

# Главное меню
main_menu = ReplyKeyboardMarkup(resize_keyboard=True)
main_menu.add(KeyboardButton("✅ Я на предприятии"))
main_menu.add(KeyboardButton("📋 Больше функций"))

# Меню "Больше функций"
more_menu = ReplyKeyboardMarkup(resize_keyboard=True)
more_menu.add(KeyboardButton("📆 Отчёт за месяц"), KeyboardButton("🏖️ Отпуск"))
more_menu.add(KeyboardButton("⬅️ Назад"))

# Кнопка отмены
cancel_menu = ReplyKeyboardMarkup(resize_keyboard=True)
cancel_menu.add(KeyboardButton("❌ Отмена"))

# Авторизация
def is_authorized(user_id):
    return user_id in AUTHORIZED_USERS

# База данных
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
async def start_handler(message: types.Message):
    if not is_authorized(message.from_user.id):
        await message.answer("⛔ У вас нет доступа к этому боту.")
        return
    await message.answer("Добро пожаловать! Выберите действие:", reply_markup=main_menu)

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
        "👋 Добро пожаловать, {}!\n"
        "⏰ Вход зафиксирован: <b>{}</b>\n"
        "🕔 Планируемый выход: <b>{}</b>".format(
            message.from_user.first_name,
            entry_time.strftime('%H:%M:%S'),
            end_time.strftime('%H:%M:%S')
        ),
        parse_mode="HTML"
    )

@dp.message_handler(lambda m: m.text == "📋 Больше функций")
async def more_menu_handler(message: types.Message):
    await message.answer("Дополнительные функции:", reply_markup=more_menu)

@dp.message_handler(lambda m: m.text == "⬅️ Назад")
async def back_to_main(message: types.Message):
    await message.answer("Вы вернулись в главное меню.", reply_markup=main_menu)

@dp.message_handler(lambda m: m.text == "🏖️ Отпуск")
async def vacation_request(message: types.Message):
    await message.answer(
        "Введите период отпуска (например: 01.07–05.07)\n\n"
        "❗ Или нажмите ❌ Отмена",
        reply_markup=cancel_menu
    )

@dp.message_handler(lambda m: m.text == "📆 Отчёт за месяц")
async def choose_month(message: types.Message):
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    now = datetime.now()
    months = []
    for i in range(3):
        m = now.month - i
        y = now.year
        if m <= 0:
            m += 12
            y -= 1
        months.append((m, y))
    for m, y in months:
        label = date(y, m, 1).strftime("%B %Y")
        markup.add(KeyboardButton(label))
    markup.add(KeyboardButton("❌ Отмена"))
    await message.answer("Выберите месяц для отчёта:", reply_markup=markup)

@dp.message_handler(lambda m: m.text == "❌ Отмена")
async def cancel_handler(message: types.Message):
    await message.answer("Действие отменено.", reply_markup=more_menu)

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
