#!/usr/bin/env python3
"""
⚛️ QUANTUM IA - Backend COMPLETO
☁️ Railway Ready
✅ API + Sinais + IQ Option + PAINEL ADMIN
🔑 Sistema por EMAIL (sem licenças)
"""

import asyncio
import json
import logging
import os
import re
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from flask_cors import CORS

# ═══════════════════════════════════════════
# 🇧🇷 HORÁRIO DE BRASÍLIA
# ═══════════════════════════════════════════
os.environ['TZ'] = 'America/Sao_Paulo'
time.tzset()

# ═══════════════════════════════════════════
# CONFIGURAÇÕES VIA AMBIENTE (SEGURO!)
# ═══════════════════════════════════════════
SENHA_APP = os.environ.get('SENHA_APP', '102030')
SENHA_ADMIN = os.environ.get('SENHA_ADMIN', 'admin123')
DB_PATH = "quantum.db"
TELEGRAM_API_ID = int(os.environ.get('TG_API_ID', '0'))
TELEGRAM_API_HASH = os.environ.get('TG_API_HASH', '')
CANAL_LINK = os.environ.get('CANAL_LINK', 'https://t.me/+_6C6EMQUg1syODdh')
ADMIN_ID = int(os.environ.get('ADMIN_ID', '0'))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════
# BANCO DE DADOS
# ═══════════════════════════════════════════

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE,
            senha TEXT,
            nome TEXT,
            ativo INTEGER DEFAULT 1,
            expiracao TEXT,
            admin INTEGER DEFAULT 0,
            criado_em TEXT,
            ultimo_login TEXT
        );
        CREATE TABLE IF NOT EXISTS config (
            id INTEGER PRIMARY KEY CHECK (id=1),
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
            saldo REAL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS operacoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data TEXT,
            ativo TEXT,
            direcao TEXT,
            expiracao INTEGER,
            valor REAL,
            resultado TEXT,
            lucro REAL
        );
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data TEXT,
            tipo TEXT,
            mensagem TEXT
        );
    """)
    conn.execute("INSERT OR IGNORE INTO config (id) VALUES (1)")
    conn.execute("INSERT OR IGNORE INTO usuarios (email, senha, nome, ativo, admin, expiracao, criado_em) VALUES (?,?,?,1,1,?,?)",
                 ('admin@quantum.com', SENHA_ADMIN, 'Administrador', '2099-12-31 23:59:59', datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()

# ═══════════════════════════════════════════
# FUNÇÕES DE USUÁRIO
# ═══════════════════════════════════════════

def criar_usuario(email, senha, nome, dias=3):
    exp = (datetime.now() + timedelta(days=dias)).strftime("%Y-%m-%d %H:%M:%S")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("INSERT INTO usuarios (email, senha, nome, ativo, expiracao, criado_em) VALUES (?,?,?,1,?,?)",
                     (email, senha, nome, exp, now))
        conn.commit()
        conn.close()
        return True, "Usuário criado!"
    except sqlite3.IntegrityError:
        conn.close()
        return False, "Email já cadastrado"

def validar_usuario(email, senha):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM usuarios WHERE email=? AND senha=? AND ativo=1", (email, senha))
    row = c.fetchone()
    if not row:
        conn.close()
        return False, "Email ou senha inválidos"
    
    cols = [d[0] for d in c.description]
    user = dict(zip(cols, row))
    
    if not user['admin']:
        try:
            exp = datetime.strptime(user['expiracao'], "%Y-%m-%d %H:%M:%S")
            if datetime.now() > exp:
                c.execute("UPDATE usuarios SET ativo=0 WHERE email=?", (email,))
                conn.commit()
                conn.close()
                return False, "Acesso expirado"
        except:
            conn.close()
            return False, "Erro na data"
    
    c.execute("UPDATE usuarios SET ultimo_login=? WHERE email=?", (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), email))
    conn.commit()
    conn.close()
    return True, user

def ativar_usuario(email, dias=30):
    exp = (datetime.now() + timedelta(days=dias)).strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE usuarios SET ativo=1, expiracao=? WHERE email=?", (exp, email))
    conn.commit()
    conn.close()

def desativar_usuario(email):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE usuarios SET ativo=0 WHERE email=?", (email,))
    conn.commit()
    conn.close()

def listar_usuarios():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, email, nome, ativo, expiracao, admin, criado_em, ultimo_login FROM usuarios ORDER BY criado_em DESC")
    rows = c.fetchall()
    cols = [d[0] for d in c.description]
    conn.close()
    return [dict(zip(cols, r)) for r in rows]

# ═══════════════════════════════════════════
# FUNÇÕES AUXILIARES
# ═══════════════════════════════════════════

def get_config():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM config WHERE id=1")
    row = c.fetchone()
    cols = [d[0] for d in c.description]
    conn.close()
    return dict(zip(cols, row)) if row else {}

def update_config(**kwargs):
    conn = sqlite3.connect(DB_PATH)
    sets = ", ".join(f"{k}=?" for k in kwargs)
    vals = list(kwargs.values())
    conn.execute(f"UPDATE config SET {sets} WHERE id=1", vals)
    conn.commit()
    conn.close()

def add_log(tipo, msg):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT INTO logs (data, tipo, mensagem) VALUES (?,?,?)", 
                 (datetime.now().strftime("%H:%M:%S"), tipo, msg))
    conn.commit()
    conn.close()
    logger.info(f"[{tipo}] {msg}")

def get_logs(limit=50):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT data, tipo, mensagem FROM logs ORDER BY id DESC LIMIT ?", (limit,))
    rows = [{"hora": r[0], "tipo": r[1], "msg": r[2]} for r in c.fetchall()]
    conn.close()
    return rows

def resultado_hoje():
    hoje = datetime.now().strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""SELECT COUNT(*), 
                        SUM(CASE WHEN resultado='win' THEN 1 ELSE 0 END), 
                        SUM(CASE WHEN resultado='loss' THEN 1 ELSE 0 END), 
                        SUM(lucro) 
                 FROM operacoes WHERE data LIKE ?""", (f"{hoje}%",))
    t, w, l, lc = c.fetchone()
    conn.close()
    return {"total": t or 0, "wins": w or 0, "losses": l or 0, "lucro": lc or 0.0}

def salvar_operacao(ativo, direcao, expiracao, valor, resultado, lucro):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""INSERT INTO operacoes (data, ativo, direcao, expiracao, valor, resultado, lucro) 
                    VALUES (?,?,?,?,?,?,?)""",
                 (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), ativo, direcao, expiracao, valor, resultado, lucro))
    conn.commit()
    conn.close()

# ═══════════════════════════════════════════
# PARSER DE SINAL
# ═══════════════════════════════════════════

def parse_sinal(texto):
    if "SINAL" not in texto.upper() and "QUANTUM" not in texto.upper():
        return None
    s = {}
    m = re.search(r'Hor[áa]rio[:\s]+(\d{1,2}:\d{2})', texto)
    if m: s["horario"] = m.group(1)
    m = re.search(r'Ativo[:\s]+([\w\-\/]+)', texto)
    if m: s["ativo"] = m.group(1).strip()
    if "CALL" in texto.upper(): s["direcao"] = "call"
    elif "PUT" in texto.upper(): s["direcao"] = "put"
    m = re.search(r'Expira[çc][aã]o[:\s]+M?(\d+)', texto, re.IGNORECASE)
    s["expiracao"] = int(m.group(1)) if m else 1
    m = re.search(r'(\d+)\s+recupera[çc][aã]o', texto, re.IGNORECASE)
    s["gales"] = int(m.group(1)) if m else 0
    return s if ("ativo" in s and "direcao" in s) else None

# ═══════════════════════════════════════════
# OPERADOR IQ OPTION
# ═══════════════════════════════════════════

class IQOperador:
    def __init__(self):
        self.api = None

    def conectar(self):
        from iqoptionapi.stable_api import IQ_Option
        cfg = get_config()
        if not cfg.get('iq_email') or not cfg.get('iq_senha'):
            return False
        try:
            self.api = IQ_Option(cfg['iq_email'], cfg['iq_senha'])
            ok, _ = self.api.connect()
            if ok:
                self.api.change_balance(cfg.get('iq_conta', 'PRACTICE'))
                saldo = self.api.get_balance()
                update_config(conectado=1, saldo=saldo)
                add_log("OK", f"✅ Conectado! Saldo: R$ {saldo:.2f}")
                return True
            return False
        except:
            return False

    def operar(self, sinal):
        cfg = get_config()
        if not cfg.get('bot_ligado'): return
        
        ativo = sinal["ativo"]
        direcao = sinal["direcao"]
        exp = sinal.get("expiracao", 1)
        valor = cfg['valor_entrada']
        max_gales = min(sinal.get("gales", 0), cfg['max_gales'])
        
        res = resultado_hoje()
        if cfg['stop_loss'] > 0 and res['lucro'] <= -cfg['stop_loss']:
            add_log("AVISO", f"🛑 Stop Loss R$ {res['lucro']:.2f}")
            update_config(bot_ligado=0)
            return
        if cfg['stop_win'] > 0 and res['lucro'] >= cfg['stop_win']:
            add_log("AVISO", f"🏆 Stop Win R$ {res['lucro']:.2f}")
            update_config(bot_ligado=0)
            return
        
        tentativa = 0
        while tentativa <= max_gales:
            val = round(valor * (cfg['multiplicador'] ** tentativa), 2)
            try:
                saldo_antes = self.api.get_balance()
                ok, id_op = self.api.buy(val, ativo, direcao, exp)
                if not ok: break
                time.sleep(exp * 60 + 5)
                saldo_depois = self.api.get_balance()
                lucro = saldo_depois - saldo_antes
                
                if lucro > 0:
                    salvar_operacao(ativo, direcao, exp, val, "win", abs(lucro))
                    add_log("WIN", f"✅ {ativo} {direcao.upper()} +R$ {abs(lucro):.2f}")
                    update_config(saldo=saldo_depois)
                    break
                elif lucro < 0:
                    salvar_operacao(ativo, direcao, exp, val, "loss", -val)
                    add_log("LOSS", f"❌ {ativo} {direcao.upper()} -R$ {val:.2f}")
                    tentativa += 1
                else:
                    break
            except Exception as e:
                add_log("ERRO", f"Erro: {str(e)[:50]}")
                break
        try: update_config(saldo=self.api.get_balance())
        except: pass

# ═══════════════════════════════════════════
# LISTENER DE SINAIS
# ═══════════════════════════════════════════

def run_listener():
    async def _run():
        from telethon import TelegramClient, events
        from telethon.sessions import StringSession
        from telethon.tl.functions.messages import ImportChatInviteRequest
        from telethon.tl.types import Channel, Chat
        
        session_str = os.environ.get('TG_SESSION_STRING', '')
        session = StringSession(session_str) if session_str else "quantum_session"
        
        add_log("INFO", "🔄 Conectando Telegram...")
        
        async with TelegramClient(session, TELEGRAM_API_ID, TELEGRAM_API_HASH) as client:
            add_log("INFO", "✅ Telegram conectado!")
            
            entity = None
            invite = CANAL_LINK.strip("/").split("+")[-1] if CANAL_LINK else ""
            
            if invite:
                try:
                    result = await client(ImportChatInviteRequest(invite))
                    entity = result.chats[0]
                except Exception as e:
                    if "already" in str(e).lower():
                        async for d in client.iter_dialogs():
                            if isinstance(d.entity, (Channel, Chat)):
                                entity = d.entity
                                break

            if not entity:
                add_log("ERRO", "Canal não encontrado!")
                return

            add_log("INFO", f"👀 Escutando: {getattr(entity, 'title', 'canal')}")

            @client.on(events.NewMessage(chats=entity))
            async def handler(event):
                texto = event.message.text or ""
                sinal = parse_sinal(texto)
                if not sinal: return
                
                cfg = get_config()
                if not cfg.get('bot_ligado'): return

                add_log("SINAL", f"📡 {sinal.get('ativo')} {sinal.get('direcao','').upper()} M{sinal.get('expiracao')}")
                
                if sinal.get("horario"):
                    agora = datetime.now()
                    h, m = map(int, sinal["horario"].split(":"))
                    alvo = agora.replace(hour=h, minute=m, second=0, microsecond=0)
                    if alvo < agora: alvo += timedelta(days=1)
                    diff = (alvo - agora).total_seconds()
                    if 0 < diff <= 600:
                        await asyncio.sleep(max(diff - 1, 0))

                operador = IQOperador()
                if operador.conectar():
                    operador.operar(sinal)

            await client.run_until_disconnected()

    asyncio.run(_run())

# ═══════════════════════════════════════════
# API FLASK
# ═══════════════════════════════════════════

app = Flask(__name__)
CORS(app)

@app.route('/')
def home():
    return jsonify({"status": "online", "app": "Quantum IA", "versao": "3.0"})

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    email = data.get('email', '')
    senha = data.get('senha', '')
    
    if not email or not senha:
        return jsonify({"status": "erro", "msg": "Email e senha obrigatórios"}), 400
    
    valido, info = validar_usuario(email, senha)
    if valido:
        return jsonify({
            "status": "ok", 
            "token": "quantum_token",
            "user": {
                "email": info['email'],
                "nome": info['nome'],
                "admin": bool(info['admin']),
                "expiracao": info['expiracao']
            }
        })
    return jsonify({"status": "erro", "msg": info}), 401

@app.route('/api/status', methods=['GET'])
def status():
    cfg = get_config()
    res = resultado_hoje()
    logs = get_logs(15)
    return jsonify({
        "bot_ligado": bool(cfg.get('bot_ligado', 0)),
        "conectado": bool(cfg.get('conectado', 0)),
        "saldo": cfg.get('saldo', 0),
        "hoje": res,
        "config": {
            "email": cfg.get('iq_email', ''),
            "conta": cfg.get('iq_conta', 'PRACTICE'),
            "valor_entrada": cfg.get('valor_entrada', 2.0),
            "multiplicador": cfg.get('multiplicador', 2.0),
            "max_gales": cfg.get('max_gales', 1),
            "stop_loss": cfg.get('stop_loss', 0),
            "stop_win": cfg.get('stop_win', 0),
        },
        "logs": logs
    })

@app.route('/api/config', methods=['POST'])
def config():
    data = request.json
    update_config(**data)
    add_log("INFO", "⚙️ Configurações atualizadas")
    return jsonify({"status": "ok"})

@app.route('/api/ligar', methods=['POST'])
def ligar():
    cfg = get_config()
    if not cfg.get('iq_email'):
        return jsonify({"status": "erro", "msg": "Configure a IQ Option primeiro!"}), 400
    update_config(bot_ligado=1)
    add_log("INFO", "▶️ Bot ligado")
    return jsonify({"status": "ok"})

@app.route('/api/desligar', methods=['POST'])
def desligar():
    update_config(bot_ligado=0)
    add_log("INFO", "⏹️ Bot desligado")
    return jsonify({"status": "ok"})

@app.route('/api/logs', methods=['GET'])
def logs():
    return jsonify(get_logs(100))

@app.route('/api/historico', methods=['GET'])
def historico():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT data, ativo, direcao, expiracao, valor, resultado, lucro FROM operacoes ORDER BY id DESC LIMIT 50")
    rows = [{"data": r[0], "ativo": r[1], "direcao": r[2], "expiracao": r[3], "valor": r[4], "resultado": r[5], "lucro": r[6]} for r in c.fetchall()]
    conn.close()
    return jsonify(rows)

# ═══════════════════════════════════════════
# ENDPOINTS ADMIN
# ═══════════════════════════════════════════

@app.route('/api/admin/usuarios', methods=['GET'])
def admin_usuarios():
    return jsonify(listar_usuarios())

@app.route('/api/admin/ativar', methods=['POST'])
def admin_ativar():
    data = request.json
    email = data.get('email', '')
    dias = data.get('dias', 30)
    if not email:
        return jsonify({"status": "erro", "msg": "Email obrigatório"}), 400
    
    # Verifica se usuário existe, senão cria
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM usuarios WHERE email=?", (email,))
    row = c.fetchone()
    
    if row:
        ativar_usuario(email, dias)
    else:
        criar_usuario(email, '123456', email.split('@')[0], dias)
    
    conn.close()
    add_log("INFO", f"👤 Usuário {email} ativado por {dias} dias")
    return jsonify({"status": "ok", "msg": f"{email} ativado por {dias} dias!"})

@app.route('/api/admin/desativar', methods=['POST'])
def admin_desativar():
    data = request.json
    email = data.get('email', '')
    if not email:
        return jsonify({"status": "erro", "msg": "Email obrigatório"}), 400
    desativar_usuario(email)
    add_log("INFO", f"🚫 Usuário {email} desativado")
    return jsonify({"status": "ok", "msg": f"{email} desativado!"})

# ═══════════════════════════════════════════
# INICIAR
# ═══════════════════════════════════════════

if __name__ == "__main__":
    init_db()
    add_log("INFO", "🚀 Sistema iniciado")
    threading.Thread(target=run_listener, daemon=True).start()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
