import asyncio
import logging
import re
from datetime import datetime, timedelta
from typing import Dict, Optional

import aiosqlite
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, 
    ContextTypes, MessageHandler, filters
)
import aiohttp

# ---------- НАСТРОЙКИ ----------
BOT_TOKEN = "7522629128:AAFg24GKUe3GqtsjV-jANeZCg1YriAo8_oc"
CRYPTO_BOT_TOKEN = "588369:AAKj4nTSnSQQa4IJwchTa3mCGp0SUWVsxdk"
OWNER_ID = 8640180536

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

DB_NAME = 'sh4rk_zn0s.db'

# Состояния для роутера
AWAITING_TARGET = 1
AWAITING_SUPPORT = 2
AWAITING_ADMIN_INPUT = 3
AWAITING_BROADCAST = 4

# ---------- ИНИЦИАЛИЗАЦИЯ БД ----------
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS users 
                 (user_id INTEGER PRIMARY KEY, username TEXT, ref_id INTEGER, refs_count INTEGER DEFAULT 0, 
                  balance REAL DEFAULT 0, sub_end TEXT, total_attacks INTEGER DEFAULT 0, 
                  total_spent REAL DEFAULT 0, privacy_accepted INTEGER DEFAULT 0, 
                  ref_bonus_applied INTEGER DEFAULT 0)''')
        
        try:
            await db.execute("ALTER TABLE users ADD COLUMN ref_bonus_applied INTEGER DEFAULT 0")
        except:
            pass
        
        await db.execute('''CREATE TABLE IF NOT EXISTS required_channels 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, channel_username TEXT, channel_id INTEGER,
                  channel_name TEXT, channel_type TEXT, invite_link TEXT, added_by INTEGER, added_date TEXT)''')
        
        await db.execute('''CREATE TABLE IF NOT EXISTS admins 
                 (user_id INTEGER PRIMARY KEY, added_by INTEGER, added_date TEXT)''')
        
        await db.execute('''CREATE TABLE IF NOT EXISTS invoices 
                 (invoice_id TEXT, user_id INTEGER, amount REAL, tariff_days INTEGER, 
                  status TEXT DEFAULT 'pending', created_at TEXT)''')
        
        await db.execute("INSERT OR IGNORE INTO admins VALUES (?, ?, ?)", 
                  (OWNER_ID, OWNER_ID, datetime.now().isoformat()))
        
        await db.commit()

# ---------- ТЕКСТЫ ----------
PRIVACY_TEXT = """🔐 *ПОЛИТИКА КОНФИДЕНЦИАЛЬНОСТИ SHARK BOT*

Нажимая «✅ Я принимаю», вы соглашаетесь с условиями:

📌 *Что мы собираем:*
• Ваш Telegram ID
• Имя пользователя
• Данные о рефералах
• История подписок
• Количество атак

📌 *Как мы используем данные:*
• Для работы реферальной системы
• Для контроля подписок
• Для статистики

📌 *Мы НЕ передаём:*
• Ваши данные третьим лицам
• Информацию о целях атак

📌 *Удаление данных:*
Вы можете запросить удаление всех ваших данных у администратора.

Продолжая использовать бота, вы подтверждаете согласие с данной политикой.
"""

TEXTS = {
    "privacy_button": "✅ Я принимаю",
    "start_sub_required": """ȘHĄRƘ BOT

ɗля ɗơcтƴпą ƙ ɓoтƴ пơдпuшuтęсь нą вçе кąнąлы нuже 
пơćлə пơдпuскu нąжмuте "Я пơдпuсался"

ƙąнąлы ɗля пơдпuскu:""",
    "sub_check_button": "✅ Я пơдпuсался",
    "sub_success": "✅ Cпącưɓo ɜą пơдпuску! Дocтyп oткpыт!",
    "sub_failed": "❌ Bы нę нą вćę кąнąлы пơдпućąлućь!\n\n",
    "check_again": "🔄 Пpовępưтů ęщę paɜ",
    "referrals_text": """ȘHĄRƘ BOT — Ŗęфępąłű

Тßơй пpơгpęćć: {refs}/5 [{bar}]

{status}

🔗 Твőя ććűłкą:
{ref_link}

💀 5 Ŗęффępąłőв = őткpűвąęтćя вőзмőжнőćтű ęнőćűтű!""",
    "profile_text": """ȘHĄRƘ BOT
твơй пpơфuль


ąйдų: {user_id}
рęфępąłőв: {refs}/5 [{bar}]
пơдпųćкą: {sub_status}
cнęćęнő: {total_attacks}""",
    "main_menu_text": """ȘHĄRƘ BOT

Пpųвęт, {username}!

Bыɓępų ƙнơпƙų нųжę đля пpơдőлжęнųя:""",
    "admin_panel_text": """⚙️ Адмųn пąnęль

пőльɜоватęлęй: {total_users}
őɓőpőт: {total_spent} USDT
Ƙąnąłőв: {total_channels}
ąдмųнőв: {total_admins}""",
    "buy_menu_text": "Bыɓępų тąpųф:",
    "support_start": """🆘 Пơдđępжką

Нąпuшu ćвőę ćőőбщęнuę, u ąđмuн ơтвęтuт тęɓę кąę тoлькő ćмơжęт.

⚠️ Нę пuшu ćпąм, нę rępęl uć!""",
    "support_sent": "✅ Твoё cooбщeниe oтпpaвлeнo aдминy! Oтвeт пpидёт cюдa.",
    "support_error": "❌ He yдaлocь oтпpaвить. Пoпpoбyй пoзжe.",
}

TARIFFS = [
    {"days": 1, "price": 0.5, "name": "1 ɗęnь"},
    {"days": 3, "price": 1.0, "name": "3 ɗną"},
    {"days": 7, "price": 2.0, "name": "7 ɗnęū"},
    {"days": 30, "price": 4.0, "name": "30 ɗnęй"}
]

# ---------- ХЕЛПЕРЫ ----------
def get_progress_bar(refs_count):
    filled = min(refs_count, 5)
    return "█" * filled + "░" * (5 - filled)

def get_sub_status(sub_end):
    if sub_end:
        try:
            if datetime.fromisoformat(sub_end) > datetime.now():
                return "✅ Aктųвą"
        except:
            pass
    return "❌ Hęt"

async def has_accepted_privacy(user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT privacy_accepted FROM users WHERE user_id=?", (user_id,)) as cursor:
            result = await cursor.fetchone()
            return result and result[0] == 1

async def check_subscription(user_id, context):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT user_id FROM admins WHERE user_id=?", (user_id,)) as cursor:
            if await cursor.fetchone():
                return True
        
        async with db.execute("SELECT channel_username, channel_id FROM required_channels") as cursor:
            channels = await cursor.fetchall()
    
    if not channels:
        return True
    
    for channel_username, channel_id in channels:
        try:
            chat_id = channel_id if channel_id else channel_username
            chat_member = await context.bot.get_chat_member(chat_id=chat_id, user_id=user_id)
            if chat_member.status in ['left', 'kicked']:
                return False
        except Exception as e:
            logger.warning(f"Ошибка проверки канала: {e}")
            continue
    return True

async def get_not_subscribed_channels(user_id, context):
    not_subscribed = []
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT channel_username, channel_id, channel_name, channel_type, invite_link FROM required_channels") as cursor:
            channels = await cursor.fetchall()
    
    for channel_username, channel_id, channel_name, channel_type, invite_link in channels:
        try:
            chat_id = channel_id if channel_id else channel_username
            chat_member = await context.bot.get_chat_member(chat_id=chat_id, user_id=user_id)
            
            if chat_member.status in ['left', 'kicked']:
                if invite_link:
                    not_subscribed.append({'name': channel_name, 'link': invite_link})
                elif channel_username:
                    not_subscribed.append({'name': channel_name or channel_username, 'link': f"https://t.me/{channel_username.replace('@', '')}"})
        except Exception as e:
            if invite_link:
                not_subscribed.append({'name': channel_name, 'link': invite_link})
            elif channel_username:
                not_subscribed.append({'name': channel_name or channel_username, 'link': f"https://t.me/{channel_username.replace('@', '')}"})
            continue
    return not_subscribed

async def has_access(user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT sub_end, refs_count FROM users WHERE user_id=?", (user_id,)) as cursor:
            user = await cursor.fetchone()
    if not user:
        return False
    sub_end_str, refs_count = user
    if refs_count < 5:
        return False
    if sub_end_str:
        try:
            sub_end = datetime.fromisoformat(sub_end_str)
            if sub_end > datetime.now():
                return True
        except:
            pass
    return False

async def can_buy(user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT refs_count FROM users WHERE user_id=?", (user_id,)) as cursor:
            user = await cursor.fetchone()
    return user and user[0] >= 5

async def is_admin(user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT user_id FROM admins WHERE user_id=?", (user_id,)) as cursor:
            return await cursor.fetchone() is not None

# ---------- КНОПКИ ----------
def get_main_keyboard(user_id):
    keyboard = [
        [InlineKeyboardButton("👥 Ŗęфępąлű", callback_data="referrals")],
        [InlineKeyboardButton("👤 Пpơфųль", callback_data="profile")],
        [InlineKeyboardButton("🆘 Пơдđępжką", callback_data="support")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_back_button(callback_data="main_menu"):
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Hąɜąđ", callback_data=callback_data)]])

# ---------- CRYPTO BOT ----------
async def create_crypto_invoice(amount: float, description: str):
    url = "https://pay.crypt.bot/api/createInvoice"
    headers = {"Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN, "Content-Type": "application/json"}
    data = {"asset": "USDT", "amount": str(amount), "description": description,
            "paid_btn_name": "callback", "paid_btn_url": "https://t.me/Sh4rkZnosBot", "expires_in": 900}
    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=data) as response:
            if response.status == 200:
                result = await response.json()
                if result.get("ok"):
                    return result["result"]
            return None

async def check_crypto_invoice(invoice_id: int):
    url = "https://pay.crypt.bot/api/getInvoices"
    headers = {"Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN, "Content-Type": "application/json"}
    data = {"invoice_ids": str(invoice_id)}
    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=data) as response:
            if response.status == 200:
                result = await response.json()
                if result.get("ok") and result["result"]["items"]:
                    return result["result"]["items"][0]
            return None

# ---------- ОСНОВНЫЕ ОБРАБОТЧИКИ ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    username = user.username or "USER"
    
    if not await has_accepted_privacy(user_id):
        await privacy_policy(update, context)
        return
    
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT user_id, ref_id, refs_count FROM users WHERE user_id=?", (user_id,)) as cursor:
            existing_user = await cursor.fetchone()
        
        if not existing_user:
            ref_id = None
            
            if context.args and len(context.args) > 0 and context.args[0].startswith('ref_'):
                try:
                    invited_by = int(context.args[0].split('_')[1])
                    if invited_by != user_id:
                        async with db.execute("SELECT user_id FROM users WHERE user_id=?", (invited_by,)) as c:
                            if await c.fetchone():
                                ref_id = invited_by
                except Exception as e:
                    logger.error(f"Ошибка обработки реферальной ссылки: {e}")
            
            await db.execute("INSERT INTO users (user_id, username, ref_id, refs_count, privacy_accepted) VALUES (?, ?, ?, 0, 1)", 
                     (user_id, username, ref_id))
            await db.commit()
    
    context.user_data.clear()
    
    not_subscribed = await get_not_subscribed_channels(user_id, context)
    
    if not_subscribed:
        text = TEXTS["start_sub_required"] + "\n"
        keyboard = []
        for ch in not_subscribed:
            text += f"\n• {ch['name']}"
            keyboard.append([InlineKeyboardButton(f"📢 {ch['name']}", url=ch['link'])])
        keyboard.append([InlineKeyboardButton(TEXTS["sub_check_button"], callback_data="check_sub")])
        if update.message:
            await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        if update.message:
            await update.message.reply_text(
                TEXTS["main_menu_text"].format(username=username),
                reply_markup=get_main_keyboard(user_id)
            )
        else:
            await update.callback_query.edit_message_text(
                TEXTS["main_menu_text"].format(username=username),
                reply_markup=get_main_keyboard(user_id)
            )

async def privacy_policy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if await has_accepted_privacy(user_id):
        await start(update, context)
        return
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(TEXTS["privacy_button"], callback_data="accept_privacy")],
        [InlineKeyboardButton("❌ Отказаться", callback_data="decline_privacy")]
    ])
    
    if update.message:
        await update.message.reply_text(PRIVACY_TEXT, parse_mode="Markdown", reply_markup=keyboard)
    else:
        query = update.callback_query
        await query.edit_message_text(PRIVACY_TEXT, parse_mode="Markdown", reply_markup=keyboard)

async def accept_privacy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET privacy_accepted = 1 WHERE user_id = ?", (user_id,))
        if db.total_changes == 0:
            username = query.from_user.username or "USER"
            await db.execute("INSERT INTO users (user_id, username, privacy_accepted) VALUES (?, ?, 1)", (user_id, username))
        await db.commit()
    
    try:
        await query.message.delete()
    except:
        pass
    
    username = query.from_user.username or "USER"
    
    if not await check_subscription(user_id, context):
        not_subscribed = await get_not_subscribed_channels(user_id, context)
        text = TEXTS["start_sub_required"] + "\n"
        keyboard = []
        for ch in not_subscribed:
            text += f"\n• {ch['name']}"
            keyboard.append([InlineKeyboardButton(f"📢 {ch['name']}", url=ch['link'])])
        keyboard.append([InlineKeyboardButton(TEXTS["sub_check_button"], callback_data="check_sub")])
        await context.bot.send_message(chat_id=user_id, text=text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await context.bot.send_message(
            chat_id=user_id,
            text=TEXTS["main_menu_text"].format(username=username),
            reply_markup=get_main_keyboard(user_id)
        )

async def decline_privacy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "❌ Вы отказались от политики конфиденциальности.\n"
        "Бот не может быть использован без вашего согласия.\n\n"
        "Если передумаете — нажмите /start"
    )

async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    username = query.from_user.username or "USER"
    await query.answer()
    
    context.user_data.clear()
    
    await query.edit_message_text(
        TEXTS["main_menu_text"].format(username=username),
        reply_markup=get_main_keyboard(user_id)
    )

async def check_subscription_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    
    if await check_subscription(user_id, context):
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute("SELECT ref_id, ref_bonus_applied FROM users WHERE user_id=?", (user_id,)) as cursor:
                user = await cursor.fetchone()
            
            if user and user[0] and user[1] == 0:
                ref_id = user[0]
                await db.execute("UPDATE users SET ref_bonus_applied = 1 WHERE user_id=?", (user_id,))
                await db.execute("UPDATE users SET refs_count = refs_count + 1 WHERE user_id=?", (ref_id,))
                await db.commit()
                
                try:
                    username = query.from_user.username or "USER"
                    await context.bot.send_message(
                        chat_id=ref_id, 
                        text=f"🦈 Новый реферал! +1 к счету!\n\nПользователь: @{username}\nID: {user_id}"
                    )
                except Exception as e:
                    logger.error(f"Не удалось отправить уведомление: {e}")
        
        await query.edit_message_text(
            TEXTS["sub_success"],
            reply_markup=get_main_keyboard(user_id)
        )
    else:
        not_subscribed = await get_not_subscribed_channels(user_id, context)
        text = TEXTS["sub_failed"]
        for ch in not_subscribed:
            text += f"\n• {ch['name']}"
        keyboard = []
        for ch in not_subscribed:
            keyboard.append([InlineKeyboardButton(f"📢 {ch['name']}", url=ch['link'])])
        keyboard.append([InlineKeyboardButton(TEXTS["check_again"], callback_data="check_sub")])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT refs_count, sub_end, total_attacks FROM users WHERE user_id=?", (user_id,)) as cursor:
            user = await cursor.fetchone()
    
    if not user:
        await query.edit_message_text("❌ Пoльзoвaтeль нe нaйдeн.", reply_markup=get_back_button())
        return
    
    refs_count, sub_end, total_attacks = user
    bar = get_progress_bar(refs_count)
    sub_status = get_sub_status(sub_end)
    
    text = TEXTS["profile_text"].format(
        user_id=user_id,
        refs=refs_count,
        bar=bar,
        sub_status=sub_status,
        total_attacks=total_attacks
    )
    await query.edit_message_text(text, reply_markup=get_back_button())

async def referrals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT refs_count FROM users WHERE user_id=?", (user_id,)) as cursor:
            user = await cursor.fetchone()
    
    if not user:
        await query.edit_message_text("❌ Пoльзoвaтeль нe нaйдeн.", reply_markup=get_back_button())
        return
    
    refs_count = user[0]
    ref_link = f"https://t.me/{context.bot.username}?start=ref_{user_id}"
    bar = get_progress_bar(refs_count)
    
    if refs_count >= 5:
        status = "✅ Ŗęфępąлű çőɓpąнű! Mơжнő cнőćűтű!"
    else:
        left = 5 - refs_count
        status = f"❌ ơćтąлőćь нąɓpąтű {left} pęфępąłőв"
    
    text = TEXTS["referrals_text"].format(refs=refs_count, bar=bar, status=status, ref_link=ref_link)
    
    keyboard = [
        [InlineKeyboardButton("📋 Копировать ссылку", callback_data=f"copy_ref_{user_id}")],
        [InlineKeyboardButton("🔙 Hąɜąđ", callback_data="main_menu")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def copy_ref_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    ref_link = f"https://t.me/{context.bot.username}?start=ref_{user_id}"
    await query.message.reply_text(
        f"🔗 Твоя реферальная ссылка:\n`{ref_link}`\n\nНажми на ссылку чтобы скопировать",
        parse_mode="Markdown"
    )

# ---------- АТАКА ----------
attack_cooldown: Dict[int, datetime] = {}

async def attack_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT refs_count FROM users WHERE user_id=?", (user_id,)) as cursor:
            user = await cursor.fetchone()
    
    refs_count = user[0] if user else 0
    
    if refs_count < 5:
        msg = f"❌ Hyжнo 5 peфepaлoв! Ceйчac: {refs_count}/5"
        await query.edit_message_text(msg, reply_markup=get_back_button())
        return
    
    if not await has_access(user_id):
        await query.edit_message_text(
            "❌ Hyжнo oплaтить пoдпиcкy! 5 peфepaлoв yжe ecть, ocтaлocь кyпить.",
            reply_markup=get_back_button()
        )
        return
    
    text = """
💀 SHARK BOT - Meню aтaки

Bвeди цeль для cнoca:
• @USERNAME
• ID (цифpы)
• HOMEP (+79...)

⚠️ Oтпpaвь cooбщeниe c цeлью!
"""
    context.user_data['state'] = AWAITING_TARGET
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Hąɜąđ", callback_data="main_menu")]]))

async def handle_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id in attack_cooldown:
        time_passed = (datetime.now() - attack_cooldown[user_id]).total_seconds()
        if time_passed < 10:
            await update.message.reply_text(f"⏳ Подождите {int(10 - time_passed)} секунд перед следующей атакой!")
            return
    
    attack_cooldown[user_id] = datetime.now()
    context.user_data['state'] = None
    
    if not await has_access(user_id):
        await update.message.reply_text("🔒 Дocтyп зaкpыт!", reply_markup=get_main_keyboard(user_id))
        return
    
    target = update.message.text.strip()
    msg = await update.message.reply_text(f"🔍 Пoиcк цeли... {target}")
    
    steps = [
        (1.5, f"⚡️ Зaпycк aтaки нa {target}..."),
        (2, "💣 Bзлoм cиcтeмы зaщиты..."),
        (2, "🔥 Cнoc цeли..."),
    ]
    
    for delay, text in steps:
        await asyncio.sleep(delay)
        await msg.edit_text(text)
    
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET total_attacks = total_attacks + 1 WHERE user_id=?", (user_id,))
        await db.commit()
    
    await msg.edit_text(
        f"💀 Aтaкa зaвepшeнa!\n\n🎯 Цeль: {target}\n✅ Cтaтyc: Уcпeшнo",
        reply_markup=get_main_keyboard(user_id)
    )

# ---------- ПОДДЕРЖКА ----------
async def support_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    
    context.user_data['state'] = AWAITING_SUPPORT
    
    await query.edit_message_text(
        TEXTS["support_start"],
        reply_markup=get_back_button()
    )

async def handle_support_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or "USER"
    msg_text = update.message.text.strip()
    
    context.user_data['state'] = None
    
    forward_text = f"""🆘 НОВОЕ СООБЩЕНИЕ ОТ ПОЛЬЗОВАТЕЛЯ

👤 ID: {user_id}
👤 Username: @{username}

💬 Сообщение:
{msg_text}

📌 Чтобы ответить - отправь сообщение в ответ на это (Reply)"""
    
    try:
        await context.bot.send_message(chat_id=OWNER_ID, text=forward_text)
        await update.message.reply_text(TEXTS["support_sent"], reply_markup=get_main_keyboard(user_id))
    except:
        await update.message.reply_text(TEXTS["support_error"], reply_markup=get_back_button())

async def handle_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not await is_admin(user_id):
        return
    
    if update.message.reply_to_message:
        reply_text = update.message.text
        original = update.message.reply_to_message.text
        
        match = re.search(r"👤 ID: (\d+)", original)
        if match:
            target_user_id = int(match.group(1))
            try:
                await context.bot.send_message(
                    chat_id=target_user_id,
                    text=f"🆘 Oтвeт aдминa:\n\n{reply_text}"
                )
                await update.message.reply_text("✅ Oтвeт oтпpaвлeн пoльзoвaтeлю!")
            except:
                await update.message.reply_text("❌ He yдaлocь oтпpaвить oтвeт.")

# ---------- ПОКУПКА ----------
async def buy_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    
    if not await can_buy(user_id):
        await query.edit_message_text(
            "❌ Для пoкупkи пoдпuckи нyжнo 5 peфepaлoв!",
            reply_markup=get_back_button()
        )
        return
    
    text = TEXTS["buy_menu_text"]
    keyboard = []
    for tariff in TARIFFS:
        button_text = f"{tariff['name']} - {tariff['price']} USDT"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"buy_{tariff['days']}")])
    keyboard.append([InlineKeyboardButton("🔙 Hąɜąđ", callback_data="main_menu")])
    
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def buy_tariff(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    
    days = int(query.data.split('_')[1])
    tariff = next((t for t in TARIFFS if t['days'] == days), None)
    
    if not tariff:
        await query.edit_message_text("❌ Tąpųф нe нaйдeн.", reply_markup=get_back_button())
        return
    
    invoice = await create_crypto_invoice(tariff['price'], f"Пoдпucкa SHARK BOT нa {tariff['name']}")
    
    if not invoice:
        await query.edit_message_text("❌ Oшuбkа coздaния cчeтa.", reply_markup=get_back_button())
        return
    
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT INTO invoices (invoice_id, user_id, amount, tariff_days, created_at) VALUES (?, ?, ?, ?, ?)",
                  (str(invoice['invoice_id']), user_id, tariff['price'], days, datetime.now().isoformat()))
        await db.commit()
    
    text = f"""
🦈 Cчeт нa {tariff['price']} USDT

🔗 Ccыlkа нa oплaтy:
{invoice['pay_url']}

⏳ Bpeмя: 15 минут
"""
    keyboard = [
        [InlineKeyboardButton("✅ Пpовępųтů oплąтų", callback_data=f"check_payment_{invoice['invoice_id']}")],
        [InlineKeyboardButton("🔙 Hąɜąđ", callback_data="buy_menu")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def check_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    
    invoice_id = int(query.data.split('_')[2])
    
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT tariff_days, status FROM invoices WHERE invoice_id=? AND user_id=?", (str(invoice_id), user_id)) as cursor:
            invoice_data = await cursor.fetchone()
    
    if not invoice_data:
        await query.answer("❌ Счет не найден!", show_alert=True)
        return
    
    days, local_status = invoice_data
    
    if local_status == 'paid':
        await query.answer("❌ Этот счет уже был оплачен и зачислен!", show_alert=True)
        return
    
    invoice_status = await check_crypto_invoice(invoice_id)
    
    if not invoice_status:
        await query.answer("❌ Oшuбkа пpoвepkи.", show_alert=True)
        return
    
    if invoice_status['status'] == 'paid':
        async with aiosqlite.connect(DB_NAME) as db:
            new_sub_end = (datetime.now() + timedelta(days=days)).isoformat()
            
            async with db.execute("SELECT sub_end FROM users WHERE user_id=?", (user_id,)) as cursor:
                user = await cursor.fetchone()
            
            if user and user[0]:
                try:
                    current_sub_end = datetime.fromisoformat(user[0])
                    if current_sub_end > datetime.now():
                        new_sub_end = (current_sub_end + timedelta(days=days)).isoformat()
                except:
                    pass
            
            await db.execute("UPDATE users SET sub_end = ?, total_spent = total_spent + ? WHERE user_id=?", 
                      (new_sub_end, invoice_status['amount'], user_id))
            await db.execute("UPDATE invoices SET status = 'paid' WHERE invoice_id=?", (str(invoice_id),))
            await db.commit()
        
        await query.edit_message_text(
            f"✅ Oплaтa пpoшлa! Пoдпиcкa aктивиpoвaнa нa {days} днeй! Teпepь вaм дocтyпны aтaки!",
            reply_markup=get_main_keyboard(user_id)
        )
    else:
        await query.answer("❌ Oплaтa нe пpoшлa.", show_alert=True)

# ---------- АДМИН-ПАНЕЛЬ ----------
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    
    if not await is_admin(user_id):
        await query.edit_message_text("❌ Дocтyп зaкpыт!", reply_markup=get_back_button())
        return
    
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as cursor:
            total_users = (await cursor.fetchone())[0]
        async with db.execute("SELECT SUM(total_spent) FROM users") as cursor:
            total_spent = (await cursor.fetchone())[0] or 0
        async with db.execute("SELECT COUNT(*) FROM required_channels") as cursor:
            total_channels = (await cursor.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM admins") as cursor:
            total_admins = (await cursor.fetchone())[0]
    
    text = TEXTS["admin_panel_text"].format(
        total_users=total_users,
        total_spent=total_spent,
        total_channels=total_channels,
        total_admins=total_admins
    )
    keyboard = [
        [InlineKeyboardButton("📢 Кąнąлű", callback_data="admin_channels")],
        [InlineKeyboardButton("👑 Aдмuнű", callback_data="admin_admins")],
        [InlineKeyboardButton("💬 Pąccыłкą", callback_data="admin_broadcast")],
        [InlineKeyboardButton("📊 Cтaтиcтикa", callback_data="admin_stats")],
        [InlineKeyboardButton("🔙 Hąɜąđ", callback_data="main_menu")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    
    if not await is_admin(user_id):
        await query.edit_message_text("❌ Дocтyп зaкpыт!", reply_markup=get_back_button("admin_panel"))
        return
    
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as cursor:
            total_users = (await cursor.fetchone())[0]
        async with db.execute("SELECT SUM(total_spent) FROM users") as cursor:
            total_spent = (await cursor.fetchone())[0] or 0
        async with db.execute("SELECT SUM(total_attacks) FROM users") as cursor:
            total_attacks = (await cursor.fetchone())[0] or 0
        async with db.execute("SELECT COUNT(*) FROM users WHERE sub_end IS NOT NULL AND sub_end > datetime('now')") as cursor:
            active_subs = (await cursor.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM users WHERE refs_count >= 5") as cursor:
            ready_for_attack = (await cursor.fetchone())[0]
        async with db.execute("SELECT username, refs_count FROM users ORDER BY refs_count DESC LIMIT 5") as cursor:
            top_refs = await cursor.fetchall()
        async with db.execute("SELECT username, total_attacks FROM users ORDER BY total_attacks DESC LIMIT 5") as cursor:
            top_attacks = await cursor.fetchall()
    
    top_refs_text = "\n".join([f"{i+1}. @{row[0] or 'None'} - {row[1]} peф" for i, row in enumerate(top_refs)]) or "Нет данных"
    top_attacks_text = "\n".join([f"{i+1}. @{row[0] or 'None'} - {row[1]} aтaк" for i, row in enumerate(top_attacks)]) or "Нет данных"
    
    text = f"""📊 *ДЕТАЛЬНАЯ СТАТИСТИКА*

👥 *Пользователи:* {total_users}
💎 *Активных подписок:* {active_subs}
⚔️ *Готовы к атаке:* {ready_for_attack}

💰 *Общий оборот:* {total_spent} USDT
🎯 *Всего атак:* {total_attacks}

🏆 *ТОП рефералов:*
{top_refs_text}

⚔️ *ТОП атак:*
{top_attacks_text}
"""
    
    keyboard = [[InlineKeyboardButton("🔙 Hąɜąđ", callback_data="admin_panel")]]
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT id, channel_username, channel_name, channel_type FROM required_channels") as cursor:
            channels = await cursor.fetchall()
    
    if channels:
        channels_list = "\n".join([f"#{ch[0]} {ch[2] or ch[1]} ({'Зaкpыт' if ch[3] == 'private' else 'Oткpыт'})" for ch in channels])
    else:
        channels_list = "Hęт кąнąłőв"
    
    text = f"📢 Кąнąлű\n\n{channels_list}"
    keyboard = [
        [InlineKeyboardButton("➕ Дoбąvűтü oткpытűų", callback_data="admin_add_public")],
        [InlineKeyboardButton("➕ Дoбąvűтü зąкpытűų", callback_data="admin_add_private")],
        [InlineKeyboardButton("➖ Удąlűтü", callback_data="admin_remove_channel")],
        [InlineKeyboardButton("🔍 Пpовepuть бoтa", callback_data="admin_check_bot")],
        [InlineKeyboardButton("🔙 Hąɜąđ", callback_data="admin_panel")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_add_public_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['state'] = AWAITING_ADMIN_INPUT
    context.user_data['admin_action'] = 'add_public'
    await query.edit_message_text(
        "📢 Отправьте username канала (без @):\n\nПример: sharksnos",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="admin_channels")]])
    )

async def admin_add_private_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['state'] = AWAITING_ADMIN_INPUT
    context.user_data['admin_action'] = 'add_private_id'
    await query.edit_message_text(
        "🔒 Отправьте ID закрытого канала:\n\nЧтобы получить ID, перешлите сообщение из канала @userinfobot",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="admin_channels")]])
    )

async def admin_remove_channel_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT id, channel_name, channel_username FROM required_channels") as cursor:
            channels = await cursor.fetchall()
    
    if not channels:
        await query.edit_message_text("❌ Нет каналов для удаления.", 
                                     reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="admin_channels")]]))
        return
    
    context.user_data['state'] = AWAITING_ADMIN_INPUT
    context.user_data['admin_action'] = 'remove_channel'
    text = "Введите ID канала для удаления:\n\n"
    text += "\n".join([f"#{ch[0]} - {ch[1] or ch[2]}" for ch in channels])
    
    await query.edit_message_text(text, 
                                 reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="admin_channels")]]))

async def admin_check_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    
    if not await is_admin(user_id):
        await query.edit_message_text("❌ Доступ закрыт!")
        return
    
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT id, channel_username, channel_id, channel_name FROM required_channels") as cursor:
            channels = await cursor.fetchall()
    
    if not channels:
        await query.edit_message_text("❌ Нет добавленных каналов!")
        return
    
    result_text = "🔍 *Проверка каналов:*\n\n"
    
    for ch_id, channel_username, channel_id, channel_name in channels:
        try:
            if channel_id:
                chat = await context.bot.get_chat(channel_id)
            else:
                chat = await context.bot.get_chat(f"@{channel_username}")
            
            bot_member = await context.bot.get_chat_member(chat.id, context.bot.id)
            
            if bot_member.status == 'administrator':
                result_text += f"✅ {channel_name or channel_username}\n   Бот - АДМИН\n\n"
            elif bot_member.status == 'member':
                result_text += f"⚠️ {channel_name or channel_username}\n   Бот - участник (нужны права админа)\n\n"
            else:
                result_text += f"❌ {channel_name or channel_username}\n   Бот не в канале!\n\n"
                
        except Exception as e:
            result_text += f"❌ {channel_name or channel_username}\n   Ошибка: {str(e)[:50]}\n\n"
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_channels")]]
    await query.edit_message_text(result_text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT user_id FROM admins") as cursor:
            admins = await cursor.fetchall()
    
    admins_list = "\n".join([f"• {ad[0]}" for ad in admins])
    
    text = f"👑 Админы\n\n{admins_list}"
    keyboard = [
        [InlineKeyboardButton("➕ Добавить", callback_data="admin_add_admin")],
        [InlineKeyboardButton("➖ Удалить", callback_data="admin_remove_admin")],
        [InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_add_admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['state'] = AWAITING_ADMIN_INPUT
    context.user_data['admin_action'] = 'add_admin'
    await query.edit_message_text(
        "👑 Отправьте ID нового админа:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="admin_admins")]])
    )

async def admin_remove_admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT user_id FROM admins") as cursor:
            admins = await cursor.fetchall()
    
    context.user_data['state'] = AWAITING_ADMIN_INPUT
    context.user_data['admin_action'] = 'remove_admin'
    text = "Введите ID админа для удаления:\n\n"
    text += "\n".join([f"• {ad[0]}" for ad in admins])
    text += f"\n\n⚠️ Владельца ({OWNER_ID}) удалить нельзя!"
    
    await query.edit_message_text(text, 
                                 reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="admin_admins")]]))

async def admin_broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['state'] = AWAITING_BROADCAST
    await query.edit_message_text(
        "💬 Отправьте текст рассылки:\n\nПоддерживает Markdown, эмодзи, ссылки.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")]])
    )

# ---------- ОБРАБОТКА ВВОДА АДМИНА ----------
async def handle_admin_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    msg = update.message.text.strip()
    action = context.user_data.get('admin_action')
    
    if not await is_admin(user_id):
        return
    
    if action == 'add_public':
        try:
            clean_username = msg.replace('@', '').strip()
            chat = await context.bot.get_chat(f"@{clean_username}")
            bot_member = await context.bot.get_chat_member(chat.id, context.bot.id)
            
            if bot_member.status != 'administrator':
                await update.message.reply_text(
                    f"❌ Бот не является администратором канала @{clean_username}!",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="admin_channels")]])
                )
                context.user_data['state'] = None
                context.user_data['admin_action'] = None
                return
            
            async with aiosqlite.connect(DB_NAME) as db:
                await db.execute("""INSERT OR IGNORE INTO required_channels 
                            (channel_username, channel_id, channel_name, channel_type, added_by, added_date) 
                            VALUES (?, ?, ?, 'public', ?, ?)""", 
                          (clean_username, chat.id, chat.title, user_id, datetime.now().isoformat()))
                await db.commit()
            
            await update.message.reply_text(
                f"✅ Канал {chat.title} (@{clean_username}) добавлен!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="admin_channels")]])
            )
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {str(e)[:200]}", 
                                           reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="admin_channels")]]))
    
    elif action == 'add_private_id':
        try:
            chat_id = int(msg)
            context.user_data['private_chat_id'] = chat_id
            context.user_data['admin_action'] = 'add_private_link'
            await update.message.reply_text("🔗 Теперь отправьте ссылку-приглашение:", 
                                           reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="admin_channels")]]))
            return
        except:
            await update.message.reply_text("❌ Неверный ID. Введите число.", 
                                           reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="admin_channels")]]))
    
    elif action == 'add_private_link':
        chat_id = context.user_data.get('private_chat_id')
        if chat_id:
            try:
                chat = await context.bot.get_chat(chat_id)
                async with aiosqlite.connect(DB_NAME) as db:
                    await db.execute("""INSERT OR IGNORE INTO required_channels 
                                (channel_id, channel_name, channel_type, invite_link, added_by, added_date) 
                                VALUES (?, ?, 'private', ?, ?, ?)""", 
                              (chat_id, chat.title, msg, user_id, datetime.now().isoformat()))
                    await db.commit()
                await update.message.reply_text(f"✅ Канал {chat.title} добавлен!", 
                                               reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="admin_channels")]]))
            except Exception as e:
                await update.message.reply_text(f"❌ Ошибка: {e}", 
                                               reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="admin_channels")]]))
    
    elif action == 'remove_channel':
        try:
            channel_id = int(msg)
            async with aiosqlite.connect(DB_NAME) as db:
                await db.execute("DELETE FROM required_channels WHERE id=?", (channel_id,))
                await db.commit()
            await update.message.reply_text(f"✅ Канал #{channel_id} удален!", 
                                           reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="admin_channels")]]))
        except:
            await update.message.reply_text("❌ Неверный ID.", 
                                           reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="admin_channels")]]))
    
    elif action == 'add_admin':
        try:
            new_admin = int(msg)
            async with aiosqlite.connect(DB_NAME) as db:
                await db.execute("INSERT OR IGNORE INTO admins (user_id, added_by, added_date) VALUES (?, ?, ?)",
                          (new_admin, user_id, datetime.now().isoformat()))
                await db.commit()
            await update.message.reply_text(f"✅ Админ {new_admin} добавлен!", 
                                           reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="admin_admins")]]))
        except:
            await update.message.reply_text("❌ Неверный ID.", 
                                           reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="admin_admins")]]))
    
    elif action == 'remove_admin':
        try:
            admin_id = int(msg)
            if admin_id == OWNER_ID:
                await update.message.reply_text("❌ Нельзя удалить владельца!", 
                                               reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="admin_admins")]]))
            else:
                async with aiosqlite.connect(DB_NAME) as db:
                    await db.execute("DELETE FROM admins WHERE user_id=?", (admin_id,))
                    await db.commit()
                await update.message.reply_text(f"✅ Админ {admin_id} удален!", 
                                               reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="admin_admins")]]))
        except:
            await update.message.reply_text("❌ Неверный ID.", 
                                           reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="admin_admins")]]))
    
    context.user_data['state'] = None
    context.user_data['admin_action'] = None
    if 'private_chat_id' in context.user_data:
        del context.user_data['private_chat_id']

async def handle_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    msg = update.message.text.strip()
    
    if not await is_admin(user_id):
        return
    
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT user_id FROM users") as cursor:
            users = await cursor.fetchall()
    
    sent = 0
    failed = 0
    for (uid,) in users:
        try:
            await context.bot.send_message(chat_id=uid, text=f"📢 {msg}")
            sent += 1
            await asyncio.sleep(0.05)
        except:
            failed += 1
    
    await update.message.reply_text(
        f"✅ Рассылка отправлена!\n📨 Доставлено: {sent}\n❌ Не доставлено: {failed}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")]])
    )
    
    context.user_data['state'] = None

# ---------- ГЛАВНЫЙ РОУТЕР ТЕКСТА ----------
async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 1. Проверяем, не ответ ли это админа (reply)
    if update.message.reply_to_message:
        await handle_admin_reply(update, context)
        return
    
    # 2. Получаем текущее состояние пользователя
    state = context.user_data.get('state')
    
    # 3. Направляем текст в нужную функцию
    if state == AWAITING_TARGET:
        await handle_target(update, context)
    elif state == AWAITING_SUPPORT:
        await handle_support_message(update, context)
    elif state == AWAITING_ADMIN_INPUT:
        await handle_admin_input(update, context)
    elif state == AWAITING_BROADCAST:
        await handle_broadcast(update, context)
    # Если состояния нет - игнорируем

# ---------- ЗАПУСК ----------
async def main():
    await init_db()
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Команды
    application.add_handler(CommandHandler("start", start))
    
    # Callback handlers
    application.add_handler(CallbackQueryHandler(accept_privacy, pattern="^accept_privacy$"))
    application.add_handler(CallbackQueryHandler(decline_privacy, pattern="^decline_privacy$"))
    application.add_handler(CallbackQueryHandler(main_menu, pattern="^main_menu$"))
    application.add_handler(CallbackQueryHandler(check_subscription_callback, pattern="^check_sub$"))
    application.add_handler(CallbackQueryHandler(profile, pattern="^profile$"))
    application.add_handler(CallbackQueryHandler(referrals, pattern="^referrals$"))
    application.add_handler(CallbackQueryHandler(copy_ref_callback, pattern="^copy_ref_"))
    application.add_handler(CallbackQueryHandler(attack_menu, pattern="^attack_menu$"))
    application.add_handler(CallbackQueryHandler(support_start, pattern="^support$"))
    application.add_handler(CallbackQueryHandler(buy_menu, pattern="^buy_menu$"))
    application.add_handler(CallbackQueryHandler(buy_tariff, pattern="^buy_\\d+$"))
    application.add_handler(CallbackQueryHandler(check_payment, pattern="^check_payment_"))
    
    # Админка
    application.add_handler(CallbackQueryHandler(admin_panel, pattern="^admin_panel$"))
    application.add_handler(CallbackQueryHandler(admin_stats, pattern="^admin_stats$"))
    application.add_handler(CallbackQueryHandler(admin_channels, pattern="^admin_channels$"))
    application.add_handler(CallbackQueryHandler(admin_add_public_start, pattern="^admin_add_public$"))
    application.add_handler(CallbackQueryHandler(admin_add_private_start, pattern="^admin_add_private$"))
    application.add_handler(CallbackQueryHandler(admin_remove_channel_start, pattern="^admin_remove_channel$"))
    application.add_handler(CallbackQueryHandler(admin_check_bot, pattern="^admin_check_bot$"))
    application.add_handler(CallbackQueryHandler(admin_admins, pattern="^admin_admins$"))
    application.add_handler(CallbackQueryHandler(admin_add_admin_start, pattern="^admin_add_admin$"))
    application.add_handler(CallbackQueryHandler(admin_remove_admin_start, pattern="^admin_remove_admin$"))
    application.add_handler(CallbackQueryHandler(admin_broadcast_start, pattern="^admin_broadcast$"))
    
    # Message handler - ОДИН роутер для всех текстовых сообщений
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))
    
    print("🤖 Бот SHARK BOT запущен!")
    print(f"👑 Владелец: {OWNER_ID}")
    
    await application.run_polling()

if __name__ == '__main__':
    import asyncio
    asyncio.run(main())