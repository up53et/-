# ========== АДМИН-КЛАВИАТУРЫ ==========
def admin_main_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Статистика", callback_data='admin_stats')],
        [InlineKeyboardButton("🔑 Управление ключами", callback_data='admin_keys')],
        [InlineKeyboardButton("🔙 Назад", callback_data='back')],
    ])

def admin_protocol_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 VLESS", callback_data='adm_proto_vless')],
        [InlineKeyboardButton("🔒 WireGuard", callback_data='adm_proto_wireguard')],
        [InlineKeyboardButton("🛡️ AmneziaWG", callback_data='adm_proto_amneziawg')],
        [InlineKeyboardButton("🔙 Назад", callback_data='admin')],
    ])

def admin_country_kb(protocol):
    kb = []
    for c in COUNTRIES[protocol]:
        # Считаем сколько ключей в наличии для этой страны
        kb.append([InlineKeyboardButton(c, callback_data=f'adm_country_{protocol}_{c}')])
    kb.append([InlineKeyboardButton("🔙 Назад", callback_data='admin_keys')])
    return InlineKeyboardMarkup(kb)

async def admin_country_menu(protocol, country):
    """Показывает статистику по стране и кнопки управления"""
    async with aiosqlite.connect('shop.db') as db:
        # Считаем ключи
        c = await db.execute('SELECT COUNT(*) FROM vpn_keys WHERE protocol=? AND country=? AND is_sold=FALSE', (protocol, country))
        available = (await c.fetchone())[0]
        c = await db.execute('SELECT COUNT(*) FROM vpn_keys WHERE protocol=? AND country=?', (protocol, country))
        total = (await c.fetchone())[0]
        c = await db.execute('SELECT COUNT(*) FROM vpn_keys WHERE protocol=? AND country=? AND is_sold=TRUE', (protocol, country))
        sold = (await c.fetchone())[0]
    
    text = f"🔐 {PROTOCOL_NAMES[protocol]} — {country}\n\n📦 Всего ключей: {total}\n✅ Доступно: {available}\n❌ Продано: {sold}"
    
    kb = [
        [InlineKeyboardButton("➕ Добавить 1 ключ", callback_data=f'adm_add_{protocol}_{country}')],
        [InlineKeyboardButton("➕➕ Добавить 5 ключей", callback_data=f'adm_add5_{protocol}_{country}')],
        [InlineKeyboardButton("📋 Список ключей", callback_data=f'adm_list_{protocol}_{country}')],
        [InlineKeyboardButton("🗑️ Удалить последний", callback_data=f'adm_del_{protocol}_{country}')],
        [InlineKeyboardButton("🔙 К странам", callback_data=f'adm_proto_{protocol}')],
    ]
    return text, InlineKeyboardMarkup(kb)

# ========== АДМИН-ОБРАБОТЧИКИ ==========
async def admin_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    d = q.data
    u = q.from_user
    
    if u.id != ADMIN_ID:
        return
    
    # Главное админ-меню
    if d == 'admin':
        await q.message.edit_text("👑 Админ-панель", reply_markup=admin_main_kb())
    
    elif d == 'admin_stats':
        async with aiosqlite.connect('shop.db') as db:
            c = await db.execute('SELECT COUNT(*) FROM users'); us = (await c.fetchone())[0]
            c = await db.execute('SELECT COUNT(*),SUM(amount) FROM purchases'); o, r = await c.fetchone()
            c = await db.execute('SELECT COUNT(*) FROM vpn_keys WHERE is_sold=FALSE'); k = (await c.fetchone())[0]
            c = await db.execute("SELECT COUNT(*) FROM vpn_keys WHERE is_sold=TRUE AND expires_at > datetime('now')"); a = (await c.fetchone())[0]
            c = await db.execute('SELECT COUNT(*),SUM(amount) FROM purchases WHERE status="paid"'); po, pr = await c.fetchone()
        
        text = (
            f"📊 Статистика\n\n"
            f"👥 Пользователей: {us}\n"
            f"🛒 Всего заказов: {o or 0}\n"
            f"✅ Оплаченных: {po or 0}\n"
            f"💰 Выручка: {pr or 0}р\n"
            f"🔑 Ключей в наличии: {k}\n"
            f"👤 Активных подписок: {a}"
        )
        await q.message.edit_text(text, reply_markup=admin_main_kb())
    
    # Управление ключами
    elif d == 'admin_keys':
        await q.message.edit_text("🔑 Выберите протокол:", reply_markup=admin_protocol_kb())
    
    elif d.startswith('adm_proto_'):
        protocol = d.replace('adm_proto_', '')
        await q.message.edit_text(f"🌍 Выберите страну для {PROTOCOL_NAMES[protocol]}:", reply_markup=admin_country_kb(protocol))
    
    elif d.startswith('adm_country_'):
        _, _, protocol, country = d.split('_', 3)
        text, kb = await admin_country_menu(protocol, country)
        await q.message.edit_text(text, reply_markup=kb)
    
    # Добавить 1 ключ
    elif d.startswith('adm_add_'):
        _, _, protocol, country = d.split('_', 3)
        context.user_data['admin_add'] = {'protocol': protocol, 'country': country, 'count': 1}
        await q.message.edit_text(
            f"➕ Добавление 1 ключа\n\n{PROTOCOL_NAMES[protocol]} — {country}\n\n"
            f"Отправьте ключ текстом (можно многострочный):\n\n"
            f"Пример:\nvless://...\n\n"
            f"🔙 /cancel для отмены",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Отмена", callback_data=f'adm_country_{protocol}_{country}')]])
        )
    
    # Добавить 5 ключей
    elif d.startswith('adm_add5_'):
        _, _, protocol, country = d.split('_', 3)
        context.user_data['admin_add'] = {'protocol': protocol, 'country': country, 'count': 5}
        await q.message.edit_text(
            f"➕➕ Добавление 5 ключей\n\n{PROTOCOL_NAMES[protocol]} — {country}\n\n"
            f"Отправьте 5 ключей, каждый с новой строки:\n\n"
            f"Пример:\nvless://key1\nvless://key2\nvless://key3\nvless://key4\nvless://key5\n\n"
            f"🔙 /cancel для отмены",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Отмена", callback_data=f'adm_country_{protocol}_{country}')]])
        )
    
    # Список ключей
    elif d.startswith('adm_list_'):
        _, _, protocol, country = d.split('_', 3)
        async with aiosqlite.connect('shop.db') as db:
            c = await db.execute('SELECT id, key_data, is_sold, expires_at FROM vpn_keys WHERE protocol=? AND country=? ORDER BY id DESC LIMIT 10', (protocol, country))
            keys = await c.fetchall()
        
        if keys:
            text = f"📋 Ключи {PROTOCOL_NAMES[protocol]} — {country}\n\n"
            for k in keys:
                status = "✅" if not k[2] else f"❌ (до {k[3][:10] if k[3] else '?'})"
                text += f"ID {k[0]}: {status}\n{k[1][:40]}...\n\n"
        else:
            text = f"Нет ключей для {PROTOCOL_NAMES[protocol]} — {country}"
        
        await q.message.edit_text(text, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Назад", callback_data=f'adm_country_{protocol}_{country}')]
        ]))
    
    # Удалить последний
    elif d.startswith('adm_del_'):
        _, _, protocol, country = d.split('_', 3)
        async with aiosqlite.connect('shop.db') as db:
            c = await db.execute('SELECT id, key_data FROM vpn_keys WHERE protocol=? AND country=? AND is_sold=FALSE ORDER BY id DESC LIMIT 1', (protocol, country))
            key = await c.fetchone()
        
        if key:
            async with aiosqlite.connect('shop.db') as db:
                await db.execute('DELETE FROM vpn_keys WHERE id=?', (key[0],))
                await db.commit()
            text, kb = await admin_country_menu(protocol, country)
            await q.message.edit_text(f"🗑️ Ключ ID {key[0]} удалён!\n\n{text}", reply_markup=kb)
        else:
            await q.answer("Нет доступных ключей для удаления", show_alert=True)

# ========== ОБРАБОТЧИК ТЕКСТА ДЛЯ АДМИНА ==========
async def admin_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает добавление ключей админом"""
    u = update.effective_user
    t = update.message.text
    
    if u.id != ADMIN_ID:
        return False
    
    if t == '/cancel':
        context.user_data.pop('admin_add', None)
        await update.message.reply_text("❌ Добавление отменено", reply_markup=admin_main_kb())
        return True
    
    add_info = context.user_data.get('admin_add')
    if not add_info:
        return False
    
    protocol = add_info['protocol']
    country = add_info['country']
    count = add_info['count']
    
    if count == 1:
        # Добавляем один ключ
        await add_key(protocol, country, t.strip())
        context.user_data.pop('admin_add', None)
        
        async with aiosqlite.connect('shop.db') as db:
            c = await db.execute('SELECT COUNT(*) FROM vpn_keys WHERE protocol=? AND country=? AND is_sold=FALSE', (protocol, country))
            available = (await c.fetchone())[0]
        
        text, kb = await admin_country_menu(protocol, country)
        await update.message.reply_text(f"✅ Ключ добавлен! Доступно: {available}", reply_markup=kb)
        return True
    
    elif count == 5:
        # Добавляем 5 ключей (каждый с новой строки)
        lines = [l.strip() for l in t.strip().split('\n') if l.strip()]
        added = 0
        for line in lines[:5]:
            await add_key(protocol, country, line)
            added += 1
        
        context.user_data.pop('admin_add', None)
        
        async with aiosqlite.connect('shop.db') as db:
            c = await db.execute('SELECT COUNT(*) FROM vpn_keys WHERE protocol=? AND country=? AND is_sold=FALSE', (protocol, country))
            available = (await c.fetchone())[0]
        
        text, kb = await admin_country_menu(protocol, country)
        await update.message.reply_text(f"✅ Добавлено {added} ключей! Доступно: {available}", reply_markup=kb)
        return True
    
    return False

# ========== ОСНОВНОЙ ОБРАБОТЧИК КНОПОК (добавить админ-обработку) ==========
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    d = q.data
    u = q.from_user
    await reg(u.id, u.username, u.first_name)
    
    # Пробуем админ-обработчик
    if d.startswith('admin') or d.startswith('adm_'):
        await admin_button_handler(update, context)
        return
    
    # Остальной код button_handler без изменений...
    if d == 'back':
        await q.message.edit_text("🏠 Главное меню:", reply_markup=main_menu(u.id))
    # ... весь остальной код button_handler ...
