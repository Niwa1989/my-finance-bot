import os
import time
import json
import shutil
import threading
import difflib
import html
import re
from datetime import datetime, timedelta
from flask import Flask
import telebot
import requests
from telebot import types

# ============================================
# КОНФИГУРАЦИЯ
# ============================================

TOKEN = os.environ.get('TELEGRAM_TOKEN')
bot = telebot.TeleBot(TOKEN)
# Сетевые запросы Playerok могут ожидать внешний API. Дополнительные рабочие
# потоки не дают им блокировать обычные кнопки финансового бота.
bot = telebot.TeleBot(TOKEN, threaded=True, num_threads=8)
app = Flask(__name__)

# Playerok не публикует официальный API для каталога. Используется поддерживаемый
# REST-адаптер Parse поверх публичных данных Playerok.
PLAYEROK_API_KEY = os.environ.get('PARSE_API_KEY')
PLAYEROK_API_URL = (
    'https://api.parse.bot/scraper/'
    '4688010c-bf13-44a2-bef6-4db5e643b286'
)
PLAYEROK_TIMEOUT = int(os.environ.get('PLAYEROK_TIMEOUT', '30'))
# Каталог читается напрямую через публичные persisted GraphQL-запросы Playerok.
# Хэши запросов взяты из PlayerokAPI: https://github.com/alleexxeeyy/PlayerokAPI
# Авторизация и PARSE_API_KEY для просмотра публичных лотов не нужны.
PLAYEROK_GRAPHQL_URL = 'https://playerok.com/graphql'
PLAYEROK_QUERY_HASHES = {
    'games': '5de9b3240c148579c82e2310a30b4aad5462884fd1abf93dd3c43d1f5ef14d85',
    'items': '3f20c731f8f769a094ee3fa32e09f8e12250357e9a4f0ebb4e6988e7a0bb9260'
}
PLAYEROK_TIMEOUT = int(os.environ.get('PLAYEROK_TIMEOUT', '12'))
PLAYEROK_SEARCH_PAGES = max(1, min(int(os.environ.get('PLAYEROK_SEARCH_PAGES', '4')), 10))
PLAYEROK_API_SNAPSHOT_VERSION = os.environ.get('PLAYEROK_API_SNAPSHOT_VERSION', '4')
PLAYEROK_API_RETRIES = max(1, min(int(os.environ.get('PLAYEROK_API_RETRIES', '3')), 5))
PLAYEROK_API_RETRIES = max(1, min(int(os.environ.get('PLAYEROK_API_RETRIES', '2')), 5))

# Пути к данным
DATA_FILE = 'bot_data.json'
BACKUP_DIR = 'backups'

if not os.path.exists(BACKUP_DIR):
    os.makedirs(BACKUP_DIR)


# ============================================
# РАБОТА С ДАННЫМИ ПОЛЬЗОВАТЕЛЕЙ
# ============================================

def get_default_user_data():
    return {
        "log": [],
        "goal": None,
        "goal_date": None,
        "settings": {
            "last_id": 0,
            "playerok_game": {
                "id": None,
                "name": "SCraft",
                "slug": "scraft",
                "items_category_id": None
            },
            "playerok_category": {
                "id": None,
                "name": "Предметы",
                "slug": "items"
            }
        }
    }


def get_default_data():
    return {
        "users": {}
    }


def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if 'users' not in data:
                    data['users'] = {}
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


def get_user_data(user_id):
    """Получает данные пользователя, если нет — создаёт"""
    data = load_data()
    user_id_str = str(user_id)
    if user_id_str not in data['users']:
        data['users'][user_id_str] = get_default_user_data()
        save_data(data)
    return data['users'][user_id_str]


def save_user_data(user_id, user_data):
    """Сохраняет данные пользователя"""
    data = load_data()
    data['users'][str(user_id)] = user_data
    save_data(data)


def get_next_id(user_data):
    try:
        if 'settings' not in user_data:
            user_data['settings'] = {"last_id": 0}
        if 'last_id' not in user_data['settings']:
            user_data['settings']['last_id'] = 0
        user_data['settings']['last_id'] += 1
        return user_data['settings']['last_id']
    except Exception as e:
        print(f"Ошибка в get_next_id: {e}")
        return len(user_data.get('log', [])) + 1


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


def get_log_summary(user_data):
    log = user_data.get('log', [])
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
    user_data = get_user_data(message.from_user.id)

    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    btn1 = types.KeyboardButton('💰 Расчеты')
    btn2 = types.KeyboardButton('📋 Лог')
    btn3 = types.KeyboardButton('🎯 Цель')
    btn4 = types.KeyboardButton('📊 Статистика')
    btn5 = types.KeyboardButton('ℹ️ Помощь')
    btn6 = types.KeyboardButton('🛒 Playerok')
    markup.add(btn1, btn2, btn3, btn4, btn6, btn5)
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


@bot.message_handler(
    func=lambda message: message.text == '🔢 Ввести число' and user_state.get(message.chat.id) == 'calc')
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


@bot.message_handler(
    func=lambda message: message.text == '📋 Добавить в лог' and user_state.get(message.chat.id) == 'calc')
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

        user_data = get_user_data(message.from_user.id)
        entry = {
            "id": get_next_id(user_data),
            "date": get_date_now(),
            "amount": amount,
            "type": "manual",
            "original_amount": amount,
            "description": description
        }
        user_data['log'].append(entry)
        save_user_data(message.from_user.id, user_data)

        bot.send_message(
            message.chat.id,
            f"✅ Сумма *{format_number(amount)}* добавлена в ваш лог!\n📝 Описание: {description}",
            parse_mode='Markdown'
        )
    except ValueError:
        bot.reply_to(message, "❌ Пожалуйста, введите корректную сумму!")


# ============================================
# ОБРАБОТЧИКИ ИНЛАЙН КНОПОК
# ============================================

@bot.callback_query_handler(
    func=lambda call: call.data.startswith('add_26_') or call.data.startswith('add_6_') or call.data.startswith(
        'add_both_'))
def handle_add_to_log(call):
    try:
        user_data = get_user_data(call.from_user.id)
        if 'settings' not in user_data:
            user_data['settings'] = {"last_id": 0}
        if 'last_id' not in user_data['settings']:
            user_data['settings']['last_id'] = 0

        if call.data.startswith('add_both_'):
            number = float(call.data.replace('add_both_', ''))
            result_26 = number * 0.74
            result_6 = number * 0.94
            entry1 = {"id": get_next_id(user_data), "date": get_date_now(), "amount": result_26, "type": "26%",
                      "original_amount": number, "description": "Чистая прибыль (26%)"}
            entry2 = {"id": get_next_id(user_data), "date": get_date_now(), "amount": result_6, "type": "6%",
                      "original_amount": number, "description": "С комиссией (6%)"}
            user_data['log'].append(entry1)
            user_data['log'].append(entry2)
            save_user_data(call.from_user.id, user_data)
            bot.edit_message_text(
                f"✅ Добавлены оба варианта:\n26%: *{format_number(result_26)}*\n6%: *{format_number(result_6)}*",
                call.message.chat.id, call.message.message_id, parse_mode='Markdown'
            )
        elif call.data.startswith('add_26_'):
            number = float(call.data.replace('add_26_', ''))
            result = number * 0.74
            entry = {"id": get_next_id(user_data), "date": get_date_now(), "amount": result, "type": "26%",
                     "original_amount": number, "description": "Чистая прибыль (26%)"}
            user_data['log'].append(entry)
            save_user_data(call.from_user.id, user_data)
            bot.edit_message_text(
                f"✅ Добавлено в ваш лог:\nСумма: *{format_number(result)}* (26% от {format_number(number)})",
                call.message.chat.id, call.message.message_id, parse_mode='Markdown'
            )
        elif call.data.startswith('add_6_'):
            number = float(call.data.replace('add_6_', ''))
            result = number * 0.94
            entry = {"id": get_next_id(user_data), "date": get_date_now(), "amount": result, "type": "6%",
                     "original_amount": number, "description": "С комиссией (6%)"}
            user_data['log'].append(entry)
            save_user_data(call.from_user.id, user_data)
            bot.edit_message_text(
                f"✅ Добавлено в ваш лог:\nСумма: *{format_number(result)}* (6% от {format_number(number)})",
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
    user_data = get_user_data(message.from_user.id)

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

    total, count, _, _, _ = get_log_summary(user_data)
    bot.send_message(
        message.chat.id,
        f"📋 *ВАШ ЛОГ*\n\n📊 Всего записей: *{count}*\n💰 Общая сумма: *{format_number(total)}*\n\nВыберите действие:",
        reply_markup=markup,
        parse_mode='Markdown'
    )


@bot.message_handler(func=lambda message: message.text == '📖 Просмотреть' and user_state.get(message.chat.id) == 'log')
def view_log(message):
    user_data = get_user_data(message.from_user.id)
    log = user_data['log']
    if not log:
        bot.reply_to(message, "📭 Ваш лог пуст")
        return

    log_text = "📋 *ВАШ ЛОГ (все записи)*\n" + "═" * 30 + "\n\n"
    sorted_log = sorted(log, key=lambda x: x['date'], reverse=True)
    for i, entry in enumerate(sorted_log, 1):
        log_text += f"*№{i}*: {entry['date']}\n💰 {format_number(entry['amount'])} ₽"
        if entry.get('type') and entry['type'] != 'manual':
            log_text += f" | {entry['type']}"
        if entry.get('description'):
            log_text += f"\n📝 {entry['description']}"
        log_text += "\n\n"

    total, count, avg, max_amt, min_amt = get_log_summary(user_data)
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
        "Введите сумму для добавления в ваш лог:\n📌 Можно добавить комментарий: '1000 приход от клиента'"
    )
    bot.register_next_step_handler(msg, process_custom_log)


@bot.message_handler(func=lambda message: message.text == '🗑️ Удалить' and user_state.get(message.chat.id) == 'log')
def delete_from_log(message):
    user_data = get_user_data(message.from_user.id)
    log = user_data['log']
    if not log:
        bot.reply_to(message, "📭 Ваш лог пуст")
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
        "🗑️ *Выберите запись для удаления из вашего лога:*\n(показываю последние 10)",
        reply_markup=markup,
        parse_mode='Markdown'
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith('delete_log_'))
def handle_delete_log(call):
    user_data = get_user_data(call.from_user.id)
    entry_id = int(call.data.replace('delete_log_', ''))
    for i, entry in enumerate(user_data['log']):
        if entry['id'] == entry_id:
            deleted = user_data['log'].pop(i)
            save_user_data(call.from_user.id, user_data)
            bot.edit_message_text(
                f"🗑️ Запись удалена из вашего лога:\n📅 {deleted['date']}\n💰 {format_number(deleted['amount'])} ₽",
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
    btn_yes = types.InlineKeyboardButton("✅ Да, очистить мой лог", callback_data="confirm_clear")
    btn_no = types.InlineKeyboardButton("❌ Нет, отмена", callback_data="cancel_clear")
    markup.add(btn_yes, btn_no)
    bot.send_message(
        message.chat.id,
        "⚠️ *ВНИМАНИЕ!*\n\nВы уверены, что хотите очистить весь ваш лог?\nЭто действие НЕЛЬЗЯ отменить!",
        reply_markup=markup,
        parse_mode='Markdown'
    )


@bot.callback_query_handler(func=lambda call: call.data == 'confirm_clear')
def handle_confirm_clear(call):
    user_data = get_user_data(call.from_user.id)
    user_data['log'] = []
    save_user_data(call.from_user.id, user_data)
    bot.edit_message_text("🧹 Ваш лог очищен!", call.message.chat.id, call.message.message_id)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data == 'cancel_clear')
def handle_cancel_clear(call):
    bot.edit_message_text("❌ Очистка отменена", call.message.chat.id, call.message.message_id)
    bot.answer_callback_query(call.id)


@bot.message_handler(func=lambda message: message.text == '📊 Сумма' and user_state.get(message.chat.id) == 'log')
def show_log_summary(message):
    user_data = get_user_data(message.from_user.id)
    log = user_data['log']
    if not log:
        bot.reply_to(message, "📭 Ваш лог пуст")
        return

    total, count, avg, max_amt, min_amt = get_log_summary(user_data)
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

    stats_text = f"📊 *СТАТИСТИКА ВАШЕГО ЛОГА*\n\n"
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
    user_data = get_user_data(message.from_user.id)
    log = user_data['log']
    if not log:
        bot.reply_to(message, "📭 Ваш лог пуст")
        return

    filename = f"log_export_{message.from_user.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    with open(filename, 'w', encoding='utf-8') as f:
        f.write("=" * 50 + "\n       ВЫГРУЗКА ВАШЕГО ЛОГА\n" + "=" * 50 + "\n\n")
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
        bot.send_document(message.chat.id, f, caption="📤 Экспорт вашего лога")
    os.remove(filename)


@bot.message_handler(func=lambda message: message.text == '🔍 Фильтр' and user_state.get(message.chat.id) == 'log')
def filter_log(message):
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn_all = types.InlineKeyboardButton("📊 Все", callback_data="filter_all")
    btn_26 = types.InlineKeyboardButton("🔹 26%", callback_data="filter_26")
    btn_6 = types.InlineKeyboardButton("🔸 6%", callback_data="filter_6")
    btn_manual = types.InlineKeyboardButton("📝 Ручные", callback_data="filter_manual")
    markup.add(btn_all, btn_26, btn_6, btn_manual)
    bot.send_message(message.chat.id, "🔍 *Выберите фильтр для вашего лога:*", reply_markup=markup,
                     parse_mode='Markdown')


@bot.callback_query_handler(func=lambda call: call.data.startswith('filter_'))
def handle_filter(call):
    user_data = get_user_data(call.from_user.id)
    filter_type = call.data.replace('filter_', '')
    if filter_type == 'all':
        filtered = user_data['log']
        title = "Все записи"
    else:
        filtered = [e for e in user_data['log'] if e.get('type') == filter_type]
        title = f"Записи по типу: {filter_type}"

    if not filtered:
        bot.edit_message_text(f"📭 Нет записей для фильтра '{title}' в вашем логе", call.message.chat.id,
                              call.message.message_id)
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
    user_data = get_user_data(message.from_user.id)

    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    btn1 = types.KeyboardButton('🎯 Установить')
    btn2 = types.KeyboardButton('📊 Статистика')
    btn3 = types.KeyboardButton('✏️ Редактировать')
    btn4 = types.KeyboardButton('🗑️ Удалить')
    btn5 = types.KeyboardButton('🏠 Главное меню')
    markup.add(btn1, btn2, btn3, btn4, btn5)

    if user_data.get('goal'):
        goal = user_data['goal']
        total_log = sum(entry['amount'] for entry in user_data['log'])
        remaining = goal - total_log
        progress = (total_log / goal) * 100 if goal > 0 else 0
        bar = create_progress_bar(progress)

        stats_text = f"🎯 *ВАША ЦЕЛЬ*\n\n💰 Цель: *{format_number(goal)}* ₽\n"
        stats_text += f"📊 Собрано: *{format_number(total_log)}* ₽ ({progress:.1f}%)\n"
        stats_text += f"📉 Осталось: *{format_number(remaining)}* ₽\n[{bar}] {progress:.1f}%\n"

        if user_data.get('goal_date'):
            goal_date = datetime.strptime(user_data['goal_date'], '%d.%m.%Y')
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
        bot.send_message(message.chat.id,
                         "❌ У вас нет установленной цели!\n\nИспользуйте '🎯 Установить' чтобы создать цель.",
                         reply_markup=markup, parse_mode='Markdown')


@bot.message_handler(func=lambda message: message.text == '🎯 Установить' and user_state.get(message.chat.id) == 'goal')
def set_goal(message):
    msg = bot.send_message(
        message.chat.id,
        "Введите сумму вашей цели (например: 1000000 или 1,000,000):"
    )
    bot.register_next_step_handler(msg, process_goal_amount)


def process_goal_amount(message):
    try:
        amount = float(message.text.replace(',', '').replace(' ', ''))
        user_data = get_user_data(message.from_user.id)
        user_data['goal'] = amount
        save_user_data(message.from_user.id, user_data)

        msg = bot.send_message(
            message.chat.id,
            f"✅ Ваша цель *{format_number(amount)}* ₽ установлена!\n\n"
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
        user_data = get_user_data(message.from_user.id)
        user_data['goal_date'] = goal_date.strftime('%d.%m.%Y')
        save_user_data(message.from_user.id, user_data)
        bot.send_message(message.chat.id, f"✅ Дата вашей цели установлена: *{goal_date.strftime('%d.%m.%Y')}*",
                         parse_mode='Markdown')
        show_goal_stats(message)
    except ValueError:
        bot.reply_to(message, "❌ Неверный формат даты! Используйте ДД.ММ.ГГГГ")


@bot.message_handler(func=lambda message: message.text == '📊 Статистика' and user_state.get(message.chat.id) == 'goal')
def show_goal_stats(message):
    user_data = get_user_data(message.from_user.id)

    if not user_data.get('goal'):
        bot.reply_to(message, "❌ У вас нет установленной цели!")
        return

    goal = user_data['goal']
    total_log = sum(entry['amount'] for entry in user_data['log'])
    remaining = goal - total_log
    progress = (total_log / goal) * 100 if goal > 0 else 0
    bar = create_progress_bar(progress)

    stats_text = f"🎯 *СТАТИСТИКА ВАШЕЙ ЦЕЛИ*\n\n💰 Цель: *{format_number(goal)}* ₽\n"
    stats_text += f"📊 Собрано: *{format_number(total_log)}* ₽\n"
    stats_text += f"📉 Осталось: *{format_number(remaining)}* ₽\n"
    stats_text += f"📈 Прогресс: *{progress:.1f}%*\n[{bar}] {progress:.1f}%\n"

    if user_data.get('goal_date'):
        goal_date = datetime.strptime(user_data['goal_date'], '%d.%m.%Y')
        days_left = (goal_date - datetime.now()).days
        if days_left > 0:
            per_day = remaining / days_left
            stats_text += f"\n📅 Дней до цели: *{days_left}*\n📈 Нужно в день: *{format_number(per_day)}* ₽"
        elif days_left == 0:
            stats_text += f"\n🎯 *СЕГОДНЯ ПОСЛЕДНИЙ ДЕНЬ!*"
        else:
            stats_text += f"\n⏰ *Срок истек!* (просрочено {abs(days_left)} дней)"

    bot.send_message(message.chat.id, stats_text, parse_mode='Markdown')


@bot.message_handler(
    func=lambda message: message.text == '✏️ Редактировать' and user_state.get(message.chat.id) == 'goal')
def edit_goal(message):
    user_data = get_user_data(message.from_user.id)

    if not user_data.get('goal'):
        bot.reply_to(message, "❌ У вас нет установленной цели!")
        return

    markup = types.InlineKeyboardMarkup(row_width=2)
    btn1 = types.InlineKeyboardButton("💰 Изменить сумму", callback_data="edit_goal_amount")
    btn2 = types.InlineKeyboardButton("📅 Изменить дату", callback_data="edit_goal_date")
    btn3 = types.InlineKeyboardButton("🔙 Назад", callback_data="back_goal")
    markup.add(btn1, btn2, btn3)
    bot.send_message(
        message.chat.id,
        f"✏️ *Редактирование вашей цели*\n\n💰 Сумма: *{format_number(user_data['goal'])}* ₽\n📅 Дата: *{user_data.get('goal_date', 'Не установлена')}*",
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
        user_data = get_user_data(message.from_user.id)
        user_data['goal'] = amount
        save_user_data(message.from_user.id, user_data)
        bot.send_message(message.chat.id, f"✅ Ваша цель обновлена: *{format_number(amount)}* ₽", parse_mode='Markdown')
        show_goal_menu(message)
    except ValueError:
        bot.reply_to(message, "❌ Введите корректное число!")


def process_edit_goal_date(message):
    try:
        goal_date = datetime.strptime(message.text, '%d.%m.%Y')
        user_data = get_user_data(message.from_user.id)
        user_data['goal_date'] = goal_date.strftime('%d.%m.%Y')
        save_user_data(message.from_user.id, user_data)
        bot.send_message(message.chat.id, f"✅ Дата вашей цели обновлена: *{goal_date.strftime('%d.%m.%Y')}*",
                         parse_mode='Markdown')
        show_goal_menu(message)
    except ValueError:
        bot.reply_to(message, "❌ Неверный формат даты! Используйте ДД.ММ.ГГГГ")


@bot.message_handler(func=lambda message: message.text == '🗑️ Удалить' and user_state.get(message.chat.id) == 'goal')
def delete_goal(message):
    markup = types.InlineKeyboardMarkup()
    btn_yes = types.InlineKeyboardButton("✅ Да, удалить мою цель", callback_data="confirm_delete_goal")
    btn_no = types.InlineKeyboardButton("❌ Нет, отмена", callback_data="cancel_delete_goal")
    markup.add(btn_yes, btn_no)
    bot.send_message(
        message.chat.id,
        "⚠️ *ВНИМАНИЕ!*\n\nВы уверены, что хотите удалить вашу цель?",
        reply_markup=markup,
        parse_mode='Markdown'
    )


@bot.callback_query_handler(func=lambda call: call.data == 'confirm_delete_goal')
def handle_confirm_delete_goal(call):
    user_data = get_user_data(call.from_user.id)
    user_data['goal'] = None
    user_data['goal_date'] = None
    save_user_data(call.from_user.id, user_data)
    bot.edit_message_text("🗑️ Ваша цель удалена!", call.message.chat.id, call.message.message_id)
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
    user_data = get_user_data(message.from_user.id)

    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    btn1 = types.KeyboardButton('📋 Общая')
    btn2 = types.KeyboardButton('📊 По типам')
    btn3 = types.KeyboardButton('📅 По периодам')
    btn4 = types.KeyboardButton('🏠 Главное меню')
    markup.add(btn1, btn2, btn3, btn4)
    bot.send_message(
        message.chat.id,
        "📊 *СТАТИСТИКА ВАШИХ ДАННЫХ*\n\nВыберите тип статистики:",
        reply_markup=markup,
        parse_mode='Markdown'
    )


@bot.message_handler(func=lambda message: message.text == '📋 Общая' and user_state.get(message.chat.id) == 'stats')
def show_general_stats(message):
    user_data = get_user_data(message.from_user.id)
    log = user_data['log']
    if not log:
        bot.reply_to(message, "📭 Ваш лог пуст")
        return

    total, count, avg, max_amt, min_amt = get_log_summary(user_data)
    stats_text = f"📋 *ОБЩАЯ СТАТИСТИКА ВАШЕГО ЛОГА*\n\n"
    stats_text += f"📊 Всего записей: *{count}*\n💰 Общая сумма: *{format_number(total)}* ₽\n"
    stats_text += f"📈 Средняя сумма: *{format_number(avg)}* ₽\n"
    stats_text += f"📈 Максимальная: *{format_number(max_amt)}* ₽\n📉 Минимальная: *{format_number(min_amt)}* ₽"
    bot.send_message(message.chat.id, stats_text, parse_mode='Markdown')


@bot.message_handler(func=lambda message: message.text == '📊 По типам' and user_state.get(message.chat.id) == 'stats')
def show_type_stats(message):
    user_data = get_user_data(message.from_user.id)
    log = user_data['log']
    if not log:
        bot.reply_to(message, "📭 Ваш лог пуст")
        return

    type_26 = [e for e in log if e.get('type') == '26%']
    type_6 = [e for e in log if e.get('type') == '6%']
    type_manual = [e for e in log if e.get('type') == 'manual']

    stats_text = f"📊 *СТАТИСТИКА ВАШЕГО ЛОГА ПО ТИПАМ*\n\n"
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


@bot.message_handler(
    func=lambda message: message.text == '📅 По периодам' and user_state.get(message.chat.id) == 'stats')
def show_period_stats(message):
    user_data = get_user_data(message.from_user.id)
    log = user_data['log']
    if not log:
        bot.reply_to(message, "📭 Ваш лог пуст")
        return

    today = get_date_only()
    week_ago = (datetime.now() - timedelta(days=7)).strftime('%d.%m.%Y')
    month_ago = (datetime.now() - timedelta(days=30)).strftime('%d.%m.%Y')
    year_ago = (datetime.now() - timedelta(days=365)).strftime('%d.%m.%Y')

    today_log = [e for e in log if e['date'].startswith(today)]
    week_log = [e for e in log if e['date'].split()[0] >= week_ago]
    month_log = [e for e in log if e['date'].split()[0] >= month_ago]
    year_log = [e for e in log if e['date'].split()[0] >= year_ago]

    stats_text = f"📅 *СТАТИСТИКА ВАШЕГО ЛОГА ПО ПЕРИОДАМ*\n\n"
    stats_text += f"📌 *Сегодня* ({len(today_log)} записей)\n   Сумма: {format_number(sum(e['amount'] for e in today_log))} ₽\n\n"
    stats_text += f"📌 *За неделю* ({len(week_log)} записей)\n   Сумма: {format_number(sum(e['amount'] for e in week_log))} ₽\n\n"
    stats_text += f"📌 *За месяц* ({len(month_log)} записей)\n   Сумма: {format_number(sum(e['amount'] for e in month_log))} ₽\n\n"
    stats_text += f"📌 *За год* ({len(year_log)} записей)\n   Сумма: {format_number(sum(e['amount'] for e in year_log))} ₽"
    bot.send_message(message.chat.id, stats_text, parse_mode='Markdown')


# ============================================
# PLAYEROK: ПОИСК И СРАВНЕНИЕ ЛОТОВ
# ============================================

class PlayerokApiError(RuntimeError):
    """Понятная пользователю ошибка доступа к каталогу Playerok."""


class PlayerokClient:
    def __init__(self, api_key=None):
        self.api_key = api_key or PLAYEROK_API_KEY
    """Клиент публичного каталога Playerok без авторизации в аккаунте."""

    def __init__(self):
        self.session = requests.Session()

    def _get(self, endpoint, **params):
        if not self.api_key:
            raise PlayerokApiError(
                "Не задан PARSE_API_KEY. Добавьте его в переменные окружения Render."
            )

    def _query(self, operation, variables):
        params = {
            "operationName": operation,
            "variables": json.dumps(variables, ensure_ascii=False, separators=(',', ':')),
            "extensions": json.dumps({
                "persistedQuery": {
                    "version": 1,
                    "sha256Hash": PLAYEROK_QUERY_HASHES[operation]
                }
            }, separators=(',', ':'))
        }
        response = None
        for attempt in range(PLAYEROK_API_RETRIES):
            try:
                response = self.session.get(
                    f"{PLAYEROK_API_URL}/{endpoint}",
                    PLAYEROK_GRAPHQL_URL,
                    headers={
                        "X-API-Key": self.api_key,
                        "API-Snapshot-Version": PLAYEROK_API_SNAPSHOT_VERSION,
                        "Accept": "application/json"
                        "Accept": "*/*",
                        "Apollo-Require-Preflight": "true",
                        "Apollographql-Client-Name": "web",
                        "Origin": "https://playerok.com",
                        "Referer": "https://playerok.com/",
                        "X-GQL-Op": operation,
                        "X-Apollo-Operation-Name": operation,
                        "User-Agent": (
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 Chrome/143.0 Safari/537.36"
                        )
                    },
                    params={key: value for key, value in params.items() if value is not None},
                    params=params,
                    timeout=PLAYEROK_TIMEOUT
                )
            except requests.Timeout as exc:
                if attempt + 1 == PLAYEROK_API_RETRIES:
                    raise PlayerokApiError(
                        "Playerok отвечает слишком долго. Попробуйте ещё раз."
                    ) from exc
                time.sleep(1 + attempt)
                continue
            except requests.RequestException as exc:
                if attempt + 1 == PLAYEROK_API_RETRIES:
                    raise PlayerokApiError(
                        "Не удалось подключиться к каталогу Playerok."
                    ) from exc
                time.sleep(1 + attempt)
                continue

            if response.status_code not in (502, 503, 504):
                break
            if attempt + 1 < PLAYEROK_API_RETRIES:
                retry_after = response.headers.get("Retry-After")
                try:
                    delay = min(max(float(retry_after), 1), 10)
                except (TypeError, ValueError):
                    delay = 1 + attempt
                time.sleep(delay)
                time.sleep(1 + attempt)

        if response is None:
            raise PlayerokApiError("Playerok API не вернул ответ.")

            raise PlayerokApiError("Playerok не вернул ответ.")
        if response.status_code == 429:
            raise PlayerokApiError("Превышен лимит запросов Playerok API. Попробуйте позже.")
            raise PlayerokApiError("Playerok ограничил частоту запросов. Попробуйте позже.")
        if response.status_code in (401, 403):
            raise PlayerokApiError("PARSE_API_KEY отсутствует или недействителен.")
            raise PlayerokApiError("Playerok отклонил запрос к публичному каталогу.")
        if response.status_code in (502, 503, 504):
            # Ошибка относится к стороне Parse/Playerok, а не к ключу пользователя.
            try:
                error_payload = response.json()
                details = error_payload.get("message") or error_payload.get("error")
            except (ValueError, AttributeError):
                details = None
            print(
                f"Playerok API временно недоступен: endpoint={endpoint}, "
                f"status={response.status_code}, details={details or response.text[:300]}"
                f"Playerok временно недоступен: operation={operation}, "
                f"status={response.status_code}, details={response.text[:300]}"
            )
            raise PlayerokApiError(
                f"Сервис каталога Playerok временно недоступен ({response.status_code}). "
                "Ключ принят; повторите поиск через несколько минут."
                f"Каталог Playerok временно недоступен ({response.status_code})."
            )

        try:
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise PlayerokApiError(
                f"Playerok API вернул некорректный ответ ({response.status_code})."
                f"Playerok вернул некорректный ответ ({response.status_code})."
            ) from exc

        if isinstance(payload, dict) and payload.get("error"):
            raise PlayerokApiError(str(payload["error"]))
        return payload
        errors = payload.get("errors") if isinstance(payload, dict) else None
        if errors:
            message = errors[0].get("message") if isinstance(errors[0], dict) else str(errors[0])
            print(f"Playerok GraphQL error ({operation}): {message}")
            raise PlayerokApiError("Playerok изменил формат каталога. Требуется обновить запросы.")

        data = payload.get("data") if isinstance(payload, dict) else None
        connection = data.get(operation) if isinstance(data, dict) else None
        if not isinstance(connection, dict):
            raise PlayerokApiError("Playerok вернул пустой или неизвестный формат каталога.")
        return connection

    def search_games(self, query, limit=10):
        return self._get("search_games", query=query, limit=max(1, min(limit, 50)))
        connection = self._query("games", {
            "pagination": {"first": max(1, min(limit, 20)), "after": None},
            "filter": {"name": query, "type": None}
        })
        games = [
            edge.get("node") for edge in connection.get("edges", [])
            if isinstance(edge, dict) and isinstance(edge.get("node"), dict)
        ]
        return {"games": games, "total_count": connection.get("totalCount", len(games))}

    def list_items(self, game_id, game_category_id=None, cursor=None, limit=50):
        return self._get(
            "list_items",
            game_id=game_id,
            game_category_id=game_category_id,
            cursor=cursor,
            limit=max(1, min(limit, 50)),
            sort_field="price",
            sort_direction="ASC"
        )
    def list_items(self, game_id, game_category_id=None, cursor=None, limit=50,
                   search_query=None):
        item_filter = {
            "gameId": game_id,
            "gameCategoryId": game_category_id,
            "status": ["APPROVED"]
        }
        if search_query:
            item_filter["searchQuery"] = search_query

        connection = self._query("items", {
            # Публичный запрос Playerok отклоняет страницы больше 20 элементов.
            "pagination": {"first": max(1, min(limit, 20)), "after": cursor},
            "filter": item_filter,
            "showForbiddenImage": True
        })
        products = []
        for edge in connection.get("edges", []):
            node = edge.get("node") if isinstance(edge, dict) else None
            if not isinstance(node, dict):
                continue
            product = dict(node)
            product["raw_price"] = product.get("rawPrice")
            product["seller"] = product.get("user") or {}
            if product.get("slug"):
                product["url"] = f"https://playerok.com/products/{product['slug']}"
            products.append(product)

        page_info = connection.get("pageInfo") or {}
        return {
            "products": products,
            "total_count": connection.get("totalCount", len(products)),
            "page_info": {
                "has_next_page": bool(page_info.get("hasNextPage")),
                "end_cursor": page_info.get("endCursor")
            }
        }


playerok_client = PlayerokClient()


def _collection(payload, *keys):
    """Извлекает массив из обычного либо обёрнутого ответа API."""
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return value
    data = payload.get("data")
    if isinstance(data, dict):
        return _collection(data, *keys)
    return []


def _normalize_search_text(value):
    value = str(value or '').casefold().replace('ё', 'е')
    return ' '.join(re.findall(r'[a-zа-я0-9]+', value, flags=re.IGNORECASE))


def _default_playerok_category(game):
    categories = game.get("categories") or []
    for category in categories:
        name = _normalize_search_text(category.get("name"))
        slug = _normalize_search_text(category.get("slug"))
        if "предмет" in name or slug in {"items", "item"}:
            return category
    return categories[0] if categories else None


def _playerok_game(user_data):
    settings = user_data.setdefault("settings", {})
    game = settings.setdefault("playerok_game", {})
    game.setdefault("id", None)
    game.setdefault("name", "SCraft")
    game.setdefault("slug", "scraft")
    game.setdefault("items_category_id", None)
    return game


def _playerok_category(user_data):
    settings = user_data.setdefault("settings", {})
    category = settings.setdefault("playerok_category", {})
    game = _playerok_game(user_data)
    category.setdefault("id", game.get("items_category_id"))
    category.setdefault("name", "Предметы")
    category.setdefault("slug", "items")
    return category


def _select_playerok_game(user_data, game):
    selected = _playerok_game(user_data)
    default_category = _default_playerok_category(game)
    selected.update({
        "id": game.get("id"),
        "name": game.get("name") or "Без названия",
        "slug": game.get("slug"),
        # Оставлено для совместимости с ранее сохранёнными данными.
        "items_category_id": default_category.get("id") if default_category else None
    })
    category = _playerok_category(user_data)
    if default_category:
        category.update({
            "id": default_category.get("id"),
            "name": default_category.get("name") or "Без категории",
            "slug": default_category.get("slug")
        })
    else:
        category.update({"id": None, "name": "Все категории", "slug": None})
    return selected


def _resolve_game(user_data):
    selected = _playerok_game(user_data)
    category = _playerok_category(user_data)
    if selected.get("id") and category.get("id"):
        return selected

    payload = playerok_client.search_games(selected.get("name") or "SCraft", limit=10)
    games = _collection(payload, "games", "results", "items")
    if not games:
        raise PlayerokApiError("Игра не найдена. Проверьте её название.")

    wanted = _normalize_search_text(selected.get("name"))
    game = min(
        games,
        key=lambda entry: (
            _normalize_search_text(entry.get("name")) != wanted,
            len(_normalize_search_text(entry.get("name")))
        )
    )
    return _select_playerok_game(user_data, game)


def _product_matches(product_name, query):
    name = _normalize_search_text(product_name)
    needle = _normalize_search_text(query)
    if not needle:
        return False
    if needle in name:
        return True
    tokens = [token for token in needle.split() if len(token) > 1]
    return bool(tokens) and all(token in name for token in tokens)


def _price_value(product):
    value = product.get("price")
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = re.sub(r'[^0-9,.]', '', str(value or '')).replace(',', '.')
    try:
        return float(cleaned)
    except ValueError:
        return float('inf')


def search_playerok_products(user_data, query, count):
    game = _resolve_game(user_data)
    category = _playerok_category(user_data)
    matches = []
    seen_ids = set()
    catalog_names = []
    cursor = None

    for _ in range(PLAYEROK_SEARCH_PAGES):
        payload = playerok_client.list_items(
            game_id=game.get("id"),
            game_category_id=category.get("id"),
            cursor=cursor,
            limit=50
            limit=50,
            search_query=query
        )
        products = _collection(payload, "products", "items", "results")
        for product in products:
            name = str(product.get("name") or '').strip()
            if name:
                catalog_names.append(name)
            product_id = product.get("id") or product.get("slug") or name
            if product_id in seen_ids:
                continue
            seen_ids.add(product_id)
            if product.get("status") not in (None, "APPROVED"):
                continue
            if _product_matches(name, query):
                matches.append(product)

        if len(matches) >= count:
            break
        page_info = payload.get("page_info", {}) if isinstance(payload, dict) else {}
        if not page_info.get("has_next_page"):
            break
        cursor = page_info.get("end_cursor")
        if not cursor:
            break

    needle = _normalize_search_text(query)
    matches.sort(key=lambda item: (
        _normalize_search_text(item.get("name")) != needle,
        not _normalize_search_text(item.get("name")).startswith(needle),
        _price_value(item)
    ))

    suggestions = []
    if not matches and catalog_names:
        normalized_to_original = {
            _normalize_search_text(name): name for name in catalog_names
        }
        close = difflib.get_close_matches(
            needle, list(normalized_to_original), n=3, cutoff=0.35
        )
        suggestions = [normalized_to_original[name] for name in close]

    return game, category, matches[:count], suggestions


def _format_playerok_results(game, category, query, products):
    lines = [
        f"🛒 <b>{html.escape(game.get('name') or 'Playerok')}</b>",
        f"📂 Категория: <b>{html.escape(category.get('name') or 'Все категории')}</b>",
        f"🔎 Запрос: <b>{html.escape(query)}</b>",
        f"📦 Найдено лотов: <b>{len(products)}</b>",
        ""
    ]
    prices = []
    for index, product in enumerate(products, 1):
        name = html.escape(str(product.get("name") or "Без названия"))
        price = _price_value(product)
        if price != float('inf'):
            prices.append(price)
            price_text = f"{price:,.2f}".replace(',', ' ').replace('.00', '') + " ₽"
        else:
            price_text = "цена не указана"
        seller = product.get("seller") or {}
        seller_name = html.escape(str(seller.get("username") or "не указан"))
        slug = str(product.get("slug") or '').strip()
        url = str(product.get("url") or '').strip()
        if not url and slug:
            url = f"https://playerok.com/products/{slug}"
        title = f'<a href="{html.escape(url, quote=True)}">{name}</a>' if url else name
        lines.append(f"{index}. {title}")
        lines.append(f"   💵 <b>{price_text}</b> · продавец: {seller_name}")

    if prices:
        minimum = min(prices)
        maximum = max(prices)
        average = sum(prices) / len(prices)
        lines.extend([
            "",
            f"📉 Минимум: <b>{minimum:.2f} ₽</b>",
            f"📊 Средняя: <b>{average:.2f} ₽</b>",
            f"📈 Максимум: <b>{maximum:.2f} ₽</b>"
        ])
    return '\n'.join(lines)


@bot.message_handler(commands=['playerok'])
@bot.message_handler(func=lambda message: message.text == '🛒 Playerok')
def show_playerok_menu(message):
    user_data = get_user_data(message.from_user.id)
    game = _playerok_game(user_data)
    category = _playerok_category(user_data)
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add(
        types.KeyboardButton('🔎 Найти товар'),
        types.KeyboardButton('🎮 Выбрать игру'),
        types.KeyboardButton('📂 Выбрать категорию'),
        types.KeyboardButton('🏠 Главное меню')
    )
    bot.send_message(
        message.chat.id,
        f"🛒 *PLAYEROK*\n\nТекущая игра: *{game.get('name', 'SCraft')}*\n"
        f"Категория: *{category.get('name', 'Предметы')}*\n"
        "Можно найти товар по названию и вывести от 1 до 10 самых дешёвых лотов.",
        reply_markup=markup,
        parse_mode='Markdown'
    )


@bot.message_handler(func=lambda message: message.text == '🎮 Выбрать игру')
def ask_playerok_game(message):
    bot.clear_step_handler_by_chat_id(message.chat.id)
    msg = bot.send_message(message.chat.id, "Введите название игры, например: SCraft")
    bot.register_next_step_handler(msg, process_playerok_game)


def process_playerok_game(message):
    query = (message.text or '').strip()
    if len(query) < 2:
        bot.reply_to(message, "❌ Название игры слишком короткое.")
        return
    progress = bot.send_message(message.chat.id, "⏳ Ищу игру на Playerok...")
    try:
        games = _collection(
            playerok_client.search_games(query=query, limit=10),
            "games", "results", "items"
        )
    except PlayerokApiError as exc:
        bot.reply_to(message, f"❌ {exc}")
        bot.edit_message_text(f"❌ {exc}", progress.chat.id, progress.message_id)
        return
    if not games:
        bot.reply_to(message, "❌ Игра не найдена. Проверьте правильность названия.")
        bot.edit_message_text(
            "❌ Игра не найдена. Проверьте правильность названия.",
            progress.chat.id,
            progress.message_id
        )
        return

    playerok_session[message.chat.id] = {"games": games}
    markup = types.InlineKeyboardMarkup(row_width=1)
    for index, game in enumerate(games[:10]):
        markup.add(types.InlineKeyboardButton(
            str(game.get("name") or "Без названия"),
            callback_data=f"pok_game:{index}"
        ))
    bot.send_message(message.chat.id, "Выберите игру:", reply_markup=markup)
    bot.edit_message_text(
        "Выберите игру:",
        progress.chat.id,
        progress.message_id,
        reply_markup=markup
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith('pok_game:'))
def select_playerok_game(call):
    try:
        index = int(call.data.split(':', 1)[1])
        game = playerok_session.get(call.message.chat.id, {}).get("games", [])[index]
    except (ValueError, IndexError):
        bot.answer_callback_query(call.id, "Список устарел. Повторите поиск.", show_alert=True)
        return

    user_data = get_user_data(call.from_user.id)
    selected = _select_playerok_game(user_data, game)
    category = _playerok_category(user_data)
    save_user_data(call.from_user.id, user_data)
    bot.answer_callback_query(call.id, "Игра выбрана")
    bot.edit_message_text(
        f"✅ Выбрана игра: <b>{html.escape(selected['name'])}</b>\n"
        f"📂 Категория: <b>{html.escape(category['name'])}</b>",
        call.message.chat.id,
        call.message.message_id,
        parse_mode='HTML'
    )


@bot.message_handler(func=lambda message: message.text == '📂 Выбрать категорию')
def choose_playerok_category(message):
    user_data = get_user_data(message.from_user.id)
    selected = _playerok_game(user_data)
    progress = bot.send_message(message.chat.id, "⏳ Загружаю категории Playerok...")
    try:
        payload = playerok_client.search_games(
            query=selected.get("name") or "SCraft",
            limit=10
        )
        games = _collection(payload, "games", "results", "items")
    except PlayerokApiError as exc:
        bot.reply_to(message, f"❌ {exc}")
        bot.edit_message_text(f"❌ {exc}", progress.chat.id, progress.message_id)
        return

    selected_id = selected.get("id")
    selected_name = _normalize_search_text(selected.get("name"))
    game = next(
        (entry for entry in games if selected_id and entry.get("id") == selected_id),
        None
    )
    if game is None:
        game = next(
            (entry for entry in games
             if _normalize_search_text(entry.get("name")) == selected_name),
            None
        )
    if game is None and games:
        game = games[0]

    categories = game.get("categories") if game else []
    if not categories:
        bot.reply_to(message, "❌ Для этой игры категории не найдены.")
        bot.edit_message_text(
            "❌ Для этой игры категории не найдены.",
            progress.chat.id,
            progress.message_id
        )
        return

    playerok_session.setdefault(message.chat.id, {})["categories"] = categories
    markup = types.InlineKeyboardMarkup(row_width=1)
    for index, category in enumerate(categories[:20]):
        markup.add(types.InlineKeyboardButton(
            str(category.get("name") or "Без категории"),
            callback_data=f"pok_category:{index}"
        ))
    bot.send_message(
        message.chat.id,
    bot.edit_message_text(
        f"📂 Выберите категорию для {selected.get('name', 'игры')}:",
        progress.chat.id,
        progress.message_id,
        reply_markup=markup
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith('pok_category:'))
def select_playerok_category(call):
    try:
        index = int(call.data.split(':', 1)[1])
        category = playerok_session.get(
            call.message.chat.id, {}
        ).get("categories", [])[index]
    except (ValueError, IndexError):
        bot.answer_callback_query(
            call.id,
            "Список устарел. Откройте категории ещё раз.",
            show_alert=True
        )
        return

    user_data = get_user_data(call.from_user.id)
    selected = _playerok_category(user_data)
    selected.update({
        "id": category.get("id"),
        "name": category.get("name") or "Без категории",
        "slug": category.get("slug")
    })
    save_user_data(call.from_user.id, user_data)
    bot.answer_callback_query(call.id, "Категория выбрана")
    bot.edit_message_text(
        f"✅ Выбрана категория: <b>{html.escape(selected['name'])}</b>",
        call.message.chat.id,
        call.message.message_id,
        parse_mode='HTML'
    )


@bot.message_handler(func=lambda message: message.text in ('🔎 Найти товар', '🔎 Найти предмет'))
def ask_playerok_item(message):
    bot.clear_step_handler_by_chat_id(message.chat.id)
    msg = bot.send_message(
        message.chat.id,
        "Введите название товара в выбранной категории. Например: QBU 191"
    )
    bot.register_next_step_handler(msg, process_playerok_item_name)


def process_playerok_item_name(message):
    query = (message.text or '').strip()
    if len(query) < 2:
        bot.reply_to(message, "❌ Ошибка в названии: введите хотя бы 2 символа.")
        return
    playerok_session.setdefault(message.chat.id, {})["item_query"] = query
    markup = types.InlineKeyboardMarkup(row_width=5)
    buttons = [
        types.InlineKeyboardButton(str(number), callback_data=f"pok_count:{number}")
        for number in range(1, 11)
    ]
    markup.add(*buttons)
    bot.send_message(
        message.chat.id,
        "Сколько лотов показать? Выберите от 1 до 10:",
        reply_markup=markup
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith('pok_count:'))
def run_playerok_search(call):
    bot.answer_callback_query(call.id)
    try:
        count = max(1, min(int(call.data.split(':', 1)[1]), 10))
    except ValueError:
        bot.send_message(call.message.chat.id, "❌ Некорректное количество лотов.")
        return

    query = playerok_session.get(call.message.chat.id, {}).get("item_query")
    if not query:
        bot.send_message(call.message.chat.id, "❌ Запрос устарел. Введите название ещё раз.")
        return

    progress = bot.send_message(call.message.chat.id, "⏳ Ищу актуальные лоты на Playerok...")
    user_data = get_user_data(call.from_user.id)
    try:
        game, category, products, suggestions = search_playerok_products(user_data, query, count)
        save_user_data(call.from_user.id, user_data)
    except PlayerokApiError as exc:
        bot.edit_message_text(f"❌ {exc}", progress.chat.id, progress.message_id)
        return
    except Exception as exc:
        print(f"Ошибка поиска Playerok: {exc}")
        bot.edit_message_text(
            "❌ Не удалось обработать ответ Playerok. Попробуйте позже.",
            progress.chat.id,
            progress.message_id
        )
        return

    if not products:
        text = "❌ Товар не найден. Возможно, ошибка в названии."
        if suggestions:
            text += "\n\nВозможно, вы имели в виду:\n• " + "\n• ".join(
                html.escape(name) for name in suggestions
            )
        bot.edit_message_text(text, progress.chat.id, progress.message_id, parse_mode='HTML')
        return

    bot.edit_message_text(
        _format_playerok_results(game, category, query, products),
        progress.chat.id,
        progress.message_id,
        parse_mode='HTML',
        disable_web_page_preview=True
    )


# ============================================
# ПОМОЩЬ И НАВИГАЦИЯ
# ============================================

@bot.message_handler(func=lambda message: message.text == 'ℹ️ Помощь')
def show_help(message):
    help_text = (
        "📖 *ПОМОЩЬ*\n\n"
        "🤖 *Бот финансовый помощник*\n\n"
        "💰 *Расчеты* - вычисление 26% и 6% от числа\n"
        "📋 *Лог* - хранение всех ваших записей с датами\n"
        "🎯 *Цель* - установка и отслеживание вашей цели\n"
        "📊 *Статистика* - анализ ваших данных\n"
        "🛒 *Playerok* - поиск и сравнение актуальных лотов\n\n"
        "⚡ *Быстрые команды:*\n"
        "/menu - Главное меню\n/calc - Калькулятор\n/log - Лог\n/goal - Цель\n/stats - Статистика\n"
        "/playerok - Поиск товаров Playerok\n/help - Помощь\n\n"
        "👤 *Ваши данные изолированы* — другие пользователи не видят ваш лог и цели."
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
                                '🛒 Playerok', '🔎 Найти товар', '🔎 Найти предмет',
                                '🎮 Выбрать игру', '📂 Выбрать категорию',
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
# ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ (после всех функций)
# ============================================

user_state = {}
temp_data = {}
playerok_session = {}


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
# УДАЛЕНИЕ ВЕБ-ХУКА ПРИ ЗАПУСКЕ (для Render)
# ============================================

# Удаляем веб-хук при запуске (для Render)
try:
    bot.delete_webhook()
    print("✅ Веб-хук удалён при запуске")
except Exception as e:
    print(f"Ошибка удаления веб-хука: {e}")

# ============================================
# ЗАПУСК (для Render — в отдельном потоке)
# ============================================

if __name__ == '__main__':
    print("🚀 Бот запускается на Render...")
    data = load_data()
    print(f"📁 Всего пользователей: {len(data.get('users', {}))}")


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
