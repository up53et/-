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

# Порт, который Render выделяет для Web Service
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
            protocol TEXT, os TEXT, duration TEXT,
            date TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS vpn_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT, protocol TEXT,
            key_data TEXT, is_sold BOOLEAN DEFAULT FALSE,
            sold_to INTEGER, sold_at TIMESTAMP,
            expires_at TIMESTAMP)''')
        await db.commit()

# ... (все функции БД оставь как в предыдущем коде: register_user, add_purchase, update_purchase_status,
#      get_available_key, mark_key_sold, add_vpn_key, get_user_subscriptions – они не меняются)

# ========== HTTP-СЕРВЕР ДЛЯ RENDER ==========
async def handle_healthcheck(reader, writer):
    """Отвечает на запросы, чтобы Render не убивал сервис."""
    try:
        request = await asyncio.wait_for(reader.read(1024), timeout=2.0)
    except:
        request = b""
    body = b"OK"
    response = (
        b"HTTP/1.1 200 OK\r\n"
        b"Content-Type: text/plain\r\n"
        b"Content-Length: " + str(len(body)).encode() + b"\r\n"
        b"Connection: close\r\n"
        b"\r\n"
        + body
    )
    writer.write(response)
    await writer.drain()
    writer.close()

async def run_healthcheck_server():
    server = await asyncio.start_server(handle_healthcheck, "0.0.0.0", PORT)
    logging.info(f"Healthcheck server started on port {PORT}")
    async with server:
        await server.serve_forever()

# ========== ОБРАБОТЧИКИ ТЕЛЕГРАМ ==========
# ... (все функции как раньше: start, web_app_data_handler, precheckout_handler,
#      successful_payment, addkey, stats, mysubs – они полностью идентичны)

# ========== ЗАПУСК ==========
async def main():
    # Инициализация БД
    await init_db()

    # Запуск healthcheck-сервера для Render (чтобы порт слушался)
    asyncio.create_task(run_healthcheck_server())

    # Настройка бота
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

    # Запуск поллинга
    await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)

    # Бесконечный цикл, чтобы процесс не завершался
    while True:
        await asyncio.sleep(3600)

if __name__ == '__main__':
    asyncio.run(main())
