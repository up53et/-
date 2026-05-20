import asyncio
import aiosqlite
import json
import os
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import logging

# ========== НАСТРОЙКИ ==========
BOT_TOKEN = "8809011538:AAFMpc0vBtMMHS0ZbXpjDbPmFkWfxW_jHtM"
ADMIN_ID = 5737961034
ADMIN_USERNAME = "@yng_beko"
CARD_NUMBER = "2200-7020-5664-8004"
PORT = int(os.environ.get("PORT", 8080))
# ===============================

logging.basicConfig(level=logging.INFO)

# URL сайта будет на Render
WEBAPP_URL = None  # Заполнится после запуска

# ========== БАЗА ДАННЫХ ==========
async def init_db():
    async with aiosqlite.connect('shop.db') as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, product TEXT, amount REAL,
            status TEXT DEFAULT 'pending', phone TEXT, address TEXT, full_name TEXT,
            protocol TEXT, os TEXT, duration TEXT, country TEXT,
            date TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS vpn_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT, protocol TEXT, country TEXT,
            key_data TEXT, is_sold BOOLEAN DEFAULT FALSE, sold_to INTEGER,
            sold_at TIMESTAMP, expires_at TIMESTAMP)''')
        await db.commit()

async def register_user(user_id, username, first_name):
    async with aiosqlite.connect('shop.db') as db:
        await db.execute('INSERT OR REPLACE INTO users (user_id, username, first_name) VALUES (?, ?, ?)', (user_id, username, first_name))
        await db.commit()

async def add_purchase(user_id, product, amount, **kwargs):
    async with aiosqlite.connect('shop.db') as db:
        await db.execute('INSERT INTO purchases (user_id, product, amount) VALUES (?, ?, ?)', (user_id, product, amount))
        await db.commit()
        c = await db.execute('SELECT last_insert_rowid()')
        return (await c.fetchone())[0]

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
        c = await db.execute("SELECT protocol, country, expires_at, key_data FROM vpn_keys WHERE sold_to=? AND is_sold=TRUE AND expires_at > datetime('now')", (user_id,))
        return await c.fetchall()

# ========== HTTP-СЕРВЕР (ОТДАЁТ САЙТ) ==========
async def handle_request(reader, writer):
    try:
        await asyncio.wait_for(reader.read(4096), timeout=2.0)
    except:
        pass
    
    try:
        with open("static/index.html", "rb") as f:
            html = f.read()
    except:
        html = b"<h1>WebApp</h1>"
    
    response = (
        b"HTTP/1.1 200 OK\r\n"
        b"Content-Type: text/html; charset=utf-8\r\n"
        b"Content-Length: " + str(len(html)).encode() + b"\r\n"
        b"Connection: close\r\n"
        b"\r\n" + html
    )
    writer.write(response)
    await writer.drain()
    writer.close()

async def run_server():
    server = await asyncio.start_server(handle_request, "0.0.0.0", PORT)
    logging.info(f"Server started on port {PORT}")
    async with server:
        await server.serve_forever()

# ========== ОБРАБОТЧИКИ ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global WEBAPP_URL
    user = update.effective_user
    await register_user(user.id, user.username, user.first_name)
    await update.message.reply_text(
        f"👋 Привет, {user.first_name}!\n\n🛒 NetVault — роутеры и VPN\n\n"
        f"📡 Роутер — 9800₽\n🌐 VLESS — 300₽/мес\n🔒 WireGuard — 350₽/мес\n🛡️ AmneziaWG — 350₽/мес\n\n"
        f"Нажми кнопку чтобы открыть магазин:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🛍️ Открыть магазин", web_app=WebAppInfo(url=WEBAPP_URL))]
        ])
    )

async def web_app_data_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message.web_app_data:
        return
    
    data = json.loads(update.effective_message.web_app_data.data)
    user = update.effective_user
    await register_user(user.id, user.username, user.first_name)
    order_type = data.get('type')
    
    if order_type == 'router':
        full_name = data.get('fullName')
        phone = data.get('phone')
        address = data.get('address')
        amount = 9800
        order_id = await add_purchase(user.id, 'router', amount)
        
        await update.message.reply_text(
            f"✅ *Заказ №{order_id}*\n\n📡 Роутер NC-1121\n👤 {full_name}\n📞 {phone}\n📍 {address}\n💰 {amount}₽\n\n"
            f"💳 Переведите на карту:\n`{CARD_NUMBER}`\n\n⚠️ После оплаты сообщите {ADMIN_USERNAME} номер заказа",
            parse_mode='Markdown'
        )
        await context.bot.send_message(ADMIN_ID,
            f"🔔 *Новый заказ №{order_id}*\n📡 Роутер\n👤 {full_name}\n📞 {phone}\n📍 {address}\n💰 {amount}₽",
            parse_mode='Markdown'
        )
    
    elif order_type == 'vpn':
        protocol = data.get('protocol')
        os_choice = data.get('os')
        country = data.get('country', '')
        duration = data.get('duration')
        duration_name = data.get('durationName')
        amount = data.get('amount')
        order_id = await add_purchase(user.id, f'vpn_{protocol}', amount)
        
        os_names = {'linux':'🐧 Linux','ios':'🍎 iOS','windows':'🪟 Windows','android':'📱 Android'}
        protocol_names = {'vless':'VLESS','wireguard':'WireGuard','amneziawg':'AmneziaWG'}
        
        await update.message.reply_text(
            f"✅ *Заказ №{order_id}*\n\n🔐 {protocol_names[protocol]}\n🌍 {country}\n🖥️ {os_names[os_choice]}\n⏱️ {duration_name}\n💰 {amount}₽\n\n"
            f"💳 Переведите на карту:\n`{CARD_NUMBER}`\n\n⚠️ После оплаты сообщите {ADMIN_USERNAME} номер заказа",
            parse_mode='Markdown'
        )
        await context.bot.send_message(ADMIN_ID,
            f"🔔 *Новый заказ №{order_id}*\n🔐 {protocol_names[protocol]}\n🌍 {country}\n💰 {amount}₽",
            parse_mode='Markdown'
        )

# ========== АДМИН-КОМАНДЫ ==========
async def addkey(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    args = context.args
    if len(args) < 3:
        await update.message.reply_text("❌ /addkey протокол Страна ключ")
        return
    await add_vpn_key(args[0], args[1], ' '.join(args[2:]))
    await update.message.reply_text(f"✅ Ключ {args[0]} ({args[1]}) добавлен!")

async def done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    args = context.args
    if len(args) < 1:
        await update.message.reply_text("❌ /done номер_заказа")
        return
    order_id = int(args[0])
    async with aiosqlite.connect('shop.db') as db:
        c = await db.execute('SELECT user_id, product FROM purchases WHERE id=?', (order_id,))
        order = await c.fetchone()
    if not order:
        await update.message.reply_text("❌ Заказ не найден")
        return
    user_id, product = order
    if 'router' in product:
        async with aiosqlite.connect('shop.db') as db:
            await db.execute('UPDATE purchases SET status="paid" WHERE id=?', (order_id,))
            await db.commit()
        await context.bot.send_message(user_id, f"✅ Заказ №{order_id} оплачен! {ADMIN_USERNAME} свяжется для доставки.")
        await update.message.reply_text(f"✅ Заказ №{order_id} отмечен")
    else:
        # Ищем протокол и страну
        async with aiosqlite.connect('shop.db') as db:
            c = await db.execute('SELECT product FROM purchases WHERE id=?', (order_id,))
            prod = (await c.fetchone())[0]
        protocol = prod.replace('vpn_', '')
        # Пытаемся найти страну в данных WebApp (сохранена в context при заказе)
        country = "Нидерланды"  # По умолчанию
        days = 30
        expires = (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d')
        key = await get_available_key(protocol, country)
        if key:
            await mark_key_sold(key[0], user_id, expires)
            async with aiosqlite.connect('shop.db') as db:
                await db.execute('UPDATE purchases SET status="paid" WHERE id=?', (order_id,))
                await db.commit()
            await context.bot.send_message(user_id, f"✅ Заказ №{order_id} оплачен!\n\n🔑 Ключ:\n`{key[1]}`\n⏱️ До: {expires}", parse_mode='Markdown')
            await update.message.reply_text(f"✅ Ключ выдан!")
        else:
            await update.message.reply_text(f"❌ Нет ключей {protocol}!")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    async with aiosqlite.connect('shop.db') as db:
        c = await db.execute('SELECT COUNT(*) FROM users'); users = (await c.fetchone())[0]
        c = await db.execute('SELECT COUNT(*), SUM(amount) FROM purchases WHERE status="paid"'); orders, rev = await c.fetchone()
        c = await db.execute('SELECT COUNT(*) FROM vpn_keys WHERE is_sold=FALSE'); keys = (await c.fetchone())[0]
    await update.message.reply_text(f"📊 Пользователей: {users}\n🛒 Заказов: {orders or 0}\n💰 Выручка: {rev or 0}₽\n🔑 Ключей: {keys}")

async def mysubs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    subs = await get_user_subscriptions(update.effective_user.id)
    if subs:
        text = "🔑 Ваши подписки:\n\n"
        for s in subs:
            text += f"🔐 {s[0]} ({s[1]})\n⏱️ До: {s[2]}\n🔑 `{s[3]}`\n\n"
    else:
        text = "У вас нет активных подписок"
    await update.message.reply_text(text, parse_mode='Markdown')

# ========== ЗАПУСК ==========
async def main():
    global WEBAPP_URL
    await init_db()
    asyncio.create_task(run_server())
    
    # Узнаём URL сервиса
    render_url = os.environ.get("RENDER_EXTERNAL_URL", "")
    if render_url:
        WEBAPP_URL = render_url + "/"
    else:
        WEBAPP_URL = f"http://localhost:{PORT}/"
    
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("addkey", addkey))
    app.add_handler(CommandHandler("done", done))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("mysubs", mysubs))
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, web_app_data_handler))
    
    await app.initialize()
    await app.start()
    print(f"🤖 Бот запущен! WebApp: {WEBAPP_URL}")
    await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    
    while True:
        await asyncio.sleep(3600)

if __name__ == '__main__':
    asyncio.run(main())
