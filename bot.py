#!/usr/bin/env python3
"""
🤖 QUANTUM IA - Bot Telegram Multi-Usuário COMPLETO
⚛️ Trader Professor com Motor de Trading Automático
👥 Cada usuário opera independente
✅ Tudo funcionando: Config, Painel Admin, Trading Real
"""

import asyncio
import json
import logging
import os
import re
import sqlite3
import threading
import time
import numpy as np
from datetime import datetime, timedelta, timezone
from collections import deque
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, filters, ContextTypes
)
from telegram.error import NetworkError, TimedOut

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
            conectado INTEGER DEFAULT 0,
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
    exp = datetime.now(FUSO_BR) + timedelta(days=3)
    exp_str = exp.strftime("%Y-%m-%d %H:%M:%S")
    now_str = datetime.now(FUSO_BR).strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""INSERT OR IGNORE INTO users (user_id, username, first_name, ativo, trial_usado, expiracao, cadastro) 
                    VALUES (?,?,?,1,1,?,?)""", (user_id, username or "", first_name or "", exp_str, now_str))
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
    exp = datetime.now(FUSO_BR) + timedelta(days=dias)
    exp_str = exp.strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE users SET ativo=1, expiracao=? WHERE user_id=?", (exp_str, user_id))
    conn.commit()
    conn.close()

def desativar_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE users SET ativo=0, bot_ligado=0 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def user_ativo(user_id):
    if user_id == ADMIN_ID: return True
    u = get_user(user_id)
    if not u or not u.get('ativo'): return False
    try:
        exp_str = u.get('expiracao', '')
        if not exp_str: return False
        exp = datetime.strptime(exp_str, "%Y-%m-%d %H:%M:%S")
        if datetime.now(FUSO_BR) > exp:
            desativar_user(user_id)
            return False
        return True
    except: return False

def listar_users():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, username, first_name, ativo, expiracao, bot_ligado, saldo, iq_email FROM users ORDER BY cadastro DESC")
    rows = []
    for r in c.fetchall():
        rows.append({"id": r[0], "user": r[1] or "", "nome": r[2] or "", "ativo": r[3], "exp": r[4] or "", "bot": r[5], "saldo": r[6] or 0, "email": r[7] or ""})
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
# 5 ESTRATÉGIAS
# ═══════════════════════════════════════════
class Mortalha:
    def sma(self, d, p):
        try:
            if len(d)>=p: return sum(d[-p:])/p
            return sum(d)/len(d) if d else 0
        except: return 0
    def wma(self, d, p):
        try:
            if len(d)<p: return sum(d)/len(d) if d else 0
            w=np.arange(1, p+1); return np.sum(np.array(d[-p:])*w)/np.sum(w)
        except: return 0
    def analisar(self, v):
        try:
            if len(v)<30: return None, 0
            c=np.array([x['close'] for x in v]); b1=np.zeros(len(c))
            for i in range(len(c)):
                if i>=33: b1[i]=self.sma(c[:i+1], 1)-self.sma(c[:i+1], 34)
            b2=np.zeros(len(b1))
            for i in range(len(b1)):
                if i>=3: b2[i]=self.wma(b1[:i+1], 4)
            if b1[-1]>b2[-1] and b1[-2]<=b2[-2]: return'CALL', min(45+abs(b1[-1]-b2[-1])*10000, 90)
            if b1[-1]<b2[-1] and b1[-2]>=b2[-2]: return'PUT', min(45+abs(b1[-1]-b2[-1])*10000, 90)
            return None, 0
        except: return None, 0

class Formiga:
    def ema(self, p, pe):
        try:
            if len(p)<pe: return sum(p)/len(p) if p else 0
            return np.mean(p[-pe:])
        except: return 0
    def analisar(self, v):
        try:
            if len(v)<15: return None, 0
            precos=np.array([x['close'] for x in v])
            ema5=self.ema(precos, 5); ema10=self.ema(precos, 10)
            dif=((ema5-ema10)/ema10)*100 if ema10>0 else 0
            sc=sp=0
            if dif>0.02: sc+=3
            elif dif>0.005: sc+=1
            elif dif<-0.02: sp+=3
            elif dif<-0.005: sp+=1
            if sc>=2 and sc>sp: return'CALL', min(50+sc*4, 85)
            if sp>=2 and sp>sc: return'PUT', min(50+sp*4, 85)
            return None, 0
        except: return None, 0

class Fortaleza:
    def rsi(self, p, pe=7):
        try:
            if len(p)<pe+1: return 50
            d=np.diff(list(p[-pe-1:])); g=np.where(d>0, d, 0); l=np.where(d<0, -d, 0)
            mg=np.mean(g) if len(g)>0 else 0; mp=np.mean(l) if len(l)>0 else 0
            if mp==0: return 100
            return 100-(100/(1+mg/mp))
        except: return 50
    def analisar(self, v):
        try:
            if len(v)<18: return None, 0
            precos=np.array([x['close'] for x in v])
            rsi_val=self.rsi(precos)
            m=np.mean(precos[-10:]) if len(precos)>=10 else np.mean(precos)
            s=np.std(precos[-10:]) if len(precos)>=10 else 0
            bs=m+2*s; bi=m-2*s
            sc=sp=0
            if rsi_val<30: sc+=3
            elif rsi_val<40: sc+=2
            if rsi_val>70: sp+=3
            elif rsi_val>60: sp+=2
            if precos[-1]<=bi*1.0004: sc+=3
            if precos[-1]>=bs*0.9996: sp+=3
            if sc>=4 and sc>sp: return'CALL', min(60+sc*3, 90)
            if sp>=4 and sp>sc: return'PUT', min(60+sp*3, 90)
            return None, 0
        except: return None, 0

class RaioNegro:
    def analisar(self, v):
        try:
            if len(v)<12: return None, 0
            precos=np.array([x['close'] for x in v])
            ema5=np.mean(precos[-5:]) if len(precos)>=5 else precos[-1]
            ema13=np.mean(precos[-13:]) if len(precos)>=13 else ema5
            macd=ema5-ema13; sinal=macd*0.5
            mom=precos[-1]-precos[-3] if len(precos)>=3 else 0
            sc=sp=0
            if macd>sinal and macd>0: sc+=3
            elif macd>sinal: sc+=1
            elif macd<sinal and macd<0: sp+=3
            elif macd<sinal: sp+=1
            if mom>0.00003: sc+=3
            elif mom>0: sc+=1
            elif mom<-0.00003: sp+=3
            elif mom<0: sp+=1
            if sc>=2 and sc>sp: return'CALL', min(48+sc*4, 85)
            if sp>=2 and sp>sc: return'PUT', min(48+sp*4, 85)
            return None, 0
        except: return None, 0

class Tsunami:
    def analisar(self, v):
        try:
            if len(v)<12: return None, 0
            precos=np.array([x['close'] for x in v])
            altas=sum(1 for i in range(-min(5, len(v)-1), 0) if precos[i]>precos[i-1])
            sc=sp=0
            if altas>=3: sc+=3
            elif altas<=2: sp+=3
            if sc>=2 and sc>sp: return'CALL', min(50+sc*3, 85)
            if sp>=2 and sp>sc: return'PUT', min(50+sp*3, 85)
            return None, 0
        except: return None, 0

class QuantumIA:
    def __init__(self):
        self.mortalha=Mortalha(); self.formiga=Formiga(); self.fortaleza=Fortaleza()
        self.raio_negro=RaioNegro(); self.tsunami=Tsunami(); self.min_estrategias=3
    def analisar_completo(self, v):
        try:
            if len(v)<30: return None, 0, 0
            resultados=[]; votos={'CALL':0, 'PUT':0}; confiancas={'CALL':[], 'PUT':[]}
            for est in [self.mortalha, self.formiga, self.fortaleza, self.raio_negro, self.tsunami]:
                try:
                    d, c=est.analisar(v)
                    if d: resultados.append(d); votos[d]+=1; confiancas[d].append(c)
                except: pass
            total=len(resultados)
            if total<self.min_estrategias: return None, 0, total
            if votos['CALL']>=self.min_estrategias and votos['CALL']>votos['PUT']:
                conf=np.mean(confiancas['CALL']); return'CALL', min(conf+(total-3)*4, 95), total
            if votos['PUT']>=self.min_estrategias and votos['PUT']>votos['CALL']:
                conf=np.mean(confiancas['PUT']); return'PUT', min(conf+(total-3)*4, 95), total
            return None, 0, total
        except: return None, 0, 0
    def melhor_par(self, velas_dict, bloqueados):
        melhor=None; melhor_score=0
        for nome, velas in velas_dict.items():
            if nome in bloqueados: continue
            if len(velas)>=30:
                d, cf, num=self.analisar_completo(velas)
                if d:
                    score=cf+(num*5)
                    if score>melhor_score: melhor_score=score; melhor={'ativo': nome, 'direcao': d, 'confianca': cf, 'estrategias': num}
        return melhor

# ═══════════════════════════════════════════
# IQ OPTION API
# ═══════════════════════════════════════════

class IQAPI:
    def __init__(self, email, senha, conta='PRACTICE'):
        self.email = email
        self.senha = senha
        self.conta = conta
        self.api = None
        self.velas = {nome: deque(maxlen=100) for nome in ["EURUSD","GBPUSD","EURGBP"]}
        self.ok = False
        self.ativo_map = {"EURUSD":"EURUSD-OTC", "GBPUSD":"GBPUSD-OTC", "EURGBP":"EURGBP-OTC"}

    def conectar(self):
        from iqoptionapi.stable_api import IQ_Option
        try:
            self.api = IQ_Option(self.email, self.senha)
            ok, _ = self.api.connect()
            if ok:
                self.api.change_balance(self.conta)
                self.ok = True
                return True, self.api.get_balance()
            return False, 0
        except Exception as e:
            return False, str(e)

    def atualizar_velas(self):
        if not self.ok: return
        for nome, ativo_id in self.ativo_map.items():
            try:
                c = self.api.get_candles(ativo_id, 60, 80, time.time())
                if c and len(c) > 0:
                    self.velas[nome].clear()
                    for x in c[-80:]:
                        if isinstance(x, dict):
                            self.velas[nome].append({
                                'time': datetime.fromtimestamp(x.get('from', 0), FUSO_BR),
                                'open': float(x['open']), 'high': float(x['max']),
                                'low': float(x['min']), 'close': float(x['close']),
                                'volume': int(x.get('volume', 0))
                            })
            except: pass

    def get_saldo(self):
        if not self.ok or not self.api: return 0
        try: return float(self.api.get_balance())
        except: return 0

    def comprar(self, ativo, direcao, exp, valor):
        if not self.ok: return False, None
        ativo_id = self.ativo_map.get(ativo, ativo)
        try:
            ok, order_id = self.api.buy(valor, ativo_id, direcao.lower(), exp)
            return ok, order_id
        except: return False, None

# ═══════════════════════════════════════════
# MOTOR DE TRADING (RODA EM BACKGROUND)
# ═══════════════════════════════════════════

user_bots = {}  # Dicionário com os bots ativos
user_locks = {}  # Locks para evitar operações simultâneas

async def trading_loop(user_id, app):
    """Loop principal de trading para um usuário"""
    logger.info(f"🔄 Trading loop iniciado para user {user_id}")
    
    while True:
        try:
            user = get_user(user_id)
            if not user or not user.get('bot_ligado') or not user_ativo(user_id):
                logger.info(f"⏹️ Trading loop encerrado para user {user_id}")
                break
            
            # Verificar stops
            res = resultado_dia(user_id)
            sl = user.get('stop_loss', 0)
            sw = user.get('stop_win', 0)
            
            if sl > 0 and res['lucro'] <= -sl:
                try: await app.bot.send_message(user_id, f"🛑 *Stop Loss atingido!*\n💰 R$ {res['lucro']:.2f}", parse_mode="Markdown")
                except: pass
                atualizar_user(user_id, bot_ligado=0)
                break
            
            if sw > 0 and res['lucro'] >= sw:
                try: await app.bot.send_message(user_id, f"🏆 *Stop Win atingido!*\n💰 R$ {res['lucro']:.2f}", parse_mode="Markdown")
                except: pass
                atualizar_user(user_id, bot_ligado=0)
                break
            
            # Obter API do usuário
            if user_id not in user_bots:
                iq = IQAPI(user.get('iq_email', ''), user.get('iq_senha', ''), user.get('iq_conta', 'PRACTICE'))
                ok, info = iq.conectar()
                if ok:
                    user_bots[user_id] = iq
                    atualizar_user(user_id, conectado=1, saldo=info)
                else:
                    logger.error(f"❌ Falha conexão IQ para user {user_id}")
                    await asyncio.sleep(60)
                    continue
            
            iq = user_bots.get(user_id)
            if not iq or not iq.ok:
                await asyncio.sleep(30)
                continue
            
            # Atualizar velas
            iq.atualizar_velas()
            
            # Buscar sinal
            m = QuantumIA()
            sinal = m.melhor_par(iq.velas, [])
            
            if sinal:
                logger.info(f"📡 Sinal user {user_id}: {sinal['ativo']} {sinal['direcao']} {sinal['confianca']:.0f}%")
                
                try:
                    await app.bot.send_message(user_id,
                        f"⚛️ *SINAL DETECTADO*\n\n"
                        f"💰 {sinal['ativo']}-OTC\n"
                        f"📈 {sinal['direcao']} {'🟢' if sinal['direcao']=='CALL' else '🔴'}\n"
                        f"📊 Confiança: {sinal['confianca']:.0f}%\n"
                        f"🧠 Estratégias: {sinal['estrategias']}/5\n\n"
                        f"⏳ Iniciando operação...",
                        parse_mode="Markdown")
                except: pass
                
                # Executar operação
                valor = user.get('valor_entrada', 2.0)
                max_gales = user.get('max_gales', 1)
                multiplicador = user.get('multiplicador', 2.0)
                
                for tentativa in range(max_gales + 1):
                    val = round(valor * (multiplicador ** tentativa), 2)
                    
                    saldo_antes = iq.get_saldo()
                    ok, order_id = iq.comprar(sinal['ativo'], sinal['direcao'], 1, val)
                    
                    if not ok: continue
                    
                    # Aguardar resultado
                    await asyncio.sleep(65)
                    
                    saldo_depois = iq.get_saldo()
                    lucro = saldo_depois - saldo_antes
                    
                    if lucro > 0:
                        salvar_trade(user_id, sinal['ativo'], sinal['direcao'], val, "win", abs(lucro))
                        atualizar_user(user_id, saldo=saldo_depois)
                        g = f" (Gale {tentativa})" if tentativa > 0 else ""
                        try:
                            await app.bot.send_message(user_id,
                                f"✅ *WIN{g}!*\n\n"
                                f"💰 {sinal['ativo']} {sinal['direcao']}\n"
                                f"💵 +R$ {abs(lucro):.2f}\n"
                                f"📊 Lucro dia: R$ {res['lucro']+abs(lucro):.2f}",
                                parse_mode="Markdown")
                        except: pass
                        break
                    elif lucro < 0:
                        if tentativa < max_gales:
                            logger.info(f"🔄 Gale {tentativa+1} para user {user_id}")
                            continue
                        salvar_trade(user_id, sinal['ativo'], sinal['direcao'], val, "loss", -val)
                        atualizar_user(user_id, saldo=saldo_depois)
                        try:
                            await app.bot.send_message(user_id,
                                f"❌ *LOSS*\n\n"
                                f"💰 {sinal['ativo']} {sinal['direcao']}\n"
                                f"💵 -R$ {val:.2f}\n"
                                f"📊 Lucro dia: R$ {res['lucro']-val:.2f}",
                                parse_mode="Markdown")
                        except: pass
                    break
            
            # Aguardar próximo ciclo
            await asyncio.sleep(30)
            
        except Exception as e:
            logger.error(f"❌ Erro trading user {user_id}: {e}")
            await asyncio.sleep(30)

# ═══════════════════════════════════════════
# ESTADOS DA CONFIGURAÇÃO
# ═══════════════════════════════════════════
(CONF_EMAIL, CONF_SENHA, CONF_CONTA, CONF_VALOR, 
 CONF_MULTI, CONF_GALES, CONF_SL, CONF_SW) = range(8)

# ═══════════════════════════════════════════
# HANDLERS
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
            f"/configurar - Setup IQ Option\n"
            f"/ligar - Iniciar bot automático\n"
            f"/parar - Parar bot\n"
            f"/status - Ver resultados",
            parse_mode="Markdown"
        )
    else:
        if user_ativo(user_id):
            try:
                exp = datetime.strptime(user.get('expiracao', ''), "%Y-%m-%d %H:%M:%S")
                dias = (exp - datetime.now(FUSO_BR)).days
                s = f"✅ {dias} dias restantes"
            except: s = "✅ Ativo"
        else:
            s = "⛔ Expirado"
        
        await update.message.reply_text(
            f"👋 *{nome}*\n📊 Plano: {s}\n🤖 Bot: {'🟢' if user.get('bot_ligado') else '🔴'}\n💰 Saldo: R$ {user.get('saldo', 0):.2f}\n\n/status",
            parse_mode="Markdown"
        )

async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    if not user: await update.message.reply_text("❌ Use /start primeiro"); return
    if not user_ativo(user_id): await update.message.reply_text("⛔ Acesso expirado!"); return
    
    res = resultado_dia(user_id)
    taxa = (res['wins']/res['total']*100) if res['total'] > 0 else 0
    
    await update.message.reply_text(
        f"⚛️ *STATUS*\n\n"
        f"🤖 {'🟢 Ligado' if user.get('bot_ligado') else '🔴 Desligado'}\n"
        f"💰 Saldo: R$ {user.get('saldo', 0):.2f}\n"
        f"💹 {user.get('iq_conta', 'PRACTICE')}\n\n"
        f"📊 *Hoje:*\n"
        f"📈 Ops: {res['total']}\n"
        f"✅ Wins: {res['wins']}\n"
        f"❌ Losses: {res['losses']}\n"
        f"🎯 Taxa: {taxa:.0f}%\n"
        f"💰 Lucro: R$ {res['lucro']:.2f}",
        parse_mode="Markdown"
    )

async def cmd_ligar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not user_ativo(user_id): await update.message.reply_text("⛔ Acesso expirado!"); return
    
    user = get_user(user_id)
    if not user or not user.get('iq_email'): 
        await update.message.reply_text("❌ Use /configurar primeiro"); return
    
    atualizar_user(user_id, bot_ligado=1)
    
    # Iniciar trading loop
    asyncio.create_task(trading_loop(user_id, ctx.application))
    
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
        "💳 @natanbinario",
        parse_mode="Markdown"
    )

# ═══════════════════════════════════════════
# CONFIGURAÇÃO
# ═══════════════════════════════════════════

async def cmd_configurar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not user_ativo(update.effective_user.id):
        await update.message.reply_text("⛔ Acesso expirado!"); return ConversationHandler.END
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
    kb = [[InlineKeyboardButton("🎯 DEMO", callback_data="conta_PRACTICE"), InlineKeyboardButton("💰 REAL", callback_data="conta_REAL")]]
    await update.message.reply_text("📊 Tipo de conta:", reply_markup=InlineKeyboardMarkup(kb))
    return CONF_CONTA

async def conf_conta(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    ctx.user_data['conta'] = q.data.replace("conta_", "")
    await q.edit_message_text(f"✅ {ctx.user_data['conta']}\n\n💰 Valor de entrada (R$):")
    return CONF_VALOR

async def conf_valor(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try: ctx.user_data['valor'] = float(update.message.text.strip().replace(',','.'))
    except: await update.message.reply_text("❌ Inválido"); return CONF_VALOR
    await update.message.reply_text("🔄 Multiplicador do Gale:\nEx: 2.0")
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
        f"/ligar para iniciar!",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def conf_cancelar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Cancelado.")
    return ConversationHandler.END

# ═══════════════════════════════════════════
# PAINEL ADMIN
# ═══════════════════════════════════════════

async def cmd_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Acesso negado!"); return
    
    users = listar_users()
    total = len(users)
    ativos = sum(1 for u in users if u['ativo'])
    bots = sum(1 for u in users if u['bot'])
    
    texto = f"👑 *PAINEL ADMIN*\n\n📊 Total: {total} | 🟢 {ativos} | 🤖 {bots}\n\n"
    for u in users[:10]:
        s = "🟢" if u['ativo'] else "🔴"
        b = "🤖" if u['bot'] else "💤"
        exp = (u['exp'] or '')[:10]
        texto += f"{s}{b} `{u['id']}` - {u['nome']}\n   📧 {u.get('email','?')} | {exp}\n\n"
    
    texto += "/ativar ID DIAS | /desativar ID | /listar"
    await update.message.reply_text(texto, parse_mode="Markdown")

async def cmd_ativar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: await update.message.reply_text("⛔ Acesso negado!"); return
    if not ctx.args: await update.message.reply_text("/ativar <user_id> <dias>"); return
    try:
        target = int(ctx.args[0])
        dias = int(ctx.args[1]) if len(ctx.args) > 1 else 30
        ativar_user(target, dias)
        await update.message.reply_text(f"✅ `{target}` ativado por {dias} dias!", parse_mode="Markdown")
        try: await ctx.bot.send_message(target, f"🎉 Licença ativada por {dias} dias!\nUse /ligar!")
        except: pass
    except: await update.message.reply_text("❌ /ativar <user_id> <dias>")

async def cmd_desativar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: await update.message.reply_text("⛔ Acesso negado!"); return
    if not ctx.args: await update.message.reply_text("/desativar <user_id>"); return
    try:
        target = int(ctx.args[0])
        desativar_user(target)
        await update.message.reply_text(f"✅ `{target}` desativado!", parse_mode="Markdown")
    except: await update.message.reply_text("❌ /desativar <user_id>")

async def cmd_listar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: await update.message.reply_text("⛔ Acesso negado!"); return
    users = listar_users()
    texto = f"👥 *USUÁRIOS ({len(users)})*\n\n"
    for u in users:
        s = "🟢" if u['ativo'] else "🔴"
        b = "🤖" if u['bot'] else "💤"
        exp = (u['exp'] or '')[:10]
        texto += f"{s}{b} `{u['id']}` {u['nome']} | {exp}\n"
    await update.message.reply_text(texto, parse_mode="Markdown")

# ═══════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════

def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    
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
    
    print(f"\n🤖 Bot Telegram COMPLETO!")
    print(f"👑 Admin ID: {ADMIN_ID}")
    print(f"📝 /start /configurar /ligar /parar /status /admin\n")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
