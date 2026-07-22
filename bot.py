#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════╗
║       ⚛️  QUANTUM IQ BOT  ⚛️            ║
║   Telegram Sinais → IQ Option Auto      ║
║   🔐 Licença + Config via Telegram      ║
║   ☁️ Railway Ready | 🇧🇷 Brasília       ║
╚══════════════════════════════════════════╝
"""

import asyncio
import json
import logging
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

# ═══════════════════════════════════════════
# 🇧🇷 HORÁRIO DE BRASÍLIA
# ═══════════════════════════════════════════
os.environ['TZ'] = 'America/Sao_Paulo'
time.tzset()

# ═══════════════════════════════════════════
# CONFIGURAÇÕES DO BOT (VIA ENVIRONMENT)
# ═══════════════════════════════════════════
BOT_TOKEN   = os.environ.get('TELEGRAM_BOT_TOKEN', '8233598336:AAHUtMg14-2hcOFObRhrBGsO4JIEyyA7gtI')
ADMIN_ID    = int(os.environ.get('ADMIN_ID', '6058265294'))
TG_API_ID   = int(os.environ.get('TG_API_ID', '22453120'))
TG_API_HASH = os.environ.get('TG_API_HASH', '89826a4104518e9ed650cdb451ad8b53')
CANAL_LINK  = os.environ.get('CANAL_LINK', 'https://t.me/+_6C6EMQUg1syODdh')
DB_PATH     = os.environ.get('DB_PATH', 'quantum.db')

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, filters, ContextTypes
)
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.tl.types import Channel, Chat

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════
# 🗄️ BANCO DE DADOS
# ═══════════════════════════════════════════

def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS usuarios (
            telegram_id     INTEGER PRIMARY KEY,
            username        TEXT,
            nome            TEXT,
            cadastro        TEXT,
            expiracao       TEXT,
            ativo           INTEGER DEFAULT 0,
            trial_usado     INTEGER DEFAULT 0,
            iq_email        TEXT DEFAULT '',
            iq_senha        TEXT DEFAULT '',
            iq_conta        TEXT DEFAULT 'PRACTICE',
            valor_entrada   REAL DEFAULT 2.0,
            multiplicador   REAL DEFAULT 2.0,
            max_gales       INTEGER DEFAULT 1,
            stop_loss       REAL DEFAULT 0,
            stop_win        REAL DEFAULT 0,
            confianca_min   INTEGER DEFAULT 0,
            score_min       INTEGER DEFAULT 0,
            bot_ligado      INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS operacoes (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER,
            data        TEXT,
            ativo       TEXT,
            direcao     TEXT,
            expiracao   INTEGER,
            valor       REAL,
            resultado   TEXT,
            lucro       REAL
        );
    """)
    conn.commit()
    conn.close()

def get_user(uid):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM usuarios WHERE telegram_id=?", (uid,))
    row = c.fetchone()
    cols = [d[0] for d in c.description] if c.description else []
    conn.close()
    return dict(zip(cols, row)) if row else None

def criar_usuario(uid, username, nome):
    exp = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_conn()
    conn.execute("INSERT OR IGNORE INTO usuarios (telegram_id,username,nome,cadastro,expiracao,ativo,trial_usado) VALUES (?,?,?,?,?,1,1)", (uid, username or "", nome or "", now, exp))
    conn.commit()
    conn.close()

def atualizar_config(uid, **kwargs):
    conn = get_conn()
    sets = ", ".join(f"{k}=?" for k in kwargs)
    vals = list(kwargs.values()) + [uid]
    conn.execute(f"UPDATE usuarios SET {sets} WHERE telegram_id=?", vals)
    conn.commit()
    conn.close()

def ativar_usuario(uid, dias=30):
    exp = (datetime.now() + timedelta(days=dias)).strftime("%Y-%m-%d %H:%M:%S")
    conn = get_conn()
    conn.execute("UPDATE usuarios SET ativo=1, expiracao=? WHERE telegram_id=?", (exp, uid))
    conn.commit()
    conn.close()

def desativar_usuario(uid):
    conn = get_conn()
    conn.execute("UPDATE usuarios SET ativo=0, bot_ligado=0 WHERE telegram_id=?", (uid,))
    conn.commit()
    conn.close()

def is_ativo(uid):
    u = get_user(uid)
    if not u or not u["ativo"]: return False
    try:
        exp = datetime.strptime(u["expiracao"], "%Y-%m-%d %H:%M:%S")
        if datetime.now() > exp:
            desativar_usuario(uid)
            return False
    except: return False
    return True

def listar_usuarios():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT telegram_id,username,nome,expiracao,ativo,bot_ligado FROM usuarios ORDER BY cadastro DESC")
    rows = c.fetchall()
    conn.close()
    return rows

def usuarios_bot_ligado():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT telegram_id FROM usuarios WHERE bot_ligado=1 AND ativo=1")
    rows = [r[0] for r in c.fetchall()]
    conn.close()
    return rows

def salvar_operacao(uid, ativo, direcao, expiracao, valor, resultado, lucro):
    conn = get_conn()
    conn.execute("INSERT INTO operacoes (telegram_id,data,ativo,direcao,expiracao,valor,resultado,lucro) VALUES (?,?,?,?,?,?,?,?)", (uid, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), ativo, direcao, expiracao, valor, resultado, lucro))
    conn.commit()
    conn.close()

def resultado_hoje(uid):
    hoje = datetime.now().strftime("%Y-%m-%d")
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*), SUM(CASE WHEN resultado='win' THEN 1 ELSE 0 END), SUM(CASE WHEN resultado='loss' THEN 1 ELSE 0 END), SUM(lucro) FROM operacoes WHERE telegram_id=? AND data LIKE ?", (uid, f"{hoje}%"))
    row = c.fetchone()
    conn.close()
    t, w, l, lc = row
    return {"total": t or 0, "wins": w or 0, "losses": l or 0, "lucro": lc or 0.0}

# ═══════════════════════════════════════════
# PARSER DE SINAL
# ═══════════════════════════════════════════

def parse_sinal(texto):
    if re.search(r'\b(WIN|LOSS|LUCRO|PREJUÍZO)\b', texto.upper()):
        if "SINAL" not in texto.upper(): return None
    if "SINAL" not in texto.upper() and "QUANTUM" not in texto.upper(): return None
    s = {}
    m = re.search(r'Hor[áa]rio[:\s]+(\d{1,2}:\d{2})', texto)
    if m: s["horario"] = m.group(1)
    m = re.search(r'Ativo[:\s]+([\w\-\/]+)', texto)
    if m: s["ativo"] = m.group(1).strip()
    if "CALL" in texto.upper(): s["direcao"] = "call"
    elif "PUT" in texto.upper(): s["direcao"] = "put"
    m = re.search(r'Expira[çc][aã]o[:\s]+M?(\d+)', texto, re.IGNORECASE)
    s["expiracao"] = int(m.group(1)) if m else 1
    m = re.search(r'Confian[çc]a[:\s]+(\d+)%', texto, re.IGNORECASE)
    if m: s["confianca"] = int(m.group(1))
    m = re.search(r'Score\s+IA[:\s]+(\d+)/100', texto, re.IGNORECASE)
    if m: s["score"] = int(m.group(1))
    m = re.search(r'(\d+)\s+recupera[çc][aã]o', texto, re.IGNORECASE)
    if m: s["gales"] = int(m.group(1))
    else:
        m = re.search(r'Gale\s*[\(]?(\d+)[\)]?', texto, re.IGNORECASE)
        if m: s["gales"] = int(m.group(1))
        else: s["gales"] = 0
    return s if ("ativo" in s and "direcao" in s) else None

# ═══════════════════════════════════════════
# OPERADOR IQ OPTION
# ═══════════════════════════════════════════

class IQOperador:
    def __init__(self, user):
        self.user = user
        self.api = None
        self.lucro_dia = 0.0
        self.ops = 0
        self.wins = 0
        self.losses = 0

    def conectar(self):
        from iqoptionapi.stable_api import IQ_Option
        try:
            self.api = IQ_Option(self.user["iq_email"], self.user["iq_senha"])
            ok, reason = self.api.connect()
            if not ok: return False, str(reason)
            self.api.change_balance(self.user.get("iq_conta", "PRACTICE"))
            return True, self.api.get_balance()
        except Exception as e: return False, str(e)

    def desconectar(self):
        try:
            if self.api: self.api.close()
        except: pass

    def operar(self, sinal):
        user      = self.user
        ativo     = sinal["ativo"]
        direcao   = sinal["direcao"]
        exp       = sinal.get("expiracao", 1)
        valor     = user["valor_entrada"]
        max_gales = min(sinal.get("gales", 0), user["max_gales"])
        resultados = []
        tentativa  = 0

        while tentativa <= max_gales:
            val = round(valor * (user["multiplicador"] ** tentativa), 2)
            try:
                try: saldo_antes = self.api.get_balance()
                except: saldo_antes = 0
                ok, id_op = self.api.buy(val, ativo, direcao, exp)
                if not ok:
                    resultados.append({"erro": "Ordem rejeitada"})
                    break
                time.sleep(exp * 60 + 5)
                try:
                    saldo_depois = self.api.get_balance()
                    lucro = saldo_depois - saldo_antes
                    if lucro > 0: status = "win"
                    elif lucro < 0: status = "loss"
                    else: status = "equal"
                except:
                    resultados.append({"erro": "Erro ao verificar saldo"})
                    break

                if status == "win":
                    salvar_operacao(user["telegram_id"], ativo, direcao, exp, val, "win", abs(lucro))
                    resultados.append({"status":"win","valor":val,"lucro":abs(lucro),"gale":tentativa})
                    break
                elif status == "loss":
                    salvar_operacao(user["telegram_id"], ativo, direcao, exp, val, "loss", -val)
                    resultados.append({"status":"loss","valor":val,"gale":tentativa})
                    tentativa += 1
                elif status == "equal":
                    salvar_operacao(user["telegram_id"], ativo, direcao, exp, val, "equal", 0)
                    resultados.append({"status":"equal","valor":val,"gale":tentativa})
                    break
                else:
                    resultados.append({"status":status,"valor":val,"gale":tentativa})
                    break
            except Exception as e:
                resultados.append({"erro": str(e)})
                break
        return resultados

# ═══════════════════════════════════════════
# BOT TELEGRAM
# ═══════════════════════════════════════════

(CONF_EMAIL, CONF_SENHA, CONF_CONTA, CONF_VALOR, CONF_MULTI, CONF_GALES, CONF_SL, CONF_SW, CONF_CONF, CONF_SCORE) = range(10)

operadores_ativos = {}

def is_admin(uid): return uid == ADMIN_ID

def fmt_exp(exp_str):
    try:
        diff = datetime.strptime(exp_str, "%Y-%m-%d %H:%M:%S") - datetime.now()
        d = diff.days
        if d < 0: return "⛔ Expirado"
        if d == 0: return "⚠️ Expira hoje"
        return f"✅ {d} dias restantes"
    except: return "?"

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    nome = update.effective_user.first_name
    user = get_user(uid)
    if not user:
        criar_usuario(uid, update.effective_user.username, nome)
        await update.message.reply_text(f"👋 Olá, *{nome}*!\n\n🎁 *3 dias grátis!*\n\n1️⃣ /configurar — IQ Option\n2️⃣ /iniciar — Ligar bot\n3️⃣ /status — Resultados", parse_mode="Markdown")
    else:
        s = fmt_exp(user["expiracao"]) if user["ativo"] else "⛔ Inativo"
        await update.message.reply_text(f"👋 *{nome}*\n📊 Plano: {s}\n\nUse /status para ver resultados.", parse_mode="Markdown")

async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user = get_user(uid)
    if not user:
        await update.message.reply_text("❌ Use /start primeiro."); return
    res = resultado_hoje(uid)
    taxa = (res["wins"] / res["total"] * 100) if res["total"] > 0 else 0
    exp = fmt_exp(user["expiracao"]) if user["ativo"] else "⛔ Inativo"
    await update.message.reply_text(f"⚛️ *STATUS*\n{'─'*25}\n👤 Plano: {exp}\n🤖 Bot: {'🟢 Ligado' if user['bot_ligado'] else '🔴 Desligado'}\n💹 IQ: {'✅' if user.get('iq_email') else '❌'}\n{'─'*25}\n📊 *Hoje*\n🔢 {res['total']} ops | ✅ {res['wins']} | ❌ {res['losses']} | 🎯 {taxa:.0f}%\n💰 Lucro: R$ {res['lucro']:.2f}\n{'─'*25}\n⚙️ Entrada: R$ {user['valor_entrada']} | Gale: {user['multiplicador']}x ({user['max_gales']})", parse_mode="Markdown")

async def cmd_iniciar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user = get_user(uid)
    if not user: await update.message.reply_text("❌ Use /start primeiro."); return
    if not is_ativo(uid): await update.message.reply_text("⛔ Licença expirada."); return
    if not user.get("iq_email"): await update.message.reply_text("❌ Use /configurar primeiro."); return
    if user["bot_ligado"]: await update.message.reply_text("⚠️ Já está ligado!"); return
    await update.message.reply_text("⏳ Conectando à IQ Option...")
    op = IQOperador(user)
    ok, info = op.conectar()
    if not ok: await update.message.reply_text(f"❌ Erro: {info}"); return
    operadores_ativos[uid] = op
    atualizar_config(uid, bot_ligado=1)
    await update.message.reply_text(f"✅ *Bot ligado!*\n💰 Saldo: R$ {info:.2f}\n👀 Monitorando sinais...", parse_mode="Markdown")

async def cmd_parar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    op = operadores_ativos.pop(uid, None)
    if op: op.desconectar()
    atualizar_config(uid, bot_ligado=0)
    res = resultado_hoje(uid)
    await update.message.reply_text(f"🔴 *Bot desligado.*\n📊 {res['wins']}W/{res['losses']}L | R$ {res['lucro']:.2f}", parse_mode="Markdown")

async def cmd_resultado(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    res = resultado_hoje(uid)
    taxa = (res["wins"] / res["total"] * 100) if res["total"] > 0 else 0
    await update.message.reply_text(f"📊 *Hoje*\n🔢 {res['total']} | ✅ {res['wins']} | ❌ {res['losses']} | 🎯 {taxa:.0f}% | 💰 R$ {res['lucro']:.2f}", parse_mode="Markdown")

async def cmd_configurar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not get_user(update.effective_user.id): await update.message.reply_text("❌ Use /start primeiro."); return ConversationHandler.END
    await update.message.reply_text("⚙️ *Configuração IQ Option*\n\n📧 Digite seu *e-mail*:", parse_mode="Markdown")
    return CONF_EMAIL

async def conf_email(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["email"] = update.message.text.strip()
    await update.message.reply_text("🔒 Digite sua *senha*:", parse_mode="Markdown")
    return CONF_SENHA

async def conf_senha(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["senha"] = update.message.text.strip()
    kb = [[InlineKeyboardButton("📊 DEMO", callback_data="conta_PRACTICE"), InlineKeyboardButton("💰 REAL", callback_data="conta_REAL")]]
    await update.message.reply_text("📊 Tipo de conta?", reply_markup=InlineKeyboardMarkup(kb))
    return CONF_CONTA

async def conf_conta(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ctx.user_data["conta"] = q.data.replace("conta_", "")
    await q.edit_message_text(f"✅ Conta: *{ctx.user_data['conta']}*\n\n💰 Valor de entrada (R$):", parse_mode="Markdown")
    return CONF_VALOR

async def conf_valor(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try: ctx.user_data["valor"] = float(update.message.text.strip().replace(",","."))
    except: await update.message.reply_text("❌ Inválido."); return CONF_VALOR
    await update.message.reply_text("🔄 Multiplicador do Gale\nEx: `2` (2x):", parse_mode="Markdown")
    return CONF_MULTI

async def conf_multi(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try: ctx.user_data["multi"] = float(update.message.text.strip().replace(",","."))
    except: await update.message.reply_text("❌ Inválido."); return CONF_MULTI
    await update.message.reply_text("🔄 Máximo de Gales\nEx: `1` ou `2`:", parse_mode="Markdown")
    return CONF_GALES

async def conf_gales(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try: ctx.user_data["gales"] = int(update.message.text.strip())
    except: await update.message.reply_text("❌ Inválido."); return CONF_GALES
    await update.message.reply_text("🛑 *Stop Loss* (R$)\n`0` para desativar:", parse_mode="Markdown")
    return CONF_SL

async def conf_sl(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try: ctx.user_data["sl"] = float(update.message.text.strip().replace(",","."))
    except: await update.message.reply_text("❌ Inválido."); return CONF_SL
    await update.message.reply_text("🏆 *Stop Win* (R$)\n`0` para desativar:", parse_mode="Markdown")
    return CONF_SW

async def conf_sw(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try: ctx.user_data["sw"] = float(update.message.text.strip().replace(",","."))
    except: await update.message.reply_text("❌ Inválido."); return CONF_SW
    await update.message.reply_text("📊 *Confiança mínima* (%)\n`0` para ignorar:", parse_mode="Markdown")
    return CONF_CONF

async def conf_conf(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try: ctx.user_data["conf"] = int(update.message.text.strip())
    except: await update.message.reply_text("❌ Inválido."); return CONF_CONF
    await update.message.reply_text("🛡️ *Score IA mínimo*\n`0` para ignorar:", parse_mode="Markdown")
    return CONF_SCORE

async def conf_score(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    try: ctx.user_data["score"] = int(update.message.text.strip())
    except: await update.message.reply_text("❌ Inválido."); return CONF_SCORE
    d = ctx.user_data
    atualizar_config(uid, iq_email=d["email"], iq_senha=d["senha"], iq_conta=d["conta"], valor_entrada=d["valor"], multiplicador=d["multi"], max_gales=d["gales"], stop_loss=d["sl"], stop_win=d["sw"], confianca_min=d["conf"], score_min=d["score"])
    await update.message.reply_text(f"✅ *Configuração salva!*\n\n📧 {d['email']}\n📊 {d['conta']}\n💰 Entrada: R$ {d['valor']}\n🔄 Gale: {d['multi']}x (max {d['gales']})\n🛑 Stop L: R$ {d['sl']}\n🏆 Stop W: R$ {d['sw']}\n📊 Conf. mín: {d['conf']}%\n🛡️ Score mín: {d['score']}\n\nUse /iniciar!", parse_mode="Markdown")
    return ConversationHandler.END

async def conf_cancelar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Cancelado.")
    return ConversationHandler.END

async def cmd_ativar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if not ctx.args: await update.message.reply_text("Uso: /ativar <id> [dias]"); return
    tid = int(ctx.args[0]); dias = int(ctx.args[1]) if len(ctx.args) > 1 else 30
    ativar_usuario(tid, dias)
    await update.message.reply_text(f"✅ {tid} ativado por {dias} dias!")

async def cmd_desativar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    desativar_usuario(int(ctx.args[0]))
    await update.message.reply_text("✅ Desativado.")

async def cmd_usuarios(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    rows = listar_usuarios()
    if not rows: await update.message.reply_text("Nenhum usuário."); return
    texto = "👥 *USUÁRIOS*\n\n"
    for tid, username, nome, exp, ativo, bot_on in rows:
        texto += f"{'🟢' if ativo else '🔴'}{'🤖' if bot_on else '💤'} {nome or '?'} (ID: {tid})\n"
    await update.message.reply_text(texto, parse_mode="Markdown")

async def cmd_broadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    msg = " ".join(ctx.args)
    if not msg: await update.message.reply_text("Uso: /broadcast <msg>"); return
    ok = 0
    for (tid, *_) in listar_usuarios():
        try: await ctx.bot.send_message(tid, f"📢 {msg}"); ok += 1
        except: pass
    await update.message.reply_text(f"✅ Enviado para {ok}.")

# ═══════════════════════════════════════════
# LISTENER DE SINAIS (TELETHON)
# ═══════════════════════════════════════════

async def executar_para_usuario(uid, sinal, app):
    try:
        user = get_user(uid)
        if not user or not user["bot_ligado"]: return
        res = resultado_hoje(uid)
        if user["stop_loss"] > 0 and res["lucro"] <= -user["stop_loss"]:
            await app.bot.send_message(uid, f"🛑 *Stop Loss!* R$ {res['lucro']:.2f}", parse_mode="Markdown")
            atualizar_config(uid, bot_ligado=0); return
        if user["stop_win"] > 0 and res["lucro"] >= user["stop_win"]:
            await app.bot.send_message(uid, f"🏆 *Stop Win!* R$ {res['lucro']:.2f}", parse_mode="Markdown")
            atualizar_config(uid, bot_ligado=0); return

        if user.get("confianca_min", 0) > 0 and sinal.get("confianca", 100) < user["confianca_min"]:
            return
        if user.get("score_min", 0) > 0 and sinal.get("score", 100) < user["score_min"]:
            return

        await app.bot.send_message(uid, f"⚛️ *SINAL DETECTADO*\n{'─'*25}\n💰 Ativo: `{sinal.get('ativo')}`\n📈 Direção: *{sinal.get('direcao','').upper()}*\n⌛ M{sinal.get('expiracao')}\n📊 Confiança: {sinal.get('confianca','?')}%\n🛡️ Score: {sinal.get('score','?')}/100", parse_mode="Markdown")
        await app.bot.send_message(uid, f"🚀 *Operando...*\n💹 {sinal.get('ativo')} {sinal.get('direcao','').upper()} M{sinal.get('expiracao')}", parse_mode="Markdown")

        op = operadores_ativos.get(uid)
        if not op:
            op = IQOperador(user)
            ok, info = op.conectar()
            if not ok: await app.bot.send_message(uid, f"❌ Erro IQ: {info}"); return
            operadores_ativos[uid] = op

        loop = asyncio.get_event_loop()
        resultados = await loop.run_in_executor(None, op.operar, sinal)

        msg = f"📊 *RESULTADO*\n{'─'*25}\n"
        for r in resultados:
            if "erro" in r: msg += f"❌ {r['erro']}\n"
            elif r["status"] == "win":
                g = f" (Gale {r['gale']})" if r["gale"] > 0 else ""
                msg += f"✅ *WIN{g}* +R$ {r['lucro']:.2f}\n"
            elif r["status"] == "loss":
                g = f" (Gale {r['gale']})" if r["gale"] > 0 else ""
                msg += f"❌ *LOSS{g}* -R$ {r['valor']:.2f}\n"
        res_hoje = resultado_hoje(uid)
        msg += f"{'─'*25}\n💰 Lucro dia: R$ {res_hoje['lucro']:.2f}"
        await app.bot.send_message(uid, msg, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"executar_para_usuario({uid}): {e}")

async def rodar_listener(app):
    session_str = os.environ.get("TG_SESSION_STRING", "")
    session = StringSession(session_str) if session_str else "quantum_session"
    async with TelegramClient(session, TG_API_ID, TG_API_HASH) as client:
        logger.info("✅ Telethon conectado!")
        entity = None
        invite = CANAL_LINK.strip("/").split("+")[-1]
        try:
            result = await client(ImportChatInviteRequest(invite))
            entity = result.chats[0]
        except Exception as e:
            if "already" in str(e).lower():
                async for d in client.iter_dialogs():
                    if isinstance(d.entity, (Channel, Chat)): entity = d.entity; break
            else: logger.error(f"Canal: {e}"); return
        if not entity: logger.error("Canal não encontrado!"); return
        logger.info(f"👀 Escutando: {getattr(entity,'title','canal')}")

        @client.on(events.NewMessage(chats=entity))
        async def handler(event):
            texto = event.message.text or ""
            sinal = parse_sinal(texto)
            if not sinal: return
            uids = usuarios_bot_ligado()
            horario = sinal.get("horario", "")
            for uid in uids:
                try: await app.bot.send_message(uid, f"📡 *SINAL RECEBIDO*\n{'─'*25}\n💰 {sinal.get('ativo')}\n📈 {'🟢 CALL' if sinal.get('direcao')=='call' else '🔴 PUT'}\n⌛ M{sinal.get('expiracao')}\n⏳ Aguardando {horario}", parse_mode="Markdown")
                except: pass
            if horario:
                agora = datetime.now()
                h, m = map(int, horario.split(":"))
                alvo = agora.replace(hour=h, minute=m, second=0, microsecond=0)
                if alvo < agora: alvo += timedelta(days=1)
                diff = (alvo - agora).total_seconds()
                if 0 < diff <= 600: await asyncio.sleep(max(diff - 1, 0))
            for uid in uids: asyncio.create_task(executar_para_usuario(uid, sinal, app))

        await client.run_until_disconnected()

async def post_init(app):
    asyncio.create_task(rodar_listener(app))

def main():
    init_db()
    app = (Application.builder().token(BOT_TOKEN).post_init(post_init).build())
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
            CONF_CONF: [MessageHandler(filters.TEXT & ~filters.COMMAND, conf_conf)],
            CONF_SCORE: [MessageHandler(filters.TEXT & ~filters.COMMAND, conf_score)],
        },
        fallbacks=[CommandHandler("cancelar", conf_cancelar)],
    )
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("iniciar", cmd_iniciar))
    app.add_handler(CommandHandler("parar", cmd_parar))
    app.add_handler(CommandHandler("resultado", cmd_resultado))
    app.add_handler(conv)
    app.add_handler(CommandHandler("ativar", cmd_ativar))
    app.add_handler(CommandHandler("desativar", cmd_desativar))
    app.add_handler(CommandHandler("usuarios", cmd_usuarios))
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))
    logger.info("🚀 Bot iniciado!")
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES, bootstrap_retries=-1)

if __name__ == "__main__":
    main()
