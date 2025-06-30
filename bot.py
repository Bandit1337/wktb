import logging
import os
import sqlite3
from datetime import datetime, timedelta, date
from aiogram import Bot, Dispatcher, executor, types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

# --- Config ---
API_TOKEN = os.getenv("API_TOKEN")
AUTHORIZED_USERS = list(map(int, os.getenv("AUTHORIZED_IDS", "").split(",")))

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

# --- Keyboards ---

def main_menu(on_shift: bool):
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    if on_shift:
        kb.add(KeyboardButton("🏁 Завершить день"))
    else:
        kb.add(KeyboardButton("✅ Я на предприятии"))
    kb.add(KeyboardButton("📋 Больше функций"))
    return kb

more_menu = ReplyKeyboardMarkup(resize_keyboard=True)
more_menu.add(
    KeyboardButton("📊 Отчёт"),
    KeyboardButton("🏖️ Отпуск"),
    KeyboardButton("⚙️ Изменить смену"),
    KeyboardButton("⬅️ Назад")
)
cancel_menu = ReplyKeyboardMarkup(resize_keyboard=True)
cancel_menu.add(KeyboardButton("❌ Отмена"))
shift_type_kb = ReplyKeyboardMarkup(resize_keyboard=True)
shift_type_kb.add(
    KeyboardButton("🕗 Утренняя"),
    KeyboardButton("🌙 Вечерняя")
)
shift_time_kb = {
    '🕗 Утренняя': ReplyKeyboardMarkup(resize_keyboard=True).add(
        KeyboardButton("07:30"), KeyboardButton("08:30")
    ),
    '🌙 Вечерняя': ReplyKeyboardMarkup(resize_keyboard=True).add(
        KeyboardButton("15:00"), KeyboardButton("16:00")
    )
}
report_kb = ReplyKeyboardMarkup(resize_keyboard=True)
report_kb.add(
    KeyboardButton("🗓️ За неделю"),
    KeyboardButton("📅 За месяц"),
    KeyboardButton("❌ Отмена")
)

# --- Database Init ---

def init_db():
    conn = sqlite3.connect("data.sqlite")
    cur = conn.cursor()
    cur.executescript('''
    CREATE TABLE IF NOT EXISTS shifts (
        user_id INTEGER,
        start_date TEXT,
        shift_type TEXT,
        shift_time TEXT
    );
    CREATE TABLE IF NOT EXISTS records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        date TEXT,
        entry_time TEXT,
        exit_time TEXT,
        vacation INTEGER DEFAULT 0
    );
    ''')
    conn.commit()
    conn.close()

init_db()
user_states = {}

# --- Helpers ---

def get_current_shift(user_id: int):
    conn = sqlite3.connect("data.sqlite")
    cur = conn.cursor()
    cur.execute(
        "SELECT shift_type, shift_time FROM shifts WHERE user_id=? AND start_date<=? ORDER BY start_date DESC LIMIT 1",
        (user_id, date.today().isoformat())
    )
    row = cur.fetchone()
    conn.close()
    return row  # (type, time)


def check_on_shift(user_id: int) -> bool:
    conn = sqlite3.connect("data.sqlite")
    cur = conn.cursor()
    cur.execute(
        "SELECT id FROM records WHERE user_id=? AND date=? AND exit_time IS NULL AND vacation=0",
        (user_id, date.today().isoformat())
    )
    exists = cur.fetchone() is not None
    conn.close()
    return exists


def parse_time(s: str) -> datetime.time:
    return datetime.strptime(s, "%H:%M").time()


def format_delta(td: timedelta) -> str:
    total_min = int(td.total_seconds() // 60)
    h, m = divmod(total_min, 60)
    parts = []
    if h:
        parts.append(f"{h} час{'ов' if h>1 else ''}")
    if m:
        parts.append(f"{m} минут")
    return ' '.join(parts) or '0 минут'


def calculate_end(user_id: int, entry_dt: datetime) -> datetime:
    shift = get_current_shift(user_id)
    if not shift:
        return entry_dt
    if shift[0] == '🕗 Утренняя':
        base = timedelta(hours=8, minutes=30)
        max_ot = base + timedelta(hours=4)
    else:
        base = timedelta(hours=7)
        max_ot = base
    start = datetime.combine(entry_dt.date(), parse_time(shift[1]))
    delay = entry_dt - start
    if delay < timedelta(0): delay = timedelta(0)
    planned = entry_dt + base + delay
    if planned - start > max_ot:
        planned = start + max_ot
    return planned


def calculate_debt(user_id: int) -> timedelta:
    first_day = date.today().replace(day=1).isoformat()
    conn = sqlite3.connect("data.sqlite")
    cur = conn.cursor()
    cur.execute(
        "SELECT entry_time, exit_time, vacation FROM records WHERE user_id=? AND date>=?",
        (user_id, first_day)
    )
    rows = cur.fetchall()
    conn.close()
    debt = timedelta(0)
    for et, xt, vac in rows:
        if vac: continue
        entry = datetime.strptime(et, "%H:%M")
        if not xt:
            continue
        exit_t = datetime.strptime(xt, "%H:%M")
        worked = exit_t - entry
        shift = get_current_shift(user_id)
        expected = timedelta(hours=8, minutes=30) if shift[0]=='🕗 Утренняя' else timedelta(hours=7)
        if worked < expected:
            debt += (expected - worked)
    return debt

# --- Handlers ---

@dp.message_handler(commands=['start'])
async def cmd_start(msg: types.Message):
    uid = msg.from_user.id
    if uid not in AUTHORIZED_USERS:
        return await msg.answer("⛔ У вас нет доступа.")
    shift = get_current_shift(uid)
    if not shift:
        user_states[uid] = 'choose_type'
        return await msg.answer("👋 Привет! Выбери смену:", reply_markup=shift_type_kb)
    if not check_on_shift(uid):
        debt = calculate_debt(uid)
        if debt > timedelta(0):
            await msg.answer(f"📉 У тебя есть недоработка: {format_delta(debt)}")
    return await msg.answer("Выбери действие:", reply_markup=main_menu(check_on_shift(uid)))

@dp.message_handler(lambda m: user_states.get(m.from_user.id)=='choose_type' and m.text in ['🕗 Утренняя','🌙 Вечерняя'])
async def choose_type(m: types.Message):
    user_states[m.from_user.id] = m.text
    await m.answer("Укажи время начала смены:", reply_markup=shift_time_kb[m.text])

@dp.message_handler(lambda m: user_states.get(m.from_user.id) in ['🕗 Утренняя','🌙 Вечерняя'] and m.text in ['07:30','08:30','15:00','16:00'])
async def choose_time(m: types.Message):
    uid = m.from_user.id
    shift_type = user_states.pop(uid)
    shift_time = m.text
    conn = sqlite3.connect("data.sqlite")
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO shifts(user_id,start_date,shift_type,shift_time) VALUES(?,?,?,?)",
        (uid, date.today().isoformat(), shift_type, shift_time)
    )
    conn.commit(); conn.close()
    await m.answer(f"✅ Смена установлена: {shift_type} в {shift_time}")
    return await cmd_start(m)

@dp.message_handler(lambda m: m.text=='✅ Я на предприятии')
async def do_entry(m: types.Message):
    uid = m.from_user.id
    now = datetime.now()
    conn = sqlite3.connect("data.sqlite")
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO records(user_id,date,entry_time) VALUES(?,?,?)",
        (uid, now.date().isoformat(), now.strftime("%H:%M"))
    )
    conn.commit(); conn.close()
    planned = calculate_end(uid, now)
    debt = calculate_debt(uid)
    text = f"🚪 Из: {now.strftime('%H:%M')} до: {planned.strftime('%H:%M')}"
    if debt>timedelta(0):
        text = f"📉 У тебя недоработка: {format_delta(debt)}\n" + text
    await m.answer(text, reply_markup=main_menu(True))

@dp.message_handler(lambda m: m.text=='🏁 Завершить день')
async def do_exit(m: types.Message):
    uid = m.from_user.id; now = datetime.now()
    conn = sqlite3.connect("data.sqlite"); cur = conn.cursor()
    cur.execute(
        "UPDATE records SET exit_time=? WHERE user_id=? AND date=? AND exit_time IS NULL",
        (now.strftime("%H:%M"), uid, now.date().isoformat())
    )
    conn.commit(); conn.close()
    await m.answer(f"🏁 Выход: {now.strftime('%H:%M')}", reply_markup=main_menu(False))

@dp.message_handler(lambda m: m.text=='📋 Больше функций')
async def more_funcs(m: types.Message): await m.answer("Дополнительные функции:", reply_markup=more_menu)

@dp.message_handler(lambda m: m.text=='⚙️ Изменить смену')
async def change_shift(m: types.Message):
    user_states[m.from_user.id] = 'choose_type'
    await m.answer("👤 Изменение смены. Выбери тип:", reply_markup=shift_type_kb)

@dp.message_handler(lambda m: m.text=='🏖️ Отпуск')
async def vacation(m: types.Message):
    user_states[m.from_user.id] = 'vacation'
    await m.answer("Введите период отпуска (дд.мм–дд.мм):", reply_markup=cancel_menu)

@dp.message_handler(lambda m: user_states.get(m.from_user.id)=='vacation')
async def set_vacation(m: types.Message):
    text = m.text.strip()
    if text.lower()=='❌ отмена':
        user_states.pop(m.from_user.id, None)
        return await m.answer("Отпуск отменён.", reply_markup=more_menu)
    try:
        start_s, end_s = text.split('–')
        start = datetime.strptime(start_s, '%d.%m').replace(year=date.today().year)
        end = datetime.strptime(end_s, '%d.%m').replace(year=date.today().year)
        days = (end.date() - start.date()).days + 1
        conn = sqlite3.connect("data.sqlite"); cur = conn.cursor()
        for i in range(days):
            d = (start + timedelta(days=i)).date().isoformat()
            cur.execute("INSERT OR IGNORE INTO records(user_id,date,vacation) VALUES(?,?,1)", (m.from_user.id, d))
        conn.commit(); conn.close()
        user_states.pop(m.from_user.id, None)
        return await m.answer(f"🏖️ Отпуск сохранён: {text}", reply_markup=more_menu)
    except:
        return await m.answer("Неверный формат. Введите дд.мм–дд.мм или ❌ Отмена.", reply_markup=cancel_menu)

@dp.message_handler(lambda m: m.text=='📊 Отчёт')
async def show_report(m: types.Message): await m.answer("Выберите отчёт:", reply_markup=report_kb)

@dp.message_handler(lambda m: m.text=='🗓️ За неделю')
async def report_week(m: types.Message):
    uid = m.from_user.id; today = date.today()
    monday = today - timedelta(days=today.weekday())
    conn = sqlite3.connect("data.sqlite"); cur = conn.cursor()
    cur.execute("SELECT date,entry_time,exit_time,vacation FROM records WHERE user_id=? AND date>=?",
                (uid, monday.isoformat(),))
    rows = cur.fetchall(); conn.close()
    if not rows: return await m.answer("😕 За эту неделю нет данных.")
    txt = "🗓️ Отчёт за неделю:\n"
    for d,e,x,v in rows:
        day = datetime.fromisoformat(d).strftime('%d.%m')
        if v:
            txt += f"{day} — 🏖️\n"
        elif e and x:
            txt += f"{day} {e}-{x}\n"
        else:
            txt += f"{day} — 🔘 {e or ''}\n"
    await m.answer(txt)

@dp.message_handler(lambda m: m.text=='📅 За месяц')
async def report_month(m: types.Message):
    uid = m.from_user.id; first = date.today().replace(day=1)
    conn = sqlite3.connect("data.sqlite"); cur = conn.cursor()
    cur.execute("SELECT date,entry_time,exit_time,vacation FROM records WHERE user_id=? AND date>=?",
                (uid, first.isoformat(),))
    rows = cur.fetchall(); conn.close()
    if not rows: return await m.answer("😕 За этот месяц нет данных.")
    txt = "📅 Отчёт за месяц:\n"
    for d,e,x,v in rows:
        day = datetime.fromisoformat(d).strftime('%d.%m')
        if v:
            txt += f"{day} — 🏖️\n"
        elif e and x:
            txt += f"{day} {e}-{x}\n"
        else:
            txt += f"{day} — 🔘 {e or ''}\n"
    await m.answer(txt)

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
