import asyncio
import aiosqlite
import os
import json
import base64
import aiohttp
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
import logging

# ========== НАСТРОЙКИ ==========
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = 5737961034
ADMIN_USERNAME = "@yng_beko"
CARD_INFO = "2200-7020-5664-8004 (Игорь Д.)"
PORT = int(os.environ.get("PORT", 8080))
BOT_NAME = "NetVault"

# Gist Backup
GIST_TOKEN = os.environ.get("GIST_TOKEN")
GIST_ID = "63fb67d2ba3f326f99a9048d42f3b5f6"
GIST_DB_FILENAME = "shop_backup.txt"
GIST_SETTINGS_FILENAME = "settings_backup.txt"

SETTINGS_FILE = "settings.json"

# ---------- Настройки по умолчанию ----------
DEFAULT_START_TEXT = (
    "👋 {bot_name}!\n\n"
    "🆔 Ваш ID: {pid}\n\n"
    "📡 Роутеры от 7800р\n"
    "🌐 VLESS - {vless_price}р/мес\n"
    "🔒 WireGuard - {wg_price}р/мес\n"
    "🛡️ AmneziaWG - {awg_price}р/мес\n\n"
    "📞 {admin_username}"
)
DEFAULT_PRICES = {'vless': 400, 'wireguard': 450, 'amneziawg': 450}
DEFAULT_ROUTER_PRICES = {
    'Netcraze NC-1121': 7800,
    'Netcraze NC-1812': 34000,
    'Netcraze NC-3811': 16800,
    'Netcraze NC-3013': 12800,
    'Netcraze NC-2212 4G (SIM)': 10800
}
DEFAULT_ROUTER_SUB_PRICES = {1: 450, 3: 1200, 6: 2100, 12: 3250}

logging.basicConfig(level=logging.INFO)

# ---------- Загрузка / сохранение настроек ----------
async def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    # Пробуем из Gist
    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://api.github.com/gists/{GIST_ID}"
            headers = {"Authorization": f"token {GIST_TOKEN}"}
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    gist = await resp.json()
                    content = gist["files"][GIST_SETTINGS_FILENAME]["content"]
                    if content:
                        settings = json.loads(content)
                        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
                            json.dump(settings, f, ensure_ascii=False, indent=2)
                        return settings
    except Exception as e:
        logging.error(f"Ошибка загрузки настроек из Gist: {e}")
    return {
        'start_text': DEFAULT_START_TEXT,
        'prices': DEFAULT_PRICES.copy(),
        'router_prices': DEFAULT_ROUTER_PRICES.copy(),
        'router_sub_prices': DEFAULT_ROUTER_SUB_PRICES.copy()
    }

async def save_settings(settings):
    with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)
    try:
        encoded = json.dumps(settings, ensure_ascii=False)
        async with aiohttp.ClientSession() as session:
            url = f"https://api.github.com/gists/{GIST_ID}"
            headers = {
                "Authorization": f"token {GIST_TOKEN}",
                "Accept": "application/vnd.github+json"
            }
            data = {"files": {GIST_SETTINGS_FILENAME: {"content": encoded}}}
            async with session.patch(url, json=data, headers=headers) as resp:
                if resp.status != 200:
                    logging.error(f"❌ Ошибка сохранения настроек: {resp.status}")
    except Exception as e:
        logging.error(f"Ошибка сохранения настроек: {e}")

# Глобальные переменные (заполняются в main)
PRICES = DEFAULT_PRICES.copy()
ROUTERS = DEFAULT_ROUTER_PRICES.copy()
ROUTER_SUB_PRICES = DEFAULT_ROUTER_SUB_PRICES.copy()
START_TEXT_TEMPLATE = DEFAULT_START_TEXT

PROTOCOL_NAMES = {'vless': 'VLESS', 'wireguard': 'WireGuard', 'amneziawg': 'AmneziaWG'}
DURATION_NAMES = {'1month': '1 мес.', '3months': '3 мес.', '6months': '6 мес.', '1year': '1 год'}
DURATION_DAYS = {'1month': 30, '3months': 90, '6months': 180, '1year': 365}
DURATION_DISCOUNTS = {'1month': 0, '3months': 0.10, '6months': 0.20, '1year': 0.30}
ROUTER_SUB_MONTHS = {1: '1 месяц', 3: '3 месяца', 6: '6 месяцев', 12: '1 год'}

DEFAULT_COUNTRIES = {
    'vless': ['Нидерланды', 'Армения', 'Казахстан', 'Турция', 'Польша'],
    'wireguard': ['Нидерланды'],
    'amneziawg': ['Казахстан', 'Нидерланды', 'Россия', 'Турция']
}

def format_date(date_str):
    if not date_str: return "?"
    try:
        d = datetime.strptime(date_str[:10], '%Y-%m-%d')
        return d.strftime('%d.%m.%Y')
    except:
        return date_str[:10]

# ========== БАЗА ДАННЫХ ==========
async def init_db():
    async with aiosqlite.connect('shop.db') as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, personal_id INTEGER UNIQUE, username TEXT, first_name TEXT)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, product TEXT, amount REAL,
            status TEXT DEFAULT "pending", phone TEXT, address TEXT, full_name TEXT,
            protocol TEXT, country TEXT, duration TEXT,
            date TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS vpn_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT, protocol TEXT, country TEXT,
            key_data TEXT, is_sold BOOLEAN DEFAULT FALSE, sold_to INTEGER,
            personal_id INTEGER, expires_at TEXT)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS countries (
            id INTEGER PRIMARY KEY AUTOINCREMENT, protocol TEXT, country TEXT,
            is_active BOOLEAN DEFAULT TRUE, UNIQUE(protocol, country))''')
        await db.commit()
    for proto, cntrs in DEFAULT_COUNTRIES.items():
        for c in cntrs:
            try:
                async with aiosqlite.connect('shop.db') as db:
                    await db.execute('INSERT OR IGNORE INTO countries (protocol, country) VALUES (?, ?)', (proto, c))
                    await db.commit()
            except: pass

async def get_or_create_pid(uid, un, fn):
    async with aiosqlite.connect('shop.db') as db:
        c = await db.execute('SELECT personal_id FROM users WHERE user_id=?', (uid,))
        row = await c.fetchone()
        if row and row[0]: return row[0]
        c = await db.execute('SELECT COALESCE(MAX(personal_id),0)+1 FROM users')
        new_id = (await c.fetchone())[0]
        await db.execute('INSERT OR REPLACE INTO users VALUES (?,?,?,?)', (uid, new_id, un, fn))
        await db.commit()
        return new_id

async def add_order(uid, prod, amt, **kw):
    protocol = kw.get('protocol', '')
    country = kw.get('country', '')
    duration = kw.get('duration', '')
    async with aiosqlite.connect('shop.db') as db:
        await db.execute(
            'INSERT INTO purchases (user_id, product, amount, protocol, country, duration) VALUES (?, ?, ?, ?, ?, ?)',
            (uid, prod, amt, protocol, country, duration)
        )
        await db.commit()
        c = await db.execute('SELECT last_insert_rowid()')
        return (await c.fetchone())[0]

async def get_purchase(oid):
    async with aiosqlite.connect('shop.db') as db:
        c = await db.execute('SELECT * FROM purchases WHERE id=?', (oid,))
        return await c.fetchone()

async def update_purchase_status(oid, status):
    async with aiosqlite.connect('shop.db') as db:
        await db.execute('UPDATE purchases SET status=? WHERE id=?', (status, oid))
        await db.commit()

async def get_key(protocol, country):
    async with aiosqlite.connect('shop.db') as db:
        c = await db.execute('SELECT id,key_data FROM vpn_keys WHERE protocol=? AND country=? AND is_sold=FALSE LIMIT 1', (protocol, country))
        return await c.fetchone()

async def sell_key(kid, uid, pid, exp):
    async with aiosqlite.connect('shop.db') as db:
        await db.execute('UPDATE vpn_keys SET is_sold=TRUE, sold_to=?, personal_id=?, expires_at=? WHERE id=?', (uid, pid, exp, kid))
        await db.commit()

async def add_key(protocol, country, key_data):
    async with aiosqlite.connect('shop.db') as db:
        await db.execute('INSERT INTO vpn_keys (protocol,country,key_data) VALUES (?,?,?)', (protocol, country, key_data))
        await db.commit()

async def add_router_subscription(uid, pid, months):
    expires_at = (datetime.now() + timedelta(days=months*30)).strftime('%Y-%m-%d %H:%M:%S')
    async with aiosqlite.connect('shop.db') as db:
        await db.execute(
            'INSERT INTO vpn_keys (protocol, country, key_data, is_sold, sold_to, personal_id, expires_at) VALUES (?, ?, ?, TRUE, ?, ?, ?)',
            ('router', 'Роутер', '', uid, pid, expires_at)
        )
        await db.commit()

async def add_country(protocol, country):
    async with aiosqlite.connect('shop.db') as db:
        await db.execute('INSERT OR REPLACE INTO countries (protocol, country, is_active) VALUES (?,?,TRUE)', (protocol, country))
        await db.commit()

async def remove_country(protocol, country):
    async with aiosqlite.connect('shop.db') as db:
        await db.execute('UPDATE countries SET is_active=FALSE WHERE protocol=? AND country=?', (protocol, country))
        await db.commit()

async def get_countries(protocol):
    async with aiosqlite.connect('shop.db') as db:
        c = await db.execute('SELECT country FROM countries WHERE protocol=? AND is_active=TRUE ORDER BY country', (protocol,))
        return [r[0] for r in await c.fetchall()]

async def get_user_by_pid(pid):
    async with aiosqlite.connect('shop.db') as db:
        c = await db.execute('SELECT user_id, first_name, username FROM users WHERE personal_id=?', (pid,))
        return await c.fetchone()

async def get_subs_by_uid(uid):
    async with aiosqlite.connect('shop.db') as db:
        c = await db.execute("SELECT id, protocol, country, expires_at, key_data FROM vpn_keys WHERE sold_to=? AND is_sold=TRUE AND expires_at > datetime('now') ORDER BY expires_at", (uid,))
        return await c.fetchall()

async def get_subs_by_pid(pid):
    async with aiosqlite.connect('shop.db') as db:
        c = await db.execute("SELECT id, protocol, country, expires_at, key_data FROM vpn_keys WHERE personal_id=? AND is_sold=TRUE AND expires_at > datetime('now') ORDER BY expires_at", (pid,))
        return await c.fetchall()

async def extend_sub(key_id, days):
    async with aiosqlite.connect('shop.db') as db:
        if days >= 0:
            await db.execute(f"UPDATE vpn_keys SET expires_at = datetime(expires_at, '+{days} days') WHERE id=?", (key_id,))
        else:
            await db.execute(f"UPDATE vpn_keys SET expires_at = datetime(expires_at, '{days} days') WHERE id=?", (key_id,))
        await db.commit()
        c = await db.execute('SELECT expires_at, sold_to FROM vpn_keys WHERE id=?', (key_id,))
        return await c.fetchone()

# ========== GIST BACKUP ==========
async def backup_database():
    try:
        with open("shop.db", "rb") as f:
            encoded = base64.b64encode(f.read()).decode()
        async with aiohttp.ClientSession() as session:
            url = f"https://api.github.com/gists/{GIST_ID}"
            headers = {
                "Authorization": f"token {GIST_TOKEN}",
                "Accept": "application/vnd.github+json"
            }
            data = {"files": {GIST_DB_FILENAME: {"content": encoded}}}
            async with session.patch(url, json=data, headers=headers) as resp:
                if resp.status == 200:
                    logging.info("✅ База сохранена в Gist")
                else:
                    logging.error(f"❌ Ошибка сохранения базы: {resp.status}")
    except Exception as e:
        logging.error(f"Ошибка бекапа базы: {e}")

async def restore_database():
    if os.path.exists("shop.db"):
        return
    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://api.github.com/gists/{GIST_ID}"
            headers = {"Authorization": f"token {GIST_TOKEN}"}
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    gist = await resp.json()
                    content = gist["files"][GIST_DB_FILENAME]["content"]
                    if content and content != "placeholder":
                        decoded = base64.b64decode(content)
                        with open("shop.db", "wb") as f:
                            f.write(decoded)
                        logging.info("✅ База восстановлена из Gist")
                else:
                    logging.error(f"❌ Ошибка загрузки базы: {resp.status}")
    except Exception as e:
        logging.error(f"Ошибка восстановления базы: {e}")

async def periodic_backup():
    while True:
        await asyncio.sleep(600)
        await backup_database()

# HTTP-заглушка
async def http_handler(reader, writer):
    try: await asyncio.wait_for(reader.read(4096), timeout=2.0)
    except: pass
    writer.write(b"HTTP/1.1 200 OK\r\n\r\nOK"); await writer.drain(); writer.close()

# ========== КЛАВИАТУРЫ ==========
def main_menu(uid=None):
    kb = [
        [InlineKeyboardButton("📡 Купить роутер", callback_data='router_menu')],
        [InlineKeyboardButton("🔑 Купить VPN", callback_data='vpn_menu')],
        [InlineKeyboardButton("📋 Мои подписки", callback_data='my_subs'),
         InlineKeyboardButton("👤 Профиль", callback_data='profile')],
    ]
    if uid == ADMIN_ID:
        kb.append([InlineKeyboardButton("👑 Админ", callback_data='admin')])
    return InlineKeyboardMarkup(kb)

def router_menu_kb():
    kb = [[InlineKeyboardButton(f"{model} — {price}₽", callback_data=f'router_{model}')] for model, price in ROUTERS.items()]
    kb.append([InlineKeyboardButton("🔙 Назад", callback_data='back')])
    return InlineKeyboardMarkup(kb)

def router_subscription_kb():
    kb = []
    for months, price in ROUTER_SUB_PRICES.items():
        per_month = price // months
        kb.append([InlineKeyboardButton(f"{ROUTER_SUB_MONTHS[months]} — {price}₽ ({per_month}₽/мес)", callback_data=f'rsub_{months}')])
    kb.append([InlineKeyboardButton("🔙 Назад", callback_data='router_menu')])
    return InlineKeyboardMarkup(kb)

def vpn_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"VLESS - {PRICES['vless']}р/мес", callback_data='vpn_vless')],
        [InlineKeyboardButton(f"WireGuard - {PRICES['wireguard']}р/мес", callback_data='vpn_wireguard')],
        [InlineKeyboardButton(f"AmneziaWG - {PRICES['amneziawg']}р/мес", callback_data='vpn_amneziawg')],
        [InlineKeyboardButton("🔙 Назад", callback_data='back')],
    ])

async def country_kb(protocol):
    countries = await get_countries(protocol)
    if not countries: return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='vpn_menu')]])
    kb = [[InlineKeyboardButton(c, callback_data=f'country_{protocol}_{c}')] for c in countries]
    kb.append([InlineKeyboardButton("🔙 Назад", callback_data='vpn_menu')])
    return InlineKeyboardMarkup(kb)

def duration_kb(protocol, country):
    base = PRICES[protocol]
    kb = []
    for dur, disc in DURATION_DISCOUNTS.items():
        months = DURATION_DAYS[dur] // 30
        price = int(base * months * (1 - disc))
        label = f"{DURATION_NAMES[dur]} - {price}р"
        if disc > 0: label += f" (-{int(disc*100)}%)"
        kb.append([InlineKeyboardButton(label, callback_data=f'dur_{protocol}_{country}_{dur}_{price}')])
    kb.append([InlineKeyboardButton("🔙 Назад", callback_data=f'vpn_{protocol}')])
    return InlineKeyboardMarkup(kb)

def admin_main_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Статистика", callback_data='admin_stats')],
        [InlineKeyboardButton("🔑 Ключи", callback_data='admin_keys')],
        [InlineKeyboardButton("🌍 Страны", callback_data='admin_countries')],
        [InlineKeyboardButton("📅 Редактировать дату", callback_data='admin_editdate')],
        [InlineKeyboardButton("💰 Изменить цены", callback_data='admin_prices')],
        [InlineKeyboardButton("📝 Стартовый текст", callback_data='admin_start_text')],
        [InlineKeyboardButton("🔙 Назад", callback_data='back')],
    ])

def admin_price_main_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📡 Цена роутера", callback_data='price_router')],
        [InlineKeyboardButton("🔑 VPN ключи", callback_data='price_vpn')],
        [InlineKeyboardButton("⏱️ Подписка на роутер", callback_data='price_router_sub')],
        [InlineKeyboardButton("🔙 Назад", callback_data='admin')]
    ])

def admin_proto_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("VLESS", callback_data='adm_proto_vless')],
        [InlineKeyboardButton("WireGuard", callback_data='adm_proto_wireguard')],
        [InlineKeyboardButton("AmneziaWG", callback_data='adm_proto_amneziawg')],
        [InlineKeyboardButton("🔙 Назад", callback_data='admin')],
    ])

async def admin_country_kb(protocol):
    countries = await get_countries(protocol)
    kb = [[InlineKeyboardButton(c, callback_data=f'adm_country_{protocol}_{c}')] for c in countries]
    kb.append([InlineKeyboardButton("➕ Страну", callback_data=f'adm_addcountry_{protocol}')])
    kb.append([InlineKeyboardButton("🔙 Назад", callback_data='admin_keys')])
    return InlineKeyboardMarkup(kb)

async def admin_country_manage_kb(protocol):
    countries = await get_countries(protocol)
    kb = [[InlineKeyboardButton(f"🗑️ {c}", callback_data=f'adm_delcountry_{protocol}_{c}')] for c in countries]
    kb.append([InlineKeyboardButton("➕ Страну", callback_data=f'adm_addcountry_{protocol}')])
    kb.append([InlineKeyboardButton("🔙 Назад", callback_data='admin_countries')])
    return InlineKeyboardMarkup(kb)

async def admin_country_menu(protocol, country):
    async with aiosqlite.connect('shop.db') as db:
        c = await db.execute('SELECT COUNT(*) FROM vpn_keys WHERE protocol=? AND country=? AND is_sold=FALSE', (protocol, country))
        avail = (await c.fetchone())[0]
        c = await db.execute('SELECT COUNT(*) FROM vpn_keys WHERE protocol=? AND country=?', (protocol, country))
        total = (await c.fetchone())[0]
        c = await db.execute('SELECT COUNT(*) FROM vpn_keys WHERE protocol=? AND country=? AND is_sold=TRUE', (protocol, country))
        sold = (await c.fetchone())[0]
    text = f"🔐 {PROTOCOL_NAMES[protocol]} — {country}\n\n📦 Всего: {total} | ✅ {avail} | ❌ {sold}"
    kb = [
        [InlineKeyboardButton("➕ Ключ", callback_data=f'adm_add1_{protocol}_{country}')],
        [InlineKeyboardButton("📋 Список", callback_data=f'adm_list_{protocol}_{country}')],
        [InlineKeyboardButton("🗑️ Регион", callback_data=f'adm_remove_region_{protocol}_{country}')],
        [InlineKeyboardButton("🔙 Назад", callback_data=f'adm_proto_{protocol}')],
    ]
    return text, InlineKeyboardMarkup(kb)

def order_admin_kb(oid):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Выдать", callback_data=f'approve_{oid}'),
         InlineKeyboardButton("❌ Отклонить", callback_data=f'reject_{oid}')],
    ])

# ========== ОБРАБОТЧИКИ ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    pid = await get_or_create_pid(u.id, u.username, u.first_name)
    text = START_TEXT_TEMPLATE.format(
        bot_name=BOT_NAME,
        pid=pid,
        vless_price=PRICES['vless'],
        wg_price=PRICES['wireguard'],
        awg_price=PRICES['amneziawg'],
        admin_username=ADMIN_USERNAME
    )
    await update.message.reply_text(text, reply_markup=main_menu(u.id))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    d = q.data; u = q.from_user
    pid = await get_or_create_pid(u.id, u.username, u.first_name)

    # АДМИН
    if u.id == ADMIN_ID:
        if d == 'admin': await q.message.edit_text("👑 Админ", reply_markup=admin_main_kb()); return
        elif d == 'admin_stats':
            async with aiosqlite.connect('shop.db') as db:
                c = await db.execute('SELECT COUNT(*) FROM users'); us = (await c.fetchone())[0]
                c = await db.execute('SELECT COUNT(*),SUM(amount) FROM purchases'); o, r = await c.fetchone()
                c = await db.execute('SELECT COUNT(*) FROM vpn_keys WHERE is_sold=FALSE AND protocol != "router"'); k = (await c.fetchone())[0]
            await q.message.edit_text(f"📊 Пользователей: {us}\n🛒 Заказов: {o or 0}\n💰 Выручка: {r or 0}р\n🔑 Ключей: {k}", reply_markup=admin_main_kb()); return
        elif d == 'admin_keys': await q.message.edit_text("🔑 Протокол:", reply_markup=admin_proto_kb()); return
        elif d == 'admin_countries':
            await q.message.edit_text("🌍 Страны:", reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("VLESS", callback_data='adm_cnt_vless')],
                [InlineKeyboardButton("WireGuard", callback_data='adm_cnt_wireguard')],
                [InlineKeyboardButton("AmneziaWG", callback_data='adm_cnt_amneziawg')],
                [InlineKeyboardButton("🔙 Назад", callback_data='admin')]])); return
        elif d == 'admin_editdate':
            context.user_data['edit_step'] = 'input_pid'
            await q.message.edit_text("📅 Введите ID пользователя:"); return
        elif d == 'admin_prices':
            await q.message.edit_text("💰 Что меняем?", reply_markup=admin_price_main_kb()); return
        elif d == 'price_router':
            kb = [[InlineKeyboardButton(model, callback_data=f'price_router_model_{model}')] for model in ROUTERS]
            kb.append([InlineKeyboardButton("🔙 Назад", callback_data='admin_prices')])
            await q.message.edit_text("📡 Выберите модель:", reply_markup=InlineKeyboardMarkup(kb)); return
        elif d.startswith('price_router_model_'):
            model = d.replace('price_router_model_', '')
            context.user_data['price_target'] = ('router', model)
            await q.message.edit_text(f"📡 {model}\n\nВведите новую цену (число):"); return
        elif d == 'price_vpn':
            kb = [
                [InlineKeyboardButton("VLESS", callback_data='price_vpn_vless')],
                [InlineKeyboardButton("WireGuard", callback_data='price_vpn_wireguard')],
                [InlineKeyboardButton("AmneziaWG", callback_data='price_vpn_amneziawg')],
                [InlineKeyboardButton("🔙 Назад", callback_data='admin_prices')]
            ]
            await q.message.edit_text("🔑 Протокол:", reply_markup=InlineKeyboardMarkup(kb)); return
        elif d.startswith('price_vpn_'):
            protocol = d.replace('price_vpn_', '')
            context.user_data['price_target'] = ('vpn', protocol)
            await q.message.edit_text(f"🔑 {PROTOCOL_NAMES[protocol]}\n\nВведите цену за 1 месяц:"); return
        elif d == 'price_router_sub':
            context.user_data['price_target'] = ('router_sub', None)
            await q.message.edit_text("⏱️ Подписка на роутер\n\nВведите цену за 1 месяц:"); return
        elif d == 'admin_start_text':
            context.user_data['admin_setting'] = 'start_text'
            await q.message.edit_text("📝 Введите новый стартовый текст."); return
        elif d.startswith('adm_cnt_'): p=d.replace('adm_cnt_',''); await q.message.edit_text(f"🌍 {PROTOCOL_NAMES[p]}:", reply_markup=await admin_country_manage_kb(p)); return
        elif d.startswith('adm_delcountry_'): _,_,p,c=d.split('_',3); await remove_country(p,c); await q.answer("✅"); await q.message.edit_text(f"🌍 {PROTOCOL_NAMES[p]}:", reply_markup=await admin_country_manage_kb(p)); return
        elif d.startswith('adm_addcountry_'): p=d.replace('adm_addcountry_',''); context.user_data['add_country']=p; await q.message.edit_text(f"➕ Страна для {PROTOCOL_NAMES[p]}:"); return
        elif d.startswith('adm_remove_region_'): _,_,_,p,c=d.split('_',4); await remove_country(p,c); await q.answer("✅"); await q.message.edit_text("🔑 Страна:", reply_markup=await admin_country_kb(p)); return
        elif d.startswith('adm_proto_'): p=d.replace('adm_proto_',''); await q.message.edit_text("🌍 Страна:", reply_markup=await admin_country_kb(p)); return
        elif d.startswith('adm_country_'): _,_,p,c=d.split('_',3); text,kb=await admin_country_menu(p,c); await q.message.edit_text(text, reply_markup=kb); return
        elif d.startswith('adm_add1_'): _,_,p,c=d.split('_',3); context.user_data['admin_add']={'protocol':p,'country':c}; await q.message.edit_text(f"➕ Ключ\n{p} — {c}\n\nОтправьте ключ:"); return
        elif d.startswith('adm_list_'):
            _,_,p,c=d.split('_',3)
            async with aiosqlite.connect('shop.db') as db:
                cur=await db.execute('SELECT id,key_data,is_sold FROM vpn_keys WHERE protocol=? AND country=? AND protocol != "router" ORDER BY id DESC LIMIT 10',(p,c)); keys=await cur.fetchall()
            text=f"📋 {PROTOCOL_NAMES[p]} — {c}\n\n"+("\n".join([f"ID {k[0]}: {'✅' if not k[2] else '❌'} | {k[1][:30]}..." for k in keys]) if keys else "Нет ключей")
            await q.message.edit_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data=f'adm_country_{p}_{c}')]])); return
        elif d.startswith('approve_'): oid=int(d.replace('approve_','')); await approve_order(q,context,oid); return
        elif d.startswith('reject_'): oid=int(d.replace('reject_','')); await reject_order(q,context,oid); return
        elif d.startswith('edit_key_'):
            key_id=int(d.replace('edit_key_',''))
            context.user_data['edit_key_id']=key_id
            context.user_data['edit_step'] = 'input_days'
            await q.message.edit_text(f"🔑 Ключ ID: {key_id}\n\nВведите +дни или -дни (например +7 или -3):"); return

    # ОБЫЧНЫЕ КНОПКИ
    if d == 'back': await q.message.edit_text("🏠 Главное меню:", reply_markup=main_menu(u.id))
    elif d == 'router_menu':
        await q.message.edit_text("📡 Выберите модель роутера:", reply_markup=router_menu_kb())
    elif d.startswith('router_'):
        model = d.replace('router_', '')
        price = ROUTERS.get(model, 7800)
        context.user_data['router_model'] = model
        context.user_data['router_price'] = price
        await q.message.edit_text(f"📡 {model} — {price}₽\n\n⏱️ Выберите срок подписки:", reply_markup=router_subscription_kb())
    elif d.startswith('rsub_'):
        months = int(d.replace('rsub_', ''))
        sub_price = ROUTER_SUB_PRICES[months]
        context.user_data['router_sub_months'] = months
        context.user_data['router_sub_price'] = sub_price
        context.user_data['wait_router'] = 'name'
        context.user_data['router_data'] = {}
        await q.message.edit_text(f"📝 Шаг 1/4: Введите Имя и Фамилию:")
    elif d == 'vpn_menu': await q.message.edit_text("🔐 Протокол:", reply_markup=vpn_menu_kb())
    elif d.startswith('vpn_'): p=d.replace('vpn_',''); await q.message.edit_text(f"🌍 {PROTOCOL_NAMES[p]}:", reply_markup=await country_kb(p))
    elif d.startswith('country_'): _,p,c=d.split('_',2); context.user_data['vp']=p; context.user_data['vc']=c; await q.message.edit_text(f"⏱️ ({c}):", reply_markup=duration_kb(p,c))
    elif d.startswith('dur_'):
        _,p,c,dur,price=d.split('_',4); price=int(price)
        oid=await add_order(u.id,f'vpn_{p}',price,protocol=p,country=c,duration=dur)
        text=f"✅ Заказ №{oid}\n\n🔐 {PROTOCOL_NAMES[p]}\n🌍 {c}\n⏱️ {DURATION_NAMES[dur]}\n💰 {price}р\n\n⚠️ ПРИ ОПЛАТЕ УКАЖИТЕ НОМЕР ЗАКАЗА: {oid}\n\n📞 {ADMIN_USERNAME}\n💳 {CARD_INFO}"
        await q.message.edit_text(text, reply_markup=main_menu(u.id))
        await context.bot.send_message(ADMIN_ID, f"🔔 Заказ №{oid}\n{p} {c}\n💰 {price}р\n👤 @{u.username or u.id} (ID: {pid})", reply_markup=order_admin_kb(oid))
        asyncio.create_task(backup_database())
    elif d == 'my_subs':
        subs=await get_subs_by_uid(u.id)
        if subs:
            text = f"🔑 Подписки (ID: {pid}):\n\n"
            for s in subs:
                if s[1] == 'router':
                    text += f"📡 Подписка на роутер\n⏱️ До: {format_date(s[3])}\n\n"
                else:
                    text += f"🔐 {PROTOCOL_NAMES.get(s[1],s[1])} ({s[2]})\n⏱️ До: {format_date(s[3])}\n🔑 {s[4][:40]}...\n\n"
        else:
            text = f"Нет подписок\nВаш ID: {pid}"
        await q.message.edit_text(text, reply_markup=main_menu(u.id))
    elif d == 'profile':
        async with aiosqlite.connect('shop.db') as db:
            c=await db.execute('SELECT COUNT(*),SUM(amount) FROM purchases WHERE user_id=? AND status="paid"',(u.id,)); o,s=await c.fetchone()
        await q.message.edit_text(f"👤 {u.first_name}\n🆔 {pid}\n🏷️ @{u.username or 'нет'}\n🛒 Заказов: {o or 0}\n💰 Потрачено: {s or 0}р", reply_markup=main_menu(u.id))

# ========== ВЫДАЧА ЗАКАЗА ==========
async def approve_order(q, context, oid):
    o = await get_purchase(oid)
    if not o: await q.answer("Заказ не найден", show_alert=True); return
    uid, prod = o[1], o[2]
    pid = await get_or_create_pid(uid, None, None)
    if 'router' in prod:
        await update_purchase_status(oid, 'paid')
        await context.bot.send_message(uid, f"✅ Заказ №{oid} оплачен! {ADMIN_USERNAME} свяжется для доставки.")
        await q.message.edit_text(q.message.text + "\n\n✅ ОДОБРЕНО", reply_markup=None)
        asyncio.create_task(backup_database())
        return
    protocol = o[8] if len(o) > 8 and o[8] else None
    country = o[9] if len(o) > 9 and o[9] else None
    duration = o[10] if len(o) > 10 and o[10] else '1month'
    if not protocol or not country:
        await q.answer("❌ В заказе не указаны протокол или страна", show_alert=True); return
    days = DURATION_DAYS.get(duration, 30)
    exp = (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
    key = await get_key(protocol, country)
    if key:
        await sell_key(key[0], uid, pid, exp); await update_purchase_status(oid, 'paid')
        await context.bot.send_message(uid, f"✅ Заказ №{oid} оплачен!\n\n🔑 Ключ:\n{key[1]}\n⏱️ До: {format_date(exp)}")
        await q.message.edit_text(q.message.text + "\n\n✅ Ключ выдан!", reply_markup=None)
        asyncio.create_task(backup_database())
    else:
        await q.answer(f"❌ Нет ключей {protocol} ({country})!", show_alert=True)

async def reject_order(q, context, oid):
    o = await get_purchase(oid)
    if not o: await q.answer("Заказ не найден", show_alert=True); return
    await update_purchase_status(oid, 'rejected')
    await context.bot.send_message(o[1], f"❌ Заказ №{oid} отклонён. Свяжитесь с {ADMIN_USERNAME}")
    await q.message.edit_text(q.message.text + "\n\n❌ ОТКЛОНЕНО", reply_markup=None)
    asyncio.create_task(backup_database())

# ========== ТЕКСТОВЫЕ КОМАНДЫ ==========
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user; t = update.message.text.strip()
    pid = await get_or_create_pid(u.id, u.username, u.first_name)

    # Админ меняет настройки цен или стартовый текст
    if u.id == ADMIN_ID:
        if context.user_data.get('price_target'):
            target, item = context.user_data['price_target']
            try:
                new_price = int(t)
                settings = await load_settings()
                if target == 'router':
                    settings['router_prices'][item] = new_price
                    ROUTERS[item] = new_price
                    await update.message.reply_text(f"✅ Цена {item} изменена на {new_price}р")
                elif target == 'vpn':
                    settings['prices'][item] = new_price
                    PRICES[item] = new_price
                    p = {}
                    for dur, disc in DURATION_DISCOUNTS.items():
                        months = DURATION_DAYS[dur] // 30
                        p[dur] = int(new_price * months * (1 - disc))
                    await update.message.reply_text(
                        f"✅ Цены {PROTOCOL_NAMES[item]} обновлены:\n"
                        f"1 мес: {p['1month']}р\n"
                        f"3 мес: {p['3months']}р (-10%)\n"
                        f"6 мес: {p['6months']}р (-20%)\n"
                        f"12 мес: {p['1year']}р (-30%)"
                    )
                elif target == 'router_sub':
                    prices = {}
                    for months, label in ROUTER_SUB_MONTHS.items():
                        if months == 1: disc = 0
                        elif months == 3: disc = 0.10
                        elif months == 6: disc = 0.20
                        elif months == 12: disc = 0.30
                        price = int(new_price * months * (1 - disc))
                        prices[months] = price
                    settings['router_sub_prices'] = prices
                    ROUTER_SUB_PRICES.update(prices)
                    await update.message.reply_text(
                        f"✅ Подписка на роутер обновлена:\n"
                        f"1 мес: {prices[1]}р\n"
                        f"3 мес: {prices[3]}р (-10%)\n"
                        f"6 мес: {prices[6]}р (-20%)\n"
                        f"12 мес: {prices[12]}р (-30%)"
                    )
                await save_settings(settings)
                asyncio.create_task(backup_database())
            except:
                await update.message.reply_text("❌ Введите число")
            context.user_data.pop('price_target', None)
            return

        if context.user_data.get('admin_setting'):
            setting = context.user_data.pop('admin_setting')
            if setting == 'start_text':
                settings = await load_settings()
                settings['start_text'] = t
                await save_settings(settings)
                global START_TEXT_TEMPLATE
                START_TEXT_TEMPLATE = t
                await update.message.reply_text("✅ Стартовый текст обновлён")
            asyncio.create_task(backup_database())
            return

        if context.user_data.get('admin_add'):
            info = context.user_data['admin_add']; await add_key(info['protocol'], info['country'], t)
            context.user_data.pop('admin_add'); text, kb = await admin_country_menu(info['protocol'], info['country'])
            await update.message.reply_text(f"✅ Ключ добавлен!\n{text}", reply_markup=kb)
            asyncio.create_task(backup_database())
            return
        if context.user_data.get('add_country'):
            p = context.user_data['add_country']; await add_country(p, t)
            context.user_data.pop('add_country'); await update.message.reply_text(f"✅ {t} добавлена!", reply_markup=await admin_country_manage_kb(p))
            asyncio.create_task(backup_database())
            return
        if context.user_data.get('edit_step') == 'input_pid':
            try:
                target_pid = int(t)
                user_info = await get_user_by_pid(target_pid)
                if not user_info: await update.message.reply_text("❌ Не найден"); context.user_data.pop('edit_step',None); return
                subs = await get_subs_by_pid(target_pid)
                if not subs: await update.message.reply_text(f"👤 {user_info[1]} (ID: {target_pid})\nНет подписок", reply_markup=admin_main_kb()); context.user_data.pop('edit_step',None); return
                kb = []
                for s in subs:
                    display_name = "📡 Подписка на роутер" if s[1] == 'router' else f"🔐 {PROTOCOL_NAMES.get(s[1],s[1])} ({s[2]})"
                    kb.append([InlineKeyboardButton(f"{display_name} до {format_date(s[3])}", callback_data=f'edit_key_{s[0]}')])
                kb.append([InlineKeyboardButton("🔙 Назад", callback_data='admin')])
                await update.message.reply_text(f"👤 {user_info[1]} (ID: {target_pid})\n\nВыберите подписку:", reply_markup=InlineKeyboardMarkup(kb))
                context.user_data['edit_step'] = None
            except: await update.message.reply_text("❌ Числовой ID"); return
        if context.user_data.get('edit_step') == 'input_days':
            try:
                days = int(t)
                key_id = context.user_data.get('edit_key_id')
                if key_id:
                    result = await extend_sub(key_id, days)
                    if result:
                        new_exp, uid = result
                        sign = "+" if days >= 0 else ""
                        await context.bot.send_message(uid, f"📅 Подписка изменена!\n🔑 Ключ ID: {key_id}\n⏱️ До: {format_date(new_exp)}\n📅 {sign}{days} дн.")
                    await update.message.reply_text(f"✅ Изменено на {sign}{days} дн.", reply_markup=admin_main_kb())
                    asyncio.create_task(backup_database())
                context.user_data.pop('edit_key_id', None); context.user_data.pop('edit_step', None)
            except: await update.message.reply_text("❌ Введите число (+7 или -3)"); return

    # Заказ роутера по шагам
    if context.user_data.get('wait_router') == 'name':
        context.user_data['router_data'] = {'name': t}
        context.user_data['wait_router'] = 'phone'
        await update.message.reply_text("📝 Шаг 2/4: Введите телефон:")
        return
    elif context.user_data.get('wait_router') == 'phone':
        context.user_data['router_data']['phone'] = t
        context.user_data['wait_router'] = 'address'
        await update.message.reply_text("📝 Шаг 3/4: Введите адрес доставки:")
        return
    elif context.user_data.get('wait_router') == 'address':
        context.user_data['router_data']['address'] = t
        context.user_data['wait_router'] = 'username'
        await update.message.reply_text("📝 Шаг 4/4: Введите ваш Telegram username (например @username):")
        return
    elif context.user_data.get('wait_router') == 'username':
        rd = context.user_data['router_data']
        name = rd['name']
        phone = rd['phone']
        addr = rd['address']
        username = t if t.startswith('@') else '@' + t
        model = context.user_data.get('router_model', 'Netcraze NC-1121')
        router_price = context.user_data.get('router_price', 7800)
        sub_months = context.user_data.get('router_sub_months', 1)
        sub_price = context.user_data.get('router_sub_price', 450)
        total = router_price + sub_price

        oid = await add_order(u.id, f'router_{model}', total, full_name=name, phone=phone, address=addr)
        await add_router_subscription(u.id, pid, sub_months)

        await update.message.reply_text(
            f"✅ Заказ №{oid}\n\n📡 {model}\n⏱️ Подписка: {ROUTER_SUB_MONTHS[sub_months]} ({sub_price}р)\n💰 Итого: {total}р\n\n⚠️ ПРИ ОПЛАТЕ УКАЖИТЕ НОМЕР ЗАКАЗА: {oid}\n\n📞 {ADMIN_USERNAME}\n💳 {CARD_INFO}",
            reply_markup=main_menu(u.id)
        )
        await context.bot.send_message(ADMIN_ID, f"🔔 Заказ №{oid}\n📡 {model}\n👤 {name}\n📞 {phone}\n📍 {addr}\nUsername: {username}\n💰 {total}р\nID: {pid}", reply_markup=order_admin_kb(oid))
        asyncio.create_task(backup_database())
        context.user_data['wait_router'] = None
        context.user_data.pop('router_data', None)
        return

# ========== КОМАНДА ПРОВЕРКИ GIST ==========
async def checkgist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://api.github.com/gists/{GIST_ID}"
            headers = {"Authorization": f"token {GIST_TOKEN}"}
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    await update.message.reply_text("✅ Gist работает")
                else:
                    await update.message.reply_text(f"❌ Ошибка Gist: {resp.status}")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")

# ========== ОСТАЛЬНЫЕ КОМАНДЫ ==========
async def addkey_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    a = context.args
    if len(a) < 3: await update.message.reply_text("❌ /addkey протокол Страна ключ"); return
    await add_key(a[0], a[1], ' '.join(a[2:])); await update.message.reply_text(f"✅ {a[0]} ({a[1]})")
    asyncio.create_task(backup_database())

async def done_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    a = context.args
    if not a: await update.message.reply_text("❌ /done номер"); return
    oid = int(a[0])
    o = await get_purchase(oid)
    if not o: await update.message.reply_text("❌ Не найден"); return
    uid, prod = o[1], o[2]
    pid = await get_or_create_pid(uid, None, None)
    if 'router' in prod:
        await update_purchase_status(oid, 'paid'); await context.bot.send_message(uid, f"✅ Заказ №{oid} оплачен!")
        await update.message.reply_text("✅ Оплачен"); return
    protocol = o[8] if len(o) > 8 and o[8] else None
    country = o[9] if len(o) > 9 and o[9] else None
    duration = o[10] if len(o) > 10 and o[10] else '1month'
    if not protocol or not country:
        await update.message.reply_text("❌ В заказе не указаны протокол или страна"); return
    days = DURATION_DAYS.get(duration, 30)
    exp = (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
    key = await get_key(protocol, country)
    if key:
        await sell_key(key[0], uid, pid, exp); await update_purchase_status(oid, 'paid')
        await context.bot.send_message(uid, f"✅ Заказ №{oid} оплачен!\n\n🔑 Ключ:\n{key[1]}\n⏱️ До: {format_date(exp)}")
        await update.message.reply_text("✅ Ключ выдан!")
        asyncio.create_task(backup_database())
    else:
        await update.message.reply_text(f"❌ Нет ключей {protocol} ({country})!")

async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    async with aiosqlite.connect('shop.db') as db:
        c = await db.execute('SELECT COUNT(*) FROM users'); u = (await c.fetchone())[0]
        c = await db.execute('SELECT COUNT(*),SUM(amount) FROM purchases WHERE status="paid"'); o, r = await c.fetchone()
        c = await db.execute('SELECT COUNT(*) FROM vpn_keys WHERE is_sold=FALSE AND protocol != "router"'); k = (await c.fetchone())[0]
    await update.message.reply_text(f"📊 Пользователей: {u}\n🛒 Заказов: {o or 0}\n💰 Выручка: {r or 0}р\n🔑 Ключей: {k}")

async def mysubs_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pid = await get_or_create_pid(update.effective_user.id, update.effective_user.username, update.effective_user.first_name)
    subs = await get_subs_by_uid(update.effective_user.id)
    if subs:
        text = f"🔑 Подписки (ID: {pid}):\n\n"
        for s in subs:
            if s[1] == 'router':
                text += f"📡 Подписка на роутер\n⏱️ До: {format_date(s[3])}\n\n"
            else:
                text += f"🔐 {PROTOCOL_NAMES.get(s[1],s[1])} ({s[2]})\n⏱️ До: {format_date(s[3])}\n"
    else:
        text = f"Нет подписок\nID: {pid}"
    await update.message.reply_text(text)

# ========== ЗАПУСК ==========
async def main():
    global PRICES, ROUTERS, ROUTER_SUB_PRICES, START_TEXT_TEMPLATE
    
    settings = await load_settings()
    PRICES = settings.get('prices', DEFAULT_PRICES.copy())
    ROUTERS = settings.get('router_prices', DEFAULT_ROUTER_PRICES.copy())
    ROUTER_SUB_PRICES = settings.get('router_sub_prices', DEFAULT_ROUTER_SUB_PRICES.copy())
    START_TEXT_TEMPLATE = settings.get('start_text', DEFAULT_START_TEXT)
    
    await init_db()
    await restore_database()
    asyncio.create_task(periodic_backup())
    asyncio.create_task(asyncio.start_server(http_handler, "0.0.0.0", PORT))
    
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("addkey", addkey_cmd))
    app.add_handler(CommandHandler("done", done_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("mysubs", mysubs_cmd))
    app.add_handler(CommandHandler("checkgist", checkgist_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    
    asyncio.create_task(check_expired_subscriptions(app, ADMIN_ID))
    
    await app.initialize(); await app.start()
    print("🤖 Бот запущен!")
    await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    while True: await asyncio.sleep(3600)

if __name__ == '__main__':
    asyncio.run(main())
