#!/usr/bin/env python3
"""
🤖 QUANTUM IA - Bot Telegram Multi-Usuário
⚛️ Trader Professor Automático
👥 Cada usuário configura e opera independente
👑 Painel Admin para gerenciamento
"""

import asyncio
import json
import logging
import os
import re
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, filters, ContextTypes
)

# ═══════════════════════════════════════════
# CONFIGURAÇÕES
# ═══════════════════════════════════════════
FUSO_BR = timezone(timedelta(hours=-3))
os.environ['TZ'] = 'America/Sao_Paulo'

BOT_TOKEN = os.environ.get('BOT_TOKEN', '')
ADMIN_ID = int(os.environ.get('ADMIN_ID', '0'))
DB_PATH = "quantum_users.db"

if not BOT_TOKEN:
    print("❌ Configure BOT_TOKEN no Railway!")
    exit(1)

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════
# BANCO DE DADOS
# ═══════════════════════════════════════════

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            iq_email TEXT DEFAULT '',
            iq_senha TEXT DEFAULT '',
            iq_conta TEXT DEFAULT 'PRACTICE',
            valor_entrada REAL DEFAULT 2.0,
            multiplicador REAL DEFAULT 2.0,
            max_gales INTEGER DEFAULT 1,
            stop_loss REAL DEFAULT 0,
            stop_win REAL DEFAULT 0,
            bot_ligado INTEGER DEFAULT 0,
            saldo REAL DEFAULT 0,
            ativo INTEGER DEFAULT 1,
            trial_usado INTEGER DEFAULT 0,
            expiracao TEXT,
            cadastro TEXT,
            ultimo_uso TEXT
        );
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            data TEXT,
            ativo TEXT,
            direcao TEXT,
            valor REAL,
            resultado TEXT,
            lucro REAL
        );
        CREATE TABLE IF NOT EXISTS admin_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data TEXT,
            acao TEXT
        );
    """)
    # Admin principal
    conn.execute("INSERT OR IGNORE INTO users (user_id, ativo, expiracao, cadastro) VALUES (?, 1, '2099-12-31', datetime('now','localtime'))", (ADMIN_ID,))
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    cols = [d[0] for d in c.description] if c.description else []
    conn.close()
    return dict(zip(cols, row)) if row else None

def criar_usuario(user_id, username, first_name):
    exp = (datetime.now(FUSO_BR) + timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
    now = datetime.now(FUSO_BR).strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""INSERT OR IGNORE INTO users (user_id, username, first_name, ativo, trial_usado, expiracao, cadastro) 
                    VALUES (?,?,?,1,1,?,?)""", (user_id, username or "", first_name or "", exp, now))
    conn.commit()
    conn.close()

def atualizar_user(user_id, **kwargs):
    conn = sqlite3.connect(DB_PATH)
    sets = ", ".join(f"{k}=?" for k in kwargs)
    vals = list(kwargs.values()) + [user_id]
    conn.execute(f"UPDATE users SET {sets} WHERE user_id=?", vals)
    conn.commit()
    conn.close()

def ativar_user(user_id, dias=30):
    exp = (datetime.now(FUSO_BR) + timedelta(days=dias)).strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE users SET ativo=1, expiracao=? WHERE user_id=?", (exp, user_id))
    conn.commit()
    conn.close()

def desativar_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE users SET ativo=0, bot_ligado=0 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def user_ativo(user_id):
    u = get_user(user_id)
    if not u or not u['ativo']: return False
    try:
        exp = datetime.strptime(u['expiracao'], "%Y-%m-%d %H:%M:%S")
        if datetime.now(FUSO_BR) > exp:
            desativar_user(user_id)
            return False
    except: return False
    return True

def listar_users():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, username, first_name, ativo, expiracao, bot_ligado, saldo FROM users ORDER BY cadastro DESC")
    rows = [{"id": r[0], "user": r[1] or "", "nome": r[2] or "", "ativo": r[3], "exp": r[4] or "", "bot": r[5], "saldo": r[6]} for r in c.fetchall()]
    conn.close()
    return rows

def salvar_trade(user_id, ativo, direcao, valor, resultado, lucro):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT INTO trades (user_id, data, ativo, direcao, valor, resultado, lucro) VALUES (?,?,?,?,?,?,?)",
                 (user_id, datetime.now(FUSO_BR).strftime("%Y-%m-%d %H:%M:%S"), ativo, direcao, valor, resultado, lucro))
    conn.commit()
    conn.close()

def resultado_dia(user_id):
    hoje = datetime.now(FUSO_BR).strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""SELECT COUNT(*), SUM(CASE WHEN resultado='win' THEN 1 ELSE 0 END), 
                        SUM(CASE WHEN resultado='loss' THEN 1 ELSE 0 END), SUM(lucro) 
                 FROM trades WHERE user_id=? AND data LIKE ?""", (user_id, f"{hoje}%"))
    t, w, l, lc = c.fetchone()
    conn.close()
    return {"total": t or 0, "wins": w or 0, "losses": l or 0, "lucro": lc or 0.0}

# ═══════════════════════════════════════════
# BOT DO USUÁRIO (TRADER PROFESSOR)
# ═══════════════════════════════════════════

class UserBot:
    def __init__(self, user_id):
        self.user_id = user_id
        self.api = None
        self.rodando = False
        self.lucro_dia = 0.0
        self.wins = 0
        self.losses = 0
        self.ops = 0

    def conectar(self):
        from iqoptionapi.stable_api import IQ_Option
        u = get_user(self.user_id)
        if not u or not u.get('iq_email'): return False
        
        try:
            self.api = IQ_Option(u['iq_email'], u['iq_senha'])
            ok, _ = self.api.connect()
            if ok:
                self.api.change_balance(u.get('iq_conta', 'PRACTICE'))
                saldo = self.api.get_balance()
                atualizar_user(self.user_id, saldo=saldo)
                return True
            return False
        except: return False

    def operar(self, ativo, direcao, exp=1):
        u = get_user(self.user_id)
        if not u: return
        
        valor = u.get('valor_entrada', 2.0)
        max_gales = u.get('max_gales', 1)
        multiplicador = u.get('multiplicador', 2.0)
        
        for tentativa in range(max_gales + 1):
            val = round(valor * (multiplicador ** tentativa), 2)
            try:
                saldo_antes = self.api.get_balance()
                ok, _ = self.api.buy(val, ativo, direcao, exp)
                if not ok: continue
                
                time.sleep(65)  # Aguarda M1
                saldo_depois = self.api.get_balance()
                lucro = saldo_depois - saldo_antes
                
                if lucro > 0:
                    self.wins += 1; self.ops += 1; self.lucro_dia += lucro
                    salvar_trade(self.user_id, ativo, direcao, val, "win", abs(lucro))
                    atualizar_user(self.user_id, saldo=saldo_depois)
                    return "WIN", abs(lucro), tentativa
                elif lucro < 0:
                    if tentativa < max_gales: continue
                    self.losses += 1; self.ops += 1; self.lucro_dia -= val
                    salvar_trade(self.user_id, ativo, direcao, val, "loss", -val)
                    atualizar_user(self.user_id, saldo=saldo_depois)
                    return "LOSS", val, tentativa
                else:
                    return "EMPATE", 0, tentativa
            except: continue
        
        return "ERRO", 0, 0

# ═══════════════════════════════════════════
# HANDLERS DO BOT
# ═══════════════════════════════════════════

# Estados da configuração
(CONF_EMAIL, CONF_SENHA, CONF_CONTA, CONF_VALOR, CONF_MULTI, CONF_GALES, CONF_SL, CONF_SW) = range(8)

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    nome = update.effective_user.first_name
    user = get_user(user_id)
    
    if not user:
        criar_usuario(user_id, update.effective_user.username, nome)
        await update.message.reply_text(
            f"👋 Olá, *{nome}*!\n\n"
            f"🎁 *3 dias grátis!*\n\n"
            f"📋 *Comandos:*\n"
            f"/configurar - Setup IQ Option\n"
            f"/ligar - Iniciar bot\n"
            f"/parar - Parar bot\n"
            f"/status - Ver resultados\n"
            f"/ajuda - Todos comandos",
            parse_mode="Markdown"
        )
    else:
        exp = user.get('expiracao', '')
        try:
            d = (datetime.strptime(exp, "%Y-%m-%d %H:%M:%S") - datetime.now(FUSO_BR)).days
            s = f"✅ {d} dias restantes" if user['ativo'] else "⛔ Expirado"
        except: s = "⛔ Expirado"
        
        await update.message.reply_text(
            f"👋 *{nome}*\n📊 Plano: {s}\n🤖 Bot: {'🟢' if user.get('bot_ligado') else '🔴'}\n💰 Saldo: R$ {user.get('saldo', 0):.2f}\n\n/status para detalhes",
            parse_mode="Markdown"
        )

async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    if not user: await update.message.reply_text("❌ Use /start primeiro"); return
    
    res = resultado_dia(user_id)
    taxa = (res['wins']/res['total']*100) if res['total'] > 0 else 0
    
    await update.message.reply_text(
        f"⚛️ *QUANTUM IA - STATUS*\n\n"
        f"🤖 Bot: {'🟢 Ligado' if user.get('bot_ligado') else '🔴 Desligado'}\n"
        f"💰 Saldo: R$ {user.get('saldo', 0):.2f}\n"
        f"💹 Conta: {user.get('iq_conta', 'PRACTICE')}\n\n"
        f"📊 *Hoje:*\n"
        f"📈 Ops: {res['total']}\n"
        f"✅ Wins: {res['wins']}\n"
        f"❌ Losses: {res['losses']}\n"
        f"🎯 Taxa: {taxa:.0f}%\n"
        f"💰 Lucro: R$ {res['lucro']:.2f}\n\n"
        f"⚙️ Entrada: R$ {user.get('valor_entrada', 2.0)}\n"
        f"🔄 Gale: {user.get('multiplicador', 2.0)}x ({user.get('max_gales', 1)})\n"
        f"🛑 Stop L: R$ {user.get('stop_loss', 0)} | Stop W: R$ {user.get('stop_win', 0)}",
        parse_mode="Markdown"
    )

async def cmd_configurar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not user_ativo(update.effective_user.id):
        await update.message.reply_text("⛔ Acesso expirado! Contate o administrador."); return ConversationHandler.END
    await update.message.reply_text("⚙️ *Configuração IQ Option*\n\n📧 Digite seu email:", parse_mode="Markdown")
    return CONF_EMAIL

async def conf_email(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data['email'] = update.message.text.strip()
    await update.message.reply_text("🔒 Digite sua senha:", parse_mode="Markdown")
    return CONF_SENHA

async def conf_senha(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data['senha'] = update.message.text.strip()
    kb = [[InlineKeyboardButton("🎯 DEMO", callback_data="conta_PRACTICE"), InlineKeyboardButton("💰 REAL", callback_data="conta_REAL")]]
    await update.message.reply_text("📊 Tipo de conta:", reply_markup=InlineKeyboardMarkup(kb))
    return CONF_CONTA

async def conf_conta(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    ctx.user_data['conta'] = q.data.replace("conta_", "")
    await q.edit_message_text(f"✅ Conta: {ctx.user_data['conta']}\n\n💰 Valor de entrada (R$):\nEx: 2.00", parse_mode="Markdown")
    return CONF_VALOR

async def conf_valor(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try: ctx.user_data['valor'] = float(update.message.text.strip().replace(',','.'))
    except: await update.message.reply_text("❌ Inválido"); return CONF_VALOR
    await update.message.reply_text("🔄 Multiplicador do Gale:\nEx: 2.0 (dobra)")
    return CONF_MULTI

async def conf_multi(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try: ctx.user_data['multi'] = float(update.message.text.strip().replace(',','.'))
    except: await update.message.reply_text("❌ Inválido"); return CONF_MULTI
    await update.message.reply_text("🎯 Máximo de Gales:\nEx: 1")
    return CONF_GALES

async def conf_gales(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try: ctx.user_data['gales'] = int(update.message.text.strip())
    except: await update.message.reply_text("❌ Inválido"); return CONF_GALES
    await update.message.reply_text("🛑 Stop Loss (R$):\n0 = desativado")
    return CONF_SL

async def conf_sl(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try: ctx.user_data['sl'] = float(update.message.text.strip().replace(',','.'))
    except: await update.message.reply_text("❌ Inválido"); return CONF_SL
    await update.message.reply_text("🏆 Stop Win (R$):\n0 = desativado")
    return CONF_SW

async def conf_sw(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    try: ctx.user_data['sw'] = float(update.message.text.strip().replace(',','.'))
    except: await update.message.reply_text("❌ Inválido"); return CONF_SW
    
    d = ctx.user_data
    atualizar_user(user_id, iq_email=d['email'], iq_senha=d['senha'], iq_conta=d['conta'],
                   valor_entrada=d['valor'], multiplicador=d['multi'], max_gales=d['gales'],
                   stop_loss=d['sl'], stop_win=d['sw'])
    
    await update.message.reply_text(
        f"✅ *Configuração salva!*\n\n"
        f"📧 {d['email']}\n📊 {d['conta']}\n"
        f"💰 R$ {d['valor']}\n🔄 {d['multi']}x (max {d['gales']})\n"
        f"🛑 Stop L: R$ {d['sl']}\n🏆 Stop W: R$ {d['sw']}\n\n"
        f"Use /ligar para iniciar!",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def cmd_ligar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not user_ativo(user_id): await update.message.reply_text("⛔ Acesso expirado!"); return
    user = get_user(user_id)
    if not user or not user.get('iq_email'): await update.message.reply_text("❌ Use /configurar primeiro"); return
    
    await update.message.reply_text("⏳ Conectando à IQ Option...")
    bot = UserBot(user_id)
    if bot.conectar():
        atualizar_user(user_id, bot_ligado=1)
        await update.message.reply_text(f"✅ *Bot ligado!*\n💰 Saldo: R$ {user.get('saldo', 0):.2f}\n🤖 Auto operação ativada\n\nUse /parar para desligar", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ Erro ao conectar! Verifique email/senha.")

async def cmd_parar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    atualizar_user(user_id, bot_ligado=0)
    res = resultado_dia(user_id)
    await update.message.reply_text(f"🔴 *Bot desligado*\n📊 Hoje: {res['wins']}W/{res['losses']}L | R$ {res['lucro']:.2f}", parse_mode="Markdown")

async def cmd_ajuda(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📚 *COMANDOS*\n\n"
        "/start - Iniciar\n"
        "/configurar - Setup IQ Option\n"
        "/ligar - Ligar bot\n"
        "/parar - Parar bot\n"
        "/status - Ver status\n"
        "/admin - Painel admin (só ADM)\n"
        "/ajuda - Esta mensagem",
        parse_mode="Markdown"
    )

# ═══════════════════════════════════════════
# PAINEL ADMIN
# ═══════════════════════════════════════════

async def cmd_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID: await update.message.reply_text("⛔ Acesso negado!"); return
    
    users = listar_users()
    texto = "👑 *PAINEL ADMIN*\n\n"
    
    for u in users[:10]:
        s = "🟢" if u['ativo'] else "🔴"
        b = "🤖" if u['bot'] else "💤"
        exp = (u['exp'] or '')[:10]
        texto += f"{s}{b} `{u['id']}` {u['nome']}\n   Exp: {exp} | R$ {u['saldo']:.2f}\n\n"
    
    kb = [[InlineKeyboardButton("➕ Ativar Usuário", callback_data="adm_ativar"),
           InlineKeyboardButton("➖ Desativar", callback_data="adm_desativar")]]
    
    await update.message.reply_text(texto, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

# ═══════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════

def main():
    init_db()
    logger.info("✅ Banco iniciado")
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Configuração
    conv = ConversationHandler(
        entry_points=[CommandHandler("configurar", cmd_configurar)],
        states={
            CONF_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, conf_email)],
            CONF_SENHA: [MessageHandler(filters.TEXT & ~filters.COMMAND, conf_senha)],
            CONF_CONTA: [CallbackQueryHandler(conf_conta, pattern="^conta_")],
            CONF_VALOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, conf_valor)],
            CONF_MULTI: [MessageHandler(filters.TEXT & ~filters.COMMAND, conf_multi)],
            CONF_GALES: [MessageHandler(filters.TEXT & ~filters.COMMAND, conf_gales)],
            CONF_SL: [MessageHandler(filters.TEXT & ~filters.COMMAND, conf_sl)],
            CONF_SW: [MessageHandler(filters.TEXT & ~filters.COMMAND, conf_sw)],
        },
        fallbacks=[CommandHandler("cancelar", lambda u, c: ConversationHandler.END)],
    )
    
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("ligar", cmd_ligar))
    app.add_handler(CommandHandler("parar", cmd_parar))
    app.add_handler(CommandHandler("ajuda", cmd_ajuda))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(conv)
    
    logger.info("🚀 Bot iniciado!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
