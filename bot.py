import os
import time
import json
import shutil
import threading
from datetime import datetime, timedelta
from flask import Flask
import telebot
from telebot import types

# ============================================
# КОНФИГУРАЦИЯ
# ============================================

TOKEN = os.environ.get('TELEGRAM_TOKEN')
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# Пути к данным (Render использует временную файловую систему)
DATA_FILE = 'bot_data.json'
BACKUP_DIR = 'backups'

if not os.path.exists(BACKUP_DIR):
    os.makedirs(BACKUP_DIR)

# ============================================
# СИСТЕМА ХРАНЕНИЯ ДАННЫХ
# ============================================

def get_default_data():
    return {
        "log": [],
        "goal": None,
        "goal_date": None,
        "settings": {"last_id": 0}
    }

def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if 'goal_date' not in data:
                    data['goal_date'] = None
                if 'settings' not in data:
                    data['settings'] = {"last_id": 0}
                if 'last_id' not in data['settings']:
                    data['settings']['last_id'] = 0
                if 'log' not in data:
                    data['log'] = []
                return data
        except Exception as e:
            print(f"Ошибка загрузки данных: {e}")
            return get_default_data()
    return get_default_data()

def save_data(data):
    try:
        backup_filename = f"{BACKUP_DIR}/backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        if os.path.exists(DATA_FILE):
            shutil.copy2(DATA_FILE, backup_filename)
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"Ошибка сохранения данных: {e}")
        return False

def get_next_id(data):
    try:
        if 'settings' not in data:
            data['settings'] = {"last_id": 0}
        if 'last_id' not in data['settings']:
            data['settings']['last_id'] = 0
        data['settings']['last_id'] += 1
        return data['settings']['last_id']
    except Exception as e:
        print(f"Ошибка в get_next_id: {e}")
        return len(data.get('log', [])) + 1

# ============================================
# ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ
# ============================================

data = load_data()
user_state = {}
temp_data = {}

# ============================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================

def format_number(number):
    return f"{number:.2f}"

def get_date_now():
    return datetime.now().strftime('%d.%m.%Y %H:%M')

def get_date_only():
    return datetime.now().strftime('%d.%m.%Y')

def create_progress_bar(progress, length=20):
    filled = int((progress / 100) * length)
    return "█" * filled + "░" * (length - filled)

def get_log_summary(data):
    log = data.get('log', [])
    if not log:
        return 0, 0, 0, 0, 0
    total = sum(entry.get('amount', 0) for entry in log)
    count = len(log)
    avg = total / count if count > 0 else 0
    max_amount = max(entry.get('amount', 0) for entry in log) if log else 0
    min_amount = min(entry.get('amount', 0) for entry in log) if log else 0
    return total, count, avg, max_amount, min_amount

# ============================================
# ГЛАВНОЕ МЕНЮ
# ============================================

@bot.message_handler(commands=['start', 'menu'])
def show_main_menu(message):
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    btn1 = types.KeyboardButton('💰 Расчеты')
    btn2 = types.KeyboardButton('📋 Лог')
    btn3 = types.KeyboardButton('🎯 Цель')
    btn4 = types.KeyboardButton('📊 Статистика')
    btn5 = types.KeyboardButton('ℹ️ Помощь')
    markup.add(btn1, btn2, btn3, btn4, btn5)
    bot.send_message(
        message.chat.id,
        "🏠 *БОТ ФИНАНСОВЫЙ ПОМОЩНИК*\n\nВыберите действие:",
        reply_markup=markup,
        parse_mode='Markdown'
    )

# ============================================
# БЫСТРЫЕ КОМАНДЫ
# ============================================

@bot.message_handler(commands=['calc'])
def quick_calc(message):
    show_calc_menu(message)

@bot.message_handler(commands=['log'])
def quick_log(message):
    show_log_menu(message)

@bot.message_handler(commands=['goal'])
def quick_goal(message):
    show_goal_menu(message)

@bot.message_handler(commands=['stats'])
def quick_stats(message):
    show_stats_menu(message)

@bot.message_handler(commands=['help'])
def quick_help(message):
    show_help(message)

# ============================================
# РЕЖИМ РАСЧЕТОВ
# ============================================

@bot.message_handler(func=lambda message: message.text == '💰 Расчеты')
def show_calc_menu(message):
    user_state[message.chat.id] = 'calc'
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    btn1 = types.KeyboardButton('🔢 Ввести число')
    btn2 = types.KeyboardButton('📋 Добавить в лог')
    btn3 = types.KeyboardButton('🏠 Главное меню')
    markup.add(btn1, btn2, btn3)
    bot.send_message(
        message.chat.id,
        "💰 *КАЛЬКУЛЯТОР*\n\nВведите число для расчета:\n"
        "📌 *Пример:* 1000\n  1000 - 26% = 740.00 (вычтено 260.00)\n  1000 - 6% = 940.00 (вычтено 60.00)\n\n"
        "📌 Можно ввести несколько чисел через запятую:\n  1200, 1500, 1221, 10004",
        reply_markup=markup,
        parse_mode='Markdown'
    )

@bot.message_handler(func=lambda message: message.text == '🔢 Ввести число' and user_state.get(message.chat.id) == 'calc')
def ask_for_number(message):
    msg = bot.send_message(
        message.chat.id,
        "Введите число или несколько чисел через запятую:\n📌 Пример: 1200, 1500, 1221, 10004"
    )
    bot.register_next_step_handler(msg, process_number_calc)

def process_number_calc(message):
    try:
        text = message.text.strip()
        if ',' in text:
            numbers = []
            for x in text.split(','):
                x = x.strip().replace(' ', '')
                if x:
                    numbers.append(float(x))
            if len(numbers) == 1:
                process_single_number(message, numbers[0])
            else:
                for number in numbers:
                    process_single_number(message, number)
                bot.send_message(message.chat.id, f"✅ Обработано *{len(numbers)}* чисел!", parse_mode='Markdown')
            return
        number = float(text.replace(' ', ''))
        process_single_number(message, number)
    except ValueError:
        bot.reply_to(message, "❌ Пожалуйста, введите корректные числа!")

def process_single_number(message, number):
    temp_data[message.chat.id] = number
    result_26 = number * 0.74
    result_6 = number * 0.94
    subtracted_26 = number * 0.26
    subtracted_6 = number * 0.06

    formatted_number = f"{number:.2f}"
    formatted_26 = f"{result_26:.2f}"
    formatted_6 = f"{result_6:.2f}"
    formatted_sub_26 = f"{subtracted_26:.2f}"
    formatted_sub_6 = f"{subtracted_6:.2f}"

    markup = types.InlineKeyboardMarkup(row_width=2)
    btn26 = types.InlineKeyboardButton("➕ 26% (чистые)", callback_data=f"add_26_{number}")
    btn6 = types.InlineKeyboardButton("➕ 6% (с комиссией)", callback_data=f"add_6_{number}")
    btn_both = types.InlineKeyboardButton("➕ Добавить оба", callback_data=f"add_both_{number}")
    markup.add(btn26, btn6, btn_both)

    bot.send_message(
        message.chat.id,
        f"📊 *Результаты для {formatted_number}:*\n\n"
        f"🔹 26%: {formatted_number} - 26% = *{formatted_26}*\n   (вычтено {formatted_sub_26})\n\n"
        f"🔸 6%: {formatted_number} - 6% = *{formatted_6}*\n   (вычтено {formatted_sub_6})\n\n"
        f"Выберите, что добавить в лог:",
        reply_markup=markup,
        parse_mode='Markdown'
    )

@bot.message_handler(func=lambda message: message.text == '📋 Добавить в лог' and user_state.get(message.chat.id) == 'calc')
def add_custom_to_log(message):
    msg = bot.send_message(
        message.chat.id,
        "Введите сумму для добавления в лог (можно с комментарием):\n📌 Пример: 1000 или 1000 приход"
    )
    bot.register_next_step_handler(msg, process_custom_log)

def process_custom_log(message):
    try:
        parts = message.text.split(' ', 1)
        amount = float(parts[0].replace(',', '').replace(' ', ''))
        description = parts[1] if len(parts) > 1 else "Ручной ввод"
        data = load_data()
        entry = {
            "id": get_next_id(data),
            "date": get_date_now(),
            "amount": amount,
            "type": "manual",
            "original_amount": amount,
            "description": description
        }
        data['log'].append(entry)
        save_data(data)
        bot.send_message(
            message.chat.id,
            f"✅ Сумма *{format_number(amount)}* добавлена в лог!\n📝 Описание: {description}",
            parse_mode='Markdown'
        )
    except ValueError:
        bot.reply_to(message, "❌ Пожалуйста, введите корректную сумму!")

# ============================================
# ОБРАБОТЧИКИ ИНЛАЙН КНОПОК
# ============================================

@bot.callback_query_handler(func=lambda call: call.data.startswith('add_26_') or call.data.startswith('add_6_') or call.data.startswith('add_both_'))
def handle_add_to_log(call):
    try:
        data = load_data()
        if 'settings' not in data:
            data['settings'] = {"last_id": 0}
        if 'last_id' not in data['settings']:
            data['settings']['last_id'] = 0

        if call.data.startswith('add_both_'):
            number = float(call.data.replace('add_both_', ''))
            result_26 = number * 0.74
            result_6 = number * 0.94
            entry1 = {"id": get_next_id(data), "date": get_date_now(), "amount": result_26, "type": "26%", "original_amount": number, "description": "Чистая прибыль (26%)"}
            entry2 = {"id": get_next_id(data), "date": get_date_now(), "amount": result_6, "type": "6%", "original_amount": number, "description": "С комиссией (6%)"}
            data['log'].append(entry1)
            data['log'].append(entry2)
            save_data(data)
            bot.edit_message_text(
                f"✅ Добавлены оба варианта:\n26%: *{format_number(result_26)}*\n6%: *{format_number(result_6)}*",
                call.message.chat.id, call.message.message_id, parse_mode='Markdown'
            )
        elif call.data.startswith('add_26_'):
            number = float(call.data.replace('add_26_', ''))
            result = number * 0.74
            entry = {"id": get_next_id(data), "date": get_date_now(), "amount": result, "type": "26%", "original_amount": number, "description": "Чистая прибыль (26%)"}
            data['log'].append(entry)
            save_data(data)
            bot.edit_message_text(
                f"✅ Добавлено в лог:\nСумма: *{format_number(result)}* (26% от {format_number(number)})",
                call.message.chat.id, call.message.message_id, parse_mode='Markdown'
            )
        elif call.data.startswith('add_6_'):
            number = float(call.data.replace('add_6_', ''))
            result = number * 0.94
            entry = {"id": get_next_id(data), "date": get_date_now(), "amount": result, "type": "6%", "original_amount": number, "description": "С комиссией (6%)"}
            data['log'].append(entry)
            save_data(data)
            bot.edit_message_text(
                f"✅ Добавлено в лог:\nСумма: *{format_number(result)}* (6% от {format_number(number)})",
                call.message.chat.id, call.message.message_id, parse_mode='Markdown'
            )
        bot.answer_callback_query(call.id, "✅ Добавлено в лог")
    except Exception as e:
        print(f"Ошибка: {e}")
        try:
            bot.answer_callback_query(call.id, "❌ Ошибка")
        except:
            pass

# ============================================
# РЕЖИМ ЛОГА
# ============================================

@bot.message_handler(func=lambda message: message.text == '📋 Лог')
def show_log_menu(message):
    user_state[message.chat.id] = 'log'
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    btn1 = types.KeyboardButton('📖 Просмотреть')
    btn2 = types.KeyboardButton('➕ Добавить')
    btn3 = types.KeyboardButton('🗑️ Удалить')
    btn4 = types.KeyboardButton('🧹 Очистить')
    btn5 = types.KeyboardButton('📊 Сумма')
    btn6 = types.KeyboardButton('📤 Экспорт')
    btn7 = types.KeyboardButton('🔍 Фильтр')
    btn8 = types.KeyboardButton('🏠 Главное меню')
    markup.add(btn1, btn2, btn3, btn4, btn5, btn6, btn7, btn8)

    data = load_data()
    total, count, _, _, _ = get_log_summary(data)
    bot.send_message(
        message.chat.id,
        f"📋 *ЛОГ*\n\n📊 Всего записей: *{count}*\n💰 Общая сумма: *{format_number(total)}*\n\nВыберите действие:",
        reply_markup=markup,
        parse_mode='Markdown'
    )

@bot.message_handler(func=lambda message: message.text == '📖 Просмотреть' and user_state.get(message.chat.id) == 'log')
def view_log(message):
    data = load_data()
    log = data['log']
    if not log:
        bot.reply_to(message, "📭 Лог пуст")
        return

    log_text = "📋 *ЛОГ (все записи)*\n" + "═" * 30 + "\n\n"
    sorted_log = sorted(log, key=lambda x: x['date'], reverse=True)
    for i, entry in enumerate(sorted_log, 1):
        log_text += f"*№{i}*: {entry['date']}\n💰 {format_number(entry['amount'])} ₽"
        if entry.get('type') and entry['type'] != 'manual':
            log_text += f" | {entry['type']}"
        if entry.get('description'):
            log_text += f"\n📝 {entry['description']}"
        log_text += "\n\n"

    total, count, avg, max_amt, min_amt = get_log_summary(data)
    log_text += "═" * 30 + "\n"
    log_text += f"📊 *Итого:* {format_number(total)} ₽\n"
    log_text += f"📈 *Средняя:* {format_number(avg)} ₽\n"
    log_text += f"📈 *Макс:* {format_number(max_amt)} ₽\n"
    log_text += f"📉 *Мин:* {format_number(min_amt)} ₽"
    bot.send_message(message.chat.id, log_text, parse_mode='Markdown')

@bot.message_handler(func=lambda message: message.text == '➕ Добавить' and user_state.get(message.chat.id) == 'log')
def add_to_log(message):
    msg = bot.send_message(
        message.chat.id,
        "Введите сумму для добавления в лог:\n📌 Можно добавить комментарий: '1000 приход от клиента'"
    )
    bot.register_next_step_handler(msg, process_custom_log)

@bot.message_handler(func=lambda message: message.text == '🗑️ Удалить' and user_state.get(message.chat.id) == 'log')
def delete_from_log(message):
    data = load_data()
    log = data['log']
    if not log:
        bot.reply_to(message, "📭 Лог пуст")
        return

    markup = types.InlineKeyboardMarkup(row_width=2)
    sorted_log = sorted(log, key=lambda x: x['date'], reverse=True)
    for i, entry in enumerate(sorted_log[:10], 1):
        btn = types.InlineKeyboardButton(
            f"№{i} | {entry['date']} | {format_number(entry['amount'])}",
            callback_data=f"delete_log_{entry['id']}"
        )
        markup.add(btn)
    btn_cancel = types.InlineKeyboardButton("❌ Отмена", callback_data="cancel_delete")
    markup.add(btn_cancel)
    bot.send_message(
        message.chat.id,
        "🗑️ *Выберите запись для удаления:*\n(показываю последние 10)",
        reply_markup=markup,
        parse_mode='Markdown'
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('delete_log_'))
def handle_delete_log(call):
    data = load_data()
    entry_id = int(call.data.replace('delete_log_', ''))
    for i, entry in enumerate(data['log']):
        if entry['id'] == entry_id:
            deleted = data['log'].pop(i)
            save_data(data)
            bot.edit_message_text(
                f"🗑️ Запись удалена:\n📅 {deleted['date']}\n💰 {format_number(deleted['amount'])} ₽",
                call.message.chat.id, call.message.message_id, parse_mode='Markdown'
            )
            bot.answer_callback_query(call.id, "✅ Запись удалена")
            return
    bot.answer_callback_query(call.id, "❌ Запись не найдена")

@bot.callback_query_handler(func=lambda call: call.data == 'cancel_delete')
def handle_cancel_delete(call):
    bot.edit_message_text("❌ Удаление отменено", call.message.chat.id, call.message.message_id)
    bot.answer_callback_query(call.id)

@bot.message_handler(func=lambda message: message.text == '🧹 Очистить' and user_state.get(message.chat.id) == 'log')
def clear_log(message):
    markup = types.InlineKeyboardMarkup()
    btn_yes = types.InlineKeyboardButton("✅ Да, очистить", callback_data="confirm_clear")
    btn_no = types.InlineKeyboardButton("❌ Нет, отмена", callback_data="cancel_clear")
    markup.add(btn_yes, btn_no)
    bot.send_message(
        message.chat.id,
        "⚠️ *ВНИМАНИЕ!*\n\nВы уверены, что хотите очистить весь лог?\nЭто действие НЕЛЬЗЯ отменить!",
        reply_markup=markup,
        parse_mode='Markdown'
    )

@bot.callback_query_handler(func=lambda call: call.data == 'confirm_clear')
def handle_confirm_clear(call):
    data = load_data()
    data['log'] = []
    save_data(data)
    bot.edit_message_text("🧹 Лог очищен!", call.message.chat.id, call.message.message_id)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == 'cancel_clear')
def handle_cancel_clear(call):
    bot.edit_message_text("❌ Очистка отменена", call.message.chat.id, call.message.message_id)
    bot.answer_callback_query(call.id)

@bot.message_handler(func=lambda message: message.text == '📊 Сумма' and user_state.get(message.chat.id) == 'log')
def show_log_summary(message):
    data = load_data()
    log = data['log']
    if not log:
        bot.reply_to(message, "📭 Лог пуст")
        return

    total, count, avg, max_amt, min_amt = get_log_summary(data)
    type_26 = sum(entry['amount'] for entry in log if entry.get('type') == '26%')
    type_6 = sum(entry['amount'] for entry in log if entry.get('type') == '6%')
    type_manual = sum(entry['amount'] for entry in log if entry.get('type') == 'manual')
    count_26 = len([e for e in log if e.get('type') == '26%'])
    count_6 = len([e for e in log if e.get('type') == '6%'])

    today = get_date_only()
    week_ago = (datetime.now() - timedelta(days=7)).strftime('%d.%m.%Y')
    month_ago = (datetime.now() - timedelta(days=30)).strftime('%d.%m.%Y')

    today_sum = sum(entry['amount'] for entry in log if entry['date'].startswith(today))
    week_sum = sum(entry['amount'] for entry in log if entry['date'].split()[0] >= week_ago)
    month_sum = sum(entry['amount'] for entry in log if entry['date'].split()[0] >= month_ago)

    stats_text = f"📊 *СТАТИСТИКА ЛОГА*\n\n"
    stats_text += f"📋 Всего записей: *{count}*\n💰 Общая сумма: *{format_number(total)}*\n"
    stats_text += f"📈 Средняя: *{format_number(avg)}*\n📈 Макс: *{format_number(max_amt)}*\n📉 Мин: *{format_number(min_amt)}*\n\n"
    stats_text += "═" * 30 + "\n*По типам:*\n"
    stats_text += f"26%: {count_26} записей | {format_number(type_26)} ₽\n"
    stats_text += f"6%: {count_6} записей | {format_number(type_6)} ₽\n"
    if type_manual > 0:
        stats_text += f"Ручные: {format_number(type_manual)} ₽\n"
    stats_text += "\n═" * 30 + "\n*По периодам:*\n"
    stats_text += f"📅 Сегодня: {format_number(today_sum)} ₽\n"
    stats_text += f"📅 За неделю: {format_number(week_sum)} ₽\n"
    stats_text += f"📅 За месяц: {format_number(month_sum)} ₽"
    bot.send_message(message.chat.id, stats_text, parse_mode='Markdown')

@bot.message_handler(func=lambda message: message.text == '📤 Экспорт' and user_state.get(message.chat.id) == 'log')
def export_log(message):
    data = load_data()
    log = data['log']
    if not log:
        bot.reply_to(message, "📭 Лог пуст")
        return

    filename = f"log_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    with open(filename, 'w', encoding='utf-8') as f:
        f.write("=" * 50 + "\n       ВЫГРУЗКА ЛОГА\n" + "=" * 50 + "\n\n")
        sorted_log = sorted(log, key=lambda x: x['date'])
        total = 0
        for entry in sorted_log:
            f.write(f"№{entry.get('id', '?')}: {entry['date']}\nСумма: {format_number(entry['amount'])} ₽")
            if entry.get('type') and entry['type'] != 'manual':
                f.write(f" | {entry['type']}")
            if entry.get('description'):
                f.write(f"\nОписание: {entry['description']}")
            f.write("\n\n")
            total += entry['amount']
        f.write("=" * 50 + f"\nИТОГО: {format_number(total)} ₽")

    with open(filename, 'rb') as f:
        bot.send_document(message.chat.id, f, caption="📤 Экспорт лога")
    os.remove(filename)

@bot.message_handler(func=lambda message: message.text == '🔍 Фильтр' and user_state.get(message.chat.id) == 'log')
def filter_log(message):
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn_all = types.InlineKeyboardButton("📊 Все", callback_data="filter_all")
    btn_26 = types.InlineKeyboardButton("🔹 26%", callback_data="filter_26")
    btn_6 = types.InlineKeyboardButton("🔸 6%", callback_data="filter_6")
    btn_manual = types.InlineKeyboardButton("📝 Ручные", callback_data="filter_manual")
    markup.add(btn_all, btn_26, btn_6, btn_manual)
    bot.send_message(message.chat.id, "🔍 *Выберите фильтр:*", reply_markup=markup, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data.startswith('filter_'))
def handle_filter(call):
    data = load_data()
    filter_type = call.data.replace('filter_', '')
    if filter_type == 'all':
        filtered = data['log']
        title = "Все записи"
    else:
        filtered = [e for e in data['log'] if e.get('type') == filter_type]
        title = f"Записи по типу: {filter_type}"

    if not filtered:
        bot.edit_message_text(f"📭 Нет записей для фильтра '{title}'", call.message.chat.id, call.message.message_id)
        return

    log_text = f"📋 *{title}*\n" + "═" * 30 + "\n\n"
    sorted_log = sorted(filtered, key=lambda x: x['date'], reverse=True)
    for entry in sorted_log[:10]:
        log_text += f"📅 {entry['date']}\n💰 {format_number(entry['amount'])} ₽"
        if entry.get('type') and entry['type'] != 'manual':
            log_text += f" | {entry['type']}"
        if entry.get('description'):
            log_text += f"\n📝 {entry['description']}"
        log_text += "\n\n"
    if len(sorted_log) > 10:
        log_text += f"... и еще {len(sorted_log) - 10} записей\n\n"
    total = sum(entry['amount'] for entry in filtered)
    log_text += f"📊 *Итого:* {format_number(total)} ₽"
    bot.edit_message_text(log_text, call.message.chat.id, call.message.message_id, parse_mode='Markdown')
    bot.answer_callback_query(call.id)

# ============================================
# РЕЖИМ ЦЕЛИ
# ============================================

@bot.message_handler(func=lambda message: message.text == '🎯 Цель')
def show_goal_menu(message):
    user_state[message.chat.id] = 'goal'
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    btn1 = types.KeyboardButton('🎯 Установить')
    btn2 = types.KeyboardButton('📊 Статистика')
    btn3 = types.KeyboardButton('✏️ Редактировать')
    btn4 = types.KeyboardButton('🗑️ Удалить')
    btn5 = types.KeyboardButton('🏠 Главное меню')
    markup.add(btn1, btn2, btn3, btn4, btn5)

    data = load_data()
    if data.get('goal'):
        goal = data['goal']
        total_log = sum(entry['amount'] for entry in data['log'])
        remaining = goal - total_log
        progress = (total_log / goal) * 100 if goal > 0 else 0
        bar = create_progress_bar(progress)

        stats_text = f"🎯 *ТЕКУЩАЯ ЦЕЛЬ*\n\n💰 Цель: *{format_number(goal)}* ₽\n"
        stats_text += f"📊 Собрано: *{format_number(total_log)}* ₽ ({progress:.1f}%)\n"
        stats_text += f"📉 Осталось: *{format_number(remaining)}* ₽\n[{bar}] {progress:.1f}%\n"

        if data.get('goal_date'):
            goal_date = datetime.strptime(data['goal_date'], '%d.%m.%Y')
            days_left = (goal_date - datetime.now()).days
            if days_left > 0:
                per_day = remaining / days_left
                stats_text += f"\n📅 До цели: *{days_left}* дней\n📈 Нужно в день: *{format_number(per_day)}* ₽"
            elif days_left == 0:
                stats_text += f"\n🎯 *СЕГОДНЯ ПОСЛЕДНИЙ ДЕНЬ!*"
            else:
                stats_text += f"\n⏰ *Срок истек!* (просрочено {abs(days_left)} дней)"

        bot.send_message(message.chat.id, stats_text, reply_markup=markup, parse_mode='Markdown')
    else:
        bot.send_message(message.chat.id, "❌ Цель не установлена!\n\nИспользуйте '🎯 Установить' чтобы создать цель.", reply_markup=markup, parse_mode='Markdown')

@bot.message_handler(func=lambda message: message.text == '🎯 Установить' and user_state.get(message.chat.id) == 'goal')
def set_goal(message):
    msg = bot.send_message(
        message.chat.id,
        "Введите сумму цели (например: 1000000 или 1,000,000):"
    )
    bot.register_next_step_handler(msg, process_goal_amount)

def process_goal_amount(message):
    try:
        amount = float(message.text.replace(',', '').replace(' ', ''))
        data = load_data()
        data['goal'] = amount
        save_data(data)
        msg = bot.send_message(
            message.chat.id,
            f"✅ Цель *{format_number(amount)}* ₽ установлена!\n\n"
            "Теперь укажите дату окончания (в формате ДД.ММ.ГГГГ):\n"
            "📌 Пример: 31.12.2024\nИли напишите 'пропустить' чтобы не указывать дату",
            parse_mode='Markdown'
        )
        bot.register_next_step_handler(msg, process_goal_date)
    except ValueError:
        bot.reply_to(message, "❌ Пожалуйста, введите корректное число!")

def process_goal_date(message):
    if message.text.lower() == 'пропустить':
        bot.send_message(message.chat.id, "⏭️ Дата не установлена")
        show_goal_stats(message)
        return
    try:
        goal_date = datetime.strptime(message.text, '%d.%m.%Y')
        data = load_data()
        data['goal_date'] = goal_date.strftime('%d.%m.%Y')
        save_data(data)
        bot.send_message(message.chat.id, f"✅ Дата цели установлена: *{goal_date.strftime('%d.%m.%Y')}*", parse_mode='Markdown')
        show_goal_stats(message)
    except ValueError:
        bot.reply_to(message, "❌ Неверный формат даты! Используйте ДД.ММ.ГГГГ")

@bot.message_handler(func=lambda message: message.text == '📊 Статистика' and user_state.get(message.chat.id) == 'goal')
def show_goal_stats(message):
    data = load_data()
    if not data.get('goal'):
        bot.reply_to(message, "❌ Цель не установлена!")
        return

    goal = data['goal']
    total_log = sum(entry['amount'] for entry in data['log'])
    remaining = goal - total_log
    progress = (total_log / goal) * 100 if goal > 0 else 0
    bar = create_progress_bar(progress)

    stats_text = f"🎯 *СТАТИСТИКА ЦЕЛИ*\n\n💰 Цель: *{format_number(goal)}* ₽\n"
    stats_text += f"📊 Собрано: *{format_number(total_log)}* ₽\n"
    stats_text += f"📉 Осталось: *{format_number(remaining)}* ₽\n"
    stats_text += f"📈 Прогресс: *{progress:.1f}%*\n[{bar}] {progress:.1f}%\n"

    if data.get('goal_date'):
        goal_date = datetime.strptime(data['goal_date'], '%d.%m.%Y')
        days_left = (goal_date - datetime.now()).days
        if days_left > 0:
            per_day = remaining / days_left
            stats_text += f"\n📅 Дней до цели: *{days_left}*\n📈 Нужно в день: *{format_number(per_day)}* ₽"
        elif days_left == 0:
            stats_text += f"\n🎯 *СЕГОДНЯ ПОСЛЕДНИЙ ДЕНЬ!*"
        else:
            stats_text += f"\n⏰ *Срок истек!* (просрочено {abs(days_left)} дней)"

    bot.send_message(message.chat.id, stats_text, parse_mode='Markdown')

@bot.message_handler(func=lambda message: message.text == '✏️ Редактировать' and user_state.get(message.chat.id) == 'goal')
def edit_goal(message):
    data = load_data()
    if not data.get('goal'):
        bot.reply_to(message, "❌ Цель не установлена!")
        return

    markup = types.InlineKeyboardMarkup(row_width=2)
    btn1 = types.InlineKeyboardButton("💰 Изменить сумму", callback_data="edit_goal_amount")
    btn2 = types.InlineKeyboardButton("📅 Изменить дату", callback_data="edit_goal_date")
    btn3 = types.InlineKeyboardButton("🔙 Назад", callback_data="back_goal")
    markup.add(btn1, btn2, btn3)
    bot.send_message(
        message.chat.id,
        f"✏️ *Редактирование цели*\n\n💰 Сумма: *{format_number(data['goal'])}* ₽\n📅 Дата: *{data.get('goal_date', 'Не установлена')}*",
        reply_markup=markup,
        parse_mode='Markdown'
    )

@bot.callback_query_handler(func=lambda call: call.data == 'edit_goal_amount')
def handle_edit_goal_amount(call):
    msg = bot.send_message(call.message.chat.id, "Введите новую сумму цели:")
    bot.register_next_step_handler(msg, process_edit_goal_amount)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == 'edit_goal_date')
def handle_edit_goal_date(call):
    msg = bot.send_message(call.message.chat.id, "Введите новую дату (ДД.ММ.ГГГГ):")
    bot.register_next_step_handler(msg, process_edit_goal_date)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == 'back_goal')
def handle_back_goal(call):
    show_goal_menu(call.message)
    bot.answer_callback_query(call.id)

def process_edit_goal_amount(message):
    try:
        amount = float(message.text.replace(',', '').replace(' ', ''))
        data = load_data()
        data['goal'] = amount
        save_data(data)
        bot.send_message(message.chat.id, f"✅ Цель обновлена: *{format_number(amount)}* ₽", parse_mode='Markdown')
        show_goal_menu(message)
    except ValueError:
        bot.reply_to(message, "❌ Введите корректное число!")

def process_edit_goal_date(message):
    try:
        goal_date = datetime.strptime(message.text, '%d.%m.%Y')
        data = load_data()
        data['goal_date'] = goal_date.strftime('%d.%m.%Y')
        save_data(data)
        bot.send_message(message.chat.id, f"✅ Дата обновлена: *{goal_date.strftime('%d.%m.%Y')}*", parse_mode='Markdown')
        show_goal_menu(message)
    except ValueError:
        bot.reply_to(message, "❌ Неверный формат даты! Используйте ДД.ММ.ГГГГ")

@bot.message_handler(func=lambda message: message.text == '🗑️ Удалить' and user_state.get(message.chat.id) == 'goal')
def delete_goal(message):
    markup = types.InlineKeyboardMarkup()
    btn_yes = types.InlineKeyboardButton("✅ Да, удалить", callback_data="confirm_delete_goal")
    btn_no = types.InlineKeyboardButton("❌ Нет, отмена", callback_data="cancel_delete_goal")
    markup.add(btn_yes, btn_no)
    bot.send_message(
        message.chat.id,
        "⚠️ *ВНИМАНИЕ!*\n\nВы уверены, что хотите удалить цель?",
        reply_markup=markup,
        parse_mode='Markdown'
    )

@bot.callback_query_handler(func=lambda call: call.data == 'confirm_delete_goal')
def handle_confirm_delete_goal(call):
    data = load_data()
    data['goal'] = None
    data['goal_date'] = None
    save_data(data)
    bot.edit_message_text("🗑️ Цель удалена!", call.message.chat.id, call.message.message_id)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == 'cancel_delete_goal')
def handle_cancel_delete_goal(call):
    bot.edit_message_text("❌ Удаление отменено", call.message.chat.id, call.message.message_id)
    bot.answer_callback_query(call.id)

# ============================================
# РЕЖИМ СТАТИСТИКИ
# ============================================

@bot.message_handler(func=lambda message: message.text == '📊 Статистика')
def show_stats_menu(message):
    user_state[message.chat.id] = 'stats'
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    btn1 = types.KeyboardButton('📋 Общая')
    btn2 = types.KeyboardButton('📊 По типам')
    btn3 = types.KeyboardButton('📅 По периодам')
    btn4 = types.KeyboardButton('🏠 Главное меню')
    markup.add(btn1, btn2, btn3, btn4)
    bot.send_message(
        message.chat.id,
        "📊 *РЕЖИМ СТАТИСТИКИ*\n\nВыберите тип статистики:",
        reply_markup=markup,
        parse_mode='Markdown'
    )

@bot.message_handler(func=lambda message: message.text == '📋 Общая' and user_state.get(message.chat.id) == 'stats')
def show_general_stats(message):
    data = load_data()
    log = data['log']
    if not log:
        bot.reply_to(message, "📭 Лог пуст")
        return

    total, count, avg, max_amt, min_amt = get_log_summary(data)
    stats_text = f"📋 *ОБЩАЯ СТАТИСТИКА*\n\n"
    stats_text += f"📊 Всего записей: *{count}*\n💰 Общая сумма: *{format_number(total)}* ₽\n"
    stats_text += f"📈 Средняя сумма: *{format_number(avg)}* ₽\n"
    stats_text += f"📈 Максимальная: *{format_number(max_amt)}* ₽\n📉 Минимальная: *{format_number(min_amt)}* ₽"
    bot.send_message(message.chat.id, stats_text, parse_mode='Markdown')

@bot.message_handler(func=lambda message: message.text == '📊 По типам' and user_state.get(message.chat.id) == 'stats')
def show_type_stats(message):
    data = load_data()
    log = data['log']
    if not log:
        bot.reply_to(message, "📭 Лог пуст")
        return

    type_26 = [e for e in log if e.get('type') == '26%']
    type_6 = [e for e in log if e.get('type') == '6%']
    type_manual = [e for e in log if e.get('type') == 'manual']

    stats_text = f"📊 *СТАТИСТИКА ПО ТИПАМ*\n\n"
    if type_26:
        total_26 = sum(e['amount'] for e in type_26)
        stats_text += f"🔹 *26% (чистые)*\n   Записей: {len(type_26)}\n   Сумма: {format_number(total_26)} ₽\n\n"
    if type_6:
        total_6 = sum(e['amount'] for e in type_6)
        stats_text += f"🔸 *6% (с комиссией)*\n   Записей: {len(type_6)}\n   Сумма: {format_number(total_6)} ₽\n\n"
    if type_manual:
        total_manual = sum(e['amount'] for e in type_manual)
        stats_text += f"📝 *Ручные записи*\n   Записей: {len(type_manual)}\n   Сумма: {format_number(total_manual)} ₽"
    bot.send_message(message.chat.id, stats_text, parse_mode='Markdown')

@bot.message_handler(func=lambda message: message.text == '📅 По периодам' and user_state.get(message.chat.id) == 'stats')
def show_period_stats(message):
    data = load_data()
    log = data['log']
    if not log:
        bot.reply_to(message, "📭 Лог пуст")
        return

    today = get_date_only()
    week_ago = (datetime.now() - timedelta(days=7)).strftime('%d.%m.%Y')
    month_ago = (datetime.now() - timedelta(days=30)).strftime('%d.%m.%Y')
    year_ago = (datetime.now() - timedelta(days=365)).strftime('%d.%m.%Y')

    today_log = [e for e in log if e['date'].startswith(today)]
    week_log = [e for e in log if e['date'].split()[0] >= week_ago]
    month_log = [e for e in log if e['date'].split()[0] >= month_ago]
    year_log = [e for e in log if e['date'].split()[0] >= year_ago]

    stats_text = f"📅 *СТАТИСТИКА ПО ПЕРИОДАМ*\n\n"
    stats_text += f"📌 *Сегодня* ({len(today_log)} записей)\n   Сумма: {format_number(sum(e['amount'] for e in today_log))} ₽\n\n"
    stats_text += f"📌 *За неделю* ({len(week_log)} записей)\n   Сумма: {format_number(sum(e['amount'] for e in week_log))} ₽\n\n"
    stats_text += f"📌 *За месяц* ({len(month_log)} записей)\n   Сумма: {format_number(sum(e['amount'] for e in month_log))} ₽\n\n"
    stats_text += f"📌 *За год* ({len(year_log)} записей)\n   Сумма: {format_number(sum(e['amount'] for e in year_log))} ₽"
    bot.send_message(message.chat.id, stats_text, parse_mode='Markdown')

# ============================================
# ПОМОЩЬ И НАВИГАЦИЯ
# ============================================

@bot.message_handler(func=lambda message: message.text == 'ℹ️ Помощь')
def show_help(message):
    help_text = (
        "📖 *ПОМОЩЬ*\n\n"
        "🤖 *Бот финансовый помощник*\n\n"
        "💰 *Расчеты* - вычисление 26% и 6% от числа\n"
        "📋 *Лог* - хранение всех записей с датами\n"
        "🎯 *Цель* - установка и отслеживание цели\n"
        "📊 *Статистика* - анализ всех данных\n\n"
        "⚡ *Быстрые команды:*\n"
        "/menu - Главное меню\n/calc - Калькулятор\n/log - Лог\n/goal - Цель\n/stats - Статистика\n/help - Помощь"
    )
    bot.send_message(message.chat.id, help_text, parse_mode='Markdown')

@bot.message_handler(func=lambda message: message.text == '🏠 Главное меню')
def back_to_main(message):
    show_main_menu(message)

# ============================================
# ОБРАБОТЧИК НЕИЗВЕСТНЫХ СООБЩЕНИЙ
# ============================================

@bot.message_handler(func=lambda message: True)
def handle_unknown(message):
    if message.text and not message.text.startswith('/'):
        if message.text not in ['💰 Расчеты', '📋 Лог', '🎯 Цель', '📊 Статистика', 'ℹ️ Помощь',
                                '🔢 Ввести число', '📋 Добавить в лог',
                                '📖 Просмотреть', '➕ Добавить', '🗑️ Удалить', '🧹 Очистить',
                                '📊 Сумма', '📤 Экспорт', '🔍 Фильтр',
                                '🎯 Установить', '✏️ Редактировать', '🗑️ Удалить',
                                '📋 Общая', '📊 По типам', '📅 По периодам',
                                '🏠 Главное меню']:
            bot.reply_to(
                message,
                "❓ Используйте кнопки меню для навигации.\n📌 /menu - открыть главное меню"
            )

# ============================================
# FLASK ДЛЯ RENDER
# ============================================

@app.route('/')
def index():
    return "✅ Bot is running!"

@app.route('/health')
def health():
    return "OK"

# ============================================
# ЗАПУСК (для Render — в отдельном потоке)
# ============================================

if __name__ == '__main__':
    print("🚀 Бот запускается на Render...")
    print(f"📁 Данные загружены: {len(load_data()['log'])} записей")
    
    # Запускаем бота в отдельном потоке
    def run_bot():
        while True:
            try:
                bot.polling(none_stop=True, timeout=60)
            except Exception as e:
                print(f"❌ Ошибка: {e}")
                time.sleep(5)
    
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.daemon = True
    bot_thread.start()
    
    # Запускаем Flask для health checks
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
