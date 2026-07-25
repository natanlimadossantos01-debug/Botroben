#!/usr/bin/env python3
"""
🤖 QUANTUM IA - Bot Telegram Multi-Usuário
⚛️ Trader Professor Automático
👥 Multi-usuário com Painel Admin
👑 Admin gerencia acessos via Telegram
✅ Datas corrigidas - Fuso Brasil
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
time.tzset()

BOT_TOKEN = os.environ.get('BOT_TOKEN', '')
ADMIN_ID = int(os.environ.get('ADMIN_ID', '0'))
DB_PATH = "quantum_users.db"

if not BOT_TOKEN:
    print("❌ Configure BOT_TOKEN no Railway!")
    exit(1)

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════
# BANCO DE DADOS (CORRIGIDO)
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
    """)
    # Admin nunca expira
    admin_exp = (datetime.now(FUSO_BR) + timedelta(days=36500)).strftime("%Y-%m-%d %H:%M:%S")
    admin_now = datetime.now(FUSO_BR).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("INSERT OR IGNORE INTO users (user_id, ativo, expiracao, cadastro) VALUES (?, 1, ?, ?)", 
                 (ADMIN_ID, admin_exp, admin_now))
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
    """Cria usuário com 3 dias de trial"""
    exp = datetime.now(FUSO_BR) + timedelta(days=3)
    exp_str = exp.strftime("%Y-%m-%d %H:%M:%S")
    now_str = datetime.now(FUSO_BR).strftime("%Y-%m-%d %H:%M:%S")
    
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""INSERT OR IGNORE INTO users (user_id, username, first_name, ativo, trial_usado, expiracao, cadastro) 
                    VALUES (?,?,?,1,1,?,?)""", (user_id, username or "", first_name or "", exp_str, now_str))
    conn.commit()
    conn.close()
    logger.info(f"✅ Novo usuário: {user_id} - Trial até {exp_str}")

def atualizar_user(user_id, **kwargs):
    conn = sqlite3.connect(DB_PATH)
    sets = ", ".join(f"{k}=?" for k in kwargs)
    vals = list(kwargs.values()) + [user_id]
    conn.execute(f"UPDATE users SET {sets} WHERE user_id=?", vals)
    conn.commit()
    conn.close()

def ativar_user(user_id, dias=30):
    """Ativa usuário por X dias a partir de AGORA"""
    exp = datetime.now(FUSO_BR) + timedelta(days=dias)
    exp_str = exp.strftime("%Y-%m-%d %H:%M:%S")
    
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE users SET ativo=1, expiracao=? WHERE user_id=?", (exp_str, user_id))
    conn.commit()
    conn.close()
    logger.info(f"✅ Usuário {user_id} ativado até {exp_str}")

def desativar_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE users SET ativo=0, bot_ligado=0 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()
    logger.info(f"🚫 Usuário {user_id} desativado")

def user_ativo(user_id):
    """Verifica se usuário está ativo e não expirado"""
    # Admin nunca expira
    if user_id == ADMIN_ID:
        return True
    
    u = get_user(user_id)
    if not u or not u.get('ativo'):
        return False
    
    try:
        exp_str = u.get('expiracao', '')
        if not exp_str:
            return False
        
        # Converte string para datetime
        exp = datetime.strptime(exp_str, "%Y-%m-%d %H:%M:%S")
        agora = datetime.now(FUSO_BR)
        
        if agora > exp:
            logger.info(f"⏰ Usuário {user_id} expirado. Exp: {exp_str} | Agora: {agora}")
            desativar_user(user_id)
            return False
        
        # Calcula dias restantes
        dias = (exp - agora).days
        logger.info(f"✅ Usuário {user_id} ativo. {dias} dias restantes")
        return True
        
    except Exception as e:
        logger.error(f"❌ Erro ao verificar expiração {user_id}: {e}")
        return False

def listar_users():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, username, first_name, ativo, expiracao, bot_ligado, saldo, iq_email FROM users ORDER BY cadastro DESC")
    rows = []
    for r in c.fetchall():
        rows.append({
            "id": r[0], "user": r[1] or "", "nome": r[2] or "", 
            "ativo": r[3], "exp": r[4] or "", "bot": r[5], 
            "saldo": r[6] or 0, "email": r[7] or ""
        })
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
# ESTADOS DA CONFIGURAÇÃO
# ═══════════════════════════════════════════
(CONF_EMAIL, CONF_SENHA, CONF_CONTA, CONF_VALOR, 
 CONF_MULTI, CONF_GALES, CONF_SL, CONF_SW) = range(8)

# ═══════════════════════════════════════════
# HANDLERS PRINCIPAIS
# ═══════════════════════════════════════════

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
        if user_ativo(user_id):
            try:
                exp = datetime.strptime(user.get('expiracao', ''), "%Y-%m-%d %H:%M:%S")
                dias = (exp - datetime.now(FUSO_BR)).days
                s = f"✅ {dias} dias restantes"
            except: 
                s = "✅ Ativo"
        else:
            s = "⛔ Expirado"
        
        await update.message.reply_text(
            f"👋 *{nome}*\n📊 Plano: {s}\n🤖 Bot: {'🟢' if user.get('bot_ligado') else '🔴'}\n💰 Saldo: R$ {user.get('saldo', 0):.2f}\n\n/status para detalhes",
            parse_mode="Markdown"
        )

async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    if not user: 
        await update.message.reply_text("❌ Use /start primeiro"); return
    
    if not user_ativo(user_id):
        await update.message.reply_text("⛔ Seu acesso expirou!\nContate: @natanbinario"); return
    
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
        f"🔄 Gale: {user.get('multiplicador', 2.0)}x ({user.get('max_gales', 1)})",
        parse_mode="Markdown"
    )

async def cmd_ligar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not user_ativo(user_id):
        await update.message.reply_text("⛔ Acesso expirado! Contate: @natanbinario"); return
    
    user = get_user(user_id)
    if not user or not user.get('iq_email'): 
        await update.message.reply_text("❌ Use /configurar primeiro"); return
    
    atualizar_user(user_id, bot_ligado=1)
    await update.message.reply_text(
        f"✅ *Bot ligado!*\n\n"
        f"💰 Saldo: R$ {user.get('saldo', 0):.2f}\n"
        f"🤖 Auto operação ativada\n"
        f"📊 3/5 estratégias = Entra\n\n"
        f"/parar - Desligar\n/status - Resultados",
        parse_mode="Markdown"
    )

async def cmd_parar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    atualizar_user(user_id, bot_ligado=0)
    res = resultado_dia(user_id)
    await update.message.reply_text(
        f"🔴 *Bot desligado*\n📊 Hoje: {res['wins']}W/{res['losses']}L | R$ {res['lucro']:.2f}",
        parse_mode="Markdown"
    )

async def cmd_ajuda(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📚 *COMANDOS*\n\n"
        "/start - Iniciar (3 dias grátis)\n"
        "/configurar - Setup IQ Option\n"
        "/ligar - Ligar bot automático\n"
        "/parar - Parar bot\n"
        "/status - Ver resultados\n"
        "/ajuda - Esta mensagem\n\n"
        "💳 Para adquirir acesso: @natanbinario",
        parse_mode="Markdown"
    )

# ═══════════════════════════════════════════
# CONFIGURAÇÃO
# ═══════════════════════════════════════════

async def cmd_configurar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not user_ativo(update.effective_user.id):
        await update.message.reply_text("⛔ Acesso expirado! Contate: @natanbinario"); return ConversationHandler.END
    await update.message.reply_text("⚙️ *Configuração IQ Option*\n\n📧 Digite seu email:", parse_mode="Markdown")
    return CONF_EMAIL

async def conf_email(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data['email'] = update.message.text.strip()
    await update.message.reply_text("🔒 Digite sua senha:", parse_mode="Markdown")
    return CONF_SENHA

async def conf_senha(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data['senha'] = update.message.text.strip()
    try: await update.message.delete()
    except: pass
    kb = [[InlineKeyboardButton("🎯 DEMO", callback_data="conta_PRACTICE"), 
           InlineKeyboardButton("💰 REAL", callback_data="conta_REAL")]]
    await update.message.reply_text("📊 Tipo de conta:", reply_markup=InlineKeyboardMarkup(kb))
    return CONF_CONTA

async def conf_conta(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    ctx.user_data['conta'] = q.data.replace("conta_", "")
    await q.edit_message_text(f"✅ Conta: {ctx.user_data['conta']}\n\n💰 Valor de entrada (R$):\nEx: 2.00")
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
    atualizar_user(user_id, 
        iq_email=d['email'], iq_senha=d['senha'], iq_conta=d['conta'],
        valor_entrada=d['valor'], multiplicador=d['multi'], max_gales=d['gales'],
        stop_loss=d['sl'], stop_win=d['sw']
    )
    
    await update.message.reply_text(
        f"✅ *Configuração salva!*\n\n"
        f"📧 {d['email']}\n📊 {d['conta']}\n"
        f"💰 R$ {d['valor']}\n🔄 {d['multi']}x (max {d['gales']})\n"
        f"🛑 Stop L: R$ {d['sl']}\n🏆 Stop W: R$ {d['sw']}\n\n"
        f"Use /ligar para iniciar!",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def conf_cancelar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Configuração cancelada.")
    return ConversationHandler.END

# ═══════════════════════════════════════════
# PAINEL ADMIN
# ═══════════════════════════════════════════

async def cmd_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ Acesso negado!"); return
    
    users = listar_users()
    total = len(users)
    ativos = sum(1 for u in users if u['ativo'])
    
    texto = f"👑 *PAINEL ADMIN*\n\n📊 Total: {total} | 🟢 Ativos: {ativos}\n\n"
    
    for u in users[:10]:
        s = "🟢" if u['ativo'] else "🔴"
        b = "🤖" if u['bot'] else "💤"
        exp = (u['exp'] or '')[:10]
        texto += f"{s}{b} `{u['id']}` - {u['nome']}\n   📧 {u.get('email','?')} | Exp: {exp}\n\n"
    
    texto += "*Comandos admin:*\n/ativar ID DIAS\n/desativar ID\n/listar"
    
    await update.message.reply_text(texto, parse_mode="Markdown")

async def cmd_ativar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID: 
        await update.message.reply_text("⛔ Acesso negado!"); return
    
    if not ctx.args: 
        await update.message.reply_text("Uso: /ativar <user_id> <dias>\nEx: /ativar 123456789 30"); return
    
    try:
        target = int(ctx.args[0])
        dias = int(ctx.args[1]) if len(ctx.args) > 1 else 30
        ativar_user(target, dias)
        
        await update.message.reply_text(f"✅ Usuário `{target}` ativado por {dias} dias!", parse_mode="Markdown")
        
        try: 
            await ctx.bot.send_message(target, f"🎉 Sua licença foi ativada por {dias} dias!\nUse /ligar para começar!")
        except: 
            await update.message.reply_text("⚠️ Não foi possível avisar o usuário.")
            
    except Exception as e:
        await update.message.reply_text(f"❌ Erro: {e}\nUse: /ativar <user_id> <dias>")

async def cmd_desativar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID: 
        await update.message.reply_text("⛔ Acesso negado!"); return
    
    if not ctx.args: 
        await update.message.reply_text("Uso: /desativar <user_id>"); return
    
    try:
        target = int(ctx.args[0])
        desativar_user(target)
        await update.message.reply_text(f"✅ Usuário `{target}` desativado!", parse_mode="Markdown")
    except: 
        await update.message.reply_text("❌ Erro! Use: /desativar <user_id>")

async def cmd_listar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID: 
        await update.message.reply_text("⛔ Acesso negado!"); return
    
    users = listar_users()
    if not users:
        await update.message.reply_text("Nenhum usuário cadastrado.")
        return
    
    texto = f"👥 *USUÁRIOS ({len(users)})*\n\n"
    for u in users[:30]:
        s = "🟢" if u['ativo'] else "🔴"
        b = "🤖" if u['bot'] else "💤"
        exp = (u['exp'] or '')[:10]
        texto += f"{s}{b} `{u['id']}` {u['nome']}\n   📧 {u.get('email','?')} | {exp}\n\n"
    
    await update.message.reply_text(texto, parse_mode="Markdown")

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
        fallbacks=[CommandHandler("cancelar", conf_cancelar)],
    )
    
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("ligar", cmd_ligar))
    app.add_handler(CommandHandler("parar", cmd_parar))
    app.add_handler(CommandHandler("ajuda", cmd_ajuda))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CommandHandler("ativar", cmd_ativar))
    app.add_handler(CommandHandler("desativar", cmd_desativar))
    app.add_handler(CommandHandler("listar", cmd_listar))
    app.add_handler(conv)
    
    logger.info("🚀 Bot iniciado!")
    print(f"\n🤖 Bot Telegram pronto!")
    print(f"👑 Admin ID: {ADMIN_ID}")
    print(f"📝 /start /configurar /ligar /parar /status /admin\n")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
