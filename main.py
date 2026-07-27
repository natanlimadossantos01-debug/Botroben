import os
import re
import asyncio
import sqlite3
import logging
from telethon import TelegramClient, events
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from iqoptionapi.stable_api import IQ_Option

# --- CONFIGURAÇÕES LOGS ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- VARIÁVEIS DO RAILWAY (Configure no painel do Railway) ---
API_ID = os.getenv('TG_API_ID')
API_HASH = os.getenv('TG_API_HASH')
BOT_TOKEN = os.getenv('BOT_TOKEN')
CHANNEL_ID = int(os.getenv('CHANNEL_ID', 0))

DB_PATH = '/app/data/users.db' if os.path.exists('/app/data') else 'users.db'
SESSION_PATH = '/app/data/monitor_session' if os.path.exists('/app/data') else 'monitor_session'

# --- BANCO DE DADOS ---
def init_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users 
                   (user_id INTEGER PRIMARY KEY, email TEXT, password TEXT, 
                    value REAL DEFAULT 5.0, account_type TEXT DEFAULT 'PRACTICE', 
                    active INTEGER DEFAULT 0, wins INTEGER DEFAULT 0, losses INTEGER DEFAULT 0)''')
    conn.commit()
    return conn

conn = init_db()
cursor = conn.cursor()

# --- PARSER QUANTUM IA ---
def parse_quantum_signal(text):
    try:
        ativo = re.search(r"Ativo: ([\w-]+)", text).group(1).strip()
        direcao = "call" if any(x in text.upper() for x in ["📈", "CALL", "🟢"]) else "put"
        exp = int(re.search(r"Expiração: M(\d+)", text).group(1))
        return {"ativo": ativo, "direcao": direcao, "exp": exp}
    except:
        return None

# --- LÓGICA DE OPERAÇÃO E GALE ---
async def execute_trade(bot, user_id, email, password, signal, value, mode):
    try:
        api = IQ_Option(email, password)
        check, reason = api.connect()
        if not check:
            await bot.send_message(chat_id=user_id, text=f"❌ Erro de Login na IQ Option: {reason}")
            return
        
        api.change_balance(mode)
        await bot.send_message(chat_id=user_id, text=f"⚡ **SINAL DETECTADO!**\nAtivo: {signal['ativo']}\nOperação: {signal['direcao'].upper()}\nValor: R$ {value}")
        
        status, id = api.buy(value, signal['ativo'], signal['direcao'], signal['exp'])
        if status:
            resultado = api.check_win_v3(id)
            if resultado < 0: # LOSS -> ENTRA GALE 1
                await bot.send_message(chat_id=user_id, text="🔄 **Loss na 1ª. Entrando com GALE 1...**")
                v_gale = value * 2.0
                st_g, id_g = api.buy(v_gale, signal['ativo'], signal['direcao'], signal['exp'])
                if st_g:
                    res_g = api.check_win_v3(id_g)
                    if res_g > 0:
                        cursor.execute("UPDATE users SET wins = wins + 1 WHERE user_id = ?", (user_id,))
                        await bot.send_message(chat_id=user_id, text="✅ **WIN NO GALE 1!** 🏆")
                    else:
                        cursor.execute("UPDATE users SET losses = losses + 1 WHERE user_id = ?", (user_id,))
                        await bot.send_message(chat_id=user_id, text="💥 **LOSS NO GALE.**")
            else:
                cursor.execute("UPDATE users SET wins = wins + 1 WHERE user_id = ?", (user_id,))
                await bot.send_message(chat_id=user_id, text="✅ **WIN DE PRIMEIRA!** 🚀")
        conn.commit()
        api.api.close()
    except Exception as e:
        logging.error(f"Erro no trade: {e}")

# --- INTERFACE TELEGRAM ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    conn.commit()
    
    cursor.execute("SELECT wins, losses FROM users WHERE user_id = ?", (user_id,))
    w, l = cursor.fetchone()
    
    kb = [[InlineKeyboardButton("⚙️ Configurar IQ", callback_data="config")],
          [InlineKeyboardButton("🟢 Conta REAL", callback_data="mode_REAL"), InlineKeyboardButton("🟡 Conta DEMO", callback_data="mode_PRACTICE")],
          [InlineKeyboardButton("✅ LIGAR ROBÔ", callback_data="on"), InlineKeyboardButton("🛑 DESLIGAR", callback_data="off")]]
    
    await update.message.reply_text(
        f"⚛️ **QUANTUM IQ BOT** ⚛️\n\n"
        f"📊 **Seu Placar:** {w}W - {l}L\n"
        f"Configure seus dados e ligue o robô:", 
        reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown"
    )

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    await q.answer()
    
    if q.data == "on": cursor.execute("UPDATE users SET active = 1 WHERE user_id = ?", (uid,))
    elif q.data == "off": cursor.execute("UPDATE users SET active = 0 WHERE user_id = ?", (uid,))
    elif "mode_" in q.data:
        m = q.data.split("_")[1]
        cursor.execute("UPDATE users SET account_type = ? WHERE user_id = ?", (m, uid))
    elif q.data == "config":
        await q.message.reply_text("📱 **Envie seus dados no formato:**\n`email;senha;valor` (Ex: joao@email.com;senha123;10.0)")
    
    conn.commit()
    await q.edit_message_text("✅ Operação realizada com sucesso!")

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if ";" in update.message.text:
        try:
            p = update.message.text.split(";")
            cursor.execute("UPDATE users SET email=?, password=?, value=? WHERE user_id=?", (p[0], p[1], float(p[2]), uid))
            conn.commit()
            await update.message.reply_text("✅ Dados salvos! Use /start para ligar o robô.")
        except:
            await update.message.reply_text("❌ Formato inválido.")

# --- INICIALIZAÇÃO SEGURA ---
async def main():
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(callback_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    tg_client = TelegramClient(SESSION_PATH, API_ID, API_HASH)
    await tg_client.start()
    logging.info("⚛️ Monitor Quantum Online!")

    @tg_client.on(events.NewMessage(chats=CHANNEL_ID))
    async def msg_handler(event):
        signal = parse_quantum_signal(event.raw_text)
        if signal:
            cursor.execute("SELECT user_id, email, password, value, account_type FROM users WHERE active = 1")
            for u in cursor.fetchall():
                asyncio.create_task(execute_trade(application.bot, u[0], u[1], u[2], signal, u[3], u[4]))

    async with application:
        await application.start()
        await application.updater.start_polling()
        await tg_client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
