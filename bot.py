import asyncio
import aiosqlite
import os
import random
import string
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
import logging

# ========== НАСТРОЙКИ ==========
BOT_TOKEN = "8809011538:AAFMpc0vBtMMHS0ZbXpjDbPmFkWfxW_jHtM"
ADMIN_ID = 5737961034
ADMIN_USERNAME = "@yng_beko"
CARD_NUMBER = "2200-7020-5664-8004"
PORT = int(os.environ.get("PORT", 8080))
BOT_NAME = "NetVault"
# ===============================

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

ROUTER_PRICE = 9800
PRICES = {'vless': 300, 'wireguard': 350, 'amneziawg': 350}
PROTOCOL_NAMES = {'vless': '🌐 VLESS', 'wireguard': '🔒 WireGuard', 'amneziawg': '🛡️ AmneziaWG'}
OS_NAMES = {'linux': '🐧 Linux', 'ios': '🍎 iOS/macOS', 'windows': '🪟 Windows', 'android': '📱 Android'}
DURATION_NAMES = {'1month': '1 месяц', '3months': '3 месяца', '6months': '6 месяцев', '1year': '1 год'}
DURATION_DAYS = {'1month': 30, '3months': 90, '6months': 180, '1year': 365}
DURATION_DISCOUNTS = {'1month': 0, '3months': 0.10, '6months': 0.20, '1year': 0.30}

COUNTRIES_VLESS = ['Армения','Великобритания','Греция','Исландия','Казахстан','Латвия','Литва','Нидерланды','Польша','Сербия','Турция','Финляндия','Швейцария','Япония']
COUNTRIES_WIREGUARD = ['Нидерланды']
COUNTRIES_AMNEZIAWG = ['Казахстан','Нидерланды','Россия','Турция']

# ========== БАЗА ДАННЫХ ==========
async def init_db():
    async with aiosqlite.connect('shop.db') as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT,
            balance REAL DEFAULT 0, total_spent REAL DEFAULT 0,
            registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        
        await db.execute('''CREATE TABLE IF NOT EXISTS purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, product TEXT, amount REAL,
            status TEXT DEFAULT 'pending', phone TEXT, address TEXT, full_name TEXT,
            protocol TEXT, country TEXT, duration TEXT, os TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            paid_at TIMESTAMP)''')
        
        await db.execute('''CREATE TABLE IF NOT EXISTS vpn_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT, protocol TEXT, country TEXT,
            key_data TEXT, is_sold BOOLEAN DEFAULT FALSE, sold_to INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            sold_at TIMESTAMP, expires_at TIMESTAMP)''')
        
        await db.execute('''CREATE TABLE IF NOT EXISTS promocodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE, discount INTEGER,
            max_uses INTEGER, used_count INTEGER DEFAULT 0,
            valid_until TIMESTAMP, created_by INTEGER)''')
        
        await db.execute('''CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, rating INTEGER,
            text TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        
        await db.execute('''CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, message TEXT,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, is_read BOOLEAN DEFAULT FALSE)''')
        
        await db.commit()

# ========== ФУНКЦИИ БД ==========
async def register_user(user_id, username, first_name):
    async with aiosqlite.connect('shop.db') as db:
        await db.execute('''INSERT OR REPLACE INTO users (user_id, username, first_name, last_activity) 
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)''', (user_id, username, first_name))
        await db.commit()

async def update_activity(user_id):
    async with aiosqlite.connect('shop.db') as db:
        await db.execute('UPDATE users SET last_activity=CURRENT_TIMESTAMP WHERE user_id=?', (user_id,))
        await db.commit()

async def add_purchase(user_id, product, amount, **kwargs):
    async with aiosqlite.connect('shop.db') as db:
        fields = ['user_id', 'product', 'amount']
        values = [user_id, product, amount]
        for k, v in kwargs.items():
            if v:
                fields.append(k)
                values.append(v)
        q = f"INSERT INTO purchases ({','.join(fields)}) VALUES ({','.join('?'*len(values))})"
        await db.execute(q, values)
        await db.commit()
        c = await db.execute('SELECT last_insert_rowid()')
        return (await c.fetchone())[0]

async def update_purchase_status(order_id, status):
    async with aiosqlite.connect('shop.db') as db:
        if status == 'paid':
            await db.execute('UPDATE purchases SET status=?, paid_at=CURRENT_TIMESTAMP WHERE id=?', (status, order_id))
        else:
            await db.execute('UPDATE purchases SET status=? WHERE id=?', (status, order_id))
        await db.commit()

async def get_purchase(order_id):
    async with aiosqlite.connect('shop.db') as db:
        c = await db.execute('SELECT * FROM purchases WHERE id=?', (order_id,))
        return await c.fetchone()

async def get_available_key(protocol, country):
    async with aiosqlite.connect('shop.db') as db:
        c = await db.execute('SELECT id, key_data FROM vpn_keys WHERE protocol=? AND country=? AND is_sold=FALSE LIMIT 1', (protocol, country))
        return await c.fetchone()

async def mark_key_sold(key_id, user_id, expires_at):
    async with aiosqlite.connect('shop.db') as db:
        await db.execute('UPDATE vpn_keys SET is_sold=TRUE, sold_to=?, sold_at=CURRENT_TIMESTAMP, expires_at=? WHERE id=?', (user_id, expires_at, key_id))
        await db.commit()

async def add_vpn_key(protocol, country, key_data):
    async with aiosqlite.connect('shop.db') as db:
        await db.execute('INSERT INTO vpn_keys (protocol, country, key_data) VALUES (?, ?, ?)', (protocol, country, key_data))
        await db.commit()

async def get_user_subscriptions(user_id):
    async with aiosqlite.connect('shop.db') as db:
        c = await db.execute("SELECT id, protocol, country, expires_at, key_data FROM vpn_keys WHERE sold_to=? AND is_sold=TRUE AND expires_at > datetime('now') ORDER BY expires_at", (user_id,))
        return await c.fetchall()

async def get_expiring_subscriptions():
    async with aiosqlite.connect('shop.db') as db:
        c = await db.execute("SELECT sold_to, protocol, country, expires_at FROM vpn_keys WHERE is_sold=TRUE AND expires_at BETWEEN datetime('now') AND datetime('now', '+3 days')")
        return await c.fetchall()

async def add_promocode(code, discount, max_uses, valid_days, created_by):
    valid_until = (datetime.now() + timedelta(days=valid_days)).strftime('%Y-%m-%d')
    async with aiosqlite.connect('shop.db') as db:
        await db.execute('INSERT INTO promocodes (code, discount, max_uses, valid_until, created_by) VALUES (?, ?, ?, ?, ?)', (code, discount, max_uses, valid_until, created_by))
        await db.commit()

async def check_promocode(code):
    async with aiosqlite.connect('shop.db') as db:
        c = await db.execute("SELECT discount, max_uses, used_count FROM promocodes WHERE code=? AND valid_until > datetime('now') AND used_count < max_uses", (code,))
        return await c.fetchone()

async def use_promocode(code):
    async with aiosqlite.connect('shop.db') as db:
        await db.execute('UPDATE promocodes SET used_count = used_count + 1 WHERE code=?', (code,))
        await db.commit()

async def add_review(user_id, rating, text):
    async with aiosqlite.connect('shop.db') as db:
        await db.execute('INSERT INTO reviews (user_id, rating, text) VALUES (?, ?, ?)', (user_id, rating, text))
        await db.commit()

async def get_reviews(limit=5):
    async with aiosqlite.connect('shop.db') as db:
        c = await db.execute('SELECT r.rating, r.text, u.first_name, r.created_at FROM reviews r JOIN users u ON r.user_id=u.user_id ORDER BY r.created_at DESC LIMIT ?', (limit,))
        return await c.fetchall()

async def add_notification(user_id, message):
    async with aiosqlite.connect('shop.db') as db:
        await db.execute('INSERT INTO notifications (user_id, message) VALUES (?, ?)', (user_id, message))
        await db.commit()

async def get_user_stats(user_id):
    async with aiosqlite.connect('shop.db') as db:
        c = await db.execute('SELECT COUNT(*), SUM(amount) FROM purchases WHERE user_id=? AND status="paid"', (user_id,))
        orders, spent = await c.fetchone()
        c = await db.execute("SELECT COUNT(*) FROM vpn_keys WHERE sold_to=? AND is_sold=TRUE AND expires_at > datetime('now')", (user_id,))
        active = (await c.fetchone())[0]
    return orders or 0, spent or 0, active or 0

# ========== HTTP ==========
async def handle_http(reader, writer):
    try: await asyncio.wait_for(reader.read(4096), timeout=2.0)
    except: pass
    writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 16\r\n\r\nNetVault Bot OK")
    await writer.drain(); writer.close()

async def run_http():
    server = await asyncio.start_server(handle_http, "0.0.0.0", PORT)
    async with server: await server.serve_forever()

# ========== КЛАВИАТУРЫ ==========
def main_menu(user_id=None):
    kb = [
        [InlineKeyboardButton("📡 Купить роутер", callback_data='buy_router')],
        [InlineKeyboardButton("🔑 Купить VPN ключ", callback_data='vpn_menu')],
        [InlineKeyboardButton("📋 Мои подписки", callback_data='my_subs')],
        [InlineKeyboardButton("👤 Профиль", callback_data='profile')],
        [InlineKeyboardButton("🎟️ Промокод", callback_data='promo')],
        [InlineKeyboardButton("⭐ Отзывы", callback_data='reviews')],
        [InlineKeyboardButton("ℹ️ Помощь", callback_data='help')],
    ]
    if user_id == ADMIN_ID:
        kb.append([InlineKeyboardButton("👑 Админ-панель", callback_data='admin')])
    return InlineKeyboardMarkup(kb)

def vpn_protocol_menu():
    kb = [
        [InlineKeyboardButton(f"🌐 VLESS — {PRICES['vless']}₽/мес", callback_data='vpn_vless')],
        [InlineKeyboardButton(f"🔒 WireGuard — {PRICES['wireguard']}₽/мес", callback_data='vpn_wireguard')],
        [InlineKeyboardButton(f"🛡️ AmneziaWG — {PRICES['amneziawg']}₽/мес", callback_data='vpn_amneziawg')],
        [InlineKeyboardButton("🔙 Назад", callback_data='back')],
    ]
    return InlineKeyboardMarkup(kb)

def country_menu(protocol):
    if protocol == 'vless': countries = COUNTRIES_VLESS
    elif protocol == 'wireguard': countries = COUNTRIES_WIREGUARD
    else: countries = COUNTRIES_AMNEZIAWG
    
    kb = []
    for c in countries:
        kb.append([InlineKeyboardButton(c, callback_data=f'country_{protocol}_{c}')])
    kb.append([InlineKeyboardButton("🔙 Назад", callback_data='vpn_menu')])
    return InlineKeyboardMarkup(kb)

def duration_menu(protocol, country):
    base = PRICES[protocol]
    kb = []
    for dur, discount in DURATION_DISCOUNTS.items():
        months = DURATION_DAYS[dur] // 30
        price = int(base * months * (1 - discount))
        label = f"{DURATION_NAMES[dur]} — {price}₽"
        if discount > 0:
            label += f" (-{int(discount*100)}%)"
        kb.append([InlineKeyboardButton(label, callback_data=f'dur_{protocol}_{country}_{dur}_{price}')])
    kb.append([InlineKeyboardButton("🔙 Назад", callback_data=f'vpn_{protocol}')])
    return InlineKeyboardMarkup(kb)

def os_menu(protocol, country, duration, price):
    kb = [
        [InlineKeyboardButton("🐧 Linux", callback_data=f'os_{protocol}_{country}_{duration}_{price}_linux')],
        [InlineKeyboardButton("🍎 iOS/macOS", callback_data=f'os_{protocol}_{country}_{duration}_{price}_ios')],
        [InlineKeyboardButton("🪟 Windows", callback_data=f'os_{protocol}_{country}_{duration}_{price}_windows')],
        [InlineKeyboardButton("📱 Android", callback_data=f'os_{protocol}_{country}_{duration}_{price}_android')],
        [InlineKeyboardButton("🔙 Назад", callback_data=f'country_{protocol}_{country}')],
    ]
    return InlineKeyboardMarkup(kb)

def admin_menu():
    kb = [
        [InlineKeyboardButton("📊 Статистика", callback_data='admin_stats')],
        [InlineKeyboardButton("🔑 Добавить ключ (инфо)", callback_data='admin_addkey_info')],
        [InlineKeyboardButton("🎟️ Создать промокод", callback_data='admin_promo')],
        [InlineKeyboardButton("📋 Все заказы", callback_data='admin_orders')],
        [InlineKeyboardButton("👥 Пользователи", callback_data='admin_users')],
        [InlineKeyboardButton("🔙 Назад", callback_data='back')],
    ]
    return InlineKeyboardMarkup(kb)

# ========== ОБРАБОТЧИКИ ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await register_user(user.id, user.username, user.first_name)
    
    welcome = (
        f"👋 *Добро пожаловать в {BOT_NAME}!*\n\n"
        f"🛒 Мы продаём:\n"
        f"📡 Роутер Netcraze NC-1121 — *{ROUTER_PRICE}₽*\n"
        f"🌐 VLESS — *{PRICES['vless']}₽/мес*\n"
        f"🔒 WireGuard — *{PRICES['wireguard']}₽/мес*\n"
        f"🛡️ AmneziaWG — *{PRICES['amneziawg']}₽/мес*\n\n"
        f"💳 Оплата переводом: `{CARD_NUMBER}`\n"
        f"📞 Поддержка: {ADMIN_USERNAME}\n\n"
        f"Выберите действие:"
    )
    await update.message.reply_text(welcome, parse_mode='Markdown', reply_markup=main_menu(user.id))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    user = q.from_user
    await register_user(user.id, user.username, user.first_name)
    await update_activity(user.id)
    
    # Навигация
    if data == 'back':
        await q.message.edit_text("🏠 Главное меню:", reply_markup=main_menu(user.id))
    
    # Роутер
    elif data == 'buy_router':
        context.user_data['awaiting'] = 'router_contact'
        await q.message.edit_text(
            f"📡 *Роутер Netcraze NC-1121*\n\n"
            f"✅ Wi-Fi 6 | 3000 Мбит/с\n✅ VPN из коробки\n✅ 4 LAN порта\n\n"
            f"💰 Цена: *{ROUTER_PRICE}₽*\n\n"
            f"📝 Введите данные для доставки (3 строки):\n"
            f"*1.* Имя Фамилия\n*2.* Телефон\n*3.* Адрес\n\n"
            f"Пример:\n`Иван Петров\n+79991234567\nМосква, ул. Ленина, 1`",
            parse_mode='Markdown'
        )
    
    # VPN меню
    elif data == 'vpn_menu':
        await q.message.edit_text("🔐 *Выберите протокол VPN:*", parse_mode='Markdown', reply_markup=vpn_protocol_menu())
    
    elif data.startswith('vpn_'):
        protocol = data.replace('vpn_', '')
        await q.message.edit_text(f"🌍 *Выберите страну для {PROTOCOL_NAMES[protocol]}:*", parse_mode='Markdown', reply_markup=country_menu(protocol))
    
    elif data.startswith('country_'):
        _, protocol, country = data.split('_', 2)
        context.user_data['vpn_protocol'] = protocol
        context.user_data['vpn_country'] = country
        await q.message.edit_text(f"⏱️ *Выберите срок ({country}):*", parse_mode='Markdown', reply_markup=duration_menu(protocol, country))
    
    elif data.startswith('dur_'):
        _, protocol, country, duration, price = data.split('_', 4)
        price = int(price)
        context.user_data['vpn_duration'] = duration
        context.user_data['vpn_price'] = price
        await q.message.edit_text(f"🖥️ *Выберите ОС:*", parse_mode='Markdown', reply_markup=os_menu(protocol, country, duration, price))
    
    elif data.startswith('os_'):
        _, protocol, country, duration, price, os_choice = data.split('_', 5)
        price = int(price)
        
        # Проверка промокода
        promocode = context.user_data.get('promocode')
        discount_pct = 0
        if promocode:
            promo = await check_promocode(promocode)
            if promo:
                discount_pct = promo[0]
                price = int(price * (1 - discount_pct / 100))
        
        order_id = await add_purchase(user.id, f'vpn_{protocol}', price, 
            protocol=protocol, country=country, duration=duration, os=os_choice)
        
        text = (
            f"✅ *Заказ №{order_id} оформлен!*\n\n"
            f"🔐 {PROTOCOL_NAMES[protocol]}\n"
            f"🌍 Страна: {country}\n"
            f"🖥️ ОС: {OS_NAMES[os_choice]}\n"
            f"⏱️ Срок: {DURATION_NAMES[duration]}\n"
            f"💰 Сумма: *{price}₽*"
        )
        if discount_pct > 0:
            text += f"\n🎟️ Промокод: -{discount_pct}%"
        
        text += f"\n\n💳 Оплатите переводом:\n`{CARD_NUMBER}`\n\n⚠️ После оплаты: {ADMIN_USERNAME}"
        
        await q.message.edit_text(text, parse_mode='Markdown', reply_markup=main_menu(user.id))
        await context.bot.send_message(ADMIN_ID, 
            f"🔔 *Новый заказ №{order_id}*\n🔐 {PROTOCOL_NAMES[protocol]}\n🌍 {country}\n💰 {price}₽\n👤 @{user.username or user.id}",
            parse_mode='Markdown')
        
        context.user_data.pop('promocode', None)
    
    # Профиль
    elif data == 'profile':
        orders, spent, active = await get_user_stats(user.id)
        subs = await get_user_subscriptions(user.id)
        text = (
            f"👤 *Профиль*\n\n"
            f"🆔 ID: `{user.id}`\n"
            f"📛 Имя: {user.first_name}\n"
            f"🏷️ username: @{user.username or 'нет'}\n"
            f"🛒 Заказов: {orders}\n"
            f"💰 Потрачено: {spent}₽\n"
            f"🔑 Активных подписок: {active}"
        )
        if subs:
            text += "\n\n📋 *Подписки:*\n"
            for s in subs[:3]:
                text += f"🔐 {PROTOCOL_NAMES.get(s[1], s[1])} ({s[2]}) до {s[3][:10]}\n"
        await q.message.edit_text(text, parse_mode='Markdown', reply_markup=main_menu(user.id))
    
    # Подписки
    elif data == 'my_subs':
        subs = await get_user_subscriptions(user.id)
        if subs:
            text = "🔑 *Ваши подписки:*\n\n"
            for s in subs:
                remaining = (datetime.strptime(s[3][:10], '%Y-%m-%d') - datetime.now()).days
                text += f"🔐 {PROTOCOL_NAMES.get(s[1], s[1])} ({s[2]})\n⏱️ До: {s[3][:10]} ({remaining} дн.)\n🔑 `{s[4][:30]}...`\n\n"
        else:
            text = "У вас нет активных подписок.\nПриобретите VPN в магазине!"
        await q.message.edit_text(text, parse_mode='Markdown', reply_markup=main_menu(user.id))
    
    # Промокод
    elif data == 'promo':
        context.user_data['awaiting'] = 'promocode'
        await q.message.edit_text(
            "🎟️ *Введите промокод:*\n\nОтправьте код текстом.\nЕсли код действителен, скидка применится к следующему заказу.",
            parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='back')]])
        )
    
    # Отзывы
    elif data == 'reviews':
        reviews = await get_reviews(5)
        if reviews:
            text = "⭐ *Отзывы:*\n\n"
            for r in reviews:
                stars = '⭐' * r[0]
                text += f"{stars} {r[1]}\n— {r[2]}\n\n"
        else:
            text = "Пока нет отзывов. Будьте первым!"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✍️ Написать отзыв", callback_data='add_review')],
            [InlineKeyboardButton("🔙 Назад", callback_data='back')],
        ])
        await q.message.edit_text(text, parse_mode='Markdown', reply_markup=kb)
    
    elif data == 'add_review':
        context.user_data['awaiting'] = 'review_text'
        await q.message.edit_text(
            "⭐ *Оставьте отзыв*\n\nНапишите оценку (1-5) и текст:\n`5 Отличный сервис!`",
            parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='reviews')]])
        )
    
    # Помощь
    elif data == 'help':
        text = (
            f"ℹ️ *Помощь*\n\n"
            f"📡 Роутер — {ROUTER_PRICE}₽ с доставкой\n"
            f"🌐 VLESS — {PRICES['vless']}₽/мес (14 стран)\n"
            f"🔒 WireGuard — {PRICES['wireguard']}₽/мес\n"
            f"🛡️ AmneziaWG — {PRICES['amneziawg']}₽/мес\n\n"
            f"💳 Оплата: перевод на карту\n"
            f"📞 Поддержка: {ADMIN_USERNAME}\n\n"
            f"Команды:\n"
            f"/start — главное меню\n"
            f"/mysubs — подписки\n"
            f"/profile — профиль\n"
            f"/support — поддержка\n"
            f"/promo — промокод"
        )
        await q.message.edit_text(text, parse_mode='Markdown', reply_markup=main_menu(user.id))
    
    # Админ-панель
    elif data == 'admin':
        if user.id != ADMIN_ID: return
        await q.message.edit_text("👑 *Админ-панель*", parse_mode='Markdown', reply_markup=admin_menu())
    
    elif data == 'admin_stats':
        if user.id != ADMIN_ID: return
        async with aiosqlite.connect('shop.db') as db:
            c = await db.execute('SELECT COUNT(*) FROM users'); users = (await c.fetchone())[0]
            c = await db.execute('SELECT COUNT(*), SUM(amount) FROM purchases'); orders, rev = await c.fetchone()
            c = await db.execute('SELECT COUNT(*) FROM vpn_keys WHERE is_sold=FALSE'); keys = (await c.fetchone())[0]
            c = await db.execute("SELECT COUNT(*) FROM vpn_keys WHERE is_sold=TRUE AND expires_at > datetime('now')"); active = (await c.fetchone())[0]
            c = await db.execute('SELECT COUNT(*) FROM promocodes WHERE valid_until > datetime("now")'); promos = (await c.fetchone())[0]
        text = (
            f"📊 *Статистика*\n\n"
            f"👥 Пользователей: {users}\n"
            f"🛒 Заказов: {orders or 0}\n"
            f"💰 Выручка: {rev or 0}₽\n"
            f"🔑 Ключей в наличии: {keys}\n"
            f"✅ Активных подписок: {active}\n"
            f"🎟️ Активных промокодов: {promos}"
        )
        await q.message.edit_text(text, parse_mode='Markdown', reply_markup=admin_menu())
    
    elif data == 'admin_addkey_info':
        if user.id != ADMIN_ID: return
        text = (
            "🔑 *Добавление ключа*\n\n"
            "Используйте команду:\n"
            "`/addkey протокол Страна ключ`\n\n"
            "Примеры:\n"
            "`/addkey vless Нидерланды vless://...`\n"
            "`/addkey wireguard Нидерланды конфиг`\n"
            "`/addkey amneziawg Россия ключ`"
        )
        await q.message.edit_text(text, parse_mode='Markdown', reply_markup=admin_menu())
    
    elif data == 'admin_promo':
        if user.id != ADMIN_ID: return
        context.user_data['awaiting'] = 'admin_promo'
        await q.message.edit_text(
            "🎟️ *Создать промокод*\n\n"
            "Отправьте: `код скидка% макс_исп дней`\n"
            "Пример: `SALE20 20 10 30`\n\n"
            "SALE20 — код, 20% скидка, 10 использований, 30 дней",
            parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='admin')]])
        )
    
    elif data == 'admin_orders':
        if user.id != ADMIN_ID: return
        async with aiosqlite.connect('shop.db') as db:
            c = await db.execute('SELECT id, user_id, product, amount, status FROM purchases ORDER BY id DESC LIMIT 10')
            orders = await c.fetchall()
        if orders:
            text = "📋 *Последние заказы:*\n\n"
            for o in orders:
                s = "✅" if o[4] == 'paid' else "⏳"
                text += f"{s} №{o[0]}: {o[2]} — {o[3]}₽ (user {o[1]})\n"
        else:
            text = "Заказов пока нет"
        await q.message.edit_text(text, parse_mode='Markdown', reply_markup=admin_menu())
    
    elif data == 'admin_users':
        if user.id != ADMIN_ID: return
        async with aiosqlite.connect('shop.db') as db:
            c = await db.execute('SELECT user_id, first_name, username, total_spent FROM users ORDER BY total_spent DESC LIMIT 10')
            users = await c.fetchall()
        if users:
            text = "👥 *Топ пользователей:*\n\n"
            for u in users:
                text += f"👤 {u[1]} (@{u[2] or 'нет'}) — {u[3] or 0}₽\n"
        else:
            text = "Нет данных"
        await q.message.edit_text(text, parse_mode='Markdown', reply_markup=admin_menu())

# ========== ТЕКСТОВЫЕ ОБРАБОТЧИКИ ==========
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text
    await update_activity(user.id)
    
    # Обработка ожиданий
    awaiting = context.user_data.get('awaiting')
    
    if awaiting == 'router_contact':
        lines = text.strip().split('\n')
        if len(lines) >= 3:
            name, phone, address = lines[0].strip(), lines[1].strip(), '\n'.join(lines[2:]).strip()
            order_id = await add_purchase(user.id, 'router', ROUTER_PRICE, full_name=name, phone=phone, address=address)
            await update.message.reply_text(
                f"✅ *Заказ №{order_id}*\n\n📡 Роутер NC-1121\n👤 {name}\n📞 {phone}\n📍 {address}\n💰 *{ROUTER_PRICE}₽*\n\n"
                f"💳 `{CARD_NUMBER}`\n⚠️ {ADMIN_USERNAME}",
                parse_mode='Markdown', reply_markup=main_menu(user.id)
            )
            await context.bot.send_message(ADMIN_ID,
                f"🔔 *Заказ №{order_id}*\n📡 Роутер\n👤 {name}\n📞 {phone}\n📍 {address}\n💰 {ROUTER_PRICE}₽",
                parse_mode='Markdown')
            context.user_data['awaiting'] = None
        else:
            await update.message.reply_text("❌ Введите 3 строки: Имя, Телефон, Адрес")
    
    elif awaiting == 'promocode':
        promo = await check_promocode(text.strip().upper())
        if promo:
            context.user_data['promocode'] = text.strip().upper()
            await update.message.reply_text(
                f"✅ Промокод активирован! Скидка *{promo[0]}%* на следующий заказ.",
                parse_mode='Markdown', reply_markup=main_menu(user.id)
            )
        else:
            await update.message.reply_text("❌ Промокод недействителен.", reply_markup=main_menu(user.id))
        context.user_data['awaiting'] = None
    
    elif awaiting == 'review_text':
        parts = text.split(' ', 1)
        try:
            rating = int(parts[0])
            review_text = parts[1] if len(parts) > 1 else ''
            if 1 <= rating <= 5:
                await add_review(user.id, rating, review_text)
                stars = '⭐' * rating
                await update.message.reply_text(f"{stars} Спасибо за отзыв!", reply_markup=main_menu(user.id))
            else:
                await update.message.reply_text("❌ Оценка от 1 до 5")
        except:
            await update.message.reply_text("❌ Формат: `5 Текст отзыва`", parse_mode='Markdown')
        context.user_data['awaiting'] = None
    
    elif awaiting == 'admin_promo':
        if user.id != ADMIN_ID: return
        parts = text.strip().split()
        if len(parts) >= 4:
            code, discount, max_uses, days = parts[0].upper(), int(parts[1]), int(parts[2]), int(parts[3])
            await add_promocode(code, discount, max_uses, days, user.id)
            await update.message.reply_text(f"✅ Промокод *{code}* создан!\nСкидка: {discount}%\nИспользований: {max_uses}\nДней: {days}",
                parse_mode='Markdown', reply_markup=admin_menu())
        context.user_data['awaiting'] = None

# ========== КОМАНДЫ ==========
async def addkey_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    args = context.args
    if len(args) < 3:
        await update.message.reply_text("❌ /addkey протокол Страна ключ\nПример: /addkey vless Нидерланды vless://...")
        return
    await add_vpn_key(args[0], args[1], ' '.join(args[2:]))
    await update.message.reply_text(f"✅ Ключ *{args[0]}* ({args[1]}) добавлен!", parse_mode='Markdown')

async def done_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    args = context.args
    if not args:
        await update.message.reply_text("❌ /done номер_заказа")
        return
    
    order_id = int(args[0])
    order = await get_purchase(order_id)
    if not order:
        await update.message.reply_text("❌ Заказ не найден")
        return
    
    user_id, product = order[1], order[2]
    
    if 'router' in product:
        await update_purchase_status(order_id, 'paid')
        await context.bot.send_message(user_id, f"✅ Заказ №{order_id} оплачен! {ADMIN_USERNAME} свяжется для доставки.")
        await update.message.reply_text(f"✅ Заказ №{order_id} отмечен как оплаченный")
    else:
        protocol = order[6] if len(order) > 6 else product.replace('vpn_', '')
        country = order[7] if len(order) > 7 else 'Нидерланды'
        duration = order[8] if len(order) > 8 else '1month'
        days = DURATION_DAYS.get(duration, 30)
        expires = (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d')
        
        key = await get_available_key(protocol, country)
        if key:
            await mark_key_sold(key[0], user_id, expires)
            await update_purchase_status(order_id, 'paid')
            await context.bot.send_message(user_id,
                f"✅ *Заказ №{order_id} оплачен!*\n\n🔑 Ключ:\n`{key[1]}`\n⏱️ До: {expires}\n\nСпасибо за покупку! 🛒",
                parse_mode='Markdown')
            await update.message.reply_text(f"✅ Ключ {protocol} ({country}) выдан пользователю {user_id}")
        else:
            await update.message.reply_text(f"❌ Нет ключей {protocol} ({country})!")

async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    async with aiosqlite.connect('shop.db') as db:
        c = await db.execute('SELECT COUNT(*) FROM users'); u = (await c.fetchone())[0]
        c = await db.execute('SELECT COUNT(*), SUM(amount) FROM purchases WHERE status="paid"'); o, r = await c.fetchone()
        c = await db.execute('SELECT COUNT(*) FROM vpn_keys WHERE is_sold=FALSE'); k = (await c.fetchone())[0]
        c = await db.execute("SELECT COUNT(*) FROM vpn_keys WHERE is_sold=TRUE AND expires_at > datetime('now')"); a = (await c.fetchone())[0]
    await update.message.reply_text(
        f"📊 *Статистика {BOT_NAME}*\n\n👥 Пользователей: {u}\n🛒 Заказов: {o or 0}\n💰 Выручка: {r or 0}₽\n🔑 Ключей: {k}\n✅ Активных: {a}",
        parse_mode='Markdown')

async def mysubs_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    subs = await get_user_subscriptions(update.effective_user.id)
    if subs:
        text = "🔑 *Подписки:*\n\n"
        for s in subs:
            d = (datetime.strptime(s[3][:10], '%Y-%m-%d') - datetime.now()).days
            text += f"🔐 {PROTOCOL_NAMES.get(s[1], s[1])} ({s[2]})\n⏱️ {s[3][:10]} ({d} дн.)\n🔑 `{s[4][:40]}...`\n\n"
    else:
        text = "Нет активных подписок"
    await update.message.reply_text(text, parse_mode='Markdown')

async def profile_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    orders, spent, active = await get_user_stats(user.id)
    await update.message.reply_text(
        f"👤 *Профиль*\n\n🆔 `{user.id}`\n📛 {user.first_name}\n🏷️ @{user.username or 'нет'}\n🛒 Заказов: {orders}\n💰 Потрачено: {spent}₽\n🔑 Активных: {active}",
        parse_mode='Markdown')

async def support_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"📞 *Поддержка*\n\nПо всем вопросам: {ADMIN_USERNAME}\n💳 Карта: `{CARD_NUMBER}`\n\nКоманды:\n/mysubs — подписки\n/profile — профиль",
        parse_mode='Markdown')

async def promo_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['awaiting'] = 'promocode'
    await update.message.reply_text("🎟️ Введите промокод:")

# ========== НАПОМИНАНИЯ ==========
async def check_expiring(app):
    while True:
        try:
            now = datetime.now()
            days_until_monday = (7 - now.weekday()) % 7
            if days_until_monday == 0 and now.hour >= 12:
                days_until_monday = 7
            next_monday = now + timedelta(days=days_until_monday)
            next_monday = next_monday.replace(hour=12, minute=0, second=0, microsecond=0)
            wait = (next_monday - now).total_seconds()
            await asyncio.sleep(wait)
            
            expiring = await get_expiring_subscriptions()
            for user_id, protocol, country, expires_at in expiring:
                try:
                    await app.bot.send_message(user_id,
                        f"⚠️ *Напоминание*\n\nПодписка {PROTOCOL_NAMES.get(protocol, protocol)} ({country})\nИстекает: {expires_at[:10]}\n\nПродлите: /start",
                        parse_mode='Markdown')
                except:
                    pass
        except Exception as e:
            logger.error(f"Check expiring error: {e}")
            await asyncio.sleep(3600)

# ========== ЗАПУСК ==========
async def main():
    await init_db()
    asyncio.create_task(run_http())
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Команды
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("addkey", addkey_cmd))
    app.add_handler(CommandHandler("done", done_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("mysubs", mysubs_cmd))
    app.add_handler(CommandHandler("profile", profile_cmd))
    app.add_handler(CommandHandler("support", support_cmd))
    app.add_handler(CommandHandler("promo", promo_cmd))
    
    # Кнопки и текст
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    
    # Напоминания
    asyncio.create_task(check_expiring(app))
    
    await app.initialize()
    await app.start()
    logger.info(f"🤖 {BOT_NAME} запущен!")
    await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    
    while True:
        await asyncio.sleep(3600)

if __name__ == '__main__':
    asyncio.run(main())
