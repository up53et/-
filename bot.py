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
CARD_NUMBER = "2200-7020-5664-8004"
PORT = int(os.environ.get("PORT", 8080))
# ===============================

logging.basicConfig(level=logging.INFO)

# Цены
ROUTER_PRICE = 9800
VLESS_PRICE = 300
WIREGUARD_PRICE = 350
AMNEZIAWG_PRICE = 350

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

# ========== HTTP ==========
async def handle_http(reader, writer):
    try: await asyncio.wait_for(reader.read(4096), timeout=2.0)
    except: pass
    body = b"OK"
    resp = b"HTTP/1.1 200 OK\r\nContent-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body
    writer.write(resp); await writer.drain(); writer.close()

async def run_http():
    server = await asyncio.start_server(handle_http, "0.0.0.0", PORT)
    async with server: await server.serve_forever()

# ========== КЛАВИАТУРЫ ==========
def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📡 Купить роутер (9800₽)", callback_data='buy_router')],
        [InlineKeyboardButton("🔑 Купить VPN", callback_data='vpn_menu')],
        [InlineKeyboardButton("📋 Мои подписки", callback_data='my_subs')],
    ])

def vpn_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 VLESS — 300₽/мес", callback_data='vpn_vless')],
        [InlineKeyboardButton("🔒 WireGuard — 350₽/мес", callback_data='vpn_wireguard')],
        [InlineKeyboardButton("🛡️ AmneziaWG — 350₽/мес", callback_data='vpn_amneziawg')],
        [InlineKeyboardButton("🔙 Назад", callback_data='back')],
    ])

def country_menu(protocol):
    countries = {
        'vless': ['Армения','Великобритания','Греция','Исландия','Казахстан','Латвия','Литва','Нидерланды','Польша','Сербия','Турция','Финляндия','Швейцария','Япония'],
        'wireguard': ['Нидерланды'],
        'amneziawg': ['Казахстан','Нидерланды','Россия','Турция']
    }
    btns = []
    for c in countries.get(protocol, []):
        btns.append([InlineKeyboardButton(c, callback_data=f'country_{protocol}_{c}')])
    btns.append([InlineKeyboardButton("🔙 Назад", callback_data='vpn_menu')])
    return InlineKeyboardMarkup(btns)

def duration_menu(protocol, country):
    base = {'vless': VLESS_PRICE, 'wireguard': WIREGUARD_PRICE, 'amneziawg': AMNEZIAWG_PRICE}[protocol]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"1 месяц — {base}₽", callback_data=f'dur_{protocol}_{country}_1month_{base}')],
        [InlineKeyboardButton(f"3 месяца — {int(base*3*0.9)}₽ (-10%)", callback_data=f'dur_{protocol}_{country}_3months_{int(base*3*0.9)}')],
        [InlineKeyboardButton(f"6 месяцев — {int(base*6*0.8)}₽ (-20%)", callback_data=f'dur_{protocol}_{country}_6months_{int(base*6*0.8)}')],
        [InlineKeyboardButton(f"1 год — {int(base*12*0.7)}₽ (-30%)", callback_data=f'dur_{protocol}_{country}_1year_{int(base*12*0.7)}')],
        [InlineKeyboardButton("🔙 Назад", callback_data=f'vpn_{protocol}')],
    ])

# ========== ОБРАБОТЧИКИ ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await register_user(user.id, user.username, user.first_name)
    await update.message.reply_text(
        f"👋 {user.first_name}, добро пожаловать в NetVault!\n\n"
        f"📡 Роутер — 9800₽\n🌐 VLESS — 300₽/мес\n🔒 WireGuard — 350₽/мес\n🛡️ AmneziaWG — 350₽/мес\n\n"
        f"💳 Оплата переводом на карту: `{CARD_NUMBER}`",
        parse_mode='Markdown', reply_markup=main_menu()
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    user = q.from_user
    await register_user(user.id, user.username, user.first_name)
    
    if data == 'back':
        await q.message.edit_text("🏠 Главное меню:", reply_markup=main_menu())
    
    elif data == 'buy_router':
        await q.message.edit_text(
            "📡 *Роутер Netcraze NC-1121*\n\n✅ Wi-Fi 6\n✅ 3000 Мбит/с\n✅ VPN из коробки\n\n"
            f"💰 Цена: {ROUTER_PRICE}₽\n\nВведите ваши данные (Имя, телефон, адрес) одним сообщением:",
            parse_mode='Markdown'
        )
        context.user_data['awaiting'] = 'router'
    
    elif data == 'vpn_menu':
        await q.message.edit_text("🔐 Выберите протокол VPN:", reply_markup=vpn_menu())
    
    elif data.startswith('vpn_'):
        protocol = data.replace('vpn_', '')
        await q.message.edit_text(f"🌍 Выберите страну:", reply_markup=country_menu(protocol))
    
    elif data.startswith('country_'):
        _, protocol, country = data.split('_', 2)
        await q.message.edit_text(f"⏱️ Выберите срок ({country}):", reply_markup=duration_menu(protocol, country))
    
    elif data.startswith('dur_'):
        parts = data.split('_')
        protocol = parts[1]
        country = parts[2]
        duration = parts[3]
        amount = int(parts[4])
        
        order_id = await add_purchase(user.id, f'vpn_{protocol}', amount)
        context.user_data['order_id'] = order_id
        context.user_data['vpn_protocol'] = protocol
        context.user_data['vpn_country'] = country
        context.user_data['vpn_duration'] = duration
        context.user_data['vpn_amount'] = amount
        
        await q.message.edit_text(
            f"✅ *Заказ №{order_id}*\n\n🔐 Протокол: {protocol}\n🌍 Страна: {country}\n⏱️ Срок: {duration}\n💰 Сумма: {amount}₽\n\n"
            f"💳 Переведите на карту: `{CARD_NUMBER}`\n\n⚠️ После оплаты сообщите администратору {ADMIN_USERNAME} номер заказа",
            parse_mode='Markdown', reply_markup=main_menu()
        )
        await context.bot.send_message(ADMIN_ID, f"🔔 Заказ №{order_id}\n🔐 {protocol}\n🌍 {country}\n💰 {amount}₽")
    
    elif data == 'my_subs':
        async with aiosqlite.connect('shop.db') as db:
            c = await db.execute("SELECT protocol, country, expires_at, key_data FROM vpn_keys WHERE sold_to=? AND is_sold=TRUE AND expires_at > datetime('now')", (user.id,))
            subs = await c.fetchall()
        if subs:
            text = "🔑 Ваши подписки:\n\n"
            for s in subs:
                text += f"🔐 {s[0]} ({s[1]})\n⏱️ До: {s[2]}\n🔑 `{s[3]}`\n\n"
        else:
            text = "У вас нет активных подписок"
        await q.message.edit_text(text, parse_mode='Markdown', reply_markup=main_menu())

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text
    
    if context.user_data.get('awaiting') == 'router':
        parts = text.strip().split('\n')
        if len(parts) >= 3:
            name, phone, address = parts[0], parts[1], parts[2]
            order_id = await add_purchase(user.id, 'router', ROUTER_PRICE)
            await update.message.reply_text(
                f"✅ *Заказ №{order_id}*\n\n📡 Роутер NC-1121\n👤 {name}\n📞 {phone}\n📍 {address}\n💰 {ROUTER_PRICE}₽\n\n"
                f"💳 Переведите на карту: `{CARD_NUMBER}`\n\n⚠️ После оплаты сообщите {ADMIN_USERNAME} номер заказа",
                parse_mode='Markdown', reply_markup=main_menu()
            )
            await context.bot.send_message(ADMIN_ID, f"🔔 Заказ №{order_id}\n📡 Роутер\n👤 {name}\n📞 {phone}\n📍 {address}\n💰 {ROUTER_PRICE}₽")
            context.user_data['awaiting'] = None
        else:
            await update.message.reply_text("Введите 3 строки: Имя, Телефон, Адрес")

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
        await context.bot.send_message(user_id, f"✅ Заказ №{order_id} оплачен!")
        await update.message.reply_text(f"✅ Заказ №{order_id} отмечен")
    else:
        # выдаём ключ
        async with aiosqlite.connect('shop.db') as db:
            c = await db.execute('SELECT protocol, country, duration FROM purchases WHERE id=?', (order_id,))
            p = await c.fetchone()
        if not p:
            await update.message.reply_text("❌ Данные заказа не найдены")
            return
        protocol, country, duration = p
        days = {'1month':30,'3months':90,'6months':180,'1year':365}.get(duration, 30)
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
            await update.message.reply_text(f"❌ Нет ключей {protocol} ({country})!")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    async with aiosqlite.connect('shop.db') as db:
        c = await db.execute('SELECT COUNT(*) FROM users'); users = (await c.fetchone())[0]
        c = await db.execute('SELECT COUNT(*), SUM(amount) FROM purchases WHERE status="paid"'); orders, rev = await c.fetchone()
        c = await db.execute('SELECT COUNT(*) FROM vpn_keys WHERE is_sold=FALSE'); keys = (await c.fetchone())[0]
    await update.message.reply_text(f"📊 Пользователей: {users}\n🛒 Заказов: {orders or 0}\n💰 Выручка: {rev or 0}₽\n🔑 Ключей: {keys}")

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
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    await app.initialize()
    await app.start()
    print("🤖 Бот запущен!")
    await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    while True: await asyncio.sleep(3600)

if __name__ == '__main__':
    asyncio.run(main())
