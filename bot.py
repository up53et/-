import asyncio
import aiosqlite
import os
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
import logging

# ========== НАСТРОЙКИ ==========
BOT_TOKEN = "8809011538:AAFMpc0vBtMMHS0ZbXpjDbPmFkWfxW_jHtM"
ADMIN_ID = 5737961034
ADMIN_USERNAME = "@yng_beko"
PORT = int(os.environ.get("PORT", 8080))
BOT_NAME = "NetVault"

logging.basicConfig(level=logging.INFO)

# Цены на роутеры
ROUTERS = {
    'NC-1121': 9800,
    'NC-1812': 36000,
    'NC-3811': 18800,
    'NC-3013': 14800,
    'NC-2212 4G': 12800
}

# Цены на VPN
PRICES = {'vless': 400, 'wireguard': 450, 'amneziawg': 450}
PROTOCOL_NAMES = {'vless': 'VLESS', 'wireguard': 'WireGuard', 'amneziawg': 'AmneziaWG'}
DURATION_NAMES = {'1month': '1 мес.', '3months': '3 мес.', '6months': '6 мес.', '1year': '1 год'}
DURATION_DAYS = {'1month': 30, '3months': 90, '6months': 180, '1year': 365}
DURATION_DISCOUNTS = {'1month': 0, '3months': 0.10, '6months': 0.20, '1year': 0.30}

# Стартовые страны
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
    """Сохраняет заказ, явно указывая protocol, country, duration если переданы"""
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
        await db.execute(f"UPDATE vpn_keys SET expires_at = datetime(expires_at, '{days} days') WHERE id=?", (key_id,))
        c = await db.execute('SELECT expires_at, sold_to FROM vpn_keys WHERE id=?', (key_id,))
        return await c.fetchone()

# HTTP-заглушка для Render
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
        [InlineKeyboardButton("ℹ️ Помощь", callback_data='help')],
    ]
    if uid == ADMIN_ID:
        kb.append([InlineKeyboardButton("👑 Админ", callback_data='admin')])
    return InlineKeyboardMarkup(kb)

def router_menu_kb():
    """Выбор модели роутера"""
    kb = []
    for model, price in ROUTERS.items():
        kb.append([InlineKeyboardButton(f"{model} — {price}₽", callback_data=f'router_{model}')])
    kb.append([InlineKeyboardButton("🔙 Назад", callback_data='back')])
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
    if not countries:
        return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='vpn_menu')]])
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
        [InlineKeyboardButton("🔑 Управление ключами", callback_data='admin_keys')],
        [InlineKeyboardButton("🌍 Управление странами", callback_data='admin_countries')],
        [InlineKeyboardButton("📅 Редактировать дату", callback_data='admin_editdate')],
        [InlineKeyboardButton("🔙 Назад", callback_data='back')],
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
    kb.append([InlineKeyboardButton("➕ Добавить страну", callback_data=f'adm_addcountry_{protocol}')])
    kb.append([InlineKeyboardButton("🔙 Назад", callback_data='admin_keys')])
    return InlineKeyboardMarkup(kb)

async def admin_country_manage_kb(protocol):
    countries = await get_countries(protocol)
    kb = [[InlineKeyboardButton(f"🗑️ Удалить {c}", callback_data=f'adm_delcountry_{protocol}_{c}')] for c in countries]
    kb.append([InlineKeyboardButton("➕ Добавить страну", callback_data=f'adm_addcountry_{protocol}')])
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
    text = f"🔐 {PROTOCOL_NAMES[protocol]} — {country}\n\n📦 Всего: {total} | ✅ Свободно: {avail} | ❌ Продано: {sold}"
    kb = [
        [InlineKeyboardButton("➕ Добавить ключ", callback_data=f'adm_add1_{protocol}_{country}')],
        [InlineKeyboardButton("📋 Список ключей", callback_data=f'adm_list_{protocol}_{country}')],
        [InlineKeyboardButton("🗑️ Удалить регион", callback_data=f'adm_remove_region_{protocol}_{country}')],
        [InlineKeyboardButton("🔙 К странам", callback_data=f'adm_proto_{protocol}')],
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
    text = f"👋 {BOT_NAME}!\n\n🆔 Ваш ID: {pid}\n\n📡 Роутеры от 9800р\n🌐 VLESS - {PRICES['vless']}р/мес\n🔒 WireGuard - {PRICES['wireguard']}р/мес\n🛡️ AmneziaWG - {PRICES['amneziawg']}р/мес\n\n📞 {ADMIN_USERNAME}"
    await update.message.reply_text(text, reply_markup=main_menu(u.id))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    d = q.data; u = q.from_user
    pid = await get_or_create_pid(u.id, u.username, u.first_name)
    
    # АДМИН
    if u.id == ADMIN_ID:
        if d == 'admin': await q.message.edit_text("👑 Админ-панель", reply_markup=admin_main_kb()); return
        elif d == 'admin_stats':
            async with aiosqlite.connect('shop.db') as db:
                c = await db.execute('SELECT COUNT(*) FROM users'); us = (await c.fetchone())[0]
                c = await db.execute('SELECT COUNT(*),SUM(amount) FROM purchases'); o, r = await c.fetchone()
                c = await db.execute('SELECT COUNT(*) FROM vpn_keys WHERE is_sold=FALSE'); k = (await c.fetchone())[0]
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
                cur=await db.execute('SELECT id,key_data,is_sold FROM vpn_keys WHERE protocol=? AND country=? ORDER BY id DESC LIMIT 10',(p,c)); keys=await cur.fetchall()
            text=f"📋 {PROTOCOL_NAMES[p]} — {c}\n\n"+("\n".join([f"ID {k[0]}: {'✅' if not k[2] else '❌'} | {k[1][:30]}..." for k in keys]) if keys else "Нет ключей")
            await q.message.edit_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data=f'adm_country_{p}_{c}')]])); return
        elif d.startswith('approve_'): oid=int(d.replace('approve_','')); await approve_order(q,context,oid); return
        elif d.startswith('reject_'): oid=int(d.replace('reject_','')); await reject_order(q,context,oid); return
        elif d.startswith('edit_key_'):
            key_id=int(d.replace('edit_key_',''))
            context.user_data['edit_key_id']=key_id
            await q.message.edit_text(f"🔑 Ключ ID: {key_id}\n\nВведите +дни или -дни (например +7):"); return
    
    # ОБЫЧНЫЕ КНОПКИ
    if d == 'back': await q.message.edit_text("🏠 Главное меню:", reply_markup=main_menu(u.id))
    elif d == 'router_menu':
        await q.message.edit_text("📡 Выберите модель роутера:", reply_markup=router_menu_kb())
    elif d.startswith('router_'):
        model = d.replace('router_', '')
        price = ROUTERS.get(model, 9800)
        context.user_data['router_model'] = model
        context.user_data['router_price'] = price
        context.user_data['wait_router'] = 'name'
        context.user_data['router_data'] = {}
        await q.message.edit_text(f"📡 {model} — {price}р\n\n📝 Шаг 1/3: Введите Имя и Фамилию:")
    elif d == 'vpn_menu': await q.message.edit_text("🔐 Протокол:", reply_markup=vpn_menu_kb())
    elif d.startswith('vpn_'): p=d.replace('vpn_',''); await q.message.edit_text(f"🌍 {PROTOCOL_NAMES[p]}:", reply_markup=await country_kb(p))
    elif d.startswith('country_'): _,p,c=d.split('_',2); context.user_data['vp']=p; context.user_data['vc']=c; await q.message.edit_text(f"⏱️ ({c}):", reply_markup=duration_kb(p,c))
    elif d.startswith('dur_'):
        _,p,c,dur,price=d.split('_',4); price=int(price)
        oid=await add_order(u.id,f'vpn_{p}',price,protocol=p,country=c,duration=dur)
        text=f"✅ Заказ №{oid}\n\n🔐 {PROTOCOL_NAMES[p]}\n🌍 {c}\n⏱️ {DURATION_NAMES[dur]}\n💰 {price}р\n\n⚠️ ПРИ ОПЛАТЕ УКАЖИТЕ НОМЕР ЗАКАЗА: {oid}\n\n📞 {ADMIN_USERNAME}"
        await q.message.edit_text(text, reply_markup=main_menu(u.id))
        await context.bot.send_message(ADMIN_ID, f"🔔 Заказ №{oid}\n{p} {c}\n💰 {price}р\n👤 @{u.username or u.id} (ID: {pid})", reply_markup=order_admin_kb(oid))
    elif d == 'my_subs':
        subs=await get_subs_by_uid(u.id)
        if subs: text=f"🔑 Подписки (ID: {pid}):\n\n"+"\n".join([f"🔐 {PROTOCOL_NAMES.get(s[1],s[1])} ({s[2]})\n⏱️ До: {format_date(s[3])}\n🔑 {s[4][:40]}...\n" for s in subs])
        else: text=f"Нет подписок\nВаш ID: {pid}"
        await q.message.edit_text(text, reply_markup=main_menu(u.id))
    elif d == 'profile':
        async with aiosqlite.connect('shop.db') as db:
            c=await db.execute('SELECT COUNT(*),SUM(amount) FROM purchases WHERE user_id=? AND status="paid"',(u.id,)); o,s=await c.fetchone()
        await q.message.edit_text(f"👤 {u.first_name}\n🆔 {pid}\n🏷️ @{u.username or 'нет'}\n🛒 Заказов: {o or 0}\n💰 Потрачено: {s or 0}р", reply_markup=main_menu(u.id))
    elif d == 'help':
        await q.message.edit_text(f"ℹ️ {BOT_NAME}\n📡 Роутеры от 9800р\n🌐 VLESS - {PRICES['vless']}р\n🔒 WireGuard - {PRICES['wireguard']}р\n🛡️ AmneziaWG - {PRICES['amneziawg']}р\n📞 {ADMIN_USERNAME}\n🆔 Ваш ID: {pid}", reply_markup=main_menu(u.id))

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
        return
    
    # Теперь правильные индексы: o[8]=protocol, o[9]=country, o[10]=duration
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
    else:
        await q.answer(f"❌ Нет ключей {protocol} ({country})!", show_alert=True)

async def reject_order(q, context, oid):
    o = await get_purchase(oid)
    if not o: await q.answer("Заказ не найден", show_alert=True); return
    await update_purchase_status(oid, 'rejected')
    await context.bot.send_message(o[1], f"❌ Заказ №{oid} отклонён. Свяжитесь с {ADMIN_USERNAME}")
    await q.message.edit_text(q.message.text + "\n\n❌ ОТКЛОНЕНО", reply_markup=None)

# ========== ТЕКСТОВЫЕ КОМАНДЫ ==========
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user; t = update.message.text.strip()
    pid = await get_or_create_pid(u.id, u.username, u.first_name)
    
    # Админ: добавление ключа
    if u.id == ADMIN_ID and context.user_data.get('admin_add'):
        info = context.user_data['admin_add']; await add_key(info['protocol'], info['country'], t)
        context.user_data.pop('admin_add'); text, kb = await admin_country_menu(info['protocol'], info['country'])
        await update.message.reply_text(f"✅ Ключ добавлен!\n{text}", reply_markup=kb); return
    
    # Админ: добавление страны
    if u.id == ADMIN_ID and context.user_data.get('add_country'):
        p = context.user_data['add_country']; await add_country(p, t)
        context.user_data.pop('add_country'); await update.message.reply_text(f"✅ {t} добавлена!", reply_markup=await admin_country_manage_kb(p)); return
    
    # Админ: ввод ID для редактирования даты
    if u.id == ADMIN_ID and context.user_data.get('edit_step') == 'input_pid':
        try:
            target_pid = int(t)
            user_info = await get_user_by_pid(target_pid)
            if not user_info: await update.message.reply_text("❌ Не найден"); context.user_data.pop('edit_step',None); return
            subs = await get_subs_by_pid(target_pid)
            if not subs: await update.message.reply_text(f"👤 {user_info[1]} (ID: {target_pid})\nНет подписок", reply_markup=admin_main_kb()); context.user_data.pop('edit_step',None); return
            kb = [[InlineKeyboardButton(f"🔐 {PROTOCOL_NAMES.get(s[1],s[1])} ({s[2]}) до {format_date(s[3])}", callback_data=f'edit_key_{s[0]}')] for s in subs]
            kb.append([InlineKeyboardButton("🔙 Назад", callback_data='admin')])
            await update.message.reply_text(f"👤 {user_info[1]} (ID: {target_pid})\n\nВыберите подписку:", reply_markup=InlineKeyboardMarkup(kb))
            context.user_data['edit_step'] = 'input_days'
        except: await update.message.reply_text("❌ Числовой ID"); return
    
    # Админ: ввод дней
    if u.id == ADMIN_ID and context.user_data.get('edit_step') == 'input_days':
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
            context.user_data.pop('edit_key_id', None); context.user_data.pop('edit_step', None)
        except: await update.message.reply_text("❌ Введите число (+7 или -3)"); return
    
    # Заказ роутера по шагам
    if context.user_data.get('wait_router') == 'name':
        context.user_data['router_data'] = {'name': t}; context.user_data['wait_router'] = 'phone'
        await update.message.reply_text("📝 Шаг 2/3: Введите телефон:"); return
    elif context.user_data.get('wait_router') == 'phone':
        context.user_data['router_data']['phone'] = t; context.user_data['wait_router'] = 'address'
        await update.message.reply_text("📝 Шаг 3/3: Введите адрес доставки:"); return
    elif context.user_data.get('wait_router') == 'address':
        rd = context.user_data['router_data']
        name, phone, addr = rd['name'], rd['phone'], t
        model = context.user_data.get('router_model', 'NC-1121')
        price = context.user_data.get('router_price', 9800)
        oid = await add_order(u.id, f'router_{model}', price)
        await update.message.reply_text(
            f"✅ Заказ №{oid}\n\n📡 {model}\n👤 {name}\n📞 {phone}\n📍 {addr}\n💰 {price}р\n\n⚠️ ПРИ ОПЛАТЕ УКАЖИТЕ НОМЕР ЗАКАЗА: {oid}\n\n📞 {ADMIN_USERNAME}",
            reply_markup=main_menu(u.id)
        )
        await context.bot.send_message(ADMIN_ID, f"🔔 Заказ №{oid}\n📡 {model}\n👤 {name}\n💰 {price}р\nID: {pid}", reply_markup=order_admin_kb(oid))
        context.user_data['wait_router'] = None; context.user_data.pop('router_data', None); return

# ========== КОМАНДЫ ==========
async def addkey_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    a = context.args
    if len(a) < 3: await update.message.reply_text("❌ /addkey протокол Страна ключ"); return
    await add_key(a[0], a[1], ' '.join(a[2:])); await update.message.reply_text(f"✅ {a[0]} ({a[1]})")

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
    # Индексы: o[8]=protocol, o[9]=country, o[10]=duration
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
    else:
        await update.message.reply_text(f"❌ Нет ключей {protocol} ({country})!")

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
    if subs: text = f"🔑 Подписки (ID: {pid}):\n\n"+"\n".join([f"🔐 {PROTOCOL_NAMES.get(s[1],s[1])} ({s[2]})\n⏱️ До: {format_date(s[3])}\n" for s in subs])
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
