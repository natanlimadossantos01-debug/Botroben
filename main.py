import os
import re
import asyncio
import sqlite3
import logging
from telethon import TelegramClient, events
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
# A biblioteca iqoptionapi deve ser listada no requirements.txt
from iqoptionapi.stable_api import IQ_Option

# --- CONFIGURAÇÕES VIA VARIÁVEIS DE AMBIENTE (RAILWAY) ---
logging.basicConfig(level=logging.INFO)
API_ID = os.getenv('TG_API_ID')
API_HASH = os.getenv('TG_API_HASH')
BOT_TOKEN = os.getenv('BOT_TOKEN')
CHANNEL_ID = int(os.getenv('CHANNEL_ID', 0))

# Caminho para persistência (Volume do Railway)
DB_PATH = '/app/data/users.db' if os.path.exists('/app/data') else 'users.db'
SESSION_PATH = '/app/data/monitor_session' if os.path.exists('/app/data') else 'monitor_session'

# --- BANCO DE DADOS (SQLite) ---
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS users 
               (user_id INTEGER PRIMARY KEY, email TEXT, password TEXT, 
                value REAL DEFAULT 2.0, account_type TEXT DEFAULT 'PRACTICE', 
                active INTEGER DEFAULT 0)''')
conn.commit()

# --- LÓGICA DE EXECUÇÃO COM GALE 1 ---
async def execute_trade_with_gale(user_id, email, password, signal, value, mode):
    try:
        api = IQ_Option(email, password)
        check, reason = api.connect()
        if not check:
            logging.error(f"Erro login {email}: {reason}")
            return

        api.change_balance(mode) 
        
        # --- ENTRADA 1 ---
        logging.info(f"[{email}] Entrada 1: {signal['ativo']} {signal['direcao']}")
        status, id = api.buy(value, signal['ativo'], signal['direcao'], signal['exp'])
        
        if status:
            resultado = api.check_win_v3(id)
            if resultado < 0: # LOSS
                logging.info(f"[{email}] Loss. Iniciando Gale 1...")
                valor_gale = value * 2.0
                status_g, id_g = api.buy(valor_gale, signal['ativo'], signal['direcao'], signal['exp'])
                if status_g:
                    res_g = api.check_win_v3(id_g)
                    logging.info(f"[{email}] Gale finalizado: {'WIN' if res_g > 0 else 'LOSS'}")
            else:
                logging.info(f"[{email}] Win de Primeira!")
        api.api.close()
    except Exception as e:
        logging.error(f"Erro na execução: {e}")

# --- PARSER DE SINAIS (PADRÃO QUANTUM IA) ---
def parse_quantum_signal(text):
    try:
        ativo = re.search(r"Ativo: ([\w-]+)", text).group(1).strip()
        direcao = "call" if "📈" in text or "CALL" in text.upper() or "🟢" in text else "put"
        exp = int(re.search(r"Expiração: M(\d+)", text).group(1))
        return {"ativo": ativo, "direcao": direcao, "exp": exp}
    except Exception:
        return None

# --- MONITOR DO TELEGRAM (TELETHON) ---
async def start_telegram_monitor():
    client = TelegramClient(SESSION_PATH, API_ID, API_HASH)
    await client.start()
    logging.info("Monitor de Sinais Ativo e Conectado!")

    @client.on(events.NewMessage(chats=CHANNEL_ID))
    async def handler(event):
        signal = parse_quantum_signal(event.raw_text)
        if signal:
            logging.info(f"Sinal Detectado: {signal['ativo']}")
            cursor.execute("SELECT email, password, value, account_type FROM users WHERE active = 1")
            for user in cursor.fetchall():
                mail, pw, val, mode = user
                asyncio.create_task(execute_trade_with_gale(None, mail, pw, signal, val, mode))
    
    await client.run_until_disconnected()

# --- INTERFACE DO BOT (BOTFATHER) ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    conn.commit()
    
    kb = [
        [InlineKeyboardButton("Configurar IQ Option", callback_data="config")],
        [InlineKeyboardButton("Conta Real", callback_data="mode_REAL"), InlineKeyboardButton("Conta Demo", callback_data="mode_PRACTICE")],
        [InlineKeyboardButton("LIGAR", callback_data="on"), InlineKeyboardButton("DESLIGAR", callback_data="off")]
    ]
    await update.message.reply_text("🤖 **Painel Quantum IA**\nConfigure sua conta:", 
                                   reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    await query.answer()

    if query.data == "on":
        cursor.execute("UPDATE users SET active = 1 WHERE user_id = ?", (uid,))
        await query.edit_message_text("✅ Robô Ativo! Monitorando sinais...")
    elif query.data == "off":
        cursor.execute("UPDATE users SET active = 0 WHERE user_id = ?", (uid,))
        await query.edit_message_text("🔴 Robô Pausado.")
    elif "mode_" in query.data:
        mode = query.data.split("_")[1]
        cursor.execute("UPDATE users SET account_type = ? WHERE user_id = ?", (mode, uid))
        await query.edit_message_text(f"✨ Modo de operação: {mode}")
    elif query.data == "config":
        await query.message.reply_text("Envie seus dados no formato:\n`email;senha;valor` (Ex: seu@email.com;suasenha;10.0)")
    conn.commit()

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text
    if ";" in text:
        try:
            parts = text.split(";")
            cursor.execute("UPDATE users SET email=?, password=?, value=? WHERE user_id=?", 
                           (parts[0], parts[1], float(parts[2]), uid))
            conn.commit()
            await update.message.reply_text("✅ Configurações salvas!")
        except Exception:
            await update.message.reply_text("❌ Erro no formato. Tente: email;senha;valor")

# --- EXECUÇÃO PRINCIPAL ---
async def main():
    bot_app = Application.builder().token(BOT_TOKEN).build()
    bot_app.add_handler(CommandHandler("start", start_command))
    bot_app.add_handler(CallbackQueryHandler(callback_handler))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    await asyncio.gather(
        bot_app.initialize(),
        bot_app.start(),
        bot_app.updater.start_polling(),
        start_telegram_monitor()
    )

if __name__ == "__main__":
    asyncio.run(main())
