import os
import re
import asyncio
import sqlite3
import logging
import sys
from telethon import TelegramClient, events
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from iqoptionapi.stable_api import IQ_Option

# --- CONFIGURAÇÕES LOGS ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- VARIÁVEIS DO RAILWAY ---
API_ID = os.getenv('TG_API_ID')
API_HASH = os.getenv('TG_API_HASH')
BOT_TOKEN = os.getenv('BOT_TOKEN')
CHANNEL_ID = int(os.getenv('CHANNEL_ID', 0))

if not all([API_ID, API_HASH, BOT_TOKEN, CHANNEL_ID]):
    logger.error("❌ Variáveis de ambiente obrigatórias não configuradas!")
    logger.error("Configure: TG_API_ID, TG_API_HASH, BOT_TOKEN, CHANNEL_ID")
    sys.exit(1)

# --- BANCO DE DADOS ---
DB_PATH = '/app/data/users.db' if os.path.exists('/app/data') else 'users.db'
SESSION_PATH = '/app/data/monitor_session' if os.path.exists('/app/data') else 'monitor_session'

os.makedirs(os.path.dirname(DB_PATH) if os.path.dirname(DB_PATH) else '.', exist_ok=True)

def init_db():
    try:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS users 
                       (user_id INTEGER PRIMARY KEY, email TEXT, password TEXT, 
                        value REAL DEFAULT 5.0, account_type TEXT DEFAULT 'PRACTICE', 
                        active INTEGER DEFAULT 0, wins INTEGER DEFAULT 0, losses INTEGER DEFAULT 0)''')
        conn.commit()
        logger.info("✅ Banco de dados inicializado com sucesso!")
        return conn
    except Exception as e:
        logger.error(f"❌ Erro ao inicializar banco: {e}")
        raise

conn = init_db()
cursor = conn.cursor()

# --- PARSER QUANTUM IA ---
def parse_quantum_signal(text):
    try:
        ativo = re.search(r"Ativo: ([\w-]+)", text)
        if not ativo:
            return None
        ativo = ativo.group(1).strip()
        direcao = "call" if any(x in text.upper() for x in ["📈", "CALL", "🟢"]) else "put"
        exp_match = re.search(r"Expiração: M(\d+)", text)
        if not exp_match:
            return None
        exp = int(exp_match.group(1))
        return {"ativo": ativo, "direcao": direcao, "exp": exp}
    except Exception as e:
        logger.error(f"Erro ao parsear sinal: {e}")
        return None

# --- LÓGICA DE OPERAÇÃO ---
async def execute_trade(bot, user_id, email, password, signal, value, mode):
    try:
        if not email or not password:
            logger.warning(f"Usuário {user_id} sem credenciais configuradas")
            return

        api = IQ_Option(email, password)
        check, reason = api.connect()
        if not check:
            await bot.send_message(chat_id=user_id, text=f"❌ Erro de Login na IQ Option: {reason}")
            return
        
        api.change_balance(mode)
        await bot.send_message(chat_id=user_id, text=f"⚡ **SINAL DETECTADO!**\n"
                                                      f"Ativo: {signal['ativo']}\n"
                                                      f"Operação: {signal['direcao'].upper()}\n"
                                                      f"Valor: R$ {value}")
        
        status, id = api.buy(value, signal['ativo'], signal['direcao'], signal['exp'])
        if not status:
            await bot.send_message(chat_id=user_id, text="❌ Erro ao realizar operação")
            api.api.close()
            return

        await asyncio.sleep(signal['exp'] * 60)
        resultado = api.check_win_v3(id)
        
        if resultado < 0:
            await bot.send_message(chat_id=user_id, text="🔄 **Loss na 1ª. Entrando com GALE 1...**")
            v_gale = value * 2.0
            st_g, id_g = api.buy(v_gale, signal['ativo'], signal['direcao'], signal['exp'])
            
            if st_g:
                await asyncio.sleep(signal['exp'] * 60)
                res_g = api.check_win_v3(id_g)
                if res_g > 0:
                    cursor.execute("UPDATE users SET wins = wins + 1 WHERE user_id = ?", (user_id,))
                    conn.commit()
                    await bot.send_message(chat_id=user_id, text="✅ **WIN NO GALE 1!** 🏆")
                else:
                    cursor.execute("UPDATE users SET losses = losses + 1 WHERE user_id = ?", (user_id,))
                    conn.commit()
                    await bot.send_message(chat_id=user_id, text="💥 **LOSS NO GALE.**")
            else:
                cursor.execute("UPDATE users SET losses = losses + 1 WHERE user_id = ?", (user_id,))
                conn.commit()
                await bot.send_message(chat_id=user_id, text="❌ Erro no GALE 1.")
        else:
            cursor.execute("UPDATE users SET wins = wins + 1 WHERE user_id = ?", (user_id,))
            conn.commit()
            await bot.send_message(chat_id=user_id, text="✅ **WIN DE PRIMEIRA!** 🚀")
        
        api.api.close()
    except Exception as e:
        logger.error(f"Erro no trade para usuário {user_id}: {e}")
        await bot.send_message(chat_id=user_id, text=f"⚠️ Erro na operação: {str(e)[:100]}")

# --- INTERFACE TELEGRAM ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    conn.commit()
    
    cursor.execute("SELECT wins, losses FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    w, l = result if result else (0, 0)
    
    kb = [
        [InlineKeyboardButton("⚙️ Configurar IQ", callback_data="config")],
        [InlineKeyboardButton("🟢 Conta REAL", callback_data="mode_REAL"), 
         InlineKeyboardButton("🟡 Conta DEMO", callback_data="mode_PRACTICE")],
        [InlineKeyboardButton("✅ LIGAR ROBÔ", callback_data="on"), 
         InlineKeyboardButton("🛑 DESLIGAR", callback_data="off")]
    ]
    
    await update.message.reply_text(
        f"⚛️ **QUANTUM IQ BOT** ⚛️\n\n"
        f"📊 **Seu Placar:** {w}W - {l}L\n"
        f"Configure seus dados e ligue o robô:", 
        reply_markup=InlineKeyboardMarkup(kb), 
        parse_mode="Markdown"
    )

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    await q.answer()
    
    if q.data == "on":
        cursor.execute("UPDATE users SET active = 1 WHERE user_id = ?", (uid,))
        conn.commit()
        await q.edit_message_text("✅ Robô ligado! Aguardando sinais...")
    elif q.data == "off":
        cursor.execute("UPDATE users SET active = 0 WHERE user_id = ?", (uid,))
        conn.commit()
        await q.edit_message_text("🛑 Robô desligado com sucesso!")
    elif "mode_" in q.data:
        m = q.data.split("_")[1]
        cursor.execute("UPDATE users SET account_type = ? WHERE user_id = ?", (m, uid))
        conn.commit()
        await q.edit_message_text(f"✅ Modo {m} configurado com sucesso!")
    elif q.data == "config":
        await q.message.reply_text(
            "📱 **Envie seus dados no formato:**\n"
            "`email;senha;valor`\n\n"
            "Exemplo: joao@email.com;senha123;10.0",
            parse_mode="Markdown"
        )

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if ";" in update.message.text:
        try:
            parts = update.message.text.split(";")
            if len(parts) >= 3:
                cursor.execute(
                    "UPDATE users SET email=?, password=?, value=? WHERE user_id=?", 
                    (parts[0], parts[1], float(parts[2]), uid)
                )
                conn.commit()
                await update.message.reply_text("✅ Dados salvos com sucesso! Use /start para ligar o robô.")
            else:
                await update.message.reply_text("❌ Formato inválido. Use: email;senha;valor")
        except Exception as e:
            await update.message.reply_text(f"❌ Erro: {str(e)[:100]}")

# --- MAIN CORRIGIDA ---
async def main():
    # Cria aplicação do Telegram
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(callback_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    
    # Inicializa a aplicação
    await application.initialize()
    await application.start()
    
    # Inicia o updater para receber mensagens
    await application.updater.start_polling()
    logger.info("🤖 Bot do Telegram iniciado!")
    
    # Inicia cliente Telethon para monitorar canal
    tg_client = TelegramClient(SESSION_PATH, API_ID, API_HASH)
    await tg_client.start()
    logger.info("⚛️ Monitor Quantum Online!")
    logger.info(f"📡 Monitorando canal: {CHANNEL_ID}")

    @tg_client.on(events.NewMessage(chats=CHANNEL_ID))
    async def msg_handler(event):
        try:
            signal = parse_quantum_signal(event.raw_text)
            if not signal:
                return
            
            logger.info(f"📈 Sinal detectado: {signal['ativo']} - {signal['direcao']}")
            
            cursor.execute("SELECT user_id, email, password, value, account_type FROM users WHERE active = 1")
            users = cursor.fetchall()
            
            for user in users:
                user_id, email, password, value, account_type = user
                if email and password:
                    asyncio.create_task(execute_trade(
                        application.bot, user_id, email, password, 
                        signal, value, account_type
                    ))
        except Exception as e:
            logger.error(f"Erro no handler de mensagem: {e}")

    # Mantém rodando
    try:
        await tg_client.run_until_disconnected()
    except Exception as e:
        logger.error(f"Erro no cliente Telethon: {e}")
    finally:
        # Limpeza adequada
        await application.updater.stop()
        await application.stop()
        await application.shutdown()
        if conn:
            conn.close()
            logger.info("🔒 Conexão com banco de dados fechada")

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 Bot desligado manualmente")
        sys.exit(0)
    except Exception as e:
        logger.error(f"❌ Erro fatal: {e}")
        sys.exit(1)
