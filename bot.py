import asyncio
import aiosqlite
import json
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import logging

BOT_TOKEN = "8809011538:AAFMpc0vBtMMHS0ZbXpjDbPmFkWfxW_jHtM"
ADMIN_ID = 5737961034
CARD_NUMBER = "2200-7020-5664-8004"
PORT = int(os.environ.get("PORT", 8080))
WEBAPP_URL = "https://up53et.github.io/vpn-shop-webapp/"

logging.basicConfig(level=logging.INFO)

async def init_db():
    async with aiosqlite.connect('shop.db') as db:
        await db.execute('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY)')
        await db.execute('CREATE TABLE IF NOT EXISTS purchases (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, product TEXT, amount REAL, status TEXT DEFAULT "pending")')
        await db.commit()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🛒:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Открыть", web_app=WebAppInfo(url=WEBAPP_URL))]]))

async def webapp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_message.web_app_data:
        d = json.loads(update.effective_message.web_app_data.data)
        uid = update.effective_user.id
        async with aiosqlite.connect('shop.db') as db:
            await db.execute('INSERT INTO purchases (user_id, product, amount) VALUES (?, ?, ?)', (uid, d.get('type','?'), d.get('amount',0)))
            await db.commit()
            c = await db.execute('SELECT last_insert_rowid()'); oid = (await c.fetchone())[0]
        await update.message.reply_text(f"✅ Заказ №{oid}\n💰 {d.get('amount')}₽\n💳 `{CARD_NUMBER}`", parse_mode='Markdown')

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = update.message.text
    if t.startswith('{') and '"type"' in t:
        try:
            d = json.loads(t)
            uid = update.effective_user.id
            async with aiosqlite.connect('shop.db') as db:
                await db.execute('INSERT INTO purchases (user_id, product, amount) VALUES (?, ?, ?)', (uid, d.get('type','?'), d.get('amount',0)))
                await db.commit()
                c = await db.execute('SELECT last_insert_rowid()'); oid = (await c.fetchone())[0]
            await update.message.reply_text(f"✅ Заказ №{oid}\n💰 {d.get('amount')}₽\n💳 `{CARD_NUMBER}`", parse_mode='Markdown')
        except: pass

async def handle_http(reader, writer):
    try: await asyncio.wait_for(reader.read(4096), timeout=2.0)
    except: pass
    resp = b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nOK"
    writer.write(resp); await writer.drain(); writer.close()

async def run_http():
    server = await asyncio.start_server(handle_http, "0.0.0.0", PORT)
    async with server: await server.serve_forever()

async def main():
    await init_db()
    asyncio.create_task(run_http())
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, webapp))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    await app.initialize(); await app.start()
    print("Bot started")
    await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    while True: await asyncio.sleep(3600)

if __name__ == '__main__': asyncio.run(main())
