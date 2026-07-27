import os
import re
import asyncio
import sqlite3
import logging
from telethon import TelegramClient, events
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from iqoptionapi.stable_api import IQ_Option

# --- CONFIGURAÇÕES ---
logging.basicConfig(level=logging.INFO)
API_ID = os.getenv('TG_API_ID')
API_HASH = os.getenv('TG_API_HASH')
BOT_TOKEN = os.getenv('BOT_TOKEN')
CHANNEL_ID = int(os.getenv('CHANNEL_ID', 0))

DB_PATH = '/app/data/users.db' if os.path.exists('/app/data') else 'users.db'
SESSION_PATH = '/app/data/monitor_session' if os.path.exists('/app/data') else 'monitor_session'

def init_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users 
                   (user_id INTEGER PRIMARY KEY, email TEXT, password TEXT, 
                    value REAL DEFAULT 2.0, account_type TEXT DEFAULT 'PRACTICE', 
                    active INTEGER DEFAULT 0)''')
    conn.commit()
    return conn

conn = init_db()
cursor = conn.cursor()

# --- FUNÇÃO DE TRADE COM AVISOS NO TELEGRAM ---
async def execute_trade_with_alerts(bot, user_id, email, password, signal, value, mode):
    try:
        api = IQ_Option(email, password)
        check, reason = api.connect()
        if not check:
            await bot.send_message(chat_id=user_id, text=f"❌ Erro ao conectar na IQ Option: {reason}")
            return
        
        api.change_balance(mode)
        await bot.send_message(chat_id=user_id, text=f"🚀 **Entrada 1 Enviada!**\nAtivo: {signal['ativo']}\nValor: R$ {value}")
        
        status, id = api.buy(value, signal['ativo'], signal['direcao'], signal['exp'])
        
        if status:
            resultado = api.check_win_v3(id)
            if resultado < 0: # LOSS
                await bot.send_message(chat_id=user_id, text=f"⚠️ Loss na 1ª entrada. **Iniciando Gale 1...**")
                valor_gale = value * 2.0
                status_g, id_g = api.buy(valor_gale, signal['ativo'], signal['direcao'], signal['exp'])
                
                if status_g:
                    res_g = api.check_win_v3(id_g)
                    msg = "✅ **WIN NO GALE!**" if res_g > 0 else "❌ **LOSS NO GALE.**"
                    await bot.send_message(chat_id=user_id, text=msg)
            else:
                await bot.send_message(chat_id=user_id, text=f"✅ **WIN DE PRIMEIRA!**")
        else:
            await bot.send_message(chat_id=user_id, text=f"❌ Erro ao abrir ordem: {id}")
        
        api.api.close()
    except Exception as e:
        await bot.send_message(chat_id=user_id, text=f"⚠️ Ocorreu um erro: {e}")

# --- PARSER ---
def parse_quantum_signal(text):
    try:
        ativo = re.search(r"Ativo: ([\w-]+)", text).group(1).strip()
        direcao = "call" if any(x in text.upper() for x in ["📈", "CALL", "🟢"]) else "put"
        exp = int(re.search(r"Expiração: M(\d+)", text).group(1))
        return {"ativo": ativo, "direcao": direcao, "exp": exp}
    except:
        return None

# --- HANDLERS DO BOT ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    conn.commit()
    kb = [[InlineKeyboardButton("Configurar", callback_data="config")],
          [InlineKeyboardButton("Real", callback_data="mode_REAL"), InlineKeyboardButton("Demo", callback_data="mode_PRACTICE")],
          [InlineKeyboardButton("LIGAR", callback_data="on"), InlineKeyboardButton("DESLIGAR", callback_data="off")]]
    await update.message.reply_text("🤖 **Painel Quantum IA**\nConfigure sua conta abaixo:", reply_markup=InlineKeyboardMarkup(kb))

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    await query.answer()
    if query.data == "on": cursor.execute("UPDATE users SET active = 1 WHERE user_id = ?", (uid,))
    elif query.data == "off": cursor.execute("UPDATE users SET active = 0 WHERE user_id = ?", (uid,))
    elif "mode_" in query.data:
        m = query.data.split("_")[1]
        cursor.execute("UPDATE users SET account_type = ? WHERE user_id = ?", (m, uid))
    elif query.data == "config":
        await query.message.reply_text("Envie seus dados: email;senha;valor")
    conn.commit()
    await query.edit_message_text("✅ Configurações atualizadas!")

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if ";" in update.message.text:
        try:
            p = update.message.text.split(";")
            cursor.execute("UPDATE users SET email=?, password=?, value=? WHERE user_id=?", (p[0], p[1], float(p[2]), uid))
            conn.commit()
            await update.message.reply_text("✅ Dados salvos com sucesso!")
        except: await update.message.reply_text("❌ Formato inválido.")

# --- MAIN ---
async def main():
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CallbackQueryHandler(callback_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    
    async with application:
        await application.start()
        await application.updater.start_polling()
        
        tg_client = TelegramClient(SESSION_PATH, API_ID, API_HASH)
        await tg_client.start()
        logging.info("Monitor de Sinais ONLINE!")

        @tg_client.on(events.NewMessage(chats=CHANNEL_ID))
        async def msg_handler(event):
            s = parse_quantum_signal(event.raw_text)
            if s:
                cursor.execute("SELECT user_id, email, password, value, account_type FROM users WHERE active = 1")
                for u in cursor.fetchall():
                    # Passamos o bot para enviar mensagens
                    asyncio.create_task(execute_trade_with_alerts(application.bot, u[0], u[1], u[2], s, u[3], u[4]))

        await tg_client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
