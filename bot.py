#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
⚛️ QUANTUM IQ BOT — Multi-usuário (arquivo único)
Configure as variáveis na seção CONFIG abaixo antes de rodar.
"""                                                                                             
# ════════════════════════════════════════════
#  ⚙️  CONFIG — preencha aqui
# ════════════════════════════════════════════
BOT_TOKEN      = "8233598336:AAHUtMg14-2hcOFObRhrBGsO4JIEyyA7gtI"   # Token do @BotFather
ADMIN_ID       = 6058265294    # Seu ID numérico do Telegram (@userinfobot)
TG_API_ID      = 22453120    # my.telegram.org → App api_id                                     TG_API_HASH    = "89826a4104518e9ed650cdb451ad8b53"   # my.telegram.org → App api_hash
TG_SESSION_STR = "1AZWarzQBu6K7sCuqn6BbtMWuH1g3aYs3PYT2Csv4uuXASN1k3L4dTY4VV3gx3Qn6Jb2hNQM8VZDp2jdjk0u3ci4tGrGEl8hVl_Z8BWp1NwFK1rU2rb4QTQnAQk3qIpg931QyiqW1m-PLpuCa6WJcrKGSNvtO6g7T_7nG1EzIRLyXHVl-46c1NDK_JqKzB2ym7kZcjScMRL2KkUgXoBbTjwv2dASbEHnSHNGM_thmun6WUQlMDnMmD5VFsDIR-GiP1FcFidKdFpm0cJvJqdt31l7jJWqCgd_E1efAm5mZVYak_wEYffHYYUtwPlgD0webWFn2tiH7bFX4D6BoUqy_S7ubdiPuIdw="   # Gerado pelo gerar_sessao.py (deixe "" para usar arquivo local)
CANAL_LINK     = "https://t.me/+_6C6EMQUg1syODdh"                                               DB_PATH        = "quantum.db"
SESSION        = "quantum_server"                                                               # ════════════════════════════════════════════

import asyncio
import logging                                                                                  import re
import sqlite3
from datetime import datetime, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup                         from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,                                              MessageHandler, ConversationHandler, filters, ContextTypes
)
from telethon import TelegramClient, events
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.tl.types import Channel, Chat

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ════════════════════════════════════════════
#  🗄️  BANCO DE DADOS
# ════════════════════════════════════════════

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

def get_user(telegram_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM usuarios WHERE telegram_id=?", (telegram_id,))
    row = c.fetchone()
    cols = [d[0] for d in c.description] if c.description else []
    conn.close()
    return dict(zip(cols, row)) if row else None

def criar_usuario(telegram_id, username, nome):
    exp = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO usuarios "
        "(telegram_id,username,nome,cadastro,expiracao,ativo,trial_usado) "
        "VALUES (?,?,?,?,?,1,1)",
        (telegram_id, username or "", nome or "", now, exp)
    )
    conn.commit()
    conn.close()

def atualizar_config(telegram_id, **kwargs):
    conn = get_conn()
    sets = ", ".join(f"{k}=?" for k in kwargs)
    vals = list(kwargs.values()) + [telegram_id]
    conn.execute(f"UPDATE usuarios SET {sets} WHERE telegram_id=?", vals)
    conn.commit()
    conn.close()

def ativar_usuario(telegram_id, dias=30):
    exp = (datetime.now() + timedelta(days=dias)).strftime("%Y-%m-%d %H:%M:%S")
    conn = get_conn()
    conn.execute("UPDATE usuarios SET ativo=1, expiracao=? WHERE telegram_id=?", (exp, telegram_id))
    conn.commit()
    conn.close()

def desativar_usuario(telegram_id):
    conn = get_conn()
    conn.execute("UPDATE usuarios SET ativo=0, bot_ligado=0 WHERE telegram_id=?", (telegram_id,))
    conn.commit()
    conn.close()

def is_ativo(telegram_id):
    u = get_user(telegram_id)
    if not u or not u["ativo"]:
        return False
    try:
        exp = datetime.strptime(u["expiracao"], "%Y-%m-%d %H:%M:%S")
        if datetime.now() > exp:
            desativar_usuario(telegram_id)
            return False
    except:
        return False
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

def salvar_operacao(telegram_id, ativo, direcao, expiracao, valor, resultado, lucro):
    conn = get_conn()
    conn.execute(
        "INSERT INTO operacoes (telegram_id,data,ativo,direcao,expiracao,valor,resultado,lucro) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (telegram_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
         ativo, direcao, expiracao, valor, resultado, lucro)
    )
    conn.commit()
    conn.close()

def resultado_hoje(telegram_id):
    hoje = datetime.now().strftime("%Y-%m-%d")
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT COUNT(*),
               SUM(CASE WHEN resultado='win'  THEN 1 ELSE 0 END),
               SUM(CASE WHEN resultado='loss' THEN 1 ELSE 0 END),
               SUM(lucro)
        FROM operacoes WHERE telegram_id=? AND data LIKE ?
    """, (telegram_id, f"{hoje}%"))
    row = c.fetchone()
    conn.close()
    t, w, l, lc = row
    return {"total": t or 0, "wins": w or 0, "losses": l or 0, "lucro": lc or 0.0}

# ════════════════════════════════════════════
#  📡  PARSER DE SINAL
# ════════════════════════════════════════════

def parse_sinal(texto):
    if "SINAL" not in texto.upper():
        return None
    s = {}

    m = re.search(r'Hor[aá]rio[:\s]+(\d{1,2}:\d{2})', texto)
    if m: s["horario"] = m.group(1)

    m = re.search(r'Ativo[:\s]+([\w\-\/]+)', texto)
    if m: s["ativo"] = m.group(1).strip()

    if "CALL" in texto.upper(): s["direcao"] = "call"
    elif "PUT" in texto.upper(): s["direcao"] = "put"

    m = re.search(r'Expira[çc][aã]o[:\s]+M(\d+)', texto, re.IGNORECASE)
    s["expiracao"] = int(m.group(1)) if m else 1

    m = re.search(r'Confian[çc]a[:\s]+(\d+)%', texto, re.IGNORECASE)
    if m: s["confianca"] = int(m.group(1))

    m = re.search(r'Score\s+IA[:\s]+(\d+)/100', texto, re.IGNORECASE)
    if m: s["score"] = int(m.group(1))

    m = re.search(r'(\d+)\s+recupera[çc][aã]o', texto, re.IGNORECASE)
    s["gales"] = int(m.group(1)) if m else 0

    return s if ("ativo" in s and "direcao" in s) else None

# ════════════════════════════════════════════
#  💹  OPERADOR IQ OPTION
# ════════════════════════════════════════════

class IQOperador:
    def __init__(self, user):
        self.user = user
        self.api  = None

    def conectar(self):
        from iqoptionapi.stable_api import IQ_Option
        self.api = IQ_Option(self.user["iq_email"], self.user["iq_senha"])
        ok, reason = self.api.connect()
        if not ok:
            return False, str(reason)
        self.api.change_balance(self.user["iq_conta"])
        return True, self.api.get_balance()

    def desconectar(self):
        try:
            if self.api: self.api.close()
        except: pass

    def checar_resultado(self, id_op):
        try:
            res = self.api.check_win_v3(id_op)
            if isinstance(res, tuple):
                status, lucro = res
                return str(status).lower(), float(lucro)
            lucro = float(res)
            if lucro > 0:  return "win",   lucro
            if lucro < 0:  return "loss",  abs(lucro)
            return "equal", 0.0
        except Exception as e:
            logger.error(f"check_win: {e}")
            return "erro", 0.0

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
                ok, id_op = self.api.buy(val, ativo, direcao, exp)
                if not ok:
                    resultados.append({"erro": "Ordem rejeitada"})
                    break

                status, lucro = self.checar_resultado(id_op)

                if status == "win":
                    salvar_operacao(user["telegram_id"], ativo, direcao, exp, val, "win", lucro)
                    resultados.append({"status":"win","valor":val,"lucro":lucro,"gale":tentativa})
                    break
                elif status in ("loss","loose"):
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

# ════════════════════════════════════════════
#  🤖  BOT TELEGRAM — ESTADOS
# ════════════════════════════════════════════

(CONF_EMAIL, CONF_SENHA, CONF_CONTA,
 CONF_VALOR, CONF_MULTI, CONF_GALES,
 CONF_SL, CONF_SW) = range(8)

operadores_ativos: dict = {}

def is_admin(uid): return uid == ADMIN_ID

def fmt_exp(exp_str):
    try:
        diff = datetime.strptime(exp_str, "%Y-%m-%d %H:%M:%S") - datetime.now()
        d = diff.days
        if d < 0:  return "⛔ Expirado"
        if d == 0: return "⚠️ Expira hoje"
        return f"✅ {d} dias restantes"
    except: return "?"

# ── /start ────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    nome = update.effective_user.first_name
    user = get_user(uid)

    if not user:
        criar_usuario(uid, update.effective_user.username, nome)
        await update.message.reply_text(
            f"👋 Olá, *{nome}*! Bem-vindo ao *⚛️ Quantum IQ Bot*!\n\n"
            f"🎁 Você ganhou *3 dias grátis* para testar!\n\n"
            f"📋 *Próximos passos:*\n"
            f"1️⃣ /configurar — cadastre sua conta IQ Option\n"
            f"2️⃣ /iniciar — ligue o bot\n"
            f"3️⃣ /status — veja seus resultados\n\n"
            f"💬 Dúvidas? Fale com o suporte.",
            parse_mode="Markdown"
        )
    else:
        s = fmt_exp(user["expiracao"]) if user["ativo"] else "⛔ Inativo"
        await update.message.reply_text(
            f"👋 Olá novamente, *{nome}*!\n\n📊 Plano: {s}\n\nUse /status para ver seus resultados.",
            parse_mode="Markdown"
        )

# ── /status ───────────────────────────────

async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    user = get_user(uid)
    if not user:
        await update.message.reply_text("❌ Use /start primeiro.")
        return

    res  = resultado_hoje(uid)
    taxa = (res["wins"] / res["total"] * 100) if res["total"] > 0 else 0
    exp  = fmt_exp(user["expiracao"]) if user["ativo"] else "⛔ Inativo"
    conf = "✅ Configurado" if user.get("iq_email") else "❌ Não configurado"

    await update.message.reply_text(
        f"⚛️ *QUANTUM IQ BOT — STATUS*\n{'─'*30}\n"
        f"👤 Plano    : {exp}\n"
        f"🤖 Bot      : {'🟢 Ligado' if user['bot_ligado'] else '🔴 Desligado'}\n"
        f"💹 IQ Option: {conf} ({user.get('iq_conta','PRACTICE')})\n"
        f"{'─'*30}\n"
        f"📊 *Resultado de hoje:*\n"
        f"🔢 Operações : {res['total']}\n"
        f"✅ Wins      : {res['wins']}\n"
        f"❌ Losses    : {res['losses']}\n"
        f"🎯 Assertiv. : {taxa:.0f}%\n"
        f"💰 Lucro     : R$ {res['lucro']:.2f}\n"
        f"{'─'*30}\n"
        f"⚙️ Entrada: R$ {user['valor_entrada']} | Gale: {user['multiplicador']}x ({user['max_gales']} max)\n"
        f"🛑 Stop L: R$ {user['stop_loss']} | Stop W: R$ {user['stop_win']}",
        parse_mode="Markdown"
    )

# ── /iniciar ──────────────────────────────

async def cmd_iniciar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    user = get_user(uid)

    if not user:
        await update.message.reply_text("❌ Use /start primeiro."); return
    if not is_ativo(uid):
        await update.message.reply_text(
            "⛔ Seu acesso está inativo.\n\n💳 Para assinar por R$ 29,90/mês, fale com o suporte."
        ); return
    if not user.get("iq_email"):
        await update.message.reply_text("❌ Configure sua conta IQ Option com /configurar"); return
    if user["bot_ligado"]:
        await update.message.reply_text("⚠️ Bot já está ligado! Use /parar para desligar."); return

    await update.message.reply_text("⏳ Conectando à IQ Option...")
    op = IQOperador(user)
    ok, info = op.conectar()

    if not ok:
        await update.message.reply_text(f"❌ Erro ao conectar: {info}\n\nVerifique email/senha com /configurar")
        return

    operadores_ativos[uid] = op
    atualizar_config(uid, bot_ligado=1)
    await update.message.reply_text(
        f"✅ *Bot ligado!*\n\n💰 Saldo: R$ {info:.2f} ({user['iq_conta']})\n"
        f"👀 Monitorando sinais...\n\nUse /parar para desligar.",
        parse_mode="Markdown"
    )

# ── /parar ────────────────────────────────

async def cmd_parar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    user = get_user(uid)
    if not user or not user["bot_ligado"]:
        await update.message.reply_text("⚠️ Bot já está desligado."); return

    op = operadores_ativos.pop(uid, None)
    if op: op.desconectar()
    atualizar_config(uid, bot_ligado=0)
    res = resultado_hoje(uid)
    await update.message.reply_text(
        f"🔴 *Bot desligado.*\n\n📊 Resultado de hoje:\n"
        f"✅ {res['wins']}W / ❌ {res['losses']}L | 💰 R$ {res['lucro']:.2f}",
        parse_mode="Markdown"
    )

# ── /resultado ────────────────────────────

async def cmd_resultado(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    res = resultado_hoje(uid)
    taxa = (res["wins"] / res["total"] * 100) if res["total"] > 0 else 0
    await update.message.reply_text(
        f"📊 *Resultado de hoje:*\n\n"
        f"🔢 Total  : {res['total']} operações\n"
        f"✅ Wins   : {res['wins']}\n"
        f"❌ Losses : {res['losses']}\n"
        f"🎯 Taxa   : {taxa:.0f}%\n"
        f"💰 Lucro  : R$ {res['lucro']:.2f}",
        parse_mode="Markdown"
    )

# ── /configurar (ConversationHandler) ────

async def cmd_configurar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not get_user(update.effective_user.id):
        await update.message.reply_text("❌ Use /start primeiro.")
        return ConversationHandler.END
    await update.message.reply_text(
        "⚙️ *Configuração da IQ Option*\n\n📧 Digite seu *e-mail* da IQ Option:",
        parse_mode="Markdown"
    )
    return CONF_EMAIL

async def conf_email(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["email"] = update.message.text.strip()
    await update.message.reply_text("🔒 Digite sua *senha* da IQ Option:", parse_mode="Markdown")
    return CONF_SENHA

async def conf_senha(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["senha"] = update.message.text.strip()
    kb = [[InlineKeyboardButton("📊 DEMO", callback_data="conta_PRACTICE"),
           InlineKeyboardButton("💰 REAL", callback_data="conta_REAL")]]
    await update.message.reply_text("📊 Qual tipo de conta?", reply_markup=InlineKeyboardMarkup(kb))
    return CONF_CONTA

async def conf_conta(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ctx.user_data["conta"] = q.data.replace("conta_", "")
    await q.edit_message_text(
        f"✅ Conta: *{ctx.user_data['conta']}*\n\n💰 Valor de entrada (R$):\nEx: `2` ou `5`",
        parse_mode="Markdown"
    )
    return CONF_VALOR

async def conf_valor(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try: ctx.user_data["valor"] = float(update.message.text.strip().replace(",","."))
    except:
        await update.message.reply_text("❌ Inválido. Ex: `5`", parse_mode="Markdown")
        return CONF_VALOR
    await update.message.reply_text("🔄 Multiplicador do Gale:\nEx: `2` (2x)", parse_mode="Markdown")
    return CONF_MULTI

async def conf_multi(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try: ctx.user_data["multi"] = float(update.message.text.strip().replace(",","."))
    except:
        await update.message.reply_text("❌ Inválido. Ex: `2`", parse_mode="Markdown")
        return CONF_MULTI
    await update.message.reply_text("🔄 Máximo de Gales:\nEx: `1` ou `2`", parse_mode="Markdown")
    return CONF_GALES

async def conf_gales(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try: ctx.user_data["gales"] = int(update.message.text.strip())
    except:
        await update.message.reply_text("❌ Inválido. Ex: `1`", parse_mode="Markdown")
        return CONF_GALES
    await update.message.reply_text(
        "🛑 *Stop Loss* (R$) — para ao perder esse valor no dia\n`0` para desativar",
        parse_mode="Markdown"
    )
    return CONF_SL

async def conf_sl(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try: ctx.user_data["sl"] = float(update.message.text.strip().replace(",","."))
    except:
        await update.message.reply_text("❌ Inválido. Ex: `20`", parse_mode="Markdown")
        return CONF_SL
    await update.message.reply_text(
        "🏆 *Stop Win* (R$) — para ao lucrar esse valor no dia\n`0` para desativar",
        parse_mode="Markdown"
    )
    return CONF_SW

async def conf_sw(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    try: ctx.user_data["sw"] = float(update.message.text.strip().replace(",","."))
    except:
        await update.message.reply_text("❌ Inválido. Ex: `30`", parse_mode="Markdown")
        return CONF_SW

    d = ctx.user_data
    atualizar_config(uid,
        iq_email=d["email"], iq_senha=d["senha"], iq_conta=d["conta"],
        valor_entrada=d["valor"], multiplicador=d["multi"], max_gales=d["gales"],
        stop_loss=d["sl"], stop_win=d["sw"]
    )
    await update.message.reply_text(
        f"✅ *Configuração salva!*\n\n"
        f"📧 E-mail  : {d['email']}\n"
        f"📊 Conta   : {d['conta']}\n"
        f"💰 Entrada : R$ {d['valor']}\n"
        f"🔄 Gale    : {d['multi']}x (max {d['gales']})\n"
        f"🛑 Stop L  : R$ {d['sl']}\n"
        f"🏆 Stop W  : R$ {d['sw']}\n\n"
        f"Use /iniciar para ligar o bot! 🚀",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def conf_cancelar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Configuração cancelada.")
    return ConversationHandler.END

# ── ADMIN ─────────────────────────────────

async def cmd_ativar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if not ctx.args:
        await update.message.reply_text("Uso: /ativar <telegram_id> [dias]"); return
    try:
        tid  = int(ctx.args[0])
        dias = int(ctx.args[1]) if len(ctx.args) > 1 else 30
        ativar_usuario(tid, dias)
        u    = get_user(tid)
        nome = u["nome"] if u else str(tid)
        await update.message.reply_text(f"✅ {nome} ativado por {dias} dias!")
        await ctx.bot.send_message(tid,
            f"🎉 *Seu acesso foi ativado!*\n\n✅ Plano ativo por *{dias} dias*\n\nUse /iniciar para ligar o bot.",
            parse_mode="Markdown"
        )
    except Exception as e:
        await update.message.reply_text(f"Erro: {e}")

async def cmd_desativar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if not ctx.args:
        await update.message.reply_text("Uso: /desativar <telegram_id>"); return
    try:
        desativar_usuario(int(ctx.args[0]))
        await update.message.reply_text(f"✅ Usuário {ctx.args[0]} desativado.")
    except Exception as e:
        await update.message.reply_text(f"Erro: {e}")

async def cmd_usuarios(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    rows = listar_usuarios()
    if not rows:
        await update.message.reply_text("Nenhum usuário cadastrado."); return
    texto = "👥 USUÁRIOS CADASTRADOS\n\n"
    for tid, username, nome, exp, ativo, bot_on in rows:
        nome_s     = str(nome or "Sem nome")
        username_s = str(username or "sem_user")
        exp_s      = str(exp or "")[:10]
        texto += (f"{'🟢' if ativo else '🔴'}{'🤖' if bot_on else '💤'} "
                  f"{nome_s} (@{username_s})\n   ID: {tid} | Exp: {exp_s}\n\n")
    await update.message.reply_text(texto)

async def cmd_broadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if not ctx.args:
        await update.message.reply_text("Uso: /broadcast <mensagem>"); return
    msg = " ".join(ctx.args)
    ok = falha = 0
    for (tid, *_) in listar_usuarios():
        try:
            await ctx.bot.send_message(tid, f"📢 *Aviso:*\n\n{msg}", parse_mode="Markdown")
            ok += 1
        except: falha += 1
    await update.message.reply_text(f"✅ Enviado para {ok}. ❌ {falha} falhas.")

# ════════════════════════════════════════════
#  📡  LISTENER DE SINAIS (Telethon)
# ════════════════════════════════════════════

async def _enviar_com_retry(bot, uid, texto, tentativas=3, **kwargs):
    """Envia mensagem com até N tentativas em caso de NetworkError."""
    from telegram.error import NetworkError, TimedOut
    for i in range(tentativas):
        try:
            await bot.send_message(uid, texto, **kwargs)
            return
        except (NetworkError, TimedOut) as e:
            if i < tentativas - 1:
                await asyncio.sleep(2 ** i)  # backoff: 1s, 2s, 4s
            else:
                logger.warning(f"⚠️ Falha ao enviar msg para {uid} após {tentativas} tentativas: {e}")

async def executar_para_usuario(uid, sinal, app):
    try:
        user = get_user(uid)
        if not user or not user["bot_ligado"]:
            return

        res = resultado_hoje(uid)
        if user["stop_loss"] > 0 and res["lucro"] <= -user["stop_loss"]:
            await _enviar_com_retry(app.bot, uid,
                f"🛑 *Stop Loss atingido!*\nLucro no dia: R$ {res['lucro']:.2f}", parse_mode="Markdown")
            atualizar_config(uid, bot_ligado=0); return
        if user["stop_win"] > 0 and res["lucro"] >= user["stop_win"]:
            await _enviar_com_retry(app.bot, uid,
                f"🏆 *Stop Win atingido!*\nLucro no dia: R$ {res['lucro']:.2f}", parse_mode="Markdown")
            atualizar_config(uid, bot_ligado=0); return

        await _enviar_com_retry(app.bot, uid,
            f"⚛️ *SINAL DETECTADO*\n{'─'*25}\n"
            f"💰 Ativo    : `{sinal.get('ativo')}`\n"
            f"📈 Direção  : *{sinal.get('direcao','').upper()}*\n"
            f"⌛ Expiração: M{sinal.get('expiracao')}\n"
            f"📊 Confiança: {sinal.get('confianca','?')}%\n"
            f"🛡️ Score IA : {sinal.get('score','?')}/100", parse_mode="Markdown"
        )

        await _enviar_com_retry(app.bot, uid,
            f"🚀 *Iniciando operação...*\n"
            f"💹 Entrando em `{sinal.get('ativo')}` {sinal.get('direcao','').upper()} M{sinal.get('expiracao')}",
            parse_mode="Markdown"
        )

        op = operadores_ativos.get(uid)
        if not op:
            op = IQOperador(user)
            ok, info = op.conectar()
            if not ok:
                await _enviar_com_retry(app.bot, uid, f"❌ Erro IQ Option: {info}"); return
            operadores_ativos[uid] = op

        loop = asyncio.get_event_loop()
        resultados = await loop.run_in_executor(None, op.operar, sinal)

        msg = f"📊 *RESULTADO*\n{'─'*25}\n"
        for r in resultados:
            if "erro" in r:
                msg += f"❌ Erro: {r['erro']}\n"
            elif r["status"] == "win":
                g = f" (Gale {r['gale']})" if r["gale"] > 0 else ""
                msg += f"✅ *WIN{g}* +R$ {r['lucro']:.2f}\n"
            elif r["status"] == "loss":
                g = f" (Gale {r['gale']})" if r["gale"] > 0 else ""
                msg += f"❌ *LOSS{g}* -R$ {r['valor']:.2f}\n"
            elif r["status"] == "equal":
                msg += "〰️ *Empate*\n"

        res_hoje = resultado_hoje(uid)
        msg += f"{'─'*25}\n💰 Lucro no dia: R$ {res_hoje['lucro']:.2f}"
        await _enviar_com_retry(app.bot, uid, msg, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"❌ executar_para_usuario({uid}): {e}", exc_info=True)


async def rodar_listener(app):
    import os
    from telethon.sessions import StringSession
    # Usa string de sessão se disponível (Railway), senão arquivo local (Termux)
    session_str = TG_SESSION_STR or os.environ.get("TG_SESSION_STRING", "")
    session = StringSession(session_str) if session_str else SESSION
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
                    t = getattr(d.entity, 'title', '') or ''
                    if 'quantum' in t.lower() or 'ia' in t.lower():
                        entity = d.entity; break
                if not entity:
                    async for d in client.iter_dialogs():
                        if isinstance(d.entity, (Channel, Chat)):
                            entity = d.entity; break
            else:
                logger.error(f"Canal: {e}"); return

        if not entity:
            logger.error("Canal não encontrado!"); return

        logger.info(f"👀 Escutando: {getattr(entity,'title','canal')}")

        @client.on(events.NewMessage(chats=entity))
        async def handler(event):
            texto = event.message.text or ""
            sinal = parse_sinal(texto)
            if not sinal: return

            logger.info(f"Sinal: {sinal.get('ativo')} {sinal.get('direcao','').upper()}")

            uids = usuarios_bot_ligado()
            horario = sinal.get("horario", "")

            # ── Notificação imediata de sinal recebido ──
            for uid in uids:
                try:
                    direcao_emoji = "🟢 CALL" if sinal.get("direcao") == "call" else "🔴 PUT"
                    await app.bot.send_message(uid,
                        f"📡 *SINAL RECEBIDO*\n{'─'*25}\n"
                        f"💰 Ativo     : `{sinal.get('ativo')}`\n"
                        f"📈 Direção   : *{direcao_emoji}*\n"
                        f"⌛ Expiração : M{sinal.get('expiracao')}\n"
                        f"📊 Confiança : {sinal.get('confianca','?')}%\n"
                        f"🛡️ Score IA  : {sinal.get('score','?')}/100\n"
                        f"{'─'*25}\n"
                        f"⏳ *Aguardando horário de entrada: {horario}*",
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    logger.warning(f"Aviso sinal para {uid}: {e}")

            # ── Aguarda o horário de entrada ──
            if horario:
                agora = datetime.now()
                h, m  = map(int, horario.split(":"))
                alvo  = agora.replace(hour=h, minute=m, second=0, microsecond=0)
                if alvo < agora:
                    alvo += timedelta(days=1)
                diff = (alvo - agora).total_seconds()
                if 0 < diff <= 600:
                    logger.info(f"⏳ Aguardando {diff:.0f}s para entrar às {horario}")
                    await asyncio.sleep(max(diff - 1, 0))
                elif diff > 600:
                    logger.info(f"⚠️ Sinal muito antecipado ({diff:.0f}s) — ignorando")
                    for uid in uids:
                        try:
                            await app.bot.send_message(uid,
                                f"⚠️ Sinal ignorado — horário muito distante ({int(diff//60)} min).",
                                parse_mode="Markdown")
                        except: pass
                    return

            logger.info(f"Disparando para {len(uids)} usuário(s)...")
            for uid in uids:
                asyncio.create_task(executar_para_usuario(uid, sinal, app))

        await client.run_until_disconnected()

# ════════════════════════════════════════════
#  🚀  MAIN
# ════════════════════════════════════════════

async def post_init(app):
    asyncio.create_task(rodar_listener(app))

async def error_handler(update: object, ctx: ContextTypes.DEFAULT_TYPE):
    """Captura erros de rede e outros sem travar o bot."""
    err = ctx.error
    # Erros de rede são normais (queda de internet) — só loga e segue
    from telegram.error import NetworkError, TimedOut
    if isinstance(err, (NetworkError, TimedOut)):
        logger.warning(f"⚠️ Erro de rede (reconectando): {err}")
        return
    logger.error(f"❌ Erro inesperado: {err}", exc_info=err)

def main():
    if not BOT_TOKEN:
        raise ValueError("Preencha BOT_TOKEN na seção CONFIG do script!")
    if not TG_API_ID or not TG_API_HASH:
        raise ValueError("Preencha TG_API_ID e TG_API_HASH na seção CONFIG!")

    init_db()
    logger.info("✅ Banco iniciado.")

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    conv = ConversationHandler(
        entry_points=[CommandHandler("configurar", cmd_configurar)],
        states={
            CONF_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, conf_email)],
            CONF_SENHA: [MessageHandler(filters.TEXT & ~filters.COMMAND, conf_senha)],
            CONF_CONTA: [CallbackQueryHandler(conf_conta, pattern="^conta_")],
            CONF_VALOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, conf_valor)],
            CONF_MULTI: [MessageHandler(filters.TEXT & ~filters.COMMAND, conf_multi)],
            CONF_GALES: [MessageHandler(filters.TEXT & ~filters.COMMAND, conf_gales)],
            CONF_SL:    [MessageHandler(filters.TEXT & ~filters.COMMAND, conf_sl)],
            CONF_SW:    [MessageHandler(filters.TEXT & ~filters.COMMAND, conf_sw)],
        },
        fallbacks=[CommandHandler("cancelar", conf_cancelar)],
    )

    app.add_handler(CommandHandler("start",      cmd_start))
    app.add_handler(CommandHandler("status",     cmd_status))
    app.add_handler(CommandHandler("iniciar",    cmd_iniciar))
    app.add_handler(CommandHandler("parar",      cmd_parar))
    app.add_handler(CommandHandler("resultado",  cmd_resultado))
    app.add_handler(conv)
    app.add_handler(CommandHandler("ativar",     cmd_ativar))
    app.add_handler(CommandHandler("desativar",  cmd_desativar))
    app.add_handler(CommandHandler("usuarios",   cmd_usuarios))
    app.add_handler(CommandHandler("broadcast",  cmd_broadcast))
    app.add_error_handler(error_handler)

    logger.info("🚀 Bot iniciado!")
    app.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
        bootstrap_retries=-1,   # tenta infinitamente até conectar
    )

if __name__ == "__main__":
    main()
