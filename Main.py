import sqlite3
import random
import logging
import asyncio
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
import aiohttp

# ---------- НАСТРОЙКИ ----------
BOT_TOKEN = "8121327318:AAG1AR-_ZjV0ByuRHGQAO0NVUaGiMYTOZJw"
CRYPTO_BOT_TOKEN = "588369:AAKj4nTSnSQQa4IJwchTa3mCGp0SUWVsxdk"
OWNER_ID = 123456789  # ЗАМЕНИ НА СВОЙ ID

# ---------- ЛОГИРОВАНИЕ ----------
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------- БАЗА ДАННЫХ ----------
DB_NAME = 'sh4rk_zn0s.db'

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (user_id INTEGER PRIMARY KEY, username TEXT, ref_id INTEGER, refs_count INTEGER DEFAULT 0, 
                  balance REAL DEFAULT 0, sub_end TEXT, total_attacks INTEGER DEFAULT 0, total_spent REAL DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS required_channels (channel_username TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY)''')
    c.execute('''CREATE TABLE IF NOT EXISTS invoices (invoice_id TEXT, user_id INTEGER, amount REAL, 
                 tariff_days INTEGER, status TEXT DEFAULT 'pending', created_at TEXT)''')
    c.execute("INSERT OR IGNORE INTO admins VALUES (?)", (OWNER_ID,))
    conn.commit()
    conn.close()

init_db()

# ---------- ПЕРЕМЕШИВАНИЕ ТЕКСТА (ЧИТАЕМЫЙ ВАРИАНТ) ----------
REPLACEMENTS = {
    'А': 'A', 'а': 'a',
    'В': 'B', 'в': 'b',
    'Е': 'E', 'е': 'e',
    'З': '3', 'з': '3',
    'К': 'K', 'к': 'k',
    'М': 'M', 'м': 'm',
    'Н': 'H', 'н': 'h',
    'О': 'O', 'о': 'o',
    'Р': 'P', 'р': 'p',
    'С': 'C', 'с': 'c',
    'Т': 'T', 'т': 't',
    'У': 'Y', 'у': 'y',
    'Х': 'X', 'х': 'x',
    'Ч': '4', 'ч': '4',
    'Ь': 'b', 'ь': 'b',
    'Ы': 'bl', 'ы': 'bl',
    'Я': 'R', 'я': 'r',
    'Д': 'D', 'д': 'd',
    'Ж': 'X', 'ж': 'x',
    'И': 'U', 'и': 'u',
    'Й': 'U', 'й': 'u',
    'Л': 'L', 'л': 'l',
    'П': 'N', 'п': 'n',
    'Ф': 'F', 'ф': 'f',
    'Ц': 'U', 'ц': 'u',
    'Ш': 'W', 'ш': 'w',
    'Щ': 'W', 'щ': 'w',
    'Ъ': 'b', 'ъ': 'b',
    'Э': 'E', 'э': 'e',
    'Ю': 'U', 'ю': 'u',
}

def S(text):
    """Перемешивает текст: заменяет кириллицу на похожую латиницу."""
    result = ''
    for char in text:
        if char in REPLACEMENTS:
            result += REPLACEMENTS[char]
        else:
            result += char
    return result

# ---------- ТАРИФЫ ----------
TARIFFS = [
    {"days": 1, "price": 0.5, "name": "1 DeHb"},
    {"days": 3, "price": 1.0, "name": "3 Dn9"},
    {"days": 7, "price": 2.0, "name": "7 HeDeJlb"},
    {"days": 30, "price": 4.0, "name": "30 Dn3u"}
]

# ---------- CRYPTO BOT API ----------
async def create_crypto_invoice(amount: float, description: str):
    """Создает счет в CryptoBot."""
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
    
    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=data) as response:
            if response.status == 200:
                result = await response.json()
                if result.get("ok"):
                    return result["result"]
            return None

async def check_crypto_invoice(invoice_id: int):
    """Проверяет статус счета в CryptoBot."""
    url = "https://pay.crypt.bot/api/getInvoices"
    headers = {
        "Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN,
        "Content-Type": "application/json"
    }
    data = {
        "invoice_ids": str(invoice_id)
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=data) as response:
            if response.status == 200:
                result = await response.json()
                if result.get("ok") and result["result"]["items"]:
                    return result["result"]["items"][0]
            return None

# ---------- ПРОВЕРКИ ----------
async def check_subscription(user_id, context):
    """Проверяет подписку на каналы."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT user_id FROM admins WHERE user_id=?", (user_id,))
    is_admin = c.fetchone()
    conn.close()
    if is_admin:
        return True
    
    c.execute("SELECT channel_username FROM required_channels")
    channels = c.fetchall()
    if not channels:
        return True
    
    for (channel_username,) in channels:
        try:
            chat_member = await context.bot.get_chat_member(chat_id=channel_username, user_id=user_id)
            if chat_member.status in ['left', 'kicked']:
                return False
        except:
            continue
    return True

def has_access(user_id):
    """Проверяет доступ к атакам."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT sub_end, refs_count FROM users WHERE user_id=?", (user_id,))
    user = c.fetchone()
    conn.close()
    if not user:
        return False
    sub_end_str, refs_count = user
    if refs_count >= 5:
        return True
    if sub_end_str:
        try:
            sub_end = datetime.fromisoformat(sub_end_str)
            if sub_end > datetime.now():
                return True
        except:
            pass
    return False

# ---------- КНОПКИ ----------
def get_main_keyboard(user_id):
    """Главное меню."""
    access_granted = has_access(user_id)
    keyboard = [
        [InlineKeyboardButton(S("💀 ATaKa") if access_granted else S("🔒 ATaKa (HeT gocTyNa)"), callback_data="attack_menu")],
        [InlineKeyboardButton(S("💳 KyNuTb"), callback_data="buy_menu")],
        [InlineKeyboardButton(S("👥 Pe<l>ePaJlbl"), callback_data="referrals"), 
         InlineKeyboardButton(S("👤 NPo<l>uJlb"), callback_data="profile")],
    ]
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT user_id FROM admins WHERE user_id=?", (user_id,))
    if c.fetchone():
        keyboard.append([InlineKeyboardButton(S("⚙️ AgMuHka"), callback_data="admin_panel")])
    conn.close()
    return InlineKeyboardMarkup(keyboard)

def get_back_button(callback_data="start"):
    return InlineKeyboardMarkup([[InlineKeyboardButton(S("🔙 Ha3ag"), callback_data=callback_data)]])

# ---------- КОМАНДЫ ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    username = user.username or "IO3EP"
    
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    c.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,))
    existing_user = c.fetchone()
    
    if not existing_user:
        ref_id = None
        if context.args and context.args[0].startswith('ref_'):
            try:
                ref_id = int(context.args[0].split('_')[1])
                c.execute("SELECT user_id FROM users WHERE user_id=?", (ref_id,))
                if c.fetchone() and ref_id != user_id:
                    c.execute("UPDATE users SET refs_count = refs_count + 1 WHERE user_id=?", (ref_id,))
                    try:
                        await context.bot.send_message(chat_id=ref_id, 
                            text=S("🦈 HoBbIu Pe<l>ePaJl! +1 k C4eTy! TBoU nPoGpeCc o6HoBLeH! 💀"))
                    except:
                        pass
            except:
                ref_id = None
        
        c.execute("INSERT INTO users (user_id, username, ref_id, refs_count) VALUES (?, ?, ?, 0)", 
                 (user_id, username, ref_id))
        conn.commit()
    
    conn.close()
    
    ref_link = f"t.me/{context.bot.username}?start=ref_{user_id}"
    
    text = f"""
🦈 {S("SH4RK ZN0S - CuCTeMa AKTuBuPoBaHa!")} 💀

{S(f"👋 NpuBeT, {username}!")}
{S(f"🆔 ID: {user_id}")}

{S(f"🔗 CCbIJlKa: {ref_link}")}

{S("💀 HaXMu Ha KHOnKy HuXe, 4To6bl Ha4aTb CHoC!")}
"""
    await update.message.reply_text(text, reply_markup=get_main_keyboard(user_id))

async def start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик кнопки 'Назад'."""
    query = update.callback_query
    user_id = query.from_user.id
    username = query.from_user.username or "IO3EP"
    
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT refs_count, sub_end, total_attacks, total_spent FROM users WHERE user_id=?", (user_id,))
    user = c.fetchone()
    conn.close()
    
    if not user:
        await query.edit_message_text(S("❌ NoJlb3oBaTeJlb He HaUgeH."), reply_markup=get_back_button())
        return
    
    refs_count, sub_end, total_attacks, total_spent = user
    
    sub_active = False
    if sub_end:
        try:
            sub_end_dt = datetime.fromisoformat(sub_end)
            if sub_end_dt > datetime.now():
                sub_active = True
        except:
            pass
    
    progress = min(refs_count, 5)
    bar = "█" * progress + "░" * (5 - progress)
    
    text = f"""
🦈 {S("SH4RK ZN0S - BOT G0T0B!")} 💀
{S(f"👋 NpuBeT, {username}!")}
{S(f"🆔 ID: {user_id}")}
{S(f"👥 Pe<l>ePaJlbl: {refs_count}/5 [{bar}]")}
{S(f"📅 NoDNucka: {'✅ AKTuBHa' if sub_active else '❌ HeT'}")}
{S(f"💀 ATaK: {total_attacks}")}
{S(f"💸 NoTPa4eHo: {total_spent} USDT")}
"""
    await query.edit_message_text(text, reply_markup=get_main_keyboard(user_id))

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT refs_count, sub_end, total_attacks, total_spent, balance FROM users WHERE user_id=?", (user_id,))
    user = c.fetchone()
    conn.close()
    
    if not user:
        await query.edit_message_text(S("❌ NoJlb3oBaTeJlb He HaUgeH."), reply_markup=get_back_button())
        return
    
    refs_count, sub_end, total_attacks, total_spent, balance = user
    
    sub_active = False
    if sub_end:
        try:
            sub_end_dt = datetime.fromisoformat(sub_end)
            if sub_end_dt > datetime.now():
                sub_active = True
        except:
            pass
    
    progress = min(refs_count, 5)
    bar = "█" * progress + "░" * (5 - progress)
    
    text = f"""
🦈 {S("SH4RK ZN0S - NPo<l>uJlb")} 💀

{S(f"🆔 ID: {user_id}")}
{S(f"👥 Pe<l>ePaJlbl: {refs_count}/5 [{bar}]")}
{S(f"📅 NoDNucka: {'✅ AKTuBHa' if sub_active else '❌ HeT'}")}
{S(f"💀 ATaK: {total_attacks}")}
{S(f"💸 NoTPa4eHo: {total_spent} USDT")}
{S(f"💰 BaJlaHc: {balance} USDT")}
"""
    await query.edit_message_text(text, reply_markup=get_back_button())

async def referrals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT refs_count FROM users WHERE user_id=?", (user_id,))
    user = c.fetchone()
    conn.close()
    
    if not user:
        await query.edit_message_text(S("❌ NoJlb3oBaTeJlb He HaUgeH."), reply_markup=get_back_button())
        return
    
    refs_count = user[0]
    ref_link = f"t.me/{context.bot.username}?start=ref_{user_id}"
    
    progress = min(refs_count, 5)
    bar = "█" * progress + "░" * (5 - progress)
    
    text = f"""
🦈 {S("SH4RK ZN0S - Pe<l>ePaJlbHa9 CuCTeMa")} 💀

{S(f"👥 NPoGPeCc: {refs_count}/5 [{bar}]")}

{S("🔗 TB0R CCbIJlKa:")}
{ref_link}

{S("💀 5 Pe<l>ePaJloB = 1 BecNJaTHbIu CHoC!")}
{S("📢 NpuGJlaWau gPy3eu u KpyWu ueJlu!")}
"""
    await query.edit_message_text(text, reply_markup=get_back_button())

# ---------- ПОКУПКА ----------
async def buy_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    
    # Проверка подписки на каналы
    if not await check_subscription(user_id, context):
        await query.edit_message_text(
            S("❌ DH9 nOKyNKu Heo6xoguMo nogNucaTbc9 Ha Bce KaHaJlbl!"),
            reply_markup=get_back_button()
        )
        return
    
    text = S("🦈 💳 Bbl6epu Tapu<l>:")
    keyboard = []
    for tariff in TARIFFS:
        keyboard.append([InlineKeyboardButton(
            S(f"{tariff['name']} - {tariff['price']} USDT"),
            callback_data=f"buy_{tariff['days']}"
        )])
    keyboard.append([InlineKeyboardButton(S("🔙 Ha3ag"), callback_data="start")])
    
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def buy_tariff(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    
    days = int(query.data.split('_')[1])
    tariff = next((t for t in TARIFFS if t['days'] == days), None)
    
    if not tariff:
        await query.edit_message_text(S("❌ Tapu<l> He HaUgeH."), reply_markup=get_back_button())
        return
    
    # Создаем счет в CryptoBot
    invoice = await create_crypto_invoice(tariff['price'], S(f"NoDNucka SH4RK ZN0S Ha {tariff['name']}"))
    
    if not invoice:
        await query.edit_message_text(S("❌ OWu6ka npu co3gaHuu c4eTa. Nonpo6yu no3Xe."), reply_markup=get_back_button())
        return
    
    # Сохраняем счет в БД
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT INTO invoices (invoice_id, user_id, amount, tariff_days, created_at) VALUES (?, ?, ?, ?, ?)",
              (str(invoice['invoice_id']), user_id, tariff['price'], days, datetime.now().isoformat()))
    conn.commit()
    conn.close()
    
    text = f"""
{S(f"🦈 C4eT co3gaH Ha {tariff['price']} USDT")}

{S("🔗 CCbIJlKa Ha oNJaTy:")}
{invoice['pay_url']}

{S("⏳ BpeM9 Ha oNJaTy: 15 MuHyT")}
{S("✅ HaXMu «NpoBepuTb oNJaTy» nocJle oNJaTbl!")}
"""
    keyboard = [
        [InlineKeyboardButton(S("✅ NpoBepuTb oNJaTy"), callback_data=f"check_payment_{invoice['invoice_id']}")],
        [InlineKeyboardButton(S("🔙 Ha3ag"), callback_data="buy_menu")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def check_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    
    invoice_id = int(query.data.split('_')[2])
    
    # Проверяем статус счета
    invoice_status = await check_crypto_invoice(invoice_id)
    
    if not invoice_status:
        await query.answer(S("❌ OWu6ka npobePku. Nonpo6yu no3Xe."), show_alert=True)
        return
    
    if invoice_status['status'] == 'paid':
        # Получаем данные счета из БД
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("SELECT tariff_days FROM invoices WHERE invoice_id=? AND user_id=?", 
                  (str(invoice_id), user_id))
        invoice_data = c.fetchone()
        
        if invoice_data:
            days = invoice_data[0]
            # Начисляем подписку
            new_sub_end = (datetime.now() + timedelta(days=days)).isoformat()
            
            # Получаем текущий sub_end
            c.execute("SELECT sub_end FROM users WHERE user_id=?", (user_id,))
            user = c.fetchone()
            if user and user[0]:
                try:
                    current_sub_end = datetime.fromisoformat(user[0])
                    if current_sub_end > datetime.now():
                        new_sub_end = (current_sub_end + timedelta(days=days)).isoformat()
                except:
                    pass
            
            c.execute("UPDATE users SET sub_end = ?, total_spent = total_spent + ? WHERE user_id=?", 
                      (new_sub_end, invoice_status['amount'], user_id))
            c.execute("UPDATE invoices SET status = 'paid' WHERE invoice_id=?", (str(invoice_id),))
            conn.commit()
            conn.close()
            
            await query.edit_message_text(
                S(f"✅ oNJaTa npoWJa! NoDNucka akTuBuPoBaHa Ha {days} gHeu!"),
                reply_markup=get_back_button()
            )
        else:
            conn.close()
            await query.edit_message_text(S("❌ C4eT He HaUgeH."), reply_markup=get_back_button())
    else:
        await query.answer(S("❌ oNJaTa He npoWJa. Nonpo6yu eWe pa3."), show_alert=True)

# ---------- АТАКА ----------
async def attack_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    
    if not has_access(user_id):
        await query.edit_message_text(
            S("🔒 gocTyn 3akpblT! HyXHo 5 pe<l>ePaJloB uJu onJaTuTb nogNuCKy."),
            reply_markup=get_back_button()
        )
        return
    
    text = f"""
{S("💀 SH4RK ZN0S - MeHro ATaKu")}

{S("BBegu ueJlb gJla CHoca:")}
{S("• @USERNAME")}
{S("• ID (u<l>pbl)")}
{S("• HOMEP TEJlE<l>OHA (+79...)")}

{S("⚠️ OTNPABb COO6WeHUe C UEJlbro gJl9 Ha4aJla ATaKu!")}
"""
    context.user_data['awaiting_target'] = True
    
    keyboard = [[InlineKeyboardButton(S("🔙 Ha3ag"), callback_data="start")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает ввод цели для атаки."""
    user_id = update.effective_user.id
    
    if not context.user_data.get('awaiting_target'):
        return
    
    context.user_data['awaiting_target'] = False
    
    if not has_access(user_id):
        await update.message.reply_text(
            S("🔒 gocTyn 3akpblT! HyXHo 5 pe<l>ePaJloB uJu onJaTuTb nogNuCKy."),
            reply_markup=get_main_keyboard(user_id)
        )
        return
    
    target = update.message.text.strip()
    
    # Имитация атаки
    msg1 = await update.message.reply_text(S(f"🔍 {S('NouCK ueJlu...')} {target}"))
    await asyncio.sleep(1.5)
    
    await msg1.edit_text(S(f"⚡️ {S('3anycK aTaKu Ha')} {target}..."))
    await asyncio.sleep(2)
    
    await msg1.edit_text(S(f"💣 {S('B3JlOM cuCTeMbl 3aWuTbl...')}"))
    await asyncio.sleep(2)
    
    await msg1.edit_text(S(f"🔥 {S('CHoC ueJlu...')}"))
    await asyncio.sleep(1.5)
    
    # Обновляем статистику
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE users SET total_attacks = total_attacks + 1 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()
    
    await msg1.edit_text(f"""
💀 {S("ATaKa 3aBePWeHa!")} 💀

{S(f"🎯 UeJlb: {target}")}
{S("✅ CTaTyc: YCNeWHO")}
{S("💀 BpeM9: 5.5 CeK")}

{S("🦈 SH4RK ZN0S - BceTga Ha CB93u!")}
""", reply_markup=get_main_keyboard(user_id))

# ---------- АДМИНКА ----------
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT user_id FROM admins WHERE user_id=?", (user_id,))
    if not c.fetchone():
        conn.close()
        await query.edit_message_text(S("❌ gocTyn 3akpblT!"), reply_markup=get_back_button())
        return
    
    # Статистика
    c.execute("SELECT COUNT(*) FROM users")
    total_users = c.fetchone()[0]
    c.execute("SELECT SUM(total_attacks) FROM users")
    total_attacks = c.fetchone()[0] or 0
    c.execute("SELECT SUM(total_spent) FROM users")
    total_spent = c.fetchone()[0] or 0
    conn.close()
    
    text = f"""
⚙️ {S("AgMuHka SH4RK ZN0S")}

{S(f"👥 NoJlb3oBaTeJeu: {total_users}")}
{S(f"💀 BceX aTaK: {total_attacks}")}
{S(f"💸 O6opoT: {total_spent} USDT")}

{S("KoMaHgl:")}
{S("/add_channel @username - go6aBuTb KaHaJl")}
{S("/remove_channel @username - ygaJuTb KaHaJl")}
{S("/add_admin ID - go6aBuTb agMuHa")}
{S("/remove_admin ID - ygaJuTb agMuHa")}
{S("/add_days ID KoJlu4ecTBo - Ha4ucJuTb gHu")}
{S("/broadcast TeKcT - paccblJlka")}
"""
    await query.edit_message_text(text, reply_markup=get_back_button())

async def add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT user_id FROM admins WHERE user_id=?", (user_id,))
    if not c.fetchone():
        conn.close()
        return
    
    if not context.args:
        await update.message.reply_text(S("❌ YkaXu @username KaHaJla"))
        conn.close()
        return
    
    channel = context.args[0]
    c.execute("INSERT OR IGNORE INTO required_channels VALUES (?)", (channel,))
    conn.commit()
    conn.close()
    
    await update.message.reply_text(S(f"✅ KaHaJl {channel} go6aBJeH!"))

async def remove_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT user_id FROM admins WHERE user_id=?", (user_id,))
    if not c.fetchone():
        conn.close()
        return
    
    if not context.args:
        await update.message.reply_text(S("❌ YkaXu @username KaHaJla"))
        conn.close()
        return
    
    channel = context.args[0]
    c.execute("DELETE FROM required_channels WHERE channel_username=?", (channel,))
    conn.commit()
    conn.close()
    
    await update.message.reply_text(S(f"✅ KaHaJl {channel} ygaJeH!"))

async def add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT user_id FROM admins WHERE user_id=?", (user_id,))
    if not c.fetchone():
        conn.close()
        return
    
    if not context.args:
        await update.message.reply_text(S("❌ YkaXu ID agMuHa"))
        conn.close()
        return
    
    try:
        new_admin = int(context.args[0])
        c.execute("INSERT OR IGNORE INTO admins VALUES (?)", (new_admin,))
        conn.commit()
        conn.close()
        await update.message.reply_text(S(f"✅ AgMuH {new_admin} go6aBJeH!"))
    except:
        conn.close()
        await update.message.reply_text(S("❌ HeBePHblu ID"))

async def remove_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT user_id FROM admins WHERE user_id=?", (user_id,))
    if not c.fetchone():
        conn.close()
        return
    
    if not context.args:
        await update.message.reply_text(S("❌ YkaXu ID agMuHa"))
        conn.close()
        return
    
    try:
        admin_id = int(context.args[0])
        if admin_id == OWNER_ID:
            await update.message.reply_text(S("❌ HeJlb39 ygaJuTb BJlageJlbua!"))
            conn.close()
            return
        c.execute("DELETE FROM admins WHERE user_id=?", (admin_id,))
        conn.commit()
        conn.close()
        await update.message.reply_text(S(f"✅ AgMuH {admin_id} ygaJeH!"))
    except:
        conn.close()
        await update.message.reply_text(S("❌ HeBePHblu ID"))

async def add_days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT user_id FROM admins WHERE user_id=?", (user_id,))
    if not c.fetchone():
        conn.close()
        return
    
    if len(context.args) < 2:
        await update.message.reply_text(S("❌ YkaXu ID u KoJlu4ecTBo gHeu"))
        conn.close()
        return
    
    try:
        target_id = int(context.args[0])
        days = int(context.args[1])
        
        c.execute("SELECT sub_end FROM users WHERE user_id=?", (target_id,))
        user = c.fetchone()
        if not user:
            await update.message.reply_text(S("❌ NoJlb3oBaTeJlb He HaUgeH"))
            conn.close()
            return
        
        if user[0]:
            try:
                current_sub_end = datetime.fromisoformat(user[0])
                if current_sub_end > datetime.now():
                    new_sub_end = (current_sub_end + timedelta(days=days)).isoformat()
                else:
                    new_sub_end = (datetime.now() + timedelta(days=days)).isoformat()
            except:
                new_sub_end = (datetime.now() + timedelta(days=days)).isoformat()
        else:
            new_sub_end = (datetime.now() + timedelta(days=days)).isoformat()
        
        c.execute("UPDATE users SET sub_end = ? WHERE user_id = ?", (new_sub_end, target_id))
        conn.commit()
        conn.close()
        
        await update.message.reply_text(S(f"✅ Ha4ucJeHo {days} gHeu noJlb3oBaTeJlro {target_id}"))
    except:
        conn.close()
        await update.message.reply_text(S("❌ OWu6ka! NpoBepb gaHHble."))

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT user_id FROM admins WHERE user_id=?", (user_id,))
    if not c.fetchone():
        conn.close()
        return
    
    if not context.args:
        await update.message.reply_text(S("❌ YkaXu TeKcT paccblJlku"))
        conn.close()
        return
    
    message = ' '.join(context.args)
    c.execute("SELECT user_id FROM users")
    users = c.fetchall()
    conn.close()
    
    sent = 0
    for (uid,) in users:
        try:
            await context.bot.send_message(chat_id=uid, text=S(f"📢 {message}"))
            sent += 1
            await asyncio.sleep(0.05)
        except:
            continue
    
    await update.message.reply_text(S(f"✅ PaccblJlka oTnpaBJeHa! NoJly4aTeJeu: {sent}"))

# ---------- ЗАПУСК ----------
def main():
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(start_callback, pattern="^start$"))
    application.add_handler(CallbackQueryHandler(profile, pattern="^profile$"))
    application.add_handler(CallbackQueryHandler(referrals, pattern="^referrals$"))
    application.add_handler(CallbackQueryHandler(buy_menu, pattern="^buy_menu$"))
    application.add_handler(CallbackQueryHandler(buy_tariff, pattern="^buy_"))
    application.add_handler(CallbackQueryHandler(check_payment, pattern="^check_payment_"))
    application.add_handler(CallbackQueryHandler(attack_menu, pattern="^attack_menu$"))
    application.add_handler(CallbackQueryHandler(admin_panel, pattern="^admin_panel$"))
    
    application.add_handler(CommandHandler("add_channel", add_channel))
    application.add_handler(CommandHandler("remove_channel", remove_channel))
    application.add_handler(CommandHandler("add_admin", add_admin))
    application.add_handler(CommandHandler("remove_admin", remove_admin))
    application.add_handler(CommandHandler("add_days", add_days))
    application.add_handler(CommandHandler("broadcast", broadcast))
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_target))
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
