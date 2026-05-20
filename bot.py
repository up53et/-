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
CARD_NUMBER = "2200-7020-5664-8004"
PORT = int(os.environ.get("PORT", 8080))
BOT_NAME = "NetVault"

logging.basicConfig(level=logging.INFO)

ROUTER_PRICE = 9800
PRICES = {'vless': 300, 'wireguard': 350, 'amneziawg': 350}
PROTOCOL_NAMES = {'vless': 'VLESS', 'wireguard': 'WireGuard', 'amneziawg': 'AmneziaWG'}
OS_NAMES = {'linux': 'Linux', 'ios': 'iOS/macOS', 'windows': 'Windows', 'android': 'Android'}
DURATION_NAMES = {'1month': '1 месяц', '3months': '3 месяца', '6months': '6 месяцев', '1year': '1 год'}
DURATION_DAYS = {'1month': 30, '3months': 90, '6months': 180, '1year': 365}
DURATION_DISCOUNTS = {'1month': 0, '3months': 0.10, '6months': 0.20, '1year': 0.30}

COUNTRIES = {
    'vless': ['Армения','Великобритания','Греция','Исландия','Казахстан','Латвия','Литва','Нидерланды','Польша','Сербия','Турция','Финляндия','Швейцария','Япония'],
    'wireguard': ['Нидерланды'],
    'amneziawg': ['Казахстан','Нидерланды','Россия','Турция']
}

async def init_db():
    async with aiosqlite.connect('shop.db') as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS purchases (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, product TEXT, amount REAL, status TEXT DEFAULT "pending", phone TEXT, address TEXT, full_name TEXT, protocol TEXT, country TEXT, duration TEXT, os TEXT, date TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS vpn_keys (id INTEGER PRIMARY KEY AUTOINCREMENT, protocol TEXT, country TEXT, key_data TEXT, is_sold BOOLEAN DEFAULT FALSE, sold_to INTEGER, expires_at TEXT)''')
        await db.commit()

async def reg(uid, un, fn):
    async with aiosqlite.connect('shop.db') as db:
        await db.execute('INSERT OR REPLACE INTO users VALUES (?,?,?)', (uid, un, fn))
        await db.commit()

async def add_order(uid, prod, amt, **kw):
    async with aiosqlite.connect('shop.db') as db:
        f = ['user_id','product','amount']; v = [uid,prod,amt]
        for k,val in kw.items():
            if val: f.append(k); v.append(val)
        await db.execute(f"INSERT INTO purchases ({','.join(f)}) VALUES ({','.join('?'*len(v))})", v)
        await db.commit()
        c = await db.execute('SELECT last_insert_rowid()')
        return (await c.fetchone())[0]

async def get_key(protocol, country):
    async with aiosqlite.connect('shop.db') as db:
        c = await db.execute('SELECT id,key_data FROM vpn_keys WHERE protocol=? AND country=? AND is_sold=FALSE LIMIT 1', (protocol, country))
        return await c.fetchone()

async def sell_key(kid, uid, exp):
    async with aiosqlite.connect('shop.db') as db:
        await db.execute('UPDATE vpn_keys SET is_sold=TRUE,sold_to=?,expires_at=? WHERE id=?', (uid, exp, kid))
        await db.commit()

async def add_key(protocol, country, key_data):
    async with aiosqlite.connect('shop.db') as db:
        await db.execute('INSERT INTO vpn_keys (protocol,country,key_data) VALUES (?,?,?)', (protocol, country, key_data))
        await db.commit()

async def get_subs(uid):
    async with aiosqlite.connect('shop.db') as db:
        c = await db.execute("SELECT protocol,country,expires_at,key_data FROM vpn_keys WHERE sold_to=? AND is_sold=TRUE AND expires_at > datetime('now')", (uid,))
        return await c.fetchall()

# HTTP
async def http_handler(reader, writer):
    try: await asyncio.wait_for(reader.read(4096), timeout=2.0)
    except: pass
    writer.write(b"HTTP/1.1 200 OK\r\n\r\nOK"); await writer.drain(); writer.close()

# Клавиатуры
def main_menu(uid=None):
    kb = [
        [InlineKeyboardButton("📡 Купить роутер", callback_data='buy_router'), InlineKeyboardButton("🔑 Купить VPN", callback_data='vpn_menu')],
        [InlineKeyboardButton("📋 Мои подписки", callback_data='my_subs'), InlineKeyboardButton("👤 Профиль", callback_data='profile')],
        [InlineKeyboardButton("ℹ️ Помощь", callback_data='help')],
    ]
    if uid == ADMIN_ID:
        kb.append([InlineKeyboardButton("👑 Админ", callback_data='admin')])
    return InlineKeyboardMarkup(kb)

def vpn_menu_kb():
    kb = [
        [InlineKeyboardButton(f"VLESS - {PRICES['vless']}р/мес", callback_data='vpn_vless')],
        [InlineKeyboardButton(f"WireGuard - {PRICES['wireguard']}р/мес", callback_data='vpn_wireguard')],
        [InlineKeyboardButton(f"AmneziaWG - {PRICES['amneziawg']}р/мес", callback_data='vpn_amneziawg')],
        [InlineKeyboardButton("Назад", callback_data='back')],
    ]
    return InlineKeyboardMarkup(kb)

def country_kb(protocol):
    kb = [[InlineKeyboardButton(c, callback_data=f'country_{protocol}_{c}')] for c in COUNTRIES[protocol]]
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

def os_kb(protocol, country, duration, price):
    kb = [
        [InlineKeyboardButton("Linux", callback_data=f'os_{protocol}_{country}_{duration}_{price}_linux')],
        [InlineKeyboardButton("iOS/macOS", callback_data=f'os_{protocol}_{country}_{duration}_{price}_ios')],
        [InlineKeyboardButton("Windows", callback_data=f'os_{protocol}_{country}_{duration}_{price}_windows')],
        [InlineKeyboardButton("Android", callback_data=f'os_{protocol}_{country}_{duration}_{price}_android')],
        [InlineKeyboardButton("Назад", callback_data=f'dur_back_{protocol}_{country}')],
    ]
    return InlineKeyboardMarkup(kb)

def admin_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Статистика", callback_data='admin_stats')],
        [InlineKeyboardButton("Назад", callback_data='back')],
    ])

# Обработчики
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    await reg(u.id, u.username, u.first_name)
    text = f"👋 Добро пожаловать в {BOT_NAME}!\n\n📡 Роутер - {ROUTER_PRICE}р\n🌐 VLESS - {PRICES['vless']}р/мес\n🔒 WireGuard - {PRICES['wireguard']}р/мес\n🛡️ AmneziaWG - {PRICES['amneziawg']}р/мес\n\n💳 Оплата: {CARD_NUMBER}\n📞 {ADMIN_USERNAME}"
    await update.message.reply_text(text, reply_markup=main_menu(u.id))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    d = q.data; u = q.from_user
    await reg(u.id, u.username, u.first_name)
    
    if d == 'back':
        await q.message.edit_text("🏠 Главное меню:", reply_markup=main_menu(u.id))
    
    elif d == 'buy_router':
        context.user_data['wait'] = 'router'
        await q.message.edit_text(f"📡 Роутер NC-1121 - {ROUTER_PRICE}р\n\nВведите 3 строки:\n1. Имя Фамилия\n2. Телефон\n3. Адрес")
    
    elif d == 'vpn_menu':
        await q.message.edit_text("🔐 Выберите протокол:", reply_markup=vpn_menu_kb())
    
    elif d.startswith('vpn_'):
        p = d.replace('vpn_', '')
        await q.message.edit_text(f"🌍 Страна для {PROTOCOL_NAMES[p]}:", reply_markup=country_kb(p))
    
    elif d.startswith('country_'):
        _, p, c = d.split('_', 2)
        context.user_data['vp'] = p
        context.user_data['vc'] = c
        await q.message.edit_text(f"⏱️ Срок ({c}):", reply_markup=duration_kb(p, c))
    
    elif d.startswith('dur_'):
        parts = d.split('_')
        if parts[1] == 'back':
            await q.message.edit_text(f"🌍 Страна:", reply_markup=country_kb(parts[2]))
            return
        _, p, c, dur, price = parts
        price = int(price)
        context.user_data['vd'] = dur
        context.user_data['vpr'] = price
        await q.message.edit_text(f"🖥️ ОС:", reply_markup=os_kb(p, c, dur, price))
    
    elif d.startswith('os_'):
        _, p, c, dur, price, os_choice = d.split('_', 5)
        price = int(price)
        oid = await add_order(u.id, f'vpn_{p}', price, protocol=p, country=c, duration=dur, os=os_choice)
        
        text = f"✅ Заказ №{oid}\n\n🔐 {PROTOCOL_NAMES[p]}\n🌍 {c}\n🖥️ {OS_NAMES[os_choice]}\n⏱️ {DURATION_NAMES[dur]}\n💰 {price}р\n\n💳 {CARD_NUMBER}\n⚠️ {ADMIN_USERNAME}"
        await q.message.edit_text(text, reply_markup=main_menu(u.id))
        await context.bot.send_message(ADMIN_ID, f"🔔 Заказ №{oid}\n{p} {c}\n💰 {price}р\n@{u.username or u.id}")
    
    elif d == 'my_subs':
        subs = await get_subs(u.id)
        if subs:
            text = "🔑 Ваши подписки:\n\n"
            for s in subs:
                text += f"🔐 {PROTOCOL_NAMES.get(s[0],s[0])} ({s[1]})\n⏱️ До: {s[2][:10]}\n\n"
        else:
            text = "Нет активных подписок"
        await q.message.edit_text(text, reply_markup=main_menu(u.id))
    
    elif d == 'profile':
        subs = await get_subs(u.id)
        async with aiosqlite.connect('shop.db') as db:
            c = await db.execute('SELECT COUNT(*),SUM(amount) FROM purchases WHERE user_id=? AND status="paid"', (u.id,))
            o, s = await c.fetchone()
        text = f"👤 Профиль\n\n🆔 {u.id}\n📛 {u.first_name}\n🏷️ @{u.username or 'нет'}\n🛒 Заказов: {o or 0}\n💰 Потрачено: {s or 0}р\n🔑 Подписок: {len(subs)}"
        await q.message.edit_text(text, reply_markup=main_menu(u.id))
    
    elif d == 'help':
        await q.message.edit_text(f"ℹ️ {BOT_NAME}\n\n📡 Роутер - {ROUTER_PRICE}р\n🌐 VLESS - {PRICES['vless']}р/мес\n🔒 WireGuard - {PRICES['wireguard']}р/мес\n🛡️ AmneziaWG - {PRICES['amneziawg']}р/мес\n\n💳 {CARD_NUMBER}\n📞 {ADMIN_USERNAME}\n\nКоманды: /start /mysubs /profile /support", reply_markup=main_menu(u.id))
    
    elif d == 'admin':
        if u.id != ADMIN_ID: return
        await q.message.edit_text("👑 Админ-панель", reply_markup=admin_kb())
    
    elif d == 'admin_stats':
        if u.id != ADMIN_ID: return
        async with aiosqlite.connect('shop.db') as db:
            c = await db.execute('SELECT COUNT(*) FROM users'); us = (await c.fetchone())[0]
            c = await db.execute('SELECT COUNT(*),SUM(amount) FROM purchases'); o, r = await c.fetchone()
            c = await db.execute('SELECT COUNT(*) FROM vpn_keys WHERE is_sold=FALSE'); k = (await c.fetchone())[0]
        await q.message.edit_text(f"📊 Статистика\n\n👥 Пользователей: {us}\n🛒 Заказов: {o or 0}\n💰 Выручка: {r or 0}р\n🔑 Ключей: {k}", reply_markup=admin_kb())

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user; t = update.message.text
    
    if context.user_data.get('wait') == 'router':
        p = t.strip().split('\n')
        if len(p) >= 3:
            oid = await add_order(u.id, 'router', ROUTER_PRICE, full_name=p[0], phone=p[1], address=p[2])
            await update.message.reply_text(f"✅ Заказ №{oid}\n📡 Роутер\n👤 {p[0]}\n📞 {p[1]}\n📍 {p[2]}\n💰 {ROUTER_PRICE}р\n\n💳 {CARD_NUMBER}\n⚠️ {ADMIN_USERNAME}", reply_markup=main_menu(u.id))
            await context.bot.send_message(ADMIN_ID, f"🔔 Заказ №{oid}\n📡 Роутер\n👤 {p[0]}\n💰 {ROUTER_PRICE}р")
        context.user_data['wait'] = None

# Админ-команды
async def addkey_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    a = context.args
    if len(a) < 3: await update.message.reply_text("❌ /addkey протокол Страна ключ"); return
    await add_key(a[0], a[1], ' '.join(a[2:]))
    await update.message.reply_text(f"✅ Ключ {a[0]} ({a[1]}) добавлен!")

async def done_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    a = context.args
    if not a: await update.message.reply_text("❌ /done номер"); return
    oid = int(a[0])
    async with aiosqlite.connect('shop.db') as db:
        c = await db.execute('SELECT * FROM purchases WHERE id=?', (oid,))
        o = await c.fetchone()
    if not o: await update.message.reply_text("❌ Не найден"); return
    uid, prod = o[1], o[2]
    if 'router' in prod:
        async with aiosqlite.connect('shop.db') as db:
            await db.execute('UPDATE purchases SET status="paid" WHERE id=?', (oid,))
            await db.commit()
        await context.bot.send_message(uid, f"✅ Заказ №{oid} оплачен!")
        await update.message.reply_text("✅ Оплачен")
    else:
        p = o[6] or prod.replace('vpn_','')
        c = o[7] or 'Нидерланды'
        dur = o[8] or '1month'
        days = DURATION_DAYS.get(dur, 30)
        exp = (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d')
        key = await get_key(p, c)
        if key:
            await sell_key(key[0], uid, exp)
            async with aiosqlite.connect('shop.db') as db:
                await db.execute('UPDATE purchases SET status="paid" WHERE id=?', (oid,))
                await db.commit()
            await context.bot.send_message(uid, f"✅ Заказ №{oid} оплачен!\n\n🔑 Ключ:\n{key[1]}\n⏱️ До: {exp}")
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
    subs = await get_subs(update.effective_user.id)
    if subs:
        text = "🔑 Подписки:\n\n"
        for s in subs: text += f"🔐 {PROTOCOL_NAMES.get(s[0],s[0])} ({s[1]}) до {s[2][:10]}\n"
    else: text = "Нет подписок"
    await update.message.reply_text(text)

async def profile_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    async with aiosqlite.connect('shop.db') as db:
        c = await db.execute('SELECT COUNT(*),SUM(amount) FROM purchases WHERE user_id=? AND status="paid"', (u.id,))
        o, s = await c.fetchone()
    await update.message.reply_text(f"👤 {u.first_name}\n🆔 {u.id}\n🛒 Заказов: {o or 0}\n💰 Потрачено: {s or 0}р")

# Запуск
async def main():
    await init_db()
    asyncio.create_task(asyncio.start_server(http_handler, "0.0.0.0", PORT))
    
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("addkey", addkey_cmd))
    app.add_handler(CommandHandler("done", done_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("mysubs", mysubs_cmd))
    app.add_handler(CommandHandler("profile", profile_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    
    await app.initialize(); await app.start()
    print("🤖 Бот запущен!")
    await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    while True: await asyncio.sleep(3600)

if __name__ == '__main__':
    asyncio.run(main())
