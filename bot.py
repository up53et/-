import asyncio
import aiosqlite
import json
import os
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
import logging

# ========== НАСТРОЙКИ ==========
BOT_TOKEN = "8809011538:AAFMpc0vBtMMHS0ZbXpjDbPmFkWfxW_jHtM"
ADMIN_ID = 5737961034
ADMIN_USERNAME = "@yng_beko"
CARD_NUMBER = "2200-7020-5664-8004"
PORT = int(os.environ.get("PORT", 8080))
WEBAPP_URL = "https://up53et.github.io/vpn-shop-webapp/"
# ===============================

logging.basicConfig(level=logging.INFO)

# ========== БАЗА ДАННЫХ ==========
async def init_db():
    async with aiosqlite.connect('shop.db') as db:
        await db.execute('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT)')
        await db.execute('CREATE TABLE IF NOT EXISTS purchases (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, product TEXT, amount REAL, status TEXT DEFAULT "pending", date TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
        await db.execute('CREATE TABLE IF NOT EXISTS vpn_keys (id INTEGER PRIMARY KEY AUTOINCREMENT, protocol TEXT, country TEXT, key_data TEXT, is_sold BOOLEAN DEFAULT FALSE, sold_to INTEGER, expires_at TEXT)')
        await db.commit()

async def register_user(uid, username, first_name):
    async with aiosqlite.connect('shop.db') as db:
        await db.execute('INSERT OR REPLACE INTO users VALUES (?, ?, ?)', (uid, username, first_name))
        await db.commit()

async def add_purchase(uid, product, amount):
    async with aiosqlite.connect('shop.db') as db:
        await db.execute('INSERT INTO purchases (user_id, product, amount) VALUES (?, ?, ?)', (uid, product, amount))
        await db.commit()
        c = await db.execute('SELECT last_insert_rowid()')
        return (await c.fetchone())[0]

async def get_available_key(protocol, country):
    async with aiosqlite.connect('shop.db') as db:
        c = await db.execute('SELECT id, key_data FROM vpn_keys WHERE protocol=? AND country=? AND is_sold=FALSE LIMIT 1', (protocol, country))
        return await c.fetchone()

async def mark_key_sold(key_id, uid, expires):
    async with aiosqlite.connect('shop.db') as db:
        await db.execute('UPDATE vpn_keys SET is_sold=TRUE, sold_to=?, expires_at=? WHERE id=?', (uid, expires, key_id))
        await db.commit()

async def add_vpn_key(protocol, country, key_data):
    async with aiosqlite.connect('shop.db') as db:
        await db.execute('INSERT INTO vpn_keys (protocol, country, key_data) VALUES (?, ?, ?)', (protocol, country, key_data))
        await db.commit()

# ========== HTTP ==========
async def handle_http(reader, writer):
    try: await asyncio.wait_for(reader.read(4096), timeout=2.0)
    except: pass
    writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nOK")
    await writer.drain(); writer.close()

async def run_http():
    server = await asyncio.start_server(handle_http, "0.0.0.0", PORT)
    async with server: await server.serve_forever()

# ========== ОБРАБОТЧИКИ ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    await register_user(u.id, u.username, u.first_name)
    await update.message.reply_text(
        f"👋 {u.first_name}!\n\n🛒 NetVault\n\n📡 Роутер — 9800₽\n🌐 VLESS — 300₽/мес\n🔒 WireGuard — 350₽/мес\n🛡️ AmneziaWG — 350₽/мес\n\n💳 Карта: `{CARD_NUMBER}`\n\nНажми кнопку:",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🛍️ Открыть магазин", web_app=WebAppInfo(url=WEBAPP_URL))],
            [InlineKeyboardButton("📋 Мои подписки", callback_data='mysubs')]
        ])
    )

async def process_order(update, context, data):
    u = update.effective_user
    await register_user(u.id, u.username, u.first_name)
    t = data.get('type')
    
    if t == 'router':
        oid = await add_purchase(u.id, 'router', 9800)
        await update.message.reply_text(
            f"✅ *Заказ №{oid}*\n📡 Роутер\n👤 {data.get('fullName')}\n📞 {data.get('phone')}\n📍 {data.get('address')}\n💰 9800₽\n\n💳 `{CARD_NUMBER}`\n⚠️ {ADMIN_USERNAME}",
            parse_mode='Markdown'
        )
        await context.bot.send_message(ADMIN_ID, f"🔔 Заказ №{oid}\n📡 Роутер\n💰 9800₽", parse_mode='Markdown')
    
    elif t == 'vpn':
        prot = data.get('protocol')
        country = data.get('country','')
        dur = data.get('durationName','')
        amt = data.get('amount',0)
        oid = await add_purchase(u.id, f'vpn_{prot}', amt)
        pn = {'vless':'VLESS','wireguard':'WireGuard','amneziawg':'AmneziaWG'}
        await update.message.reply_text(
            f"✅ *Заказ №{oid}*\n🔐 {pn.get(prot,prot)}\n🌍 {country}\n⏱️ {dur}\n💰 {amt}₽\n\n💳 `{CARD_NUMBER}`\n⚠️ {ADMIN_USERNAME}",
            parse_mode='Markdown'
        )
        await context.bot.send_message(ADMIN_ID, f"🔔 Заказ №{oid}\n🔐 {pn.get(prot,prot)}\n🌍 {country}\n💰 {amt}₽", parse_mode='Markdown')

async def webapp_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_message.web_app_data:
        await process_order(update, context, json.loads(update.effective_message.web_app_data.data))

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = update.message.text
    if t.startswith('{"type"'):
        try:
            await process_order(update, context, json.loads(t))
        except:
            pass

# ========== АДМИН ==========
async def addkey(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    a = context.args
    if len(a) < 3: await update.message.reply_text("❌ /addkey протокол Страна ключ"); return
    await add_vpn_key(a[0], a[1], ' '.join(a[2:]))
    await update.message.reply_text(f"✅ Ключ {a[0]} ({a[1]}) добавлен!")

async def done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    a = context.args
    if not a: await update.message.reply_text("❌ /done номер"); return
    oid = int(a[0])
    async with aiosqlite.connect('shop.db') as db:
        c = await db.execute('SELECT user_id, product FROM purchases WHERE id=?', (oid,))
        o = await c.fetchone()
    if not o: await update.message.reply_text("❌ Не найден"); return
    uid, prod = o
    if 'router' in prod:
        async with aiosqlite.connect('shop.db') as db:
            await db.execute('UPDATE purchases SET status="paid" WHERE id=?', (oid,))
            await db.commit()
        await context.bot.send_message(uid, f"✅ Заказ №{oid} оплачен! {ADMIN_USERNAME}")
        await update.message.reply_text("✅ Оплачен")
    else:
        prot = prod.replace('vpn_','')
        key = await get_available_key(prot, "Нидерланды")
        if key:
            exp = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')
            await mark_key_sold(key[0], uid, exp)
            async with aiosqlite.connect('shop.db') as db:
                await db.execute('UPDATE purchases SET status="paid" WHERE id=?', (oid,))
                await db.commit()
            await context.bot.send_message(uid, f"✅ Заказ №{oid} оплачен!\n🔑 `{key[1]}`\n⏱️ До: {exp}", parse_mode='Markdown')
            await update.message.reply_text("✅ Ключ выдан!")
        else:
            await update.message.reply_text(f"❌ Нет ключей {prot}!")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    async with aiosqlite.connect('shop.db') as db:
        c = await db.execute('SELECT COUNT(*) FROM users'); u = (await c.fetchone())[0]
        c = await db.execute('SELECT COUNT(*), SUM(amount) FROM purchases WHERE status="paid"'); o, r = await c.fetchone()
        c = await db.execute('SELECT COUNT(*) FROM vpn_keys WHERE is_sold=FALSE'); k = (await c.fetchone())[0]
    await update.message.reply_text(f"📊 Пользователей: {u}\n🛒 Заказов: {o or 0}\n💰 Выручка: {r or 0}₽\n🔑 Ключей: {k}")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if q.data == 'mysubs':
        async with aiosqlite.connect('shop.db') as db:
            c = await db.execute("SELECT protocol, country, expires_at, key_data FROM vpn_keys WHERE sold_to=? AND is_sold=TRUE AND expires_at > datetime('now')", (q.from_user.id,))
            s = await c.fetchall()
        if s:
            t = "🔑 Подписки:\n\n"
            for x in s: t += f"🔐 {x[0]} ({x[1]})\n⏱️ {x[2]}\n🔑 `{x[3]}`\n\n"
        else: t = "Нет подписок"
        await q.message.edit_text(t, parse_mode='Markdown')

# ========== ЗАПУСК ==========
async def main():
    await init_db()
    asyncio.create_task(run_http())
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("addkey", addkey))
    app.add_handler(CommandHandler("done", done))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, webapp_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    await app.initialize(); await app.start()
    print("🤖 Бот запущен!")
    await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    while True: await asyncio.sleep(3600)

if __name__ == '__main__':
    asyncio.run(main())
