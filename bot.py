import asyncio
import aiosqlite
import os
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
import logging

BOT_TOKEN = "8809011538:AAFMpc0vBtMMHS0ZbXpjDbPmFkWfxW_jHtM"
ADMIN_ID = 5737961034
ADMIN_USERNAME = "@yng_beko"
PORT = int(os.environ.get("PORT", 8080))
BOT_NAME = "NetVault"

logging.basicConfig(level=logging.INFO)

ROUTER_PRICE = 9800
PRICES = {'vless': 300, 'wireguard': 350, 'amneziawg': 350}
PROTOCOL_NAMES = {'vless': 'VLESS', 'wireguard': 'WireGuard', 'amneziawg': 'AmneziaWG'}
DURATION_NAMES = {'1month': '1 месяц', '3months': '3 месяца', '6months': '6 месяцев', '1year': '1 год'}
DURATION_DAYS = {'1month': 30, '3months': 90, '6months': 180, '1year': 365}
DURATION_DISCOUNTS = {'1month': 0, '3months': 0.10, '6months': 0.20, '1year': 0.30}
EXTEND_NAMES = {30: '+1 месяц', 90: '+3 месяца', 180: '+6 месяцев', 365: '+1 год',
                -30: '-1 месяц', -90: '-3 месяца', -180: '-6 месяцев', -365: '-1 год'}

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
    async with aiosqlite.connect('shop.db') as db:
        f = ['user_id','product','amount']; v = [uid,prod,amt]
        for k,val in kw.items():
            if val: f.append(k); v.append(val)
        await db.execute(f"INSERT INTO purchases ({','.join(f)}) VALUES ({','.join('?'*len(v))})", v)
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

async def get_subs_by_pid(pid):
    async with aiosqlite.connect('shop.db') as db:
        c = await db.execute("SELECT id, protocol, country, expires_at, key_data FROM vpn_keys WHERE personal_id=? AND is_sold=TRUE AND expires_at > datetime('now') ORDER BY expires_at", (pid,))
        return await c.fetchall()

async def get_subs_by_uid(uid):
    async with aiosqlite.connect('shop.db') as db:
        c = await db.execute("SELECT id, protocol, country, expires_at, key_data FROM vpn_keys WHERE sold_to=? AND is_sold=TRUE AND expires_at > datetime('now') ORDER BY expires_at", (uid,))
        return await c.fetchall()

async def extend_sub(key_id, days):
    async with aiosqlite.connect('shop.db') as db:
        await db.execute(f"UPDATE vpn_keys SET expires_at = datetime(expires_at, '{days} days') WHERE id=?", (key_id,))
        c = await db.execute('SELECT expires_at, sold_to FROM vpn_keys WHERE id=?', (key_id,))
        return await c.fetchone()

# HTTP
async def http_handler(reader, writer):
    try: await asyncio.wait_for(reader.read(4096), timeout=2.0)
    except: pass
    writer.write(b"HTTP/1.1 200 OK\r\n\r\nOK"); await writer.drain(); writer.close()

# ========== КЛАВИАТУРЫ ==========
def main_menu(uid=None):
    kb = [
        [InlineKeyboardButton("📡 Роутер", callback_data='buy_router'), InlineKeyboardButton("🔑 VPN", callback_data='vpn_menu')],
        [InlineKeyboardButton("📋 Подписки", callback_data='my_subs'), InlineKeyboardButton("👤 Профиль", callback_data='profile')],
        [InlineKeyboardButton("ℹ️ Помощь", callback_data='help')],
    ]
    if uid == ADMIN_ID: kb.append([InlineKeyboardButton("👑 Админ", callback_data='admin')])
    return InlineKeyboardMarkup(kb)

def vpn_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"VLESS - {PRICES['vless']}р", callback_data='vpn_vless')],
        [InlineKeyboardButton(f"WireGuard - {PRICES['wireguard']}р", callback_data='vpn_wireguard')],
        [InlineKeyboardButton(f"AmneziaWG - {PRICES['amneziawg']}р", callback_data='vpn_amneziawg')],
        [InlineKeyboardButton("Назад", callback_data='back')],
    ])

async def country_kb(protocol):
    countries = await get_countries(protocol)
    if not countries:
        return InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data='vpn_menu')]])
    kb = [[InlineKeyboardButton(c, callback_data=f'country_{protocol}_{c}')] for c in countries]
    kb.append([InlineKeyboardButton("Назад", callback_data='vpn_menu')])
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
    kb.append([InlineKeyboardButton("Назад", callback_data=f'vpn_{protocol}')])
    return InlineKeyboardMarkup(kb)

def admin_main_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Статистика", callback_data='admin_stats')],
        [InlineKeyboardButton("🔑 Ключи", callback_data='admin_keys')],
        [InlineKeyboardButton("🌍 Страны", callback_data='admin_countries')],
        [InlineKeyboardButton("⏱️ Продлить", callback_data='admin_extend')],
        [InlineKeyboardButton("⏪ Отнять время", callback_data='admin_reduce')],
        [InlineKeyboardButton("🔙 Назад", callback_data='back')],
    ])

def admin_proto_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("VLESS", callback_data='adm_proto_vless')],
        [InlineKeyboardButton("WireGuard", callback_data='adm_proto_wireguard')],
        [InlineKeyboardButton("AmneziaWG", callback_data='adm_proto_amneziawg')],
        [InlineKeyboardButton("Назад", callback_data='admin')],
    ])

async def admin_country_kb(protocol):
    countries = await get_countries(protocol)
    kb = [[InlineKeyboardButton(c, callback_data=f'adm_country_{protocol}_{c}')] for c in countries]
    kb.append([InlineKeyboardButton("➕ Страну", callback_data=f'adm_addcountry_{protocol}')])
    kb.append([InlineKeyboardButton("Назад", callback_data='admin_keys')])
    return InlineKeyboardMarkup(kb)

async def admin_country_manage_kb(protocol):
    countries = await get_countries(protocol)
    kb = [[InlineKeyboardButton(f"🗑️ {c}", callback_data=f'adm_delcountry_{protocol}_{c}')] for c in countries]
    kb.append([InlineKeyboardButton("➕ Страну", callback_data=f'adm_addcountry_{protocol}')])
    kb.append([InlineKeyboardButton("Назад", callback_data='admin_countries')])
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
        [InlineKeyboardButton("Назад", callback_data=f'adm_proto_{protocol}')],
    ]
    return text, InlineKeyboardMarkup(kb)

def extend_dur_kb(action='extend'):
    prefix = 'ext' if action == 'extend' else 'red'
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("1 мес (+30 дн)" if action == 'extend' else "1 мес (-30 дн)", callback_data=f'{prefix}_30')],
        [InlineKeyboardButton("3 мес (+90 дн)" if action == 'extend' else "3 мес (-90 дн)", callback_data=f'{prefix}_90')],
        [InlineKeyboardButton("6 мес (+180 дн)" if action == 'extend' else "6 мес (-180 дн)", callback_data=f'{prefix}_180')],
        [InlineKeyboardButton("1 год (+365 дн)" if action == 'extend' else "1 год (-365 дн)", callback_data=f'{prefix}_365')],
        [InlineKeyboardButton("Назад", callback_data='admin')],
    ])

def order_admin_kb(oid):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Выдать", callback_data=f'approve_{oid}'),
         InlineKeyboardButton("❌ Отклонить", callback_data=f'reject_{oid}')],
    ])

# ========== ОБРАБОТЧИКИ ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    pid = await get_or_create_pid(u.id, u.username, u.first_name)
    text = f"👋 {BOT_NAME}!\n\n🆔 Ваш ID: {pid}\n\n📡 Роутер - {ROUTER_PRICE}р\n🌐 VLESS - {PRICES['vless']}р\n🔒 WireGuard - {PRICES['wireguard']}р\n🛡️ AmneziaWG - {PRICES['amneziawg']}р\n\n📞 {ADMIN_USERNAME}"
    await update.message.reply_text(text, reply_markup=main_menu(u.id))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    d = q.data
    u = q.from_user
    pid = await get_or_create_pid(u.id, u.username, u.first_name)
    
    # АДМИН
    if u.id == ADMIN_ID:
        if d == 'admin':
            await q.message.edit_text("👑 Админ", reply_markup=admin_main_kb())
            return
        elif d == 'admin_stats':
            async with aiosqlite.connect('shop.db') as db:
                c = await db.execute('SELECT COUNT(*) FROM users'); us = (await c.fetchone())[0]
                c = await db.execute('SELECT COUNT(*),SUM(amount) FROM purchases'); o, r = await c.fetchone()
                c = await db.execute('SELECT COUNT(*) FROM vpn_keys WHERE is_sold=FALSE'); k = (await c.fetchone())[0]
            await q.message.edit_text(f"📊 Пользователей: {us}\n🛒 Заказов: {o or 0}\n💰 Выручка: {r or 0}р\n🔑 Ключей: {k}", reply_markup=admin_main_kb())
            return
        elif d == 'admin_keys':
            await q.message.edit_text("🔑 Протокол:", reply_markup=admin_proto_kb())
            return
        elif d == 'admin_countries':
            await q.message.edit_text("🌍 Страны:", reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("VLESS", callback_data='adm_cnt_vless')],
                [InlineKeyboardButton("WireGuard", callback_data='adm_cnt_wireguard')],
                [InlineKeyboardButton("AmneziaWG", callback_data='adm_cnt_amneziawg')],
                [InlineKeyboardButton("Назад", callback_data='admin')]
            ]))
            return
        elif d == 'admin_extend':
            context.user_data['ext_action'] = 'extend'
            context.user_data['ext_step'] = 'input_pid'
            await q.message.edit_text("⏱️ Продление\n\nВведите ID пользователя:")
            return
        elif d == 'admin_reduce':
            context.user_data['ext_action'] = 'reduce'
            context.user_data['ext_step'] = 'input_pid'
            await q.message.edit_text("⏪ Отнять время\n\nВведите ID пользователя:")
            return
        elif d.startswith('adm_cnt_'):
            p = d.replace('adm_cnt_', '')
            await q.message.edit_text(f"🌍 {PROTOCOL_NAMES[p]}:", reply_markup=await admin_country_manage_kb(p))
            return
        elif d.startswith('adm_delcountry_'):
            _, _, p, c = d.split('_', 3)
            await remove_country(p, c)
            await q.answer("✅ Удалён!")
            await q.message.edit_text(f"🌍 {PROTOCOL_NAMES[p]}:", reply_markup=await admin_country_manage_kb(p))
            return
        elif d.startswith('adm_addcountry_'):
            p = d.replace('adm_addcountry_', '')
            context.user_data['add_country'] = p
            await q.message.edit_text(f"➕ Страна для {PROTOCOL_NAMES[p]}:")
            return
        elif d.startswith('adm_remove_region_'):
            _, _, _, p, c = d.split('_', 4)
            await remove_country(p, c)
            await q.answer("✅")
            await q.message.edit_text("🔑 Страна:", reply_markup=await admin_country_kb(p))
            return
        elif d.startswith('adm_proto_'):
            p = d.replace('adm_proto_', '')
            await q.message.edit_text("🌍 Страна:", reply_markup=await admin_country_kb(p))
            return
        elif d.startswith('adm_country_'):
            _, _, p, c = d.split('_', 3)
            text, kb = await admin_country_menu(p, c)
            await q.message.edit_text(text, reply_markup=kb)
            return
        elif d.startswith('adm_add1_'):
            _, _, p, c = d.split('_', 3)
            context.user_data['admin_add'] = {'protocol': p, 'country': c}
            await q.message.edit_text(f"➕ Ключ\n{p} — {c}\n\nОтправьте ключ:")
            return
        elif d.startswith('adm_list_'):
            _, _, p, c = d.split('_', 3)
            async with aiosqlite.connect('shop.db') as db:
                cur = await db.execute('SELECT id, key_data, is_sold FROM vpn_keys WHERE protocol=? AND country=? ORDER BY id DESC LIMIT 10', (p, c))
                keys = await cur.fetchall()
            if keys:
                text = f"📋 {PROTOCOL_NAMES[p]} — {c}\n\n"
                for k in keys:
                    s = "✅" if not k[2] else "❌"
                    text += f"ID {k[0]}: {s} | {k[1][:30]}...\n"
            else:
                text = "Нет ключей"
            await q.message.edit_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data=f'adm_country_{p}_{c}')]]))
            return
        elif d.startswith('approve_'):
            oid = int(d.replace('approve_', ''))
            await approve_order(q, context, oid)
            return
        elif d.startswith('reject_'):
            oid = int(d.replace('reject_', ''))
            await reject_order(q, context, oid)
            return
        elif d.startswith('ext_key_'):
            key_id = int(d.replace('ext_key_', ''))
            context.user_data['ext_key_id'] = key_id
            action = context.user_data.get('ext_action', 'extend')
            await q.message.edit_text(f"🔑 Ключ ID: {key_id}\n\nСрок:", reply_markup=extend_dur_kb(action))
            return
        elif d.startswith('ext_'):
            days = int(d.replace('ext_', ''))
            await do_extend(q, context, days)
            return
        elif d.startswith('red_'):
            days = -int(d.replace('red_', ''))
            await do_extend(q, context, days)
            return
    
    # ОБЫЧНЫЕ
    if d == 'back':
        await q.message.edit_text("🏠 Меню:", reply_markup=main_menu(u.id))
    elif d == 'buy_router':
        context.user_data['wait'] = 'router'
        await q.message.edit_text(f"📡 Роутер - {ROUTER_PRICE}р\n\nВведите 3 строки:\n1. Имя\n2. Телефон\n3. Адрес")
    elif d == 'vpn_menu':
        await q.message.edit_text("🔐 Протокол:", reply_markup=vpn_menu_kb())
    elif d.startswith('vpn_'):
        p = d.replace('vpn_', '')
        kb = await country_kb(p)
        await q.message.edit_text(f"🌍 {PROTOCOL_NAMES[p]}:", reply_markup=kb)
    elif d.startswith('country_'):
        _, p, c = d.split('_', 2)
        context.user_data['vp'] = p
        context.user_data['vc'] = c
        await q.message.edit_text(f"⏱️ ({c}):", reply_markup=duration_kb(p, c))
    elif d.startswith('dur_'):
        _, p, c, dur, price = d.split('_', 4)
        price = int(price)
        oid = await add_order(u.id, f'vpn_{p}', price, protocol=p, country=c, duration=dur)
        text = f"✅ Заказ №{oid}\n\n🔐 {PROTOCOL_NAMES[p]}\n🌍 {c}\n⏱️ {DURATION_NAMES[dur]}\n💰 {price}р\n\n⚠️ ПРИ ОПЛАТЕ УКАЖИТЕ НОМЕР ЗАКАЗА: {oid}\n\n📞 {ADMIN_USERNAME}"
        await q.message.edit_text(text, reply_markup=main_menu(u.id))
        await context.bot.send_message(ADMIN_ID, f"🔔 Заказ №{oid}\n{p} {c}\n💰 {price}р\n👤 @{u.username or u.id} (ID: {pid})", reply_markup=order_admin_kb(oid))
    elif d == 'my_subs':
        subs = await get_subs_by_uid(u.id)
        if subs:
            text = f"🔑 Подписки (ID: {pid}):\n\n"
            for s in subs:
                text += f"🔐 {PROTOCOL_NAMES.get(s[1],s[1])} ({s[2]})\n⏱️ До: {format_date(s[3])}\n🔑 {s[4][:40]}...\n\n"
        else:
            text = f"Нет подписок\nВаш ID: {pid}"
        await q.message.edit_text(text, reply_markup=main_menu(u.id))
    elif d == 'profile':
        async with aiosqlite.connect('shop.db') as db:
            c = await db.execute('SELECT COUNT(*),SUM(amount) FROM purchases WHERE user_id=? AND status="paid"', (u.id,))
            o, s = await c.fetchone()
        await q.message.edit_text(f"👤 {u.first_name}\n🆔 {pid}\n🏷️ @{u.username or 'нет'}\n🛒 Заказов: {o or 0}\n💰 Потрачено: {s or 0}р", reply_markup=main_menu(u.id))
    elif d == 'help':
        await q.message.edit_text(f"ℹ️ {BOT_NAME}\n📡 {ROUTER_PRICE}р\n🌐 {PRICES['vless']}р\n🔒 {PRICES['wireguard']}р\n🛡️ {PRICES['amneziawg']}р\n📞 {ADMIN_USERNAME}\n🆔 Ваш ID: {pid}", reply_markup=main_menu(u.id))

async def do_extend(q, context, days):
    key_id = context.user_data.get('ext_key_id')
    if not key_id: return
    
    result = await extend_sub(key_id, days)
    if result:
        new_exp, uid = result
        label = EXTEND_NAMES.get(days, f'{days} дн.')
        await context.bot.send_message(uid, f"✅ Вам изменили подписку!\n\n🔑 Ключ ID: {key_id}\n⏱️ До: {format_date(new_exp)}\n📅 {label}")
    
    context.user_data.pop('ext_key_id', None)
    context.user_data.pop('ext_action', None)
    text = f"✅ Подписка изменена!\nДо: {format_date(new_exp) if result else '?'}\n{label if result else ''}"
    await q.message.edit_text(text, reply_markup=admin_main_kb())

async def approve_order(q, context, oid):
    o = await get_purchase(oid)
    if not o:
        await q.answer("Заказ не найден", show_alert=True)
        return
    
    uid = o[1]
    prod = o[2]
    pid = await get_or_create_pid(uid, None, None)
    
    if 'router' in prod:
        await update_purchase_status(oid, 'paid')
        await context.bot.send_message(uid, f"✅ Заказ №{oid} оплачен! {ADMIN_USERNAME} свяжется.")
        await q.message.edit_text(q.message.text + "\n\n✅ ОДОБРЕНО", reply_markup=None)
        await q.answer("✅ Заказ одобрен!", show_alert=True)
    else:
        # VPN заказ - берём протокол и страну из заказа
        protocol = o[6]
        country = o[7]
        duration = o[8]
        
        if not protocol:
            protocol = prod.replace('vpn_', '')
        if not country:
            country = 'Нидерланды'
        if not duration:
            duration = '1month'
        
        days = DURATION_DAYS.get(duration, 30)
        exp = (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
        
        key = await get_key(protocol, country)
        if key:
            await sell_key(key[0], uid, pid, exp)
            await update_purchase_status(oid, 'paid')
            await context.bot.send_message(uid, f"✅ Заказ №{oid} оплачен!\n\n🔑 Ключ:\n{key[1]}\n⏱️ До: {format_date(exp)}")
            await q.message.edit_text(q.message.text + "\n\n✅ Ключ выдан!", reply_markup=None)
            await q.answer("✅ Ключ выдан!", show_alert=True)
        else:
            await q.answer(f"❌ Нет ключей {PROTOCOL_NAMES.get(protocol, protocol)} ({country})!", show_alert=True)

async def reject_order(q, context, oid):
    o = await get_purchase(oid)
    if not o:
        await q.answer("Заказ не найден", show_alert=True)
        return
    uid = o[1]
    await update_purchase_status(oid, 'rejected')
    await context.bot.send_message(uid, f"❌ Заказ №{oid} отклонён. Свяжитесь с {ADMIN_USERNAME}")
    await q.message.edit_text(q.message.text + "\n\n❌ ОТКЛОНЕНО", reply_markup=None)
    await q.answer("❌ Заказ отклонён", show_alert=True)

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    t = update.message.text
    pid = await get_or_create_pid(u.id, u.username, u.first_name)
    
    if u.id == ADMIN_ID and context.user_data.get('admin_add'):
        info = context.user_data['admin_add']
        await add_key(info['protocol'], info['country'], t.strip())
        context.user_data.pop('admin_add')
        text, kb = await admin_country_menu(info['protocol'], info['country'])
        await update.message.reply_text(f"✅ Ключ добавлен!\n{text}", reply_markup=kb)
        return
    
    if u.id == ADMIN_ID and context.user_data.get('add_country'):
        p = context.user_data['add_country']
        await add_country(p, t.strip())
        context.user_data.pop('add_country')
        await update.message.reply_text(f"✅ {t.strip()} добавлена!", reply_markup=await admin_country_manage_kb(p))
        return
    
    if u.id == ADMIN_ID and context.user_data.get('ext_step') == 'input_pid':
        try:
            target_pid = int(t.strip())
            user_info = await get_user_by_pid(target_pid)
            if not user_info:
                await update.message.reply_text("❌ Не найден")
                context.user_data.pop('ext_step', None)
                return
            subs = await get_subs_by_pid(target_pid)
            if not subs:
                await update.message.reply_text(f"👤 {user_info[1]} (ID: {target_pid})\nНет подписок", reply_markup=admin_main_kb())
                context.user_data.pop('ext_step', None)
                return
            kb = []
            for s in subs:
                kb.append([InlineKeyboardButton(f"🔐 {PROTOCOL_NAMES.get(s[1],s[1])} ({s[2]}) до {format_date(s[3])}", callback_data=f'ext_key_{s[0]}')])
            kb.append([InlineKeyboardButton("Назад", callback_data='admin')])
            await update.message.reply_text(f"👤 {user_info[1]} (ID: {target_pid})\n\nВыберите подписку:", reply_markup=InlineKeyboardMarkup(kb))
            context.user_data['ext_step'] = None
        except:
            await update.message.reply_text("❌ Числовой ID")
        return
    
    if context.user_data.get('wait') == 'router':
        p = t.strip().split('\n')
        if len(p) >= 3:
            name, phone, addr = p[0].strip(), p[1].strip(), '\n'.join(p[2:]).strip()
            oid = await add_order(u.id, 'router', ROUTER_PRICE, full_name=name, phone=phone, address=addr)
            await update.message.reply_text(
                f"✅ Заказ №{oid}\n\n📡 Роутер\n👤 {name}\n📞 {phone}\n📍 {addr}\n💰 {ROUTER_PRICE}р\n\n⚠️ ПРИ ОПЛАТЕ УКАЖИТЕ НОМЕР ЗАКАЗА: {oid}\n\n📞 {ADMIN_USERNAME}",
                reply_markup=main_menu(u.id)
            )
            await context.bot.send_message(ADMIN_ID, f"🔔 Заказ №{oid}\n📡 Роутер\n👤 {name}\n💰 {ROUTER_PRICE}р\nID: {pid}", reply_markup=order_admin_kb(oid))
            context.user_data['wait'] = None
        else:
            await update.message.reply_text("❌ 3 строки: Имя, Телефон, Адрес")
        return

# ========== КОМАНДЫ ==========
async def addkey_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    a = context.args
    if len(a) < 3: await update.message.reply_text("❌ /addkey протокол Страна ключ"); return
    await add_key(a[0], a[1], ' '.join(a[2:]))
    await update.message.reply_text(f"✅ {a[0]} ({a[1]})")

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
        await update_purchase_status(oid, 'paid')
        await context.bot.send_message(uid, f"✅ Заказ №{oid} оплачен!")
        await update.message.reply_text("✅ Оплачен")
    else:
        p = o[6] or prod.replace('vpn_','')
        c = o[7] or 'Нидерланды'
        dur = o[8] or '1month'
        days = DURATION_DAYS.get(dur, 30)
        exp = (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
        key = await get_key(p, c)
        if key:
            await sell_key(key[0], uid, pid, exp)
            await update_purchase_status(oid, 'paid')
            await context.bot.send_message(uid, f"✅ Заказ №{oid} оплачен!\n\n🔑 Ключ:\n{key[1]}\n⏱️ До: {format_date(exp)}")
            await update.message.reply_text("✅ Ключ выдан!")
        else:
            await update.message.reply_text(f"❌ Нет ключей {p} ({c})!")

async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    async with aiosqlite.connect('shop.db') as db:
        c = await db.execute('SELECT COUNT(*) FROM users'); u = (await c.fetchone())[0]
        c = await db.execute('SELECT COUNT(*),SUM(amount) FROM purchases WHERE status="paid"'); o, r = await c.fetchone()
        c = await db.execute('SELECT COUNT(*) FROM vpn_keys WHERE is_sold=FALSE'); k = (await c.fetchone())[0]
    await update.message.reply_text(f"📊 Пользователей: {u}\n🛒 Заказов: {o or 0}\n💰 Выручка: {r or 0}р\n🔑 Ключей: {k}")

async def mysubs_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pid = await get_or_create_pid(update.effective_user.id, update.effective_user.username, update.effective_user.first_name)
    subs = await get_subs_by_uid(update.effective_user.id)
    if subs:
        text = f"🔑 Подписки (ID: {pid}):\n\n"
        for s in subs: text += f"🔐 {PROTOCOL_NAMES.get(s[1],s[1])} ({s[2]})\n⏱️ До: {format_date(s[3])}\n"
    else: text = f"Нет подписок\nID: {pid}"
    await update.message.reply_text(text)

# ========== ЗАПУСК ==========
async def main():
    await init_db()
    asyncio.create_task(asyncio.start_server(http_handler, "0.0.0.0", PORT))
    
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("addkey", addkey_cmd))
    app.add_handler(CommandHandler("done", done_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("mysubs", mysubs_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    
    await app.initialize(); await app.start()
    print("🤖 Бот запущен!")
    await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    while True: await asyncio.sleep(3600)

if __name__ == '__main__':
    asyncio.run(main())
