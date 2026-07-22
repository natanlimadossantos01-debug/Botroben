#!/usr/bin/env python3
"""
⚛️ QUANTUM IA - Backend API + Bot
☁️ Railway Ready
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

os.environ['TZ'] = 'America/Sao_Paulo'
time.tzset()

SENHA_APP = "102030"
DB_PATH = "quantum.db"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
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
    conn.commit()
    conn.close()

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
    conn.execute("INSERT INTO logs (data, tipo, mensagem) VALUES (?,?,?)", (datetime.now().strftime("%H:%M:%S"), tipo, msg))
    conn.commit()
    conn.close()

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
    c.execute("SELECT COUNT(*), SUM(CASE WHEN resultado='win' THEN 1 ELSE 0 END), SUM(CASE WHEN resultado='loss' THEN 1 ELSE 0 END), SUM(lucro) FROM operacoes WHERE data LIKE ?", (f"{hoje}%",))
    t, w, l, lc = c.fetchone()
    conn.close()
    return {"total": t or 0, "wins": w or 0, "losses": l or 0, "lucro": lc or 0.0}

app = Flask(__name__)
CORS(app)

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    if data.get('senha') == SENHA_APP:
        return jsonify({"status": "ok", "token": "quantum_token"})
    return jsonify({"status": "erro", "msg": "Senha incorreta"}), 401

@app.route('/api/status', methods=['GET'])
def status():
    cfg = get_config()
    res = resultado_hoje()
    logs = get_logs(10)
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
    add_log("INFO", "Configuração atualizada")
    return jsonify({"status": "ok"})

@app.route('/api/ligar', methods=['POST'])
def ligar():
    update_config(bot_ligado=1)
    add_log("INFO", "Bot ligado pelo app")
    return jsonify({"status": "ok"})

@app.route('/api/desligar', methods=['POST'])
def desligar():
    update_config(bot_ligado=0)
    add_log("INFO", "Bot desligado pelo app")
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

if __name__ == "__main__":
    init_db()
    add_log("INFO", "Sistema iniciado")
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
