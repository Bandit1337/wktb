import asyncio
import locale
import logging
import sqlite3
import os
from datetime import datetime, timedelta, date
from aiogram import Bot, Dispatcher, executor, types
from aiogram.dispatcher import filters
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InputFile

API_TOKEN = os.getenv("API_TOKEN")
AUTHORIZED_USERS = list(map(int, os.getenv("AUTHORIZED_IDS", "").split(",")))
OWNER_ID = int(os.getenv("OWNER_ID", "0"))  # Твой Telegram ID

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

# Главное меню с учётом статуса смены
def get_main_menu(on_shift):
    menu = ReplyKeyboardMarkup(resize_keyboard=True)
    if on_shift:
        menu.add(KeyboardButton("🏁 Завершить день"))
    else:
        menu.add(KeyboardButton("✅ Я на предприятии"))
    menu.add(KeyboardButton("📋 Больше функций"))
    return menu

more_menu = ReplyKeyboardMarkup(resize_keyboard=True)
more_menu.add(KeyboardButton("📊 Отчёт"), KeyboardButton("🏖️ Отпуск"))
more_menu.add(KeyboardButton("⚙️ Изменить смену"), KeyboardButton("📈 Аналитика"))
more_menu.add(KeyboardButton("📦 Бэкап сейчас"))
more_menu.add(KeyboardButton("⬅️ Назад"))

cancel_menu = ReplyKeyboardMarkup(resize_keyboard=True)
cancel_menu.add(KeyboardButton("❌ Отмена"))

report_menu = ReplyKeyboardMarkup(resize_keyboard=True)
report_menu.add(KeyboardButton("🗓️ За неделю"), KeyboardButton("📅 За месяц"))
report_menu.add(KeyboardButton("❌ Отмена"))

MONTHS_RU = {
    "January": "Январь", "February": "Февраль", "March": "Март", "April": "Апрель",
    "May": "Май", "June": "Июнь", "July": "Июль", "August": "Август",
    "September": "Сентябрь", "October": "Октябрь", "November": "Ноябрь", "December": "Декабрь"
}

# Смены с параметрами: (start_time, duration, is_evening)
SHIFTS = {
    "07:30": {"start": "07:30", "duration": 8.5, "evening": False},
    "08:30": {"start": "08:30", "duration": 8.5, "evening": False},
    "15:00": {"start": "15:00", "duration": 7.0, "evening": True},
    "16:00": {"start": "16:00", "duration": 7.0, "evening": True},
}

def init_db():
    conn = sqlite3.connect("data.sqlite")
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            date TEXT,
            entry_time TEXT,
            exit_time TEXT,
            vacation INTEGER DEFAULT 0
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS shifts (
            user_id INTEGER,
            start_time TEXT,
            effective_from TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS debt (
            user_id INTEGER,
            day TEXT,
            minutes INTEGER
        )
    """)
    conn.commit()
    conn.close()

init_db()

@dp.message_handler(commands=["start"])
async def start_handler(message: types.Message):
    if not is_authorized(message.from_user.id):
        await message.answer("⛔ У вас нет доступа к этому боту.")
        return

    if not user_has_shift(message.from_user.id):
        await ask_shift_type(message)
        return

    on_shift = check_user_on_shift(message.from_user.id)
    await message.answer("Выберите действие:", reply_markup=get_main_menu(on_shift))


def is_authorized(user_id):
    return user_id in AUTHORIZED_USERS


def user_has_shift(user_id):
    conn = sqlite3.connect("data.sqlite")
    cur = conn.cursor()
    cur.execute("SELECT * FROM shifts WHERE user_id = ?", (user_id,))
    result = cur.fetchone()
    conn.close()
    return result is not None


async def ask_shift_type(message):
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(KeyboardButton("🕗 Утренняя"), KeyboardButton("🌙 Вечерняя"))
    await message.answer("👋 Привет! Выбери свою смену:", reply_markup=markup)


@dp.message_handler(lambda m: m.text in ["🕗 Утренняя", "🌙 Вечерняя"])
async def choose_shift_time(message: types.Message):
    user_id = message.from_user.id
    shift_type = message.text
    if shift_type == "🕗 Утренняя":
        times = ["07:30", "08:30"]
    else:
        times = ["15:00", "16:00"]
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    for t in times:
        markup.add(KeyboardButton(t))
    markup.add(KeyboardButton("❌ Отмена"))
    await message.answer("⏱ Укажи время начала смены:", reply_markup=markup)


@dp.message_handler(lambda m: m.text in SHIFTS.keys())
async def save_user_shift(message: types.Message):
    user_id = message.from_user.id
    selected_time = message.text
    today = date.today().isoformat()

    conn = sqlite3.connect("data.sqlite")
    cur = conn.cursor()
    cur.execute("DELETE FROM shifts WHERE user_id = ?", (user_id,))
    cur.execute("INSERT INTO shifts (user_id, start_time, effective_from) VALUES (?, ?, ?)",
                (user_id, selected_time, today))
    conn.commit()
    conn.close()

    await message.answer(f"✅ Смена сохранена ({selected_time}).", reply_markup=get_main_menu(False))

def get_user_shift(user_id, target_date=None):
    conn = sqlite3.connect("data.sqlite")
    cur = conn.cursor()
    if target_date is None:
        target_date = date.today().isoformat()
    cur.execute(
        "SELECT start_time FROM shifts WHERE user_id = ? AND effective_from <= ? ORDER BY effective_from DESC LIMIT 1",
        (user_id, target_date))
    row = cur.fetchone()
    conn.close()
    if row:
        return SHIFTS.get(row[0])
    return None

def check_user_on_shift(user_id):
    conn = sqlite3.connect("data.sqlite")
    cur = conn.cursor()
    cur.execute("""
        SELECT 1 FROM records
        WHERE user_id = ? AND date = ? AND exit_time IS NULL AND vacation = 0
    """, (user_id, date.today().isoformat()))
    result = cur.fetchone()
    conn.close()
    return result is not None


@dp.message_handler(lambda m: m.text == "✅ Я на предприятии")
async def handle_entry(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username
    today = date.today().isoformat()
    now = datetime.now()
    now_str = now.strftime("%H:%M:%S")

    shift = get_user_shift(user_id)
    if not shift:
        await message.answer("⚠️ Не удалось определить смену.")
        await ask_shift_type(message)

    entry_time = datetime.strptime(shift['start'], "%H:%M").time()
    actual_entry = datetime.combine(date.today(), now.time())
    planned_start = datetime.combine(date.today(), entry_time)
    early = (planned_start - actual_entry).total_seconds() // 60
    if early < 0:
        early = 0

    # Сохраняем вход
    conn = sqlite3.connect("data.sqlite")
    cur = conn.cursor()
    cur.execute("INSERT INTO records (user_id, username, date, entry_time) VALUES (?, ?, ?, ?)",
                (user_id, username or "", today, now_str))
    conn.commit()
    conn.close()

    # Сообщаем про долг
    debt = get_total_debt(user_id)
    debt_str = ""
    if debt > 0:
        hours = debt // 60
        mins = debt % 60
        debt_str = f"📉 У тебя есть недоработка: {hours} час{'а' if 1 <= hours <= 4 else ''} {mins} минут\n"

    # Расчёт выхода
    work_minutes = int(shift['duration'] * 60)
    planned_exit = actual_entry + timedelta(minutes=work_minutes)
    await message.answer(
        f"{debt_str}🚪 Вход зарегистрирован!\n⏰ Вход: {now_str}\n🕔 Плановый выход: {planned_exit.strftime('%H:%M:%S')}",
        reply_markup=get_main_menu(True)
    )


def get_total_debt(user_id):
    conn = sqlite3.connect("data.sqlite")
    cur = conn.cursor()
    cur.execute("SELECT SUM(minutes) FROM debt WHERE user_id = ?", (user_id,))
    result = cur.fetchone()
    conn.close()
    return result[0] if result and result[0] is not None else 0

def update_debt(user_id, date_str, diff_minutes):
    conn = sqlite3.connect("data.sqlite")
    cur = conn.cursor()
    cur.execute("INSERT INTO debt (user_id, day, minutes) VALUES (?, ?, ?)",
                (user_id, date_str, diff_minutes))
    conn.commit()
    conn.close()


def reduce_debt(user_id, minutes_available):
    conn = sqlite3.connect("data.sqlite")
    cur = conn.cursor()
    cur.execute("SELECT day, minutes FROM debt WHERE user_id = ? ORDER BY day", (user_id,))
    rows = cur.fetchall()
    remaining = minutes_available

    for day, minutes in rows:
        if remaining <= 0:
            break
        to_deduct = min(remaining, minutes)
        new_balance = minutes - to_deduct
        if new_balance == 0:
            cur.execute("DELETE FROM debt WHERE user_id = ? AND day = ?", (user_id, day))
        else:
            cur.execute("UPDATE debt SET minutes = ? WHERE user_id = ? AND day = ?", (new_balance, user_id, day))
        remaining -= to_deduct

    conn.commit()
    conn.close()


@dp.message_handler(lambda m: m.text == "🏁 Завершить день")
async def handle_exit(message: types.Message):
    user_id = message.from_user.id
    today = date.today().isoformat()
    now = datetime.now().time()
    now_str = now.strftime("%H:%M:%S")

    shift = get_user_shift(user_id)
    if not shift:
        await message.answer("⚠️ Смена не найдена.")
        return

    conn = sqlite3.connect("data.sqlite")
    cur = conn.cursor()
    cur.execute("""
        SELECT entry_time FROM records
        WHERE user_id = ? AND date = ? AND exit_time IS NULL AND vacation = 0
    """, (user_id, today))
    row = cur.fetchone()

    if not row:
        await message.answer("⚠️ Вход не найден.")
        conn.close()
        return

    entry_time = datetime.strptime(row[0], "%H:%M:%S")
    exit_time = datetime.combine(date.today(), now)
    worked_minutes = int((exit_time - datetime.combine(date.today(), entry_time.time())).total_seconds() // 60)

    required_minutes = int(shift["duration"] * 60)
    overtime = worked_minutes - required_minutes

    # ❌ Вечерняя смена запрещает переработку
    if shift["evening"] and overtime > 0:
        overtime = 0

    if overtime < 0:
        update_debt(user_id, today, -overtime)
    elif overtime > 0:
        reduce_debt(user_id, overtime)

    cur.execute("""
        UPDATE records SET exit_time = ?
        WHERE user_id = ? AND date = ? AND exit_time IS NULL
    """, (now_str, user_id, today))
    conn.commit()
    conn.close()

    await message.answer(f"🏁 Выход зарегистрирован: {now_str}", reply_markup=get_main_menu(False))


@dp.message_handler(lambda m: m.text == "📋 Больше функций")
async def more_menu_handler(message: types.Message):
    await message.answer("Дополнительные функции:", reply_markup=more_menu)

@dp.message_handler(lambda m: m.text == "⬅️ Назад")
async def back_to_main(message: types.Message):
    on_shift = check_user_on_shift(message.from_user.id)
    await message.answer("Вы вернулись в главное меню.", reply_markup=get_main_menu(on_shift))

@dp.message_handler(lambda m: m.text == "⚙️ Изменить смену")
async def change_shift(message: types.Message):
    await ask_shift_type(message)

@dp.message_handler(lambda m: m.text == "📊 Отчёт")
async def report_menu_handler(message: types.Message):
    await message.answer("Выберите тип отчёта:", reply_markup=report_menu)


@dp.message_handler(lambda m: m.text == "📅 За месяц")
async def report_month(message: types.Message):
    now = datetime.now()
    first_day = date(now.year, now.month, 1)
    conn = sqlite3.connect("data.sqlite")
    cur = conn.cursor()
    cur.execute("""
        SELECT date, entry_time, exit_time, vacation
        FROM records
        WHERE user_id = ? AND date >= ?
        ORDER BY date
    """, (message.from_user.id, first_day.isoformat()))
    rows = cur.fetchall()
    conn.close()

    if not rows:
        await message.answer("😕 За этот месяц пока нет данных.")
        return

    total_days = 0
    total_vac = 0
    report = f"📅 Отчёт за {now.strftime('%B')}\n"
    for row in rows:
        d = date.fromisoformat(row[0]).strftime("%d.%m")
        if row[3]:
            report += f"{d} — 🏖️ Отпуск\n"
            total_vac += 1
        elif row[1] and row[2]:
            report += f"{d} — 🔘 {row[1]}–{row[2]}\n"
            total_days += 1
        else:
            report += f"{d} — 🔘 Вход: {row[1]}\n"
            total_days += 1

    report += f"\n📊 Рабочих дней: {total_days} | Отпускных: {total_vac}"
    await message.answer(report)


@dp.message_handler(lambda m: m.text == "🗓️ За неделю")
async def report_week(message: types.Message):
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    conn = sqlite3.connect("data.sqlite")
    cur = conn.cursor()
    cur.execute("""
        SELECT date, entry_time, exit_time, vacation
        FROM records
        WHERE user_id = ? AND date >= ?
        ORDER BY date
    """, (message.from_user.id, monday.isoformat()))
    rows = cur.fetchall()
    conn.close()

    if not rows:
        await message.answer("😕 За эту неделю пока нет данных.")
        return

    report = "🗓️ Отчёт за неделю:\n"
    for row in rows:
        d = date.fromisoformat(row[0]).strftime("%d.%m")
        if row[3]:
            report += f"{d} — 🏖️ Отпуск\n"
        elif row[1] and row[2]:
            report += f"{d} — 🔘 {row[1]}–{row[2]}\n"
        else:
            report += f"{d} — 🔘 Вход: {row[1]}\n"

    await message.answer(report)


@dp.message_handler(lambda m: m.text == "🏖️ Отпуск")
async def set_vacation(message: types.Message):
    await message.answer("Введите период отпуска:\nнапример: 01.07–05.07", reply_markup=cancel_menu)

@dp.message_handler(lambda m: "-" in m.text and len(m.text) <= 25, state=None)
async def handle_vacation_period(message: types.Message):
    try:
        user_id = message.from_user.id
        year = date.today().year

        # Убираем пробелы и заменяем длинное тире
        raw = message.text.replace(" ", "").replace("–", "-")
        start_str, end_str = raw.split("-")
        start_date = datetime.strptime(f"{start_str}.{year}", "%d.%m.%Y").date()
        end_date = datetime.strptime(f"{end_str}.{year}", "%d.%m.%Y").date()

        if end_date < start_date:
            await message.answer("⚠️ Дата окончания раньше начала.")
            return

        conn = sqlite3.connect("data.sqlite")
        cur = conn.cursor()

        current = start_date
        added = 0
        skipped = 0

        while current <= end_date:
            cur.execute("SELECT entry_time, exit_time FROM records WHERE user_id = ? AND date = ?", (user_id, current.isoformat()))
            row = cur.fetchone()
            if row and (row[0] or row[1]):
                skipped += 1  # уже есть реальные данные — не перезаписываем
            else:
                cur.execute("""
                    INSERT OR REPLACE INTO records (user_id, date, vacation)
                    VALUES (?, ?, 1)
                """, (user_id, current.isoformat()))
                added += 1
            current += timedelta(days=1)

        conn.commit()
        conn.close()

        if added == 0:
            await message.answer("⚠️ Отпуск не добавлен: во всех днях уже есть данные.")
        else:
            await message.answer(
                f"🏖️ Отпуск добавлен: {start_str}–{end_str}\n✅ Дней добавлено: {added}\n⏩ Пропущено (уже есть данные): {skipped}",
                reply_markup=get_main_menu(False)
            )

    except Exception:
        await message.answer("⚠️ Неверный формат. Пример: 01.07–05.07", reply_markup=cancel_menu)


@dp.message_handler(lambda m: m.text == "❌ Отмена")
async def cancel_action(message: types.Message):
    on_shift = check_user_on_shift(message.from_user.id)
    await message.answer("❌ Отменено.", reply_markup=get_main_menu(on_shift))

async def daily_backup():
    while True:
        now = datetime.now()
        target_time = now.replace(hour=21, minute=0, second=0, microsecond=0)
        if now >= target_time:
            target_time += timedelta(days=1)

        wait_seconds = (target_time - now).total_seconds()
        await asyncio.sleep(wait_seconds)

        try:
            backup_path = "backup.sqlite"
            with open("data.sqlite", "rb") as src, open(backup_path, "wb") as dst:
                dst.write(src.read())

            if OWNER_ID:
                await bot.send_document(OWNER_ID, InputFile(backup_path), caption="🗂 Бэкап за сегодня")

        except Exception as e:
            logging.error(f"[Бэкап] Ошибка при отправке: {e}")

@dp.message_handler(lambda m: m.text == "📈 Аналитика")
async def analytics_handler(message: types.Message):
    user_id = message.from_user.id
    now = datetime.now()
    first_day = date(now.year, now.month, 1)

    conn = sqlite3.connect("data.sqlite")
    cur = conn.cursor()
    cur.execute("""
        SELECT date, entry_time, exit_time FROM records
        WHERE user_id = ? AND date >= ? AND vacation = 0
    """, (user_id, first_day.isoformat()))
    rows = cur.fetchall()
    conn.close()

    if not rows:
        await message.answer("📈 Нет данных за этот месяц.")
        return

    total_days = 0
    total_minutes = 0
    total_entry = []
    total_exit = []
    overtime_days = 0
    debt_days = 0

    for row in rows:
        total_days += 1
        entry = datetime.strptime(row[1], "%H:%M:%S")
        if row[2]:
            exit = datetime.strptime(row[2], "%H:%M:%S")
            duration = (exit - entry).total_seconds() // 60
            total_minutes += duration
            total_entry.append(entry)
            total_exit.append(exit)

            if duration > 420:
                overtime_days += 1
            elif duration < 420:
                debt_days += 1

    avg_minutes = total_minutes // total_days if total_days else 0
    avg_entry = (
        sum([e.hour * 60 + e.minute for e in total_entry]) // len(total_entry)
        if total_entry else None
    )
    avg_exit = (
        sum([e.hour * 60 + e.minute for e in total_exit]) // len(total_exit)
        if total_exit else None
    )

    entry_time = f"{avg_entry // 60:02}:{avg_entry % 60:02}" if avg_entry else "—"
    exit_time = f"{avg_exit // 60:02}:{avg_exit % 60:02}" if avg_exit else "—"

    report = (
        f"📈 *Аналитика за {MONTHS_RU[now.month]}*\n\n"
        f"🔘 Смен: {total_days}\n"
        f"⏰ Средняя длительность: {avg_minutes // 60} ч {avg_minutes % 60} мин\n"
        f"🚪 Средний вход: {entry_time}\n"
        f"🏁 Средний выход: {exit_time}\n"
        f"📉 Долгов: {debt_days}\n"
        f"📈 Переработок: {overtime_days}"
    )

    await message.answer(report, parse_mode="Markdown")

@dp.message_handler(lambda m: m.text == "📦 Бэкап сейчас")
async def manual_backup(message: types.Message):
    if message.from_user.id != OWNER_ID:
        await message.answer("⛔ Только админ может получить бэкап.")
        return

    try:
        with open("data.sqlite", "rb") as f:
            await bot.send_document(message.from_user.id, InputFile(f, filename="data.sqlite"))
    except Exception as e:
        await message.answer(f"⚠️ Ошибка при отправке бэкапа: {e}")

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.create_task(daily_backup())
    executor.start_polling(dp, skip_updates=True)
