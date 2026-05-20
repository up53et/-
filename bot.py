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
# URL твоего сервиса на Render
RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL", "https://rh715clfb2.onrender.com")
WEBAPP_URL = RENDER_URL + "/"
# ===============================

logging.basicConfig(level=logging.INFO)

# ========== БАЗА ДАННЫХ ==========
async def init_db():
    async with aiosqlite.connect('shop.db') as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
            product TEXT, amount REAL, status TEXT DEFAULT 'pending',
            phone TEXT, address TEXT, full_name TEXT,
            protocol TEXT, os TEXT, duration TEXT, country TEXT,
            date TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS vpn_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT, protocol TEXT, country TEXT,
            key_data TEXT, is_sold BOOLEAN DEFAULT FALSE,
            sold_to INTEGER, sold_at TIMESTAMP,
            expires_at TIMESTAMP)''')
        await db.commit()

async def register_user(user_id, username, first_name):
    async with aiosqlite.connect('shop.db') as db:
        await db.execute('INSERT OR REPLACE INTO users (user_id, username, first_name) VALUES (?, ?, ?)',
                         (user_id, username, first_name))
        await db.commit()

async def add_purchase(user_id, product, amount, phone='', address='', full_name='', protocol='', os='', duration='', country=''):
    async with aiosqlite.connect('shop.db') as db:
        cursor = await db.execute(
            'INSERT INTO purchases (user_id, product, amount, phone, address, full_name, protocol, os, duration, country) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (user_id, product, amount, phone, address, full_name, protocol, os, duration, country))
        await db.commit()
        return cursor.lastrowid

async def get_available_key(protocol, country):
    async with aiosqlite.connect('shop.db') as db:
        cursor = await db.execute(
            'SELECT id, key_data FROM vpn_keys WHERE protocol=? AND country=? AND is_sold=FALSE LIMIT 1',
            (protocol, country))
        return await cursor.fetchone()

async def mark_key_sold(key_id, user_id, expires_at):
    async with aiosqlite.connect('shop.db') as db:
        await db.execute('UPDATE vpn_keys SET is_sold=TRUE, sold_to=?, sold_at=CURRENT_TIMESTAMP, expires_at=? WHERE id=?',
                         (user_id, expires_at, key_id))
        await db.commit()

async def add_vpn_key(protocol, country, key_data):
    async with aiosqlite.connect('shop.db') as db:
        await db.execute('INSERT INTO vpn_keys (protocol, country, key_data) VALUES (?, ?, ?)',
                         (protocol, country, key_data))
        await db.commit()

async def get_user_subscriptions(user_id):
    async with aiosqlite.connect('shop.db') as db:
        cursor = await db.execute(
            'SELECT protocol, country, expires_at, key_data FROM vpn_keys WHERE sold_to=? AND is_sold=TRUE AND expires_at > CURRENT_TIMESTAMP',
            (user_id,))
        return await cursor.fetchall()

# ========== HTTP-СЕРВЕР (ОТДАЁТ index.html) ==========
async def handle_request(reader, writer):
    try:
        await asyncio.wait_for(reader.read(4096), timeout=2.0)
    except:
        pass
    
    try:
        with open("static/index.html", "rb") as f:
            html = f.read()
    except:
        html = b"<h1>WebApp not found</h1>"
    
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
    logging.info(f"WebApp server started on port {PORT}")
    async with server:
        await server.serve_forever()

# ========== ОБРАБОТЧИКИ ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await register_user(user.id, user.username, user.first_name)
    await update.message.reply_text(
        f"👋 Привет, {user.first_name}!\n\n"
        f"🛒 NetVault — роутеры и VPN\n\n"
        f"📡 Роутер NC-1121 — 9800₽\n"
        f"🌐 VLESS — 300₽/мес\n"
        f"🔒 WireGuard — 350₽/мес\n"
        f"🛡️ AmneziaWG — 350₽/мес\n\n"
        f"💳 Оплата переводом на карту\n\n"
        f"Нажми кнопку чтобы открыть магазин:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🛍️ Открыть магазин", web_app=WebAppInfo(url=WEBAPP_URL))]
        ])
    )

async def process_order(update: Update, context: ContextTypes.DEFAULT_TYPE, data_str: str):
    data = json.loads(data_str)
    user = update.effective_user
    await register_user(user.id, user.username, user.first_name)
    
    order_type = data.get('type')
    
    if order_type == 'router':
        full_name = data.get('fullName')
        phone = data.get('phone')
        address = data.get('address')
        amount = 9800
        order_id = await add_purchase(user.id, 'router_nc1121', amount, phone, address, full_name)
        
        await update.message.reply_text(
            f"✅ *Заказ №{order_id}*\n\n"
            f"📡 Роутер NC-1121\n"
            f"👤 {full_name}\n📞 {phone}\n📍 {address}\n"
            f"💰 Сумма: {amount}₽\n\n"
            f"💳 Оплатите переводом на карту:\n`{CARD_NUMBER}`\n\n"
            f"⚠️ После оплаты напишите {ADMIN_USERNAME} номер заказа",
            parse_mode='Markdown'
        )
        await context.bot.send_message(ADMIN_ID,
            f"🔔 *Новый заказ №{order_id}*\n\n📡 Роутер\n👤 {full_name}\n📞 {phone}\n📍 {address}\n💰 {amount}₽",
            parse_mode='Markdown'
        )
    
    elif order_type == 'vpn':
        protocol = data.get('protocol')
        os_choice = data.get('os')
        country = data.get('country', '')
        duration = data.get('duration')
        duration_name = data.get('durationName')
        amount = data.get('amount')
        order_id = await add_purchase(user.id, f'vpn_{protocol}', amount, protocol=protocol, os=os_choice, duration=duration, country=country)
        
        os_names = {'linux':'🐧 Linux','ios':'🍎 iOS','windows':'🪟 Windows','android':'📱 Android'}
        protocol_names = {'vless':'VLESS','wireguard':'WireGuard','amneziawg':'AmneziaWG'}
        
        await update.message.reply_text(
            f"✅ *Заказ №{order_id}*\n\n"
            f"🔐 {protocol_names[protocol]}\n🌍 {country}\n🖥️ {os_names[os_choice]}\n⏱️ {duration_name}\n"
            f"💰 Сумма: {amount}₽\n\n"
            f"💳 Оплатите переводом на карту:\n`{CARD_NUMBER}`\n\n"
            f"⚠️ После оплаты ключ придёт автоматически",
            parse_mode='Markdown'
        )
        await context.bot.send_message(ADMIN_ID,
            f"🔔 *Новый заказ №{order_id}*\n\n🔐 {protocol_names[protocol]}\n🌍 {country}\n🖥️ {os_names[os_choice]}\n⏱️ {duration_name}\n💰 {amount}₽",
            parse_mode='Markdown'
        )

async def web_app_data_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_message.web_app_data:
        await process_order(update, context, update.effective_message.web_app_data.data)

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text.startswith('{') and '"type"' in text:
        try:
            await process_order(update, context, text)
        except:
            pass

# ========== АДМИН-КОМАНДЫ ==========
async def addkey(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    args = context.args
    if len(args) < 3:
        await update.message.reply_text("❌ /addkey протокол Страна ключ\nПример: /addkey vless Армения vless://...")
        return
    await add_vpn_key(args[0], args[1], ' '.join(args[2:]))
    await update.message.reply_text(f"✅ Ключ {args[0]} ({args[1]}) добавлен!")

async def done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    args = context.args
    if len(args) < 1:
        await update.message.reply_text("❌ /done номер_заказа")
        return
    
    order_id = int(args[0])
    
    async with aiosqlite.connect('shop.db') as db:
        c = await db.execute('SELECT user_id, product, protocol, country, duration FROM purchases WHERE id=?', (order_id,))
        order = await c.fetchone()
    
    if not order:
        await update.message.reply_text("❌ Заказ не найден")
        return
    
    user_id, product, protocol, country, duration = order
    
    if 'router' in product:
        async with aiosqlite.connect('shop.db') as db:
            await db.execute('UPDATE purchases SET status="paid" WHERE id=?', (order_id,))
            await db.commit()
        await context.bot.send_message(user_id, f"✅ Заказ №{order_id} оплачен! {ADMIN_USERNAME} свяжется для доставки.")
        await update.message.reply_text(f"✅ Заказ №{order_id} отмечен как оплаченный")
    else:
        duration_days = {'1month':30,'3months':90,'6months':180,'1year':365}
        days = duration_days.get(duration, 30)
        expires_at = (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
        
        key = await get_available_key(protocol, country)
        if key:
            await mark_key_sold(key[0], user_id, expires_at)
            async with aiosqlite.connect('shop.db') as db:
                await db.execute('UPDATE purchases SET status="paid" WHERE id=?', (order_id,))
                await db.commit()
            await context.bot.send_message(user_id,
                f"✅ Заказ №{order_id} оплачен!\n\n🔑 Ваш ключ:\n`{key[1]}`\n⏱️ До: {expires_at}",
                parse_mode='Markdown')
            await update.message.reply_text(f"✅ Ключ {protocol} ({country}) выдан пользователю {user_id}")
        else:
            await update.message.reply_text(f"❌ Нет ключей {protocol} ({country})!")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    async with aiosqlite.connect('shop.db') as db:
        c = await db.execute('SELECT COUNT(*) FROM users'); users = (await c.fetchone())[0]
        c = await db.execute('SELECT COUNT(*), SUM(amount) FROM purchases WHERE status="paid"'); orders, rev = await c.fetchone()
        c = await db.execute('SELECT COUNT(*) FROM vpn_keys WHERE is_sold=FALSE'); keys = (await c.fetchone())[0]
        c = await db.execute('SELECT COUNT(*) FROM vpn_keys WHERE is_sold=TRUE AND expires_at > datetime("now")'); active = (await c.fetchone())[0]
    await update.message.reply_text(
        f"📊 *Статистика*\n\n👥 Пользователей: {users}\n🛒 Заказов: {orders or 0}\n💰 Выручка: {rev or 0}₽\n🔑 Ключей: {keys}\n✅ Активных: {active}",
        parse_mode='Markdown'
    )

async def mysubs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    subs = await get_user_subscriptions(update.effective_user.id)
    if subs:
        text = "🔑 *Ваши подписки:*\n\n"
        for s in subs:
            text += f"🔐 {s[0]} ({s[1]})\n⏱️ До: {s[2]}\n🔑 `{s[3]}`\n\n"
    else:
        text = "У вас нет активных подписок"
    await update.message.reply_text(text, parse_mode='Markdown')

# ========== ЗАПУСК ==========
async def main():
    await init_db()
    asyncio.create_task(run_server())
    
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("addkey", addkey))
    app.add_handler(CommandHandler("done", done))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("mysubs", mysubs))
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, web_app_data_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    
    await app.initialize()
    await app.start()
    print("🤖 Бот запущен!")
    await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    
    while True:
        await asyncio.sleep(3600)

if __name__ == '__main__':
    asyncio.run(main())
