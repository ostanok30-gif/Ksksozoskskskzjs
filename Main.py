import sqlite3
import random
import logging
import asyncio
import os
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from telegram.error import TelegramError, BadRequest, Forbidden
import aiohttp
import re
from functools import wraps
from contextlib import contextmanager

# ========== НАСТРОЙКИ И КОНСТАНТЫ ==========
BOT_TOKEN = os.getenv("BOT_TOKEN", "7522629128:AAFg24GKUe3GqtsjV-jANeZCg1YriAo8_oc")
CRYPTO_BOT_TOKEN = os.getenv("CRYPTO_BOT_TOKEN", "588369:AAKj4nTSnSQQa4IJwchTa3mCGp0SUWVsxdk")
OWNER_ID = int(os.getenv("OWNER_ID", "8640180536"))

DB_NAME = 'sh4rk_zn0s.db'
DB_TIMEOUT = 30
ATTACK_COOLDOWN = 10
API_TIMEOUT = 30
MAX_REFERRALS = 5

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ========== УПРАВЛЕНИЕ БАЗОЙ ДАННЫХ ==========
@contextmanager
def get_db():
    """Безопасное подключение к БД с автоматическим закрытием"""
    conn = sqlite3.connect(DB_NAME, timeout=DB_TIMEOUT)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    """Инициализация базы данных с проверкой целостности"""
    try:
        with get_db() as conn:
            c = conn.cursor()
            
            # Таблица пользователей
            c.execute('''CREATE TABLE IF NOT EXISTS users 
                         (user_id INTEGER PRIMARY KEY,
                          username TEXT,
                          ref_id INTEGER,
                          refs_count INTEGER DEFAULT 0,
                          balance REAL DEFAULT 0,
                          sub_end TEXT,
                          total_attacks INTEGER DEFAULT 0,
                          total_spent REAL DEFAULT 0,
                          ref_bonus_applied INTEGER DEFAULT 0,
                          created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                          last_activity TEXT)''')
            
            # Таблица обязательных каналов
            c.execute('''CREATE TABLE IF NOT EXISTS required_channels 
                         (id INTEGER PRIMARY KEY AUTOINCREMENT,
                          channel_username TEXT,
                          channel_id INTEGER,
                          channel_name TEXT,
                          channel_type TEXT,
                          invite_link TEXT,
                          added_by INTEGER,
                          added_date TEXT,
                          UNIQUE(channel_id, channel_username))''')
            
            # Таблица администраторов
            c.execute('''CREATE TABLE IF NOT EXISTS admins 
                         (user_id INTEGER PRIMARY KEY,
                          added_by INTEGER,
                          added_date TEXT)''')
            
            # Таблица счетов
            c.execute('''CREATE TABLE IF NOT EXISTS invoices 
                         (invoice_id TEXT PRIMARY KEY,
                          user_id INTEGER,
                          amount REAL,
                          tariff_days INTEGER,
                          status TEXT DEFAULT 'pending',
                          created_at TEXT,
                          expires_at TEXT,
                          FOREIGN KEY (user_id) REFERENCES users(user_id))''')
            
            # Индексы для оптимизации
            c.execute('CREATE INDEX IF NOT EXISTS idx_user_sub_end ON users(sub_end)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_invoice_user ON invoices(user_id)')
            
            # Добавляем владельца как администратора
            c.execute("INSERT OR IGNORE INTO admins VALUES (?, ?, ?)",
                      (OWNER_ID, OWNER_ID, datetime.now().isoformat()))
            
            conn.commit()
            logger.info("✅ База данных инициализирована")
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации БД: {e}")
        raise

init_db()

# ========== ТЕКСТЫ СООБЩЕНИЙ ==========
TEXTS = {
    "start_sub_required": """🦈 *SHARK BOT*

Для доступа к боту подпишитесь на все каналы ниже,
затем нажмите "✅ Я подписался"

*Каналы для подписки:*""",

    "sub_check_button": "✅ Я подписался",
    "sub_success": "✅ Спасибо за подписку! Доступ открыт! 🎉",
    "sub_failed": "❌ Вы не подписались на все каналы!\n\n*Подпишитесь на:*",
    "check_again": "🔄 Проверить ещё раз",

    "referrals_text": """🦈 *SHARK BOT — Рефералы*

Твой прогресс: {refs}/{max_refs} [{bar}]

{status}

🔗 *Твоя ссылка:*
`{ref_link}`

💀 {max_refs} Рефералов = откроется возможность атак!""",

    "profile_text": """🦈 *SHARK BOT - Профиль*

👤 ID: `{user_id}`
👥 Рефералов: {refs}/{max_refs} [{bar}]
🎫 Подписка: {sub_status}
⚔️ Атак: {total_attacks}
💰 Потрачено: {total_spent} USDT""",

    "main_menu_text": """🦈 *SHARK BOT*

Привет, {username}! 

Выбери действие:""",

    "admin_panel_text": """⚙️ *Админ панель*

👥 Пользователей: {total_users}
💰 Оборот: {total_spent} USDT
📢 Каналов: {total_channels}
👑 Админов: {total_admins}""",

    "buy_menu_text": "💳 *Выбери тариф:*",
    
    "support_start": """🆘 *Поддержка*

Напиши своё сообщение, и админ ответит тебе как только сможет.

⚠️ Не пиши спам, не перепроси!""",
    
    "support_sent": "✅ Твое сообщение отправлено админу! Ответ придет сюда.",
    "support_error": "❌ Не удалось отправить. Попробуй позже.",
    
    "attack_start": """💀 *МЕНЮ АТАКИ*

Введи цель для сноса:
• @USERNAME
• ID (цифры)
• НОМЕР (+79...)

⚠️ Отправь сообщение с целью!""",

    "attack_cooldown": "⏳ Подождите {time}с до следующей атаки!",
    "attack_success": """💀 *Атака завершена!*

🎯 Цель: {target}
✅ Статус: Успешно
⚡️ Мощность: {power}%""",
    
    "access_denied": "🔒 Доступ закрыт! Нужна подписка или 5 рефералов.",
    "error_generic": "❌ Произошла ошибка. Попробуй позже.",
}

TARIFFS = [
    {"days": 1, "price": 0.5, "name": "1 день"},
    {"days": 3, "price": 1.0, "name": "3 дня"},
    {"days": 7, "price": 2.0, "name": "7 дней"},
    {"days": 30, "price": 4.0, "name": "30 дней"}
]

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def get_progress_bar(current: int, max_val: int = 5) -> str:
    """Создает прогресс-бар"""
    filled = min(current, max_val)
    return "█" * filled + "░" * (max_val - filled)

def get_sub_status(sub_end: Optional[str]) -> str:
    """Проверяет статус подписки"""
    if not sub_end:
        return "❌ Нет"
    try:
        if datetime.fromisoformat(sub_end) > datetime.now():
            return "✅ Активна"
    except (ValueError, TypeError):
        pass
    return "❌ Истекла"

def has_access(user_id: int) -> bool:
    """Проверяет доступ пользователя к функциям"""
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT sub_end, refs_count FROM users WHERE user_id=?", (user_id,))
            user = c.fetchone()
            
            if not user:
                return False
            
            sub_end_str, refs_count = user['sub_end'], user['refs_count']
            
            # Доступ если 5+ рефералов ИЛИ активная подписка
            if refs_count >= MAX_REFERRALS:
                return True
            
            if sub_end_str:
                try:
                    if datetime.fromisoformat(sub_end_str) > datetime.now():
                        return True
                except (ValueError, TypeError):
                    pass
            
            return False
    except Exception as e:
        logger.error(f"Ошибка проверки доступа: {e}")
        return False

def can_buy(user_id: int) -> bool:
    """Проверяет, может ли пользователь купить подписку"""
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT refs_count FROM users WHERE user_id=?", (user_id,))
            user = c.fetchone()
            return user is not None and user['refs_count'] >= MAX_REFERRALS
    except Exception as e:
        logger.error(f"Ошибка проверки возможности покупки: {e}")
        return False

def is_admin(user_id: int) -> bool:
    """Проверяет, является ли пользователь админом"""
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT user_id FROM admins WHERE user_id=?", (user_id,))
            return c.fetchone() is not None
    except Exception as e:
        logger.error(f"Ошибка проверки админа: {e}")
        return False

def get_or_create_user(user_id: int, username: str = "USER") -> bool:
    """Создает пользователя если его нет"""
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,))
            if c.fetchone():
                return True
            
            c.execute("""INSERT INTO users 
                         (user_id, username, refs_count, ref_bonus_applied, last_activity) 
                         VALUES (?, ?, 0, 0, ?)""",
                      (user_id, username, datetime.now().isoformat()))
            conn.commit()
            return True
    except Exception as e:
        logger.error(f"Ошибка создания пользователя: {e}")
        return False

def handle_errors(func):
    """Декоратор для обработки ошибок в обработчиках"""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            return await func(update, context)
        except Exception as e:
            logger.error(f"Ошибка в {func.__name__}: {e}", exc_info=True)
            try:
                if update.callback_query:
                    await update.callback_query.answer(TEXTS["error_generic"], show_alert=True)
                elif update.message:
                    await update.message.reply_text(TEXTS["error_generic"])
            except:
                pass
    return wrapper

# ========== КРИПТО-ПЛАТЕЖИ ==========
async def create_crypto_invoice(amount: float, description: str) -> Optional[Dict]:
    """Создает счет на оплату в Crypto Pay"""
    try:
        url = "https://pay.crypt.bot/api/createInvoice"
        headers = {
            "Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN,
            "Content-Type": "application/json"
        }
        data = {
            "asset": "USDT",
            "amount": str(amount),
            "description": description,
            "paid_btn_name": "callback",
            "paid_btn_url": "https://t.me/Sh4rkZnosBot",
            "expires_in": 900
        }
        
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=API_TIMEOUT)) as session:
            async with session.post(url, headers=headers, json=data) as response:
                if response.status == 200:
                    result = await response.json()
                    if result.get("ok") and result.get("result"):
                        return result["result"]
        
        logger.warning(f"Ошибка создания счета: статус {response.status}")
        return None
    except asyncio.TimeoutError:
        logger.error("Таймаут при создании счета")
        return None
    except Exception as e:
        logger.error(f"Ошибка Crypto Pay: {e}")
        return None

async def check_crypto_invoice(invoice_id: int) -> Optional[Dict]:
    """Проверяет статус счета"""
    try:
        url = "https://pay.crypt.bot/api/getInvoices"
        headers = {
            "Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN,
            "Content-Type": "application/json"
        }
        data = {"invoice_ids": str(invoice_id)}
        
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=API_TIMEOUT)) as session:
            async with session.post(url, headers=headers, json=data) as response:
                if response.status == 200:
                    result = await response.json()
                    if result.get("ok") and result.get("result", {}).get("items"):
                        return result["result"]["items"][0]
        
        return None
    except asyncio.TimeoutError:
        logger.error("Таймаут при проверке счета")
        return None
    except Exception as e:
        logger.error(f"Ошибка проверки счета: {e}")
        return None

# ========== ПРОВЕРКА ПОДПИСКИ ==========
async def check_subscription(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Проверяет подписку пользователя на каналы"""
    try:
        # Админ всегда имеет доступ
        if is_admin(user_id):
            return True
        
        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT channel_username, channel_id, channel_type FROM required_channels")
            channels = c.fetchall()
        
        if not channels:
            return True
        
        for channel in channels:
            channel_username = channel['channel_username']
            channel_id = channel['channel_id']
            channel_type = channel['channel_type']
            
            try:
                if channel_type == 'private' and channel_id:
                    try:
                        chat_member = await context.bot.get_chat_member(
                            chat_id=channel_id,
                            user_id=user_id
                        )
                        if chat_member.status in ['left', 'kicked', 'restricted']:
                            return False
                    except (TelegramError, BadRequest):
                        return False
                else:
                    if channel_username:
                        try:
                            username = channel_username.replace('@', '').strip()
                            chat_member = await context.bot.get_chat_member(
                                chat_id=f"@{username}",
                                user_id=user_id
                            )
                            if chat_member.status in ['left', 'kicked', 'restricted']:
                                return False
                        except (TelegramError, BadRequest):
                            return False
            except Exception as e:
                logger.warning(f"Ошибка проверки канала {channel_id}: {e}")
                return False
        
        return True
    except Exception as e:
        logger.error(f"Ошибка проверки подписки: {e}")
        return False

async def get_not_subscribed_channels(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> List[Dict]:
    """Получает список каналов, на которые не подписан пользователь"""
    not_subscribed = []
    
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute("""SELECT channel_username, channel_id, channel_name, 
                        channel_type, invite_link FROM required_channels""")
            channels = c.fetchall()
        
        for channel in channels:
            is_subscribed = False
            
            try:
                if channel['channel_type'] == 'private' and channel['channel_id']:
                    try:
                        chat_member = await context.bot.get_chat_member(
                            chat_id=channel['channel_id'],
                            user_id=user_id
                        )
                        if chat_member.status not in ['left', 'kicked', 'restricted']:
                            is_subscribed = True
                    except (TelegramError, BadRequest):
                        is_subscribed = False
                else:
                    if channel['channel_username']:
                        try:
                            username = channel['channel_username'].replace('@', '').strip()
                            chat_member = await context.bot.get_chat_member(
                                chat_id=f"@{username}",
                                user_id=user_id
                            )
                            if chat_member.status not in ['left', 'kicked', 'restricted']:
                                is_subscribed = True
                        except (TelegramError, BadRequest):
                            is_subscribed = False
                
                if not is_subscribed:
                    name = channel['channel_name'] or channel['channel_username'] or str(channel['channel_id'])
                    link = channel['invite_link']
                    
                    if not link:
                        if channel['channel_username']:
                            link = f"https://t.me/{channel['channel_username'].replace('@', '')}"
                        elif channel['channel_id']:
                            link = "#"
                    
                    if link and link != "#":
                        not_subscribed.append({'name': name, 'link': link})
            except Exception as e:
                logger.warning(f"Ошибка проверки канала: {e}")
        
        return not_subscribed
    except Exception as e:
        logger.error(f"Ошибка получения списка каналов: {e}")
        return []

# ========== КЛАВИАТУРЫ ==========
def get_main_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Главное меню"""
    access_granted = has_access(user_id)
    can_buy_sub = can_buy(user_id)
    
    keyboard = []
    
    if access_granted:
        keyboard.append([InlineKeyboardButton("💀 Атака", callback_data="attack_menu")])
    elif can_buy_sub:
        keyboard.append([InlineKeyboardButton("💀 Атака (купи подписку)", callback_data="attack_menu")])
    else:
        keyboard.append([InlineKeyboardButton("🔒 Атака (надо 5 реф)", callback_data="attack_menu")])
    
    if can_buy_sub:
        keyboard.append([InlineKeyboardButton("💳 Купить подписку", callback_data="buy_menu")])
    
    keyboard.extend([
        [
            InlineKeyboardButton("👥 Рефералы", callback_data="referrals"),
            InlineKeyboardButton("👤 Профиль", callback_data="profile")
        ],
        [InlineKeyboardButton("🆘 Поддержка", callback_data="support")]
    ])
    
    if is_admin(user_id):
        keyboard.append([InlineKeyboardButton("⚙️ Админка", callback_data="admin_panel")])
    
    return InlineKeyboardMarkup(keyboard)

def get_back_button(callback_data: str = "main_menu") -> InlineKeyboardMarkup:
    """Кнопка назад"""
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data=callback_data)]])

# ========== ОСНОВНЫЕ ОБРАБОТЧИКИ ==========
@handle_errors
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало работы с ботом"""
    user = update.effective_user
    user_id = user.id
    username = user.username or "USER"
    
    # Создаем пользователя если его нет
    get_or_create_user(user_id, username)
    
    # Проверяем реферальную ссылку
    if context.args and len(context.args) > 0:
        try:
            if context.args[0].startswith('ref_'):
                ref_id = int(context.args[0].split('_')[1])
                if ref_id != user_id:
                    with get_db() as conn:
                        c = conn.cursor()
                        c.execute("SELECT user_id FROM users WHERE user_id=?", (ref_id,))
                        if c.fetchone():
                            # Проверяем не применен ли уже бонус
                            c.execute("SELECT ref_bonus_applied FROM users WHERE user_id=?", (user_id,))
                            if not c.fetchone()['ref_bonus_applied']:
                                c.execute("UPDATE users SET ref_id=? WHERE user_id=?", (ref_id, user_id))
                                c.execute("UPDATE users SET refs_count = refs_count + 1 WHERE user_id=?", (ref_id,))
                                c.execute("UPDATE users SET ref_bonus_applied=1 WHERE user_id=?", (user_id,))
                                conn.commit()
                                
                                logger.info(f"Новый реферал {user_id} через {ref_id}")
                                try:
                                    await context.bot.send_message(
                                        chat_id=ref_id,
                                        text=f"🦈 *Новый реферал!*\n\n👤 {username}\n🆔 {user_id}",
                                        parse_mode="Markdown"
                                    )
                                except:
                                    pass
        except (ValueError, IndexError):
            pass
    
    # Проверяем подписку
    not_subscribed = await get_not_subscribed_channels(user_id, context)
    
    if not_subscribed:
        text = TEXTS["start_sub_required"]
        keyboard = []
        
        for ch in not_subscribed:
            text += f"\n• {ch['name']}"
            keyboard.append([InlineKeyboardButton(f"📢 {ch['name']}", url=ch['link'])])
        
        keyboard.append([InlineKeyboardButton(TEXTS["sub_check_button"], callback_data="check_sub")])
        
        if update.message:
            await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        else:
            await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    else:
        text = TEXTS["main_menu_text"].format(username=username)
        
        if update.message:
            await update.message.reply_text(text, reply_markup=get_main_keyboard(user_id), parse_mode="Markdown")
        else:
            await update.callback_query.edit_message_text(text, reply_markup=get_main_keyboard(user_id), parse_mode="Markdown")

@handle_errors
async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Главное меню"""
    query = update.callback_query
    user_id = query.from_user.id
    username = query.from_user.username or "USER"
    await query.answer()
    
    # Очищаем состояние
    context.user_data.pop('awaiting_target', None)
    context.user_data.pop('awaiting_support', None)
    context.user_data.pop('awaiting_channel', None)
    context.user_data.pop('awaiting_admin', None)
    
    # Проверяем подписку
    if not await check_subscription(user_id, context):
        not_subscribed = await get_not_subscribed_channels(user_id, context)
        text = TEXTS["sub_failed"]
        keyboard = []
        
        for ch in not_subscribed:
            text += f"\n• {ch['name']}"
            keyboard.append([InlineKeyboardButton(f"📢 {ch['name']}", url=ch['link'])])
        
        keyboard.append([InlineKeyboardButton(TEXTS["check_again"], callback_data="check_sub")])
        
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return
    
    text = TEXTS["main_menu_text"].format(username=username)
    await query.edit_message_text(text, reply_markup=get_main_keyboard(user_id), parse_mode="Markdown")

@handle_errors
async def check_subscription_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверка подписки"""
    query = update.callback_query
    user_id = query.from_user.id
    username = query.from_user.username or "USER"
    await query.answer()
    
    if await check_subscription(user_id, context):
        text = TEXTS["sub_success"]
        await query.edit_message_text(text, reply_markup=get_main_keyboard(user_id), parse_mode="Markdown")
    else:
        not_subscribed = await get_not_subscribed_channels(user_id, context)
        text = TEXTS["sub_failed"]
        keyboard = []
        
        for ch in not_subscribed:
            text += f"\n• {ch['name']}"
            keyboard.append([InlineKeyboardButton(f"📢 {ch['name']}", url=ch['link'])])
        
        keyboard.append([InlineKeyboardButton(TEXTS["check_again"], callback_data="check_sub")])
        
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ========== ПРОФИЛЬ И РЕФЕРАЛЫ ==========
@handle_errors
async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Профиль пользователя"""
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute("""SELECT refs_count, sub_end, total_attacks, total_spent 
                        FROM users WHERE user_id=?""", (user_id,))
            user = c.fetchone()
        
        if not user:
            await query.edit_message_text("❌ Пользователь не найден.", reply_markup=get_back_button(), parse_mode="Markdown")
            return
        
        refs_count = user['refs_count']
        bar = get_progress_bar(refs_count, MAX_REFERRALS)
        sub_status = get_sub_status(user['sub_end'])
        
        text = TEXTS["profile_text"].format(
            user_id=user_id,
            refs=refs_count,
            max_refs=MAX_REFERRALS,
            bar=bar,
            sub_status=sub_status,
            total_attacks=user['total_attacks'],
            total_spent=round(user['total_spent'], 2)
        )
        
        await query.edit_message_text(text, reply_markup=get_back_button(), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Ошибка профиля: {e}")
        await query.edit_message_text(TEXTS["error_generic"], reply_markup=get_back_button(), parse_mode="Markdown")

@handle_errors
async def referrals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Реферальная программа"""
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT refs_count FROM users WHERE user_id=?", (user_id,))
            user = c.fetchone()
        
        if not user:
            await query.edit_message_text("❌ Пользователь не найден.", reply_markup=get_back_button(), parse_mode="Markdown")
            return
        
        refs_count = user['refs_count']
        ref_link = f"https://t.me/{context.bot.username}?start=ref_{user_id}"
        bar = get_progress_bar(refs_count, MAX_REFERRALS)
        
        if refs_count >= MAX_REFERRALS:
            status = "✅ Рефералы собраны! Можно снощить!"
        else:
            left = MAX_REFERRALS - refs_count
            status = f"❌ Осталось набрать {left} рефералов"
        
        text = TEXTS["referrals_text"].format(
            refs=refs_count,
            max_refs=MAX_REFERRALS,
            bar=bar,
            status=status,
            ref_link=ref_link
        )
        
        keyboard = [
            [InlineKeyboardButton("📋 Копировать ссылку", callback_data=f"copy_ref_{user_id}")],
            [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
        ]
        
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Ошибка рефералов: {e}")
        await query.edit_message_text(TEXTS["error_generic"], reply_markup=get_back_button(), parse_mode="Markdown")

@handle_errors
async def copy_ref_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Копирование реферальной ссылки"""
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    
    ref_link = f"https://t.me/{context.bot.username}?start=ref_{user_id}"
    await query.message.reply_text(f"🔗 *Твоя реферальная ссылка:*\n`{ref_link}`", parse_mode="Markdown")

# ========== АТАКА ==========
attack_cooldown = {}

@handle_errors
async def attack_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню атаки"""
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT refs_count FROM users WHERE user_id=?", (user_id,))
            user = c.fetchone()
        
        refs_count = user['refs_count'] if user else 0
        
        if refs_count < MAX_REFERRALS and not is_admin(user_id):
            msg = f"❌ Нужно {MAX_REFERRALS} рефералов! Сейчас: {refs_count}/{MAX_REFERRALS}"
            await query.edit_message_text(msg, reply_markup=get_back_button(), parse_mode="Markdown")
            return
        
        if not has_access(user_id) and not is_admin(user_id):
            await query.edit_message_text(TEXTS["access_denied"], reply_markup=get_back_button(), parse_mode="Markdown")
            return
        
        context.user_data['awaiting_target'] = True
        await query.edit_message_text(TEXTS["attack_start"], reply_markup=get_back_button(), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Ошибка меню атаки: {e}")
        await query.edit_message_text(TEXTS["error_generic"], reply_markup=get_back_button(), parse_mode="Markdown")

@handle_errors
async def handle_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка целей для атаки"""
    user_id = update.effective_user.id
    
    if not context.user_data.get('awaiting_target'):
        return
    
    # Проверка cooldown
    if user_id in attack_cooldown:
        time_passed = (datetime.now() - attack_cooldown[user_id]).total_seconds()
        if time_passed < ATTACK_COOLDOWN:
            await update.message.reply_text(
                TEXTS["attack_cooldown"].format(time=int(ATTACK_COOLDOWN - time_passed)),
                parse_mode="Markdown"
            )
            return
    
    attack_cooldown[user_id] = datetime.now()
    context.user_data['awaiting_target'] = False
    
    if not has_access(user_id) and not is_admin(user_id):
        await update.message.reply_text(TEXTS["access_denied"], reply_markup=get_main_keyboard(user_id), parse_mode="Markdown")
        return
    
    target = update.message.text.strip()
    if not target or len(target) < 2:
        await update.message.reply_text("❌ Неверная цель!", reply_markup=get_main_keyboard(user_id), parse_mode="Markdown")
        return
    
    msg = await update.message.reply_text("🔍 Поиск цели...")
    
    try:
        await asyncio.sleep(1)
        await msg.edit_text("⚡️ Запуск атаки...")
        await asyncio.sleep(1.5)
        await msg.edit_text("💣 Взлом защиты...")
        await asyncio.sleep(1.5)
        await msg.edit_text("🔥 Сноса...")
        await asyncio.sleep(1)
        
        # Обновляем статистику
        with get_db() as conn:
            c = conn.cursor()
            c.execute("UPDATE users SET total_attacks = total_attacks + 1 WHERE user_id=?", (user_id,))
            conn.commit()
        
        power = random.randint(50, 150)
        text = TEXTS["attack_success"].format(target=target, power=power)
        
        await msg.edit_text(text, reply_markup=get_main_keyboard(user_id), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Ошибка атаки: {e}")
        await msg.edit_text(TEXTS["error_generic"], reply_markup=get_main_keyboard(user_id), parse_mode="Markdown")

# ========== ПОДДЕРЖКА ==========
@handle_errors
async def support_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало поддержки"""
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    
    context.user_data.pop('awaiting_target', None)
    context.user_data.pop('awaiting_channel', None)
    context.user_data.pop('awaiting_admin', None)
    context.user_data['awaiting_support'] = True
    
    await query.edit_message_text(TEXTS["support_start"], reply_markup=get_back_button(), parse_mode="Markdown")

@handle_errors
async def handle_support_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка сообщения поддержки"""
    user_id = update.effective_user.id
    username = update.effective_user.username or "USER"
    msg_text = update.message.text.strip()
    
    if not context.user_data.get('awaiting_support'):
        return
    
    context.user_data['awaiting_support'] = False
    
    if len(msg_text) < 3:
        await update.message.reply_text("❌ Сообщение слишком короткое!", reply_markup=get_main_keyboard(user_id), parse_mode="Markdown")
        return
    
    forward_text = f"""🆘 *НОВОЕ СООБЩЕНИЕ ОТ ПОЛЬЗОВАТЕЛЯ*

👤 ID: `{user_id}`
👤 Username: @{username}

💬 *Сообщение:*
{msg_text}

📌 Чтобы ответить - отправь сообщение в ответ на это (Reply)"""
    
    try:
        await context.bot.send_message(chat_id=OWNER_ID, text=forward_text, parse_mode="Markdown")
        await update.message.reply_text(TEXTS["support_sent"], reply_markup=get_main_keyboard(user_id), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Ошибка поддержки: {e}")
        await update.message.reply_text(TEXTS["support_error"], reply_markup=get_main_keyboard(user_id), parse_mode="Markdown")

@handle_errors
async def handle_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ответ админа на сообщение поддержки"""
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        return
    
    if update.message.reply_to_message:
        reply_text = update.message.text
        original = update.message.reply_to_message.text
        
        match = re.search(r"👤 ID: `(\d+)`", original)
        if match:
            target_user_id = int(match.group(1))
            try:
                await context.bot.send_message(
                    chat_id=target_user_id,
                    text=f"🆘 *Ответ админа:*\n\n{reply_text}",
                    parse_mode="Markdown"
                )
                await update.message.reply_text("✅ Ответ отправлен!", parse_mode="Markdown")
            except Exception as e:
                logger.error(f"Ошибка ответа админа: {e}")
                await update.message.reply_text("❌ Не удалось отправить.", parse_mode="Markdown")

# ========== ПОКУПКА ==========
@handle_errors
async def buy_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню покупки подписки"""
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    
    if not can_buy(user_id):
        await query.edit_message_text("❌ Для покупки нужно 5 рефералов!", reply_markup=get_back_button(), parse_mode="Markdown")
        return
    
    keyboard = []
    for tariff in TARIFFS:
        keyboard.append([
            InlineKeyboardButton(
                f"{tariff['name']} - {tariff['price']} USDT",
                callback_data=f"buy_tariff_{tariff['days']}"
            )
        ])
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="main_menu")])
    
    await query.edit_message_text(TEXTS["buy_menu_text"], reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

@handle_errors
async def buy_tariff(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Покупка тарифа"""
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    
    try:
        days = int(query.data.split('_')[2])
    except (IndexError, ValueError):
        await query.edit_message_text(TEXTS["error_generic"], reply_markup=get_back_button(), parse_mode="Markdown")
        return
    
    tariff = next((t for t in TARIFFS if t['days'] == days), None)
    if not tariff:
        await query.edit_message_text("❌ Тариф не найден.", reply_markup=get_back_button(), parse_mode="Markdown")
        return
    
    invoice = await create_crypto_invoice(tariff['price'], f"SHARK BOT - {tariff['name']}")
    if not invoice:
        await query.edit_message_text("❌ Ошибка создания счета.", reply_markup=get_back_button(), parse_mode="Markdown")
        return
    
    invoice_id = str(invoice['invoice_id'])
    
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute("""INSERT OR REPLACE INTO invoices 
                        (invoice_id, user_id, amount, tariff_days, created_at, expires_at) 
                        VALUES (?, ?, ?, ?, ?, ?)""",
                      (invoice_id, user_id, tariff['price'], days,
                       datetime.now().isoformat(),
                       (datetime.now() + timedelta(minutes=15)).isoformat()))
            conn.commit()
    except Exception as e:
        logger.error(f"Ошибка сохранения счета: {e}")
        await query.edit_message_text(TEXTS["error_generic"], reply_markup=get_back_button(), parse_mode="Markdown")
        return
    
    text = f"""🦈 *Счет на {tariff['price']} USDT*

🔗 [Ссылка на оплату]({invoice['pay_url']})

⏳ Время: 15 минут"""
    
    keyboard = [
        [InlineKeyboardButton("✅ Проверить оплату", callback_data=f"check_payment_{invoice_id}")],
        [InlineKeyboardButton("🔙 Назад", callback_data="buy_menu")]
    ]
    
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

@handle_errors
async def check_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверка оплаты"""
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer("🔍 Проверяю...")
    
    try:
        invoice_id = query.data.split('_')[2]
    except IndexError:
        await query.answer(TEXTS["error_generic"], show_alert=True)
        return
    
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute("""SELECT tariff_days, status, expires_at FROM invoices 
                        WHERE invoice_id=? AND user_id=?""", (invoice_id, user_id))
            invoice_data = c.fetchone()
        
        if not invoice_data:
            await query.answer("❌ Счет не найден!", show_alert=True)
            return
        
        days, local_status, expires_at = invoice_data['tariff_days'], invoice_data['status'], invoice_data['expires_at']
        
        if local_status == 'paid':
            await query.answer("❌ Счет уже оплачен!", show_alert=True)
            return
        
        # Проверяем не истек ли срок
        try:
            if datetime.fromisoformat(expires_at) < datetime.now():
                await query.answer("❌ Счет истек!", show_alert=True)
                return
        except:
            pass
    except Exception as e:
        logger.error(f"Ошибка получения счета: {e}")
        await query.answer(TEXTS["error_generic"], show_alert=True)
        return
    
    # Проверяем статус платежа
    invoice_status = await check_crypto_invoice(int(invoice_id))
    
    if not invoice_status:
        await query.answer("❌ Ошибка проверки статуса.", show_alert=True)
        return
    
    if invoice_status.get('status') == 'paid':
        try:
            with get_db() as conn:
                c = conn.cursor()
                
                new_sub_end = (datetime.now() + timedelta(days=days)).isoformat()
                
                c.execute("SELECT sub_end FROM users WHERE user_id=?", (user_id,))
                user = c.fetchone()
                if user and user['sub_end']:
                    try:
                        current_sub_end = datetime.fromisoformat(user['sub_end'])
                        if current_sub_end > datetime.now():
                            new_sub_end = (current_sub_end + timedelta(days=days)).isoformat()
                    except:
                        pass
                
                amount = invoice_status.get('amount', invoice_status.get('usd_amount', days))
                c.execute("""UPDATE users SET sub_end=?, total_spent = total_spent + ? 
                            WHERE user_id=?""",
                          (new_sub_end, amount, user_id))
                c.execute("UPDATE invoices SET status='paid' WHERE invoice_id=?", (invoice_id,))
                conn.commit()
            
            await query.edit_message_text(
                f"✅ *Оплата прошла!*\n\nПодписка активирована на {days} дней!",
                reply_markup=get_main_keyboard(user_id),
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Ошибка обновления подписки: {e}")
            await query.answer("❌ Ошибка обновления подписки.", show_alert=True)
    else:
        await query.answer("❌ Оплата не прошла.", show_alert=True)

# ========== АДМИНКА ==========
@handle_errors
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Админ панель"""
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    
    if not is_admin(user_id):
        await query.edit_message_text("❌ Доступ закрыт!", reply_markup=get_back_button(), parse_mode="Markdown")
        return
    
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) as count FROM users")
            total_users = c.fetchone()['count']
            
            c.execute("SELECT COALESCE(SUM(total_spent), 0) as total FROM users")
            total_spent = c.fetchone()['total']
            
            c.execute("SELECT COUNT(*) as count FROM required_channels")
            total_channels = c.fetchone()['count']
            
            c.execute("SELECT COUNT(*) as count FROM admins")
            total_admins = c.fetchone()['count']
        
        text = TEXTS["admin_panel_text"].format(
            total_users=total_users,
            total_spent=round(total_spent, 2),
            total_channels=total_channels,
            total_admins=total_admins
        )
        
        keyboard = [
            [InlineKeyboardButton("📢 Каналы", callback_data="admin_channels")],
            [InlineKeyboardButton("👑 Админы", callback_data="admin_admins")],
            [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")],
            [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
        ]
        
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Ошибка админ панели: {e}")
        await query.edit_message_text(TEXTS["error_generic"], reply_markup=get_back_button(), parse_mode="Markdown")

@handle_errors
async def admin_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Управление каналами"""
    query = update.callback_query
    await query.answer()
    
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute("""SELECT id, channel_username, channel_name, channel_type 
                        FROM required_channels""")
            channels = c.fetchall()
        
        if channels:
            channels_list = "\n".join([
                f"#{ch['id']} {ch['channel_name'] or ch['channel_username']} "
                f"({'🔒 Закрыт' if ch['channel_type'] == 'private' else '🌐 Открыт'})"
                for ch in channels
            ])
        else:
            channels_list = "Нет каналов"
        
        text = f"📢 *Каналы для подписки:*\n\n{channels_list}"
        
        keyboard = [
            [InlineKeyboardButton("➕ Открытый канал", callback_data="admin_add_public")],
            [InlineKeyboardButton("➕ Закрытый канал", callback_data="admin_add_private")],
            [InlineKeyboardButton("➖ Удалить", callback_data="admin_remove_channel")],
            [InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")]
        ]
        
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Ошибка управления каналами: {e}")
        await query.edit_message_text(TEXTS["error_generic"], reply_markup=get_back_button(), parse_mode="Markdown")

@handle_errors
async def admin_add_public_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Добавление открытого канала"""
    query = update.callback_query
    await query.answer()
    context.user_data['awaiting_channel'] = 'public'
    
    await query.edit_message_text(
        "📢 *Отправьте username канала:*\n\nПример: `sharkbot`",
        reply_markup=get_back_button("admin_channels"),
        parse_mode="Markdown"
    )

@handle_errors
async def admin_add_private_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Добавление закрытого канала"""
    query = update.callback_query
    await query.answer()
    context.user_data['awaiting_channel'] = 'private_id'
    
    await query.edit_message_text(
        "🔒 *Отправьте ID канала:*\n\nПолучить ID: перешлите сообщение из канала @userinfobot",
        reply_markup=get_back_button("admin_channels"),
        parse_mode="Markdown"
    )

@handle_errors
async def admin_remove_channel_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удаление канала"""
    query = update.callback_query
    await query.answer()
    
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT id, channel_name, channel_username FROM required_channels")
            channels = c.fetchall()
        
        if not channels:
            await query.edit_message_text(
                "❌ Нет каналов.",
                reply_markup=get_back_button("admin_channels"),
                parse_mode="Markdown"
            )
            return
        
        context.user_data['awaiting_channel'] = 'remove'
        text = "Введите ID канала:\n\n"
        text += "\n".join([f"#{ch['id']} - {ch['channel_name'] or ch['channel_username']}" for ch in channels])
        
        await query.edit_message_text(text, reply_markup=get_back_button("admin_channels"), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Ошибка удаления канала: {e}")
        await query.edit_message_text(TEXTS["error_generic"], reply_markup=get_back_button("admin_channels"), parse_mode="Markdown")

@handle_errors
async def admin_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Управление админами"""
    query = update.callback_query
    await query.answer()
    
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT user_id FROM admins ORDER BY user_id")
            admins = c.fetchall()
        
        admins_list = "\n".join([f"• `{ad['user_id']}`" for ad in admins])
        text = f"👑 *Админы:*\n\n{admins_list}"
        
        keyboard = [
            [InlineKeyboardButton("➕ Добавить", callback_data="admin_add_admin")],
            [InlineKeyboardButton("➖ Удалить", callback_data="admin_remove_admin")],
            [InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")]
        ]
        
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Ошибка управления админами: {e}")
        await query.edit_message_text(TEXTS["error_generic"], reply_markup=get_back_button(), parse_mode="Markdown")

@handle_errors
async def admin_add_admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Добавление админа"""
    query = update.callback_query
    await query.answer()
    context.user_data['awaiting_admin'] = 'add'
    
    await query.edit_message_text(
        "👑 *Отправьте ID нового админа:*",
        reply_markup=get_back_button("admin_admins"),
        parse_mode="Markdown"
    )

@handle_errors
async def admin_remove_admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удаление админа"""
    query = update.callback_query
    await query.answer()
    
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT user_id FROM admins ORDER BY user_id")
            admins = c.fetchall()
        
        context.user_data['awaiting_admin'] = 'remove'
        text = "Введите ID админа:\n\n"
        text += "\n".join([f"• `{ad['user_id']}`" for ad in admins])
        text += f"\n\n⚠️ Владельца (`{OWNER_ID}`) удалить нельзя!"
        
        await query.edit_message_text(text, reply_markup=get_back_button("admin_admins"), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Ошибка удаления админа: {e}")
        await query.edit_message_text(TEXTS["error_generic"], reply_markup=get_back_button("admin_admins"), parse_mode="Markdown")

@handle_errors
async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Статистика"""
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    
    if not is_admin(user_id):
        await query.edit_message_text("❌ Доступ закрыт!", reply_markup=get_back_button(), parse_mode="Markdown")
        return
    
    try:
        with get_db() as conn:
            c = conn.cursor()
            
            c.execute("SELECT COUNT(*) as count FROM users")
            total_users = c.fetchone()['count']
            
            c.execute("SELECT COALESCE(SUM(total_spent), 0) as total FROM users")
            total_spent = c.fetchone()['total']
            
            c.execute("SELECT COALESCE(SUM(total_attacks), 0) as total FROM users")
            total_attacks = c.fetchone()['total']
            
            c.execute("""SELECT COUNT(*) as count FROM users 
                        WHERE sub_end IS NOT NULL AND sub_end > datetime('now')""")
            active_subs = c.fetchone()['count']
            
            c.execute("SELECT COUNT(*) as count FROM users WHERE refs_count >= ?", (MAX_REFERRALS,))
            ready_for_attack = c.fetchone()['count']
        
        text = f"""📊 *СТАТИСТИКА*

👥 Пользователей: {total_users}
💎 Активных подписок: {active_subs}
⚔️ Готовых к атаке: {ready_for_attack}
💰 Оборот: {round(total_spent, 2)} USDT
🎯 Всего атак: {total_attacks}"""
        
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Ошибка статистики: {e}")
        await query.edit_message_text(TEXTS["error_generic"], reply_markup=get_back_button(), parse_mode="Markdown")

# ========== ОБРАБОТКА ТЕКСТОВЫХ КОМАНД ==========
@handle_errors
async def handle_admin_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка вводов админа"""
    user_id = update.effective_user.id
    msg = update.message.text.strip()
    
    if not is_admin(user_id):
        return
    
    # ===== ДОБАВЛЕНИЕ ОТКРЫТОГО КАНАЛА =====
    if context.user_data.get('awaiting_channel') == 'public':
        try:
            clean_username = msg.replace('@', '').strip()
            chat = await context.bot.get_chat(f"@{clean_username}")
            
            with get_db() as conn:
                c = conn.cursor()
                c.execute("""INSERT OR IGNORE INTO required_channels 
                            (channel_username, channel_id, channel_name, channel_type, added_by, added_date) 
                            VALUES (?, ?, ?, 'public', ?, ?)""",
                          (clean_username, chat.id, chat.title, user_id, datetime.now().isoformat()))
                conn.commit()
            
            await update.message.reply_text(
                f"✅ Канал *{chat.title}* добавлен!",
                reply_markup=get_back_button("admin_channels"),
                parse_mode="Markdown"
            )
        except BadRequest:
            await update.message.reply_text(
                "❌ Канал не найден.",
                reply_markup=get_back_button("admin_channels"),
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Ошибка добавления канала: {e}")
            await update.message.reply_text(
                f"❌ Ошибка: {str(e)[:50]}",
                reply_markup=get_back_button("admin_channels"),
                parse_mode="Markdown"
            )
        finally:
            context.user_data.pop('awaiting_channel', None)
    
    # ===== ДОБАВЛЕНИЕ ЗАКРЫТОГО КАНАЛА (ID) =====
    elif context.user_data.get('awaiting_channel') == 'private_id':
        try:
            channel_id = int(msg)
            context.user_data['private_channel_id'] = channel_id
            context.user_data['awaiting_channel'] = 'private_link'
            
            await update.message.reply_text(
                "🔗 *Отправьте ссылку-приглашение:*",
                reply_markup=get_back_button("admin_channels"),
                parse_mode="Markdown"
            )
        except ValueError:
            await update.message.reply_text(
                "❌ Неверный формат ID.",
                reply_markup=get_back_button("admin_channels"),
                parse_mode="Markdown"
            )
    
    # ===== ДОБАВЛЕНИЕ ЗАКРЫТОГО КАНАЛА (ССЫЛКА) =====
    elif context.user_data.get('awaiting_channel') == 'private_link':
        try:
            channel_id = context.user_data.get('private_channel_id')
            invite_link = msg.strip()
            chat = await context.bot.get_chat(channel_id)
            
            with get_db() as conn:
                c = conn.cursor()
                c.execute("""INSERT OR IGNORE INTO required_channels 
                            (channel_id, channel_name, channel_type, invite_link, added_by, added_date) 
                            VALUES (?, ?, 'private', ?, ?, ?)""",
                          (channel_id, chat.title, invite_link, user_id, datetime.now().isoformat()))
                conn.commit()
            
            await update.message.reply_text(
                f"✅ Канал *{chat.title}* добавлен!",
                reply_markup=get_back_button("admin_channels"),
                parse_mode="Markdown"
            )
        except BadRequest:
            await update.message.reply_text(
                "❌ Канал не найден.",
                reply_markup=get_back_button("admin_channels"),
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Ошибка добавления закрытого канала: {e}")
            await update.message.reply_text(
                f"❌ Ошибка: {str(e)[:50]}",
                reply_markup=get_back_button("admin_channels"),
                parse_mode="Markdown"
            )
        finally:
            context.user_data.pop('awaiting_channel', None)
            context.user_data.pop('private_channel_id', None)
    
    # ===== УДАЛЕНИЕ КАНАЛА =====
    elif context.user_data.get('awaiting_channel') == 'remove':
        try:
            channel_id = int(msg)
            with get_db() as conn:
                c = conn.cursor()
                c.execute("DELETE FROM required_channels WHERE id=?", (channel_id,))
                if c.rowcount > 0:
                    conn.commit()
                    await update.message.reply_text(
                        f"✅ Канал #{channel_id} удален!",
                        reply_markup=get_back_button("admin_channels"),
                        parse_mode="Markdown"
                    )
                else:
                    await update.message.reply_text(
                        "❌ Канал не найден.",
                        reply_markup=get_back_button("admin_channels"),
                        parse_mode="Markdown"
                    )
        except ValueError:
            await update.message.reply_text(
                "❌ Неверный формат ID.",
                reply_markup=get_back_button("admin_channels"),
                parse_mode="Markdown"
            )
        finally:
            context.user_data.pop('awaiting_channel', None)
    
    # ===== ДОБАВЛЕНИЕ АДМИНА =====
    elif context.user_data.get('awaiting_admin') == 'add':
        try:
            new_admin = int(msg)
            with get_db() as conn:
                c = conn.cursor()
                c.execute("INSERT OR IGNORE INTO admins VALUES (?, ?, ?)",
                          (new_admin, user_id, datetime.now().isoformat()))
                conn.commit()
            
            await update.message.reply_text(
                f"✅ Админ `{new_admin}` добавлен!",
                reply_markup=get_back_button("admin_admins"),
                parse_mode="Markdown"
            )
        except ValueError:
            await update.message.reply_text(
                "❌ Неверный ID.",
                reply_markup=get_back_button("admin_admins"),
                parse_mode="Markdown"
            )
        finally:
            context.user_data.pop('awaiting_admin', None)
    
    # ===== УДАЛЕНИЕ АДМИНА =====
    elif context.user_data.get('awaiting_admin') == 'remove':
        try:
            admin_id = int(msg)
            if admin_id == OWNER_ID:
                await update.message.reply_text(
                    "❌ Нельзя удалить владельца!",
                    reply_markup=get_back_button("admin_admins"),
                    parse_mode="Markdown"
                )
            else:
                with get_db() as conn:
                    c = conn.cursor()
                    c.execute("DELETE FROM admins WHERE user_id=?", (admin_id,))
                    if c.rowcount > 0:
                        conn.commit()
                        await update.message.reply_text(
                            f"✅ Админ `{admin_id}` удален!",
                            reply_markup=get_back_button("admin_admins"),
                            parse_mode="Markdown"
                        )
                    else:
                        await update.message.reply_text(
                            "❌ Админ не найден.",
                            reply_markup=get_back_button("admin_admins"),
                            parse_mode="Markdown"
                        )
        except ValueError:
            await update.message.reply_text(
                "❌ Неверный ID.",
                reply_markup=get_back_button("admin_admins"),
                parse_mode="Markdown"
            )
        finally:
            context.user_data.pop('awaiting_admin', None)

# ========== ГЛАВНЫЙ РОУТЕР ТЕКСТОВЫХ СООБЩЕНИЙ ==========
@handle_errors
async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Маршрутизация текстовых сообщений"""
    user_id = update.effective_user.id
    
    # Проверяем ответ админа
    if update.message.reply_to_message:
        await handle_admin_reply(update, context)
        return
    
    # Проверяем вводы админа
    if is_admin(user_id) and context.user_data.get('awaiting_channel'):
        await handle_admin_input(update, context)
        return
    
    if is_admin(user_id) and context.user_data.get('awaiting_admin'):
        await handle_admin_input(update, context)
        return
    
    # Проверяем поддержку
    if context.user_data.get('awaiting_support'):
        await handle_support_message(update, context)
        return
    
    # Проверяем атаку
    if context.user_data.get('awaiting_target'):
        await handle_target(update, context)

# ========== ЗАПУСК БОТА ==========
def main():
    """Главная функция запуска"""
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Команды
    application.add_handler(CommandHandler("start", start))
    
    # Callback обработчики - ПРАВИЛЬНЫЙ ПОРЯДОК (от специфичных к общим)
    application.add_handler(CallbackQueryHandler(check_subscription_callback, pattern="^check_sub$"))
    application.add_handler(CallbackQueryHandler(main_menu, pattern="^main_menu$"))
    application.add_handler(CallbackQueryHandler(profile, pattern="^profile$"))
    application.add_handler(CallbackQueryHandler(referrals, pattern="^referrals$"))
    application.add_handler(CallbackQueryHandler(copy_ref_callback, pattern="^copy_ref_\\d+$"))
    application.add_handler(CallbackQueryHandler(attack_menu, pattern="^attack_menu$"))
    application.add_handler(CallbackQueryHandler(support_start, pattern="^support$"))
    application.add_handler(CallbackQueryHandler(buy_menu, pattern="^buy_menu$"))
    application.add_handler(CallbackQueryHandler(buy_tariff, pattern="^buy_tariff_\\d+$"))
    application.add_handler(CallbackQueryHandler(check_payment, pattern="^check_payment_\\d+$"))
    
    # Админка
    application.add_handler(CallbackQueryHandler(admin_panel, pattern="^admin_panel$"))
    application.add_handler(CallbackQueryHandler(admin_channels, pattern="^admin_channels$"))
    application.add_handler(CallbackQueryHandler(admin_add_public_start, pattern="^admin_add_public$"))
    application.add_handler(CallbackQueryHandler(admin_add_private_start, pattern="^admin_add_private$"))
    application.add_handler(CallbackQueryHandler(admin_remove_channel_start, pattern="^admin_remove_channel$"))
    application.add_handler(CallbackQueryHandler(admin_admins, pattern="^admin_admins$"))
    application.add_handler(CallbackQueryHandler(admin_add_admin_start, pattern="^admin_add_admin$"))
    application.add_handler(CallbackQueryHandler(admin_remove_admin_start, pattern="^admin_remove_admin$"))
    application.add_handler(CallbackQueryHandler(admin_stats, pattern="^admin_stats$"))
    
    # Текстовые сообщения
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))
    
    logger.info("🤖 Бот SHARK BOT запущен успешно!")
    logger.info(f"👑 Владелец: {OWNER_ID}")
    logger.info(f"📊 БД: {DB_NAME}")
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()