import asyncio
import aiosqlite
import json
import os
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo, LabeledPrice
from telegram.ext import Application, CommandHandler, MessageHandler, filters, PreCheckoutQueryHandler, ContextTypes
import logging

# ========== НАСТРОЙКИ ==========
BOT_TOKEN = "8809011538:AAFMpc0vBtMMHS0ZbXpjDbPmFkWfxW_jHtM"
ADMIN_ID = 5737961034
ADMIN_USERNAME = "@yng_beko"
WEBAPP_URL = "https://up53et.github.io/vpn-shop-webapp/"
PORT = int(os.environ.get("PORT", 8080))
# ===============================

logging.basicConfig(level=logging.INFO)

# ========== БАЗА ДАННЫХ ==========
async def init_db():
    async with aiosqlite.connect('shop.db') as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT,
            registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
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

async def update_purchase_status(order_id, status):
    async with aiosqlite.connect('shop.db') as db:
        await db.execute('UPDATE purchases SET status=? WHERE id=?', (status, order_id))
        await db.commit()

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

# ========== HTTP-СЕРВЕР ==========
async def handle_healthcheck(reader, writer):
    try:
        await asyncio.wait_for(reader.read(1024), timeout=2.0)
    except:
        pass
    body = b"OK"
    response = (
        b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n"
        b"Content-Length: " + str(len(body)).encode() + b"\r\n"
        b"Connection: close\r\n\r\n" + body
    )
    writer.write(response)
    await writer.drain()
    writer.close()

async def run_healthcheck_server():
    server = await asyncio.start_server(handle_healthcheck, "0.0.0.0", PORT)
    async with server:
        await server.serve_forever()

# ========== ОБРАБОТЧИКИ ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await register_user(user.id, user.username, user.first_name)
    await update.message.reply_text(
        f"👋 Привет, {user.first_name}!\n\n🛒 NetVault — роутеры и VPN\n\n"
        f"📡 Роутер NC-1121 — 9800₽\n🌐 VLESS — 300₽/мес\n"
        f"🔒 WireGuard — 350₽/мес\n🛡️ AmneziaWG — 350₽/мес\n\n"
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
        order_id = await add_purchase(user.id, 'router_nc1121', amount, phone, address, full_name)
        
        await update.message.reply_text(
            f"✅ *Заказ №{order_id}*\n\n📡 Роутер NC-1121\n👤 {full_name}\n📞 {phone}\n📍 {address}\n💰 {amount} XTR",
            parse_mode='Markdown'
        )
        await context.bot.send_invoice(
            chat_id=user.id, title="Роутер Netcraze NC-1121",
            description=f"Заказ №{order_id}\n👤 {full_name}\n📍 {address}",
            payload=f"router_{order_id}", provider_token="", currency="XTR",
            prices=[LabeledPrice("Роутер NC-1121", amount)]
        )
        await context.bot.send_message(ADMIN_ID,
            f"🔔 *Новый заказ №{order_id}*\n📡 Роутер\n👤 {full_name}\n📞 {phone}\n📍 {address}\n💰 {amount} XTR",
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
            f"✅ *Заказ №{order_id}*\n\n🔐 {protocol_names[protocol]}\n🌍 {country}\n🖥️ {os_names[os_choice]}\n⏱️ {duration_name}\n💰 {amount} XTR",
            parse_mode='Markdown'
        )
        await context.bot.send_invoice(
            chat_id=user.id, title=f"{protocol_names[protocol]} VPN",
            description=f"Страна: {country}\nОС: {os_names[os_choice]}\nСрок: {duration_name}",
            payload=f"vpn_{order_id}_{protocol}_{duration}_{country}",
            provider_token="", currency="XTR",
            prices=[LabeledPrice(f"{protocol_names[protocol]} ({duration_name})", amount)]
        )
        await context.bot.send_message(ADMIN_ID,
            f"🔔 *Новый заказ №{order_id}*\n🔐 {protocol_names[protocol]}\n🌍 {country}\n🖥️ {os_names[os_choice]}\n⏱️ {duration_name}\n💰 {amount} XTR",
            parse_mode='Markdown'
        )

async def precheckout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.pre_checkout_query.answer(ok=True)

async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    payment = update.message.successful_payment
    user = update.effective_user
    payload = payment.invoice_payload
    
    if payload.startswith('router_'):
        order_id = int(payload.replace('router_', ''))
        await update_purchase_status(order_id, 'paid')
        await update.message.reply_text(f"✅ *Оплата прошла!*\n\n📦 Заказ №{order_id}\n📡 Роутер NC-1121\n\n📞 {ADMIN_USERNAME} свяжется с вами", parse_mode='Markdown')
    
    elif payload.startswith('vpn_'):
        parts = payload.split('_')
        order_id = int(parts[1])
        protocol = parts[2]
        duration = parts[3]
        country = parts[4]
        await update_purchase_status(order_id, 'paid')
        
        duration_days = {'1month':30,'3months':90,'6months':180,'1year':365}
        days = duration_days.get(duration, 30)
        expires_at = (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
        
        key = await get_available_key(protocol, country)
        protocol_names = {'vless':'VLESS','wireguard':'WireGuard','amneziawg':'AmneziaWG'}
        
        if key:
            await mark_key_sold(key[0], user.id, expires_at)
            key_text = key[1]
        else:
            key_text = f"Ключи закончились. {ADMIN_USERNAME} выдаст вручную"
            await context.bot.send_message(ADMIN_ID, f"⚠️ Закончились ключи {protocol} ({country})!\nЗаказ №{order_id}")
        
        await update.message.reply_text(
            f"✅ *Оплата прошла!*\n\n📦 Заказ №{order_id}\n🔐 {protocol_names[protocol]}\n🌍 {country}\n⏱️ До: {expires_at}\n\n🔑 Ключ:\n`{key_text}`\n\n📞 {ADMIN_USERNAME}",
            parse_mode='Markdown'
        )

# ========== АДМИН-КОМАНДЫ ==========
async def addkey(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    args = context.args
    if len(args) < 3:
        await update.message.reply_text("❌ Использование: /addkey протокол Страна ключ\nПример: /addkey vless Армения vless://...")
        return
    protocol = args[0]
    country = args[1]
    key_data = ' '.join(args[2:])
    await add_vpn_key(protocol, country, key_data)
    await update.message.reply_text(f"✅ Ключ {protocol} ({country}) добавлен!")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    async with aiosqlite.connect('shop.db') as db:
        c = await db.execute('SELECT COUNT(*) FROM users')
        users = (await c.fetchone())[0]
        c = await db.execute('SELECT COUNT(*), SUM(amount) FROM purchases WHERE status="paid"')
        orders, rev = await c.fetchone()
        c = await db.execute('SELECT COUNT(*) FROM vpn_keys WHERE is_sold=FALSE')
        keys = (await c.fetchone())[0]
        c = await db.execute('SELECT COUNT(*) FROM vpn_keys WHERE is_sold=TRUE AND expires_at > datetime("now")')
        active = (await c.fetchone())[0]
    await update.message.reply_text(
        f"📊 *Статистика*\n\n👥 Пользователей: {users}\n🛒 Заказов: {orders or 0}\n💰 Выручка: {rev or 0} XTR\n🔑 Ключей: {keys}\n✅ Активных: {active}",
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
    asyncio.create_task(run_healthcheck_server())
    
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("addkey", addkey))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("mysubs", mysubs))
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, web_app_data_handler))
    app.add_handler(PreCheckoutQueryHandler(precheckout_handler))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))
    
    await app.initialize()
    await app.start()
    print("🤖 Бот запущен!")
    await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    
    while True:
        await asyncio.sleep(3600)

if __name__ == '__main__':
    asyncio.run(main())
