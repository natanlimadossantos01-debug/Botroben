#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║          🤖  R O B I N  B O T  v6.1                        ║
╠══════════════════════════════════════════════════════════════╣
║  FIX RAILWAY v6.1:                                         ║
║  • Timeouts com ThreadPoolExecutor em todas operações      ║
║  • MAX_USUARIOS reduzido para 10 (Railway free)            ║
║  • Watchdog mais agressivo (30s)                           ║
║  • Kill processos travados automaticamente                 ║
║  • Limpeza de recursos aprimorada                          ║
╚══════════════════════════════════════════════════════════════╝
"""

import asyncio
import json
import logging
import multiprocessing as mp
import os
import re
import sys
import time
import traceback
from datetime import datetime, timedelta
from enum import Enum, auto
from pathlib import Path
from typing import Optional, Dict, Any
import concurrent.futures

from telethon import TelegramClient, events, Button

# ══════════════════════════════════════════════
# CONFIGURAÇÕES - OTIMIZADAS PARA RAILWAY
# ══════════════════════════════════════════════

MAX_USUARIOS  = 8           # Railway free: 8 usuários simultâneos
TIMEOUT_ORDEM = 180         # segundos aguardando resultado
WATCHDOG_INT  = 30          # watchdog mais agressivo
SESSAO_LIMITE = 2           # horas sem interação
WORKER_TIMEOUT = 60         # timeout geral do worker
API_TIMEOUT = 25            # timeout para chamadas HTTP

DIR_CONFIG = Path("dados/configs")
DIR_STATS  = Path("dados/stats")
DIR_CONFIG.mkdir(parents=True, exist_ok=True)
DIR_STATS.mkdir(parents=True, exist_ok=True)

_CRED_FILE = Path(".robin_creds.json")

# ══════════════════════════════════════════════
# CREDENCIAIS (mesmo código anterior)
# ══════════════════════════════════════════════

def _is_tty() -> bool:
    return sys.stdin.isatty()

def _carregar_credenciais() -> tuple:
    creds: dict = {}
    if _CRED_FILE.exists():
        try:
            creds = json.loads(_CRED_FILE.read_text(encoding="utf-8"))
        except Exception:
            creds = {}

    def _salvar():
        _CRED_FILE.write_text(
            json.dumps(creds, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def _pedir(nome: str, dica: str) -> str:
        if not _is_tty():
            print(f"\n❌ ERRO: '{nome}' não configurado e não há terminal interativo.\n"
                  f"   No Railway, configure a variável de ambiente:\n"
                  f"   {dica}\n")
            sys.exit(1)
        return input(f"   {nome}: ").strip()

    token = os.getenv("ROBIN_BOT_TOKEN", "") or creds.get("bot_token", "")
    if not token or ":" not in token:
        if not _is_tty():
            print("\n❌ ERRO: ROBIN_BOT_TOKEN não configurado.\n"
                  "   Configure a env var ROBIN_BOT_TOKEN no Railway.\n")
            sys.exit(1)
        print("\n🔑 BOT TOKEN não encontrado.")
        token = _pedir("Token", "ROBIN_BOT_TOKEN=123456789:ABC...")
        if ":" not in token:
            print("❌ Token inválido."); sys.exit(1)
        creds["bot_token"] = token
        _salvar()

    api_id_str = os.getenv("TG_API_ID", "") or str(creds.get("api_id", ""))
    if not api_id_str.isdigit():
        if not _is_tty():
            print("\n❌ ERRO: TG_API_ID não configurado.\n"
                  "   Configure a env var TG_API_ID no Railway.\n")
            sys.exit(1)
        api_id_str = _pedir("API ID (somente números)", "TG_API_ID=12345678")
        if not api_id_str.isdigit():
            print("❌ API ID inválido."); sys.exit(1)
        creds["api_id"] = int(api_id_str)
        _salvar()

    api_hash = os.getenv("TG_API_HASH", "") or creds.get("api_hash", "")
    if not api_hash or len(api_hash) < 10:
        if not _is_tty():
            print("\n❌ ERRO: TG_API_HASH não configurado.\n"
                  "   Configure a env var TG_API_HASH no Railway.\n")
            sys.exit(1)
        api_hash = _pedir("API Hash", "TG_API_HASH=abcdef1234...")
        if len(api_hash) < 10:
            print("❌ API Hash inválido."); sys.exit(1)
        creds["api_hash"] = api_hash
        _salvar()

    return token, int(api_id_str), api_hash

# ══════════════════════════════════════════════
# LOGGER
# ══════════════════════════════════════════════

class _C:
    R="\033[0m"; B="\033[1m"; G="\033[92m"; V="\033[91m"
    Y="\033[93m"; C="\033[96m"; M="\033[95m"; GY="\033[90m"

class _Fmt(logging.Formatter):
    _M = {logging.DEBUG:_C.GY, logging.INFO:_C.C,
          logging.WARNING:_C.Y, logging.ERROR:_C.V, logging.CRITICAL:_C.M}
    def format(self, r):
        cor = self._M.get(r.levelno, _C.R)
        h   = datetime.now().strftime("%H:%M:%S")
        return f"{_C.GY}{h}{_C.R} {cor}{r.levelname:<8}{_C.R} {_C.GY}[{r.name}]{_C.R} {r.getMessage()}"

def _mk_log(name="ROBIN") -> logging.Logger:
    lg = logging.getLogger(name)
    if lg.handlers: return lg
    lg.setLevel(logging.INFO)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(_Fmt())
    lg.addHandler(sh)
    fh = logging.FileHandler("robin_bot.log", encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(message)s"))
    lg.addHandler(fh)
    return lg

log = _mk_log()

# ══════════════════════════════════════════════
# IQ WORKER COM TIMEOUTS
# ══════════════════════════════════════════════

def _iq_worker_fn(uid: int, cmd_q: mp.Queue, res_q: mp.Queue):
    api = None
    conta_atual = "PRACTICE"
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)

    def _send(data: dict):
        try:
            res_q.put(data, timeout=5)
        except Exception:
            pass

    while True:
        try:
            cmd = cmd_q.get(timeout=300)
        except Exception:
            break

        action = cmd.get("action", "")

        if action == "conectar":
            email = cmd["email"]; senha = cmd["senha"]
            conta = cmd.get("conta", "PRACTICE")
            try:
                from iqoptionapi.stable_api import IQ_Option
                
                # Conectar com timeout
                def _connect():
                    api_new = IQ_Option(email, senha)
                    api_new.connect()
                    return api_new
                
                future = executor.submit(_connect)
                api_new = future.result(timeout=API_TIMEOUT)
                
                if not api_new.check_connect():
                    _send({"ok": False, "erro": "❌ Email ou senha incorretos."})
                    continue
                
                api_new.change_balance(conta)
                api = api_new
                conta_atual = conta
                
                try:
                    saldo = float(api.get_balance())
                except Exception:
                    saldo = 0.0
                _send({"ok": True, "saldo": saldo, "conta": conta})
            except concurrent.futures.TimeoutError:
                _send({"ok": False, "erro": "❌ Timeout na conexão (IQ Option lenta)"})
            except ImportError:
                _send({"ok": False, "erro": "❌ iqoptionapi não instalada."})
            except Exception as e:
                _send({"ok": False, "erro": f"❌ Erro: {e}"})

        elif action == "saldo":
            if not api:
                _send({"ok": False, "saldo": 0.0}); continue
            try:
                def _get_balance():
                    return float(api.get_balance())
                saldo = executor.submit(_get_balance).result(timeout=API_TIMEOUT)
                _send({"ok": True, "saldo": saldo})
            except concurrent.futures.TimeoutError:
                _send({"ok": False, "saldo": 0.0, "erro": "Timeout"})
            except Exception as e:
                _send({"ok": False, "saldo": 0.0, "erro": str(e)})

        elif action == "ping":
            try:
                if not api:
                    _send({"ok": False, "saldo": 0.0}); continue
                def _check():
                    return bool(api and api.check_connect())
                alive = executor.submit(_check).result(timeout=10)
                saldo = float(api.get_balance()) if alive else 0.0
                _send({"ok": alive, "saldo": saldo})
            except Exception:
                _send({"ok": False, "saldo": 0.0})

        elif action == "comprar":
            if not api:
                _send({"ok": False, "erro": "Não conectado"}); continue
            try:
                def _buy():
                    return api.buy(
                        cmd["valor"], cmd["ativo"],
                        cmd["direcao"].lower(), cmd["tempo"]
                    )
                future = executor.submit(_buy)
                ok, order_id = future.result(timeout=API_TIMEOUT)
                _send({"ok": bool(ok), "order_id": order_id})
            except concurrent.futures.TimeoutError:
                _send({"ok": False, "order_id": None, "erro": "Timeout na compra"})
            except Exception as e:
                _send({"ok": False, "order_id": None, "erro": str(e)})

        elif action == "verificar":
            if not api:
                _send({"ok": False, "resultado": None}); continue
            order_id = cmd["order_id"]
            deadline = time.time() + cmd.get("timeout", TIMEOUT_ORDEM)
            resultado = None
            
            while time.time() < deadline:
                try:
                    def _check_win():
                        return api.check_win_v3(order_id)
                    r = executor.submit(_check_win).result(timeout=5)
                    if r is not None:
                        resultado = float(r)
                        break
                except (concurrent.futures.TimeoutError, Exception):
                    pass
                time.sleep(0.5)
            _send({"ok": resultado is not None, "resultado": resultado})

        elif action == "trocar_conta":
            if api:
                try:
                    def _change():
                        api.change_balance(cmd["conta"])
                        return float(api.get_balance())
                    saldo = executor.submit(_change).result(timeout=API_TIMEOUT)
                    conta_atual = cmd["conta"]
                    _send({"ok": True, "saldo": saldo, "conta": conta_atual})
                except Exception as e:
                    _send({"ok": False, "erro": str(e)})
            else:
                _send({"ok": False, "erro": "Não conectado"})

        elif action == "stop":
            _send({"ok": True})
            break

        else:
            _send({"ok": False, "erro": f"Ação desconhecida: {action}"})
    
    executor.shutdown(wait=False)

# ══════════════════════════════════════════════
# IQProcess - Versão com melhor gerenciamento
# ══════════════════════════════════════════════

class IQProcess:
    def __init__(self, uid: int):
        self.uid     = uid
        self.ok      = False
        self.saldo   = 0.0
        self.conta   = "PRACTICE"
        self._proc:  Optional[mp.Process] = None
        self._cmd_q: Optional[mp.Queue]   = None
        self._res_q: Optional[mp.Queue]   = None
        self._lock   = asyncio.Lock()
        self._last_ping = 0

    def _iniciar_processo(self):
        if self._proc and self._proc.is_alive():
            return
        try:
            ctx = mp.get_context("fork")
            self._cmd_q = ctx.Queue()
            self._res_q = ctx.Queue()
            self._proc = ctx.Process(
                target=_iq_worker_fn,
                args=(self.uid, self._cmd_q, self._res_q),
                daemon=True,
                name=f"iq-uid-{self.uid}"
            )
            self._proc.start()
            log.info(f"[IQProcess] Iniciado uid={self.uid} pid={self._proc.pid}")
        except Exception as e:
            log.error(f"[IQProcess] Falha ao iniciar: {e}")

    async def _cmd(self, cmd: dict, timeout: float = WORKER_TIMEOUT) -> dict:
        async with self._lock:
            self._iniciar_processo()
            if not self._proc or not self._proc.is_alive():
                return {"ok": False, "erro": "Processo morto"}
            
            loop = asyncio.get_event_loop()
            try:
                self._cmd_q.put_nowait(cmd)
            except Exception:
                return {"ok": False, "erro": "Fila cheia"}
            
            try:
                res = await asyncio.wait_for(
                    loop.run_in_executor(None, self._res_q.get),
                    timeout=timeout
                )
                return res
            except asyncio.TimeoutError:
                log.error(f"[IQProcess] Timeout uid={self.uid} cmd={cmd['action']}")
                # Se timeout, mata o processo para evitar travamento
                self._kill_process()
                return {"ok": False, "erro": "Timeout no worker IQ"}
            except Exception as e:
                return {"ok": False, "erro": str(e)}

    def _kill_process(self):
        """Mata o processo imediatamente"""
        if self._proc and self._proc.is_alive():
            try:
                self._proc.kill()
                self._proc.join(timeout=2)
                log.warning(f"[IQProcess] Processo morto uid={self.uid}")
            except Exception:
                pass
            self.ok = False
            self._proc = None

    async def conectar(self, email: str, senha: str, conta: str) -> tuple:
        res = await self._cmd(
            {"action": "conectar", "email": email, "senha": senha, "conta": conta},
            timeout=90
        )
        if res.get("ok"):
            self.ok    = True
            self.saldo = res.get("saldo", 0.0)
            self.conta = res.get("conta", conta)
            log.info(f"IQ conectado uid={self.uid} conta={self.conta} saldo=${self.saldo:.2f}")
            return True, f"✅ Conectado! Saldo: ${self.saldo:,.2f}"
        self.ok = False
        return False, res.get("erro", "❌ Erro desconhecido")

    async def get_saldo(self) -> float:
        res = await self._cmd({"action": "saldo"})
        return res.get("saldo", 0.0)

    async def ping(self) -> tuple:
        self._last_ping = time.time()
        res = await self._cmd({"action": "ping"}, timeout=15)
        self.saldo = res.get("saldo", 0.0)
        self.ok    = res.get("ok", False)
        return self.ok, self.saldo

    async def comprar(self, valor: float, ativo: str, direcao: str, tempo: int) -> tuple:
        res = await self._cmd({
            "action": "comprar",
            "valor": valor, "ativo": ativo,
            "direcao": direcao, "tempo": tempo
        }, timeout=30)
        return res.get("ok", False), res.get("order_id") or res.get("erro", "")

    async def verificar(self, order_id, timeout: int = TIMEOUT_ORDEM) -> Optional[float]:
        res = await self._cmd(
            {"action": "verificar", "order_id": order_id, "timeout": timeout},
            timeout=timeout + 20
        )
        return res.get("resultado")

    async def trocar_conta(self, conta: str) -> tuple:
        res = await self._cmd({"action": "trocar_conta", "conta": conta})
        if res.get("ok"):
            self.conta = conta
            self.saldo = res.get("saldo", 0.0)
        return res.get("ok", False), res.get("saldo", 0.0)

    def is_alive(self) -> bool:
        return self._proc is not None and self._proc.is_alive()

    def encerrar(self):
        if self._proc and self._proc.is_alive():
            try:
                self._cmd_q.put_nowait({"action": "stop"})
                self._proc.join(timeout=5)
            except Exception:
                pass
            if self._proc.is_alive():
                self._proc.kill()
                self._proc.join(timeout=1)
            try:
                self._cmd_q.close()
                self._res_q.close()
            except Exception:
                pass
            log.info(f"[IQProcess] Encerrado uid={self.uid}")

# ══════════════════════════════════════════════
# FSM, Config, Stats (mesmo código anterior)
# ══════════════════════════════════════════════

class Est(Enum):
    IDLE=auto(); EMAIL=auto(); SENHA=auto(); VALOR=auto()
    GALES=auto(); MULTIPLICADOR=auto(); ANTECIPACAO=auto()
    STOP_WIN=auto(); STOP_LOSS=auto(); CANAL=auto()
    EDIT_EMAIL=auto(); EDIT_SENHA=auto(); EDIT_VALOR=auto()
    EDIT_GALES=auto(); EDIT_MULT=auto(); EDIT_ANT=auto()
    EDIT_SW=auto(); EDIT_SL=auto(); EDIT_CANAL=auto()

DEFAULTS_CFG = {
    "email": "", "senha": "",
    "valor_entrada": 2.0, "gales": 2, "multiplicador": 2.0,
    "antecipacao": 2.0, "sincronizar_vela": True,
    "stop_win": 100.0, "stop_loss": 50.0,
    "tipo_conta": "PRACTICE", "canal_id": None,
    "modo_auto": False, "configurado": False,
    "ultima_interacao": None,
}

class Config:
    def __init__(self, uid: int):
        self._f = DIR_CONFIG / f"{uid}.json"
        self._d = self._load()

    def _load(self) -> dict:
        if self._f.exists():
            try:
                d = json.loads(self._f.read_text(encoding="utf-8"))
                for k, v in DEFAULTS_CFG.items():
                    d.setdefault(k, v)
                return d
            except Exception:
                pass
        return dict(DEFAULTS_CFG)

    def _save(self):
        tmp = str(self._f) + ".tmp"
        Path(tmp).write_text(json.dumps(self._d, indent=2, ensure_ascii=False), encoding="utf-8")
        Path(tmp).replace(self._f)

    def get(self, k, default=None): return self._d.get(k, default)
    def set(self, k, v):           self._d[k] = v; self._save()
    def set_many(self, d: dict):   self._d.update(d); self._save()
    def touch(self):
        self._d["ultima_interacao"] = datetime.now().isoformat(); self._save()

    @property
    def ok(self) -> bool: return bool(self._d.get("configurado"))

class Stats:
    def __init__(self, uid: int):
        self._f = DIR_STATS / f"{uid}.json"
        self._d = self._load(); self._reset_dia()

    def _load(self) -> dict:
        if self._f.exists():
            try: return json.loads(self._f.read_text(encoding="utf-8"))
            except: pass
        return {"d_trades":0,"d_wins":0,"d_losses":0,"d_profit":0.0,
                "t_trades":0,"t_wins":0,"t_losses":0,"t_profit":0.0,
                "reset_em": datetime.now().strftime("%Y-%m-%d")}

    def _save(self):
        tmp = str(self._f) + ".tmp"
        Path(tmp).write_text(json.dumps(self._d, indent=2, ensure_ascii=False), encoding="utf-8")
        Path(tmp).replace(self._f)

    def _reset_dia(self):
        hoje = datetime.now().strftime("%Y-%m-%d")
        if self._d.get("reset_em") != hoje:
            self._d.update(d_trades=0,d_wins=0,d_losses=0,d_profit=0.0,reset_em=hoje)
            self._save()

    def registrar(self, win: bool, profit: float):
        self._reset_dia()
        self._d["d_trades"]+=1; self._d["t_trades"]+=1
        self._d["d_profit"]+=profit; self._d["t_profit"]+=profit
        if win: self._d["d_wins"]+=1; self._d["t_wins"]+=1
        else:   self._d["d_losses"]+=1; self._d["t_losses"]+=1
        self._save()

    def resetar(self):
        if self._f.exists(): self._f.unlink()
        self._d = self._load(); self._reset_dia()

    @property
    def dados(self) -> dict: self._reset_dia(); return dict(self._d)

class UserSession:
    def __init__(self, uid: int):
        self.uid       = uid
        self.config    = Config(uid)
        self.stats     = Stats(uid)
        self.iq        = IQProcess(uid)
        self.estado    = Est.IDLE
        self.tmp: dict = {}
        self.modo_auto = self.config.get("modo_auto", False)
        self.operando  = False
        self._sem      = asyncio.Semaphore(1)

    def touch(self): self.config.touch()

    def encerrar(self):
        self.iq.encerrar()

# ══════════════════════════════════════════════
# MAPEADOR DE ATIVOS, PARSER (mesmo código)
# ══════════════════════════════════════════════

_ATIVOS = {
    "BTC":"BTC","ETH":"ETH","XRP":"XRP","BNB":"BNB","ADA":"ADA",
    "SOL":"SOL","DOGE":"DOGE","DOT":"DOT","AVAX":"AVAX","MATIC":"MATIC",
    "LINK":"LINK","UNI":"UNI","ATOM":"ATOM","TRX":"TRX","LTC":"LTC",
    "SHIB":"SHIB","PEPE":"PEPE","FLOKI":"FLOKI","BONK":"BONK",
    "ARB":"ARB","OP":"OP","INJ":"INJ","APT":"APT","SUI":"SUI",
    "NEAR":"NEAR","ICP":"ICP","STX":"STX","SEI":"SEI","TIA":"TIA",
    "AAPL":"AAPL-OTC","APPLE":"AAPL-OTC","TSLA":"TSLA-OTC","TESLA":"TSLA-OTC",
    "AMZN":"AMZN-OTC","AMAZON":"AMZN-OTC","GOOGL":"GOOGL-OTC","MSFT":"MSFT-OTC",
    "META":"META-OTC","NVDA":"NVDA-OTC",
    "US30":"US30-OTC","NAS100":"NAS100-OTC","NASDAQ":"NAS100-OTC",
    "SPX500":"SPX500-OTC","SP500":"SPX500-OTC","DAX":"DAX-OTC",
    "FTSE":"FTSE-OTC","NIKKEI":"NIKKEI-OTC","CAC":"CAC-OTC",
    "XAUUSD":"XAUUSD-OTC","GOLD":"XAUUSD-OTC","XAGUSD":"XAGUSD-OTC",
    "WTI":"WTI-OTC","BRENT":"BRENT-OTC",
    "EURUSD-OTC":"EURUSD-OTC","GBPUSD-OTC":"GBPUSD-OTC",
    "USDJPY-OTC":"USDJPY-OTC","USDCAD-OTC":"USDCAD-OTC",
    "USDCHF-OTC":"USDCHF-OTC","AUDUSD-OTC":"AUDUSD-OTC",
    "NZDUSD-OTC":"NZDUSD-OTC","EURGBP-OTC":"EURGBP-OTC",
    "EURUSD":"EURUSD","GBPUSD":"GBPUSD","USDJPY":"USDJPY",
    "AUDUSD":"AUDUSD","USDCAD":"USDCAD","USDCHF":"USDCHF",
    "NZDUSD":"NZDUSD","EURGBP":"EURGBP","EURJPY":"EURJPY","GBPJPY":"GBPJPY",
}

def mapear_ativo(ativo: str) -> tuple:
    up  = ativo.upper().strip()
    res = _ATIVOS.get(up)
    if not res:
        for k, v in _ATIVOS.items():
            if k in up or up in k: res = v; break
    if not res: res = up.replace("/", "")
    return res, ("OTC" if "-OTC" in res else "DIGITAL")

_IGNORAR = re.compile(r"\b(WIN|LOSS|APURAÇÃO|RESULTADO)\b", re.I)

def _extrair_tempo(txt: str) -> int:
    t = txt.upper()
    for n in [5, 3, 2, 1]:
        if f"M{n}" in t or f"{n}MIN" in t or f"{n} MIN" in t:
            return n
    return 1

def _extrair_horario(txt: str) -> Optional[str]:
    m = re.search(r"\b(\d{1,2}:\d{2})\b", txt)
    return m.group(1) if m else None

def _extrair_ativo(txt: str) -> Optional[str]:
    limpo  = re.sub(r"[^\w\s/.-]", " ", txt)
    tokens = limpo.upper().split()
    for tok in tokens:
        if len(tok) < 2: continue
        if re.match(r"^\d+:\d+$", tok): continue
        if re.match(r"^M\d+$", tok): continue
        if tok in ("CALL","PUT","COMPRA","VENDA","MIN","SIM","NAO","BOT"): continue
        if tok in _ATIVOS or re.match(r"^[A-Z]{2,10}(-OTC)?$", tok):
            return tok
    return None

def parse_sinal(texto: str) -> Optional[dict]:
    if _IGNORAR.search(texto):
        return None
    txt = texto.strip()

    direcao = None
    if re.search(r"\bCALL\b|\bCOMPRA\b|⬆️|↑", txt, re.I): direcao = "CALL"
    elif re.search(r"\bPUT\b|\bVENDA\b|⬇️|↓", txt, re.I): direcao = "PUT"
    elif "🟢" in txt: direcao = "CALL"
    elif "🔴" in txt: direcao = "PUT"
    if not direcao: return None

    ativo = None
    for pat in [
        r"(?:Ativo|Par|Asset|Pair)[:\s*]+([^\n,|/]+)",
        r"(?:💰|📊|🎯)\s*([A-Z]{2,10}(?:-OTC)?)",
    ]:
        m = re.search(pat, txt, re.I)
        if m:
            ativo = re.sub(r"[^\w.-]", "", m.group(1)).strip().upper()
            break
    if not ativo:
        ativo = _extrair_ativo(txt)
    if not ativo: return None

    return {
        "ativo":   ativo,
        "direcao": direcao,
        "tempo":   _extrair_tempo(txt),
        "horario": _extrair_horario(txt),
    }

# ══════════════════════════════════════════════
# MOTOR DE OPERAÇÃO (mesmo código)
# ══════════════════════════════════════════════

async def executar_operacao(session: UserSession, sinal: dict, send):
    async with session._sem:
        cfg   = session.config
        stats = session.stats
        iq    = session.iq

        if not iq.ok:
            await send("⚠️ IQ Option desconectada. Reconectando...")
            return

        d  = stats.dados
        sw = float(cfg.get("stop_win",  100.0))
        sl = float(cfg.get("stop_loss",  50.0))
        if d["d_profit"] >= sw:
            await send(f"🏆 Stop Win já atingido (${d['d_profit']:,.2f}). Bot pausado.")
            cfg.set("modo_auto", False); session.modo_auto = False; return
        if d["d_profit"] <= -sl:
            await send(f"🛑 Stop Loss já atingido (${d['d_profit']:,.2f}). Bot pausado.")
            cfg.set("modo_auto", False); session.modo_auto = False; return

        ativo_raw    = sinal["ativo"]
        direcao      = sinal["direcao"]
        tempo        = sinal["tempo"]
        ativo_iq, _  = mapear_ativo(ativo_raw)
        valor_base   = float(cfg.get("valor_entrada",  2.0))
        max_gales    = int(cfg.get("gales",            2))
        multiplicador= float(cfg.get("multiplicador",  2.0))
        antecipacao  = float(cfg.get("antecipacao",    2.0))
        sinc_vela    = bool(cfg.get("sincronizar_vela", True))
        perda_acum   = 0.0
        session.operando = True

        try:
            if sinc_vela:
                alvo = await _calcular_entrada(sinal, antecipacao)
                if alvo:
                    espera = (alvo - datetime.now()).total_seconds()
                    if 0.05 < espera <= 120:
                        await send(
                            f"🕯️ Aguardando {alvo.strftime('%H:%M:%S')}\n"
                            f"⏱️ Antecipação: {antecipacao:.1f}s"
                        )
                        while datetime.now() < alvo:
                            await asyncio.sleep(0.001)
                    elif espera > 120:
                        await send("⚠️ Sinal distante — entrada imediata.")

            for tentativa in range(max_gales + 1):
                valor = (valor_base if tentativa == 0
                         else round(valor_base * (multiplicador ** tentativa), 2))
                label = "Entrada" if tentativa == 0 else f"Gale {tentativa}"

                if tentativa > 0:
                    await send(
                        f"🔄 *{label}* — {multiplicador}x → ${valor:,.2f}\n⚡ Vela atual!"
                    )

                order_id    = None
                saldo_antes = await iq.get_saldo()

                for tentativa_buy in range(3):
                    if tentativa == 0 and tentativa_buy == 0:
                        await send(
                            f"📈 *{label}* | {ativo_raw} {direcao} | ${valor:,.2f} | {tempo}min"
                        )
                    ok, retorno = await iq.comprar(valor, ativo_iq, direcao, tempo)
                    if ok:
                        order_id = retorno; break
                    else:
                        erro = str(retorno).lower()
                        if "late" in erro or "closed" in erro:
                            await send(f"⏳ Buy late (tentativa {tentativa_buy+1}/3)...")
                            await asyncio.sleep(0.3)
                        else:
                            await send(f"❌ Falha na ordem: {retorno}")
                            session.operando = False; return

                if order_id is None:
                    await send("❌ Não foi possível abrir ordem após 3 tentativas.")
                    break

                resultado = await iq.verificar(order_id)
                if resultado is None:
                    saldo_depois = await iq.get_saldo()
                    resultado    = saldo_depois - saldo_antes

                iq.saldo = await iq.get_saldo()
                delta    = float(resultado)

                if delta > 0:
                    lucro_final = delta - perda_acum
                    stats.registrar(True, lucro_final)
                    d    = stats.dados
                    tipo = "SEM GALE" if tentativa == 0 else f"WIN G{tentativa}"
                    await send(_fmt_resultado(
                        True, tipo, ativo_raw, direcao, tempo, valor,
                        lucro_final, d["d_profit"], iq.saldo, cfg.get("tipo_conta","PRACTICE")
                    ))
                    if d["d_profit"] >= sw:
                        await send(f"🏆 *Stop Win!* +${d['d_profit']:,.2f}\n⛔ Bot pausado.")
                        cfg.set("modo_auto", False); session.modo_auto = False
                    break
                else:
                    perda_acum += abs(delta)
                    if tentativa < max_gales:
                        await asyncio.sleep(1.0)
                        continue
                    stats.registrar(False, -perda_acum)
                    d = stats.dados
                    await send(_fmt_resultado(
                        False, "LOSS", ativo_raw, direcao, tempo, valor,
                        -perda_acum, d["d_profit"], iq.saldo, cfg.get("tipo_conta","PRACTICE")
                    ))
                    if d["d_profit"] <= -sl:
                        await send(f"🛑 *Stop Loss!* {d['d_profit']:,.2f}\n⛔ Bot pausado.")
                        cfg.set("modo_auto", False); session.modo_auto = False

        except Exception as e:
            log.error(f"Erro op uid={session.uid}: {e}\n{traceback.format_exc()}")
            await send(f"❌ Erro interno: {e}")
        finally:
            session.operando = False

async def _calcular_entrada(sinal: dict, ant: float) -> Optional[datetime]:
    try:
        horario = sinal.get("horario")
        if horario:
            nums = re.findall(r"\d+", horario)
            if len(nums) >= 2:
                hora, minuto = int(nums[0]), int(nums[1])
                agora = datetime.now()
                alvo  = agora.replace(hour=hora, minute=minuto, second=0, microsecond=0)
                if alvo <= agora:
                    alvo += timedelta(days=1)
                return alvo - timedelta(seconds=ant)
        agora = datetime.now()
        seg   = agora.minute * 60 + agora.second + agora.microsecond / 1e6
        bloco = sinal["tempo"] * 60
        return agora + timedelta(seconds=(bloco - seg % bloco) - ant)
    except:
        return None

def _fmt_resultado(win, tipo, ativo, direcao, tempo, valor, lucro, dia, saldo, conta):
    e1 = "🟢" if win else "🔴"
    e2 = "✅" if win else "⛔"
    c  = "Treinamento" if conta == "PRACTICE" else "Real"
    ls = (f"+${lucro:,.2f}" if lucro >= 0 else f"-${abs(lucro):,.2f}")
    ds = (f"+${dia:,.2f}"   if dia   >= 0 else f"-${abs(dia):,.2f}")
    return (
        f"{e1} *APURAÇÃO ROBIN* {e1}\n\n"
        f"══ {tipo} ══\n\n"
        f"{e2} M{tempo} {ativo} {direcao}\n\n"
        f"💵 Entrada: ${valor:,.2f}\n"
        f"💲 Ordem: {ls}\n"
        f"📊 Resultado do dia: {ds}\n"
        f"🏦 Saldo: ${saldo:,.2f}\n"
        f"👤 Conta {c}"
    )

# ══════════════════════════════════════════════
# BOT PRINCIPAL
# ══════════════════════════════════════════════

class RobinBot:
    def __init__(self):
        self.sessions: Dict[int, UserSession] = {}
        self.client:   Optional[TelegramClient] = None
        self.admin_id: Optional[int]            = None
        self._token   = ""
        self._api_id  = 0
        self._api_hash= ""

    async def _get(self, uid: int) -> Optional[UserSession]:
        if uid not in self.sessions:
            if len(self.sessions) >= MAX_USUARIOS:
                await self.client.send_message(
                    uid, f"⚠️ Servidor lotado ({MAX_USUARIOS} usuários). Tente mais tarde."
                )
                return None
            self.sessions[uid] = UserSession(uid)
            log.info(f"Nova sessão uid={uid} | total={len(self.sessions)}")
        self.sessions[uid].touch()
        return self.sessions[uid]

    async def _send(self, uid: int, texto: str, **kw):
        try:
            await self.client.send_message(uid, texto, parse_mode="md", **kw)
        except Exception as e:
            log.warning(f"Erro envio uid={uid}: {e}")

    def _sender(self, uid: int):
        async def _fn(txt): await self._send(uid, txt)
        return _fn

    def _is_admin(self, uid: int) -> bool:
        return self.admin_id is not None and uid == self.admin_id

    def _resumo_cfg(self, s: UserSession) -> str:
        c = s.config
        sinc = "✅" if c.get("sincronizar_vela", True) else "❌"
        tp   = "Treinamento" if c.get("tipo_conta") == "PRACTICE" else "Real"
        return (
            f"⚙️ *CONFIGURAÇÕES*\n\n"
            f"📧 Email: `{c.get('email') or '—'}`\n"
            f"💵 Entrada: ${c.get('valor_entrada', 2.0):,.2f}\n"
            f"🎯 Gales: {c.get('gales', 2)}\n"
            f"✖️ Multiplicador: {c.get('multiplicador', 2.0)}x\n"
            f"⏱️ Antecipação: {c.get('antecipacao', 2.0)}s\n"
            f"🕯️ Sinc. vela: {sinc}\n"
            f"🟢 Stop Win: ${c.get('stop_win', 100):,.2f}\n"
            f"🔴 Stop Loss: ${c.get('stop_loss', 50):,.2f}\n"
            f"🏦 Conta: {tp}\n"
            f"📡 Canal: `{c.get('canal_id') or '—'}`"
        )

    def _resumo_status(self, s: UserSession) -> str:
        iq  = s.iq; st = s.stats.dados
        con = "🟢 Conectado" if iq.ok else "🔴 Desconectado"
        aut = "▶️ Ativo"    if s.modo_auto else "⏹️ Parado"
        tp  = "Treinamento" if iq.conta == "PRACTICE" else "Real"
        dt  = st["d_trades"]; dw = st["d_wins"]
        wr  = f"{dw/dt*100:.1f}%" if dt else "—"
        dp  = st["d_profit"]
        dps = f"+${dp:,.2f}" if dp >= 0 else f"-${abs(dp):,.2f}"
        return (
            f"📊 *STATUS*\n\n"
            f"🤖 Bot: {aut}\n"
            f"🔗 IQ Option: {con}\n"
            f"📧 Conta: `{s.config.get('email') or '—'}`\n"
            f"💰 Saldo: ${iq.saldo:,.2f} ({tp})\n\n"
            f"📅 *Hoje*\n"
            f"📈 {dt} trades | 🟢 {dw} | 🔴 {st['d_losses']} | 🎯 {wr}\n"
            f"💵 P&L: {dps}\n\n"
            f"🏆 *Total*\n"
            f"📈 {st['t_trades']} trades | 🟢 {st['t_wins']} | 🔴 {st['t_losses']}\n"
            f"💵 P&L: ${st['t_profit']:,.2f}"
        )

    def _bts_menu(self):
        return [
            [Button.inline("📊 Status",      b"status"),
             Button.inline("📈 Stats",        b"stats")],
            [Button.inline("⚙️ Configurar",  b"config")],
            [Button.inline("▶️ Ligar Bot",   b"ligar"),
             Button.inline("⏹️ Parar Bot",   b"parar")],
            [Button.inline("🔗 Conectar IQ", b"conectar"),
             Button.inline("🔄 Reset Stats", b"resetstats")],
            [Button.inline("📶 Ping IQ",     b"ping"),
             Button.inline("❓ Ajuda",        b"ajuda")],
        ]

    def _bts_cfg(self):
        return [
            [Button.inline("📧 Email",         b"e_email"),
             Button.inline("🔐 Senha",         b"e_senha")],
            [Button.inline("💵 Entrada",       b"e_valor"),
             Button.inline("🎯 Gales",         b"e_gales")],
            [Button.inline("✖️ Multiplicador", b"e_mult"),
             Button.inline("⏱️ Antecipação",  b"e_ant")],
            [Button.inline("🟢 Stop Win",      b"e_sw"),
             Button.inline("🔴 Stop Loss",     b"e_sl")],
            [Button.inline("🏦 Conta",         b"e_conta"),
             Button.inline("📡 Canal",         b"e_canal")],
            [Button.inline("🔗 Conectar IQ",  b"conectar")],
            [Button.inline("📋 Menu",          b"menu")],
        ]

    def _bts_conta(self, sufixo=b""):
        return [[
            Button.inline("🎯 Treinamento", sufixo + b"conta_practice"),
            Button.inline("💰 Real",        sufixo + b"conta_real"),
        ]]

    def _bts_sinc(self):
        return [[
            Button.inline("✅ Sim (recomendado)", b"sinc_sim"),
            Button.inline("❌ Não",               b"sinc_nao"),
        ]]

    def _bts_voltar(self):
        return [[Button.inline("📋 Menu", b"menu")]]

    # ══════════════════════════════════════════
    # HANDLERS (versão compacta)
    # ══════════════════════════════════════════

    async def _h_start(self, event):
        uid = event.sender_id; s = await self._get(uid)
        if not s: return
        if not s.config.ok:
            s.estado = Est.EMAIL; s.tmp = {}
            await event.reply(
                "👋 Bem-vindo ao *ROBIN BOT v6.1*!\n\n"
                "📌 *PASSO 1/8* — Digite seu **email** da IQ Option:"
            )
        else:
            await event.reply("🤖 *ROBIN BOT v6.1*", buttons=self._bts_menu())

    async def _h_menu(self, event):
        uid = event.sender_id; s = await self._get(uid)
        if not s: return
        await event.reply("🤖 *ROBIN BOT v6.1*", buttons=self._bts_menu())

    async def _h_config(self, event):
        uid = event.sender_id; s = await self._get(uid)
        if not s: return
        await event.reply(self._resumo_cfg(s), buttons=self._bts_cfg())

    async def _h_status(self, event):
        uid = event.sender_id; s = await self._get(uid)
        if not s: return
        await event.reply(self._resumo_status(s), buttons=self._bts_voltar())

    async def _h_conectar_cmd(self, event):
        uid = event.sender_id; s = await self._get(uid)
        if not s: return
        await self._conectar(uid, s)

    async def _conectar(self, uid: int, s: UserSession):
        email = s.config.get("email"); senha = s.config.get("senha")
        conta = s.config.get("tipo_conta", "PRACTICE")
        if not email or not senha:
            await self._send(uid, "⚠️ Configure email e senha primeiro. Use /config.")
            return
        await self._send(uid, "🔄 Conectando à IQ Option...")
        ok, msg = await s.iq.conectar(email, senha, conta)
        await self._send(uid, msg)

    async def _h_ligar(self, event):
        uid = event.sender_id; s = await self._get(uid)
        if not s: return
        if not s.iq.ok:
            await event.reply("⚠️ Conecte à IQ Option primeiro. Use /conectar."); return
        s.modo_auto = True; s.config.set("modo_auto", True)
        await event.reply("▶️ *Bot ligado!* Aguardando sinais do canal...")

    async def _h_parar(self, event):
        uid = event.sender_id; s = await self._get(uid)
        if not s: return
        s.modo_auto = False; s.config.set("modo_auto", False)
        await event.reply("⏹️ *Bot parado.*")

    async def _h_reset(self, event):
        uid = event.sender_id; s = await self._get(uid)
        if not s: return
        s.stats.resetar()
        await event.reply("✅ Estatísticas zeradas.")

    async def _h_ping(self, event):
        uid = event.sender_id; s = await self._get(uid)
        if not s: return
        await event.reply("📶 Testando conexão IQ Option...")
        ok, saldo = await s.iq.ping()
        if ok:
            await event.reply(
                f"✅ IQ Option online!\n"
                f"📧 Conta: `{s.config.get('email') or '—'}`\n"
                f"💰 Saldo: ${saldo:,.2f}"
            )
        else:
            await event.reply("🔴 IQ Option offline. Use /conectar.")

    async def _h_ajuda(self, event):
        await event.reply(
            "📚 *COMANDOS*\n\n"
            "/start — Iniciar / configurar\n"
            "/menu — Menu principal\n"
            "/config — Ver / editar configurações\n"
            "/conectar — Conectar à IQ Option\n"
            "/ligar — Ativar modo automático\n"
            "/parar — Parar modo automático\n"
            "/status — Ver status e saldo\n"
            "/ping — Testar conexão IQ Option\n"
            "/resetstats — Zerar estatísticas\n"
            "/admin — Painel administrador\n"
            "/ajuda — Esta mensagem"
        )

    async def _h_admin(self, event):
        uid = event.sender_id
        if self.admin_id is None:
            self.admin_id = uid
            await event.reply(f"👑 Você ({uid}) é agora o administrador.")
        elif not self._is_admin(uid):
            await event.reply("⛔ Acesso negado."); return

        total = len(self.sessions)
        txt   = f"👑 *PAINEL ADMIN*\n\n🖥️ Usuários: {total}/{MAX_USUARIOS}\n\n"
        for u, s in self.sessions.items():
            st    = s.stats.dados
            email = s.config.get("email") or "—"
            pid   = s.iq._proc.pid if s.iq._proc else "—"
            txt  += (
                f"👤 `{u}` [{email[:20]}] | {'▶️' if s.modo_auto else '⏹️'} "
                f"| IQ {'🟢' if s.iq.ok else '🔴'} (pid:{pid})"
                f"| {st['d_trades']} trades | ${st['d_profit']:,.2f}/dia\n"
            )
        txt += (
            "\n*Comandos admin:*\n"
            "`/broadcast <msg>` — Enviar para todos\n"
            "`/kick <uid>` — Remover usuário\n"
            "`/info <uid>` — Detalhes de usuário"
        )
        await event.reply(txt)

    async def _h_broadcast(self, event):
        if not self._is_admin(event.sender_id): return
        msg = (event.message.raw_text or "").replace("/broadcast", "", 1).strip()
        if not msg:
            await event.reply("Uso: /broadcast <mensagem>"); return
        enviado = 0
        for uid in list(self.sessions.keys()):
            await self._send(uid, f"📢 *Aviso do servidor:*\n\n{msg}")
            enviado += 1
        await event.reply(f"✅ Enviado para {enviado} usuário(s).")

    async def _h_kick(self, event):
        if not self._is_admin(event.sender_id): return
        partes = (event.message.raw_text or "").split()
        if len(partes) < 2:
            await event.reply("Uso: /kick <uid>"); return
        try:
            uid = int(partes[1])
            s   = self.sessions.get(uid)
            if s:
                await self._send(uid, "⛔ Você foi removido pelo administrador.")
                s.encerrar()
                del self.sessions[uid]
                await event.reply(f"✅ Usuário {uid} removido.")
            else:
                await event.reply(f"❌ Usuário {uid} não encontrado.")
        except ValueError:
            await event.reply("❌ UID inválido.")

    async def _h_info(self, event):
        if not self._is_admin(event.sender_id): return
        partes = (event.message.raw_text or "").split()
        if len(partes) < 2:
            await event.reply("Uso: /info <uid>"); return
        try:
            uid = int(partes[1])
            s   = self.sessions.get(uid)
            if not s:
                await event.reply(f"❌ Usuário {uid} não está ativo."); return
            await event.reply(self._resumo_status(s) + "\n\n" + self._resumo_cfg(s))
        except ValueError:
            await event.reply("❌ UID inválido.")

    async def _h_text(self, event):
        if not event.is_private or event.message.out: return
        uid = event.sender_id; s = await self._get(uid)
        if not s: return
        txt = (event.message.raw_text or "").strip()
        if not txt or txt.startswith("/"): return
        est = s.estado

        async def _inval(msg): await event.reply(msg)
        async def _ok(msg):    await event.reply(msg)

        if est == Est.EMAIL:
            s.tmp["email"] = txt; s.estado = Est.SENHA
            await _ok("📌 *PASSO 2/8* — Digite sua **senha** da IQ Option:")
        elif est == Est.SENHA:
            s.tmp["senha"] = txt; s.estado = Est.VALOR
            try: await event.delete()
            except: pass
            await _ok("📌 *PASSO 3/8* — **Valor de entrada** ($):\n_Ex: 2.00_")
        elif est == Est.VALOR:
            try:
                v = float(txt.replace(",",".")); assert v >= 0.5
                s.tmp["valor_entrada"] = v; s.estado = Est.GALES
                await _ok("📌 *PASSO 4/8* — Quantos **gales**? (0 a 5):")
            except: await _inval("❌ Valor inválido. Ex: `2.00`")
        elif est == Est.GALES:
            try:
                g = int(txt); assert 0 <= g <= 5
                s.tmp["gales"] = g; s.estado = Est.MULTIPLICADOR
                await _ok("📌 *PASSO 5/8* — **Multiplicador** do gale:\n_Ex: 2.0_")
            except: await _inval("❌ Digite número de 0 a 5.")
        elif est == Est.MULTIPLICADOR:
            try:
                m = float(txt.replace(",",".")); assert 1.1 <= m <= 5.0
                s.tmp["multiplicador"] = m; s.estado = Est.ANTECIPACAO
                await _ok("📌 *PASSO 6/8* — **Antecipação** (segundos):\n_Ex: 2.0_")
            except: await _inval("❌ Entre 1.1 e 5.0.")
        elif est == Est.ANTECIPACAO:
            try:
                a = float(txt.replace(",",".")); assert 0 <= a <= 60
                s.tmp["antecipacao"] = a; s.estado = Est.STOP_WIN
                await _ok("📌 *PASSO 7/8* — **Stop Win** ($):\n_Ex: 100.00_")
            except: await _inval("❌ Entre 0 e 60 segundos.")
        elif est == Est.STOP_WIN:
            try:
                sw = float(txt.replace(",",".")); assert sw >= 5
                s.tmp["stop_win"] = sw; s.estado = Est.STOP_LOSS
                await _ok("📌 *PASSO 8/8* — **Stop Loss** ($):\n_Ex: 50.00_")
            except: await _inval("❌ Mínimo $5.00.")
        elif est == Est.STOP_LOSS:
            try:
                sl = float(txt.replace(",",".")); assert sl >= 5
                s.tmp["stop_loss"] = sl; s.estado = Est.IDLE
                await event.reply("🏦 *Tipo de conta IQ Option:*", buttons=self._bts_conta())
            except: await _inval("❌ Mínimo $5.00.")
        elif est == Est.CANAL:
            try:
                cid = int(txt); s.config.set("canal_id", cid); s.estado = Est.IDLE
                await _ok(f"✅ Canal: `{cid}`\n\nUse /ligar para ativar o robô! 🚀")
            except: await _inval("❌ ID inválido. Ex: `-1001234567890`")
        elif est == Est.EDIT_EMAIL:
            s.config.set("email", txt); s.estado = Est.IDLE
            await _ok(f"✅ Email: `{txt}`")
        elif est == Est.EDIT_SENHA:
            s.config.set("senha", txt); s.estado = Est.IDLE
            try: await event.delete()
            except: pass
            await _ok("✅ Senha atualizada!")
        elif est == Est.EDIT_VALOR:
            try:
                v = float(txt.replace(",",".")); assert v >= 0.5
                s.config.set("valor_entrada", v); s.estado = Est.IDLE
                await _ok(f"✅ Entrada: ${v:,.2f}")
            except: await _inval("❌ Ex: `2.00`")
        elif est == Est.EDIT_GALES:
            try:
                g = int(txt); assert 0 <= g <= 5
                s.config.set("gales", g); s.estado = Est.IDLE
                await _ok(f"✅ Gales: {g}")
            except: await _inval("❌ 0 a 5.")
        elif est == Est.EDIT_MULT:
            try:
                m = float(txt.replace(",",".")); assert 1.1 <= m <= 5.0
                s.config.set("multiplicador", m); s.estado = Est.IDLE
                await _ok(f"✅ Multiplicador: {m}x")
            except: await _inval("❌ 1.1 a 5.0.")
        elif est == Est.EDIT_ANT:
            try:
                a = float(txt.replace(",",".")); assert 0 <= a <= 60
                s.config.set("antecipacao", a); s.estado = Est.IDLE
                await _ok(f"✅ Antecipação: {a}s")
            except: await _inval("❌ 0 a 60.")
        elif est == Est.EDIT_SW:
            try:
                v = float(txt.replace(",",".")); assert v >= 5
                s.config.set("stop_win", v); s.estado = Est.IDLE
                await _ok(f"✅ Stop Win: ${v:,.2f}")
            except: await _inval("❌ Mínimo $5.")
        elif est == Est.EDIT_SL:
            try:
                v = float(txt.replace(",",".")); assert v >= 5
                s.config.set("stop_loss", v); s.estado = Est.IDLE
                await _ok(f"✅ Stop Loss: ${v:,.2f}")
            except: await _inval("❌ Mínimo $5.")
        elif est == Est.EDIT_CANAL:
            try:
                cid = int(txt); s.config.set("canal_id", cid); s.estado = Est.IDLE
                await _ok(f"✅ Canal: `{cid}`")
            except: await _inval("❌ ID inválido.")

    async def _h_callback(self, event):
        uid = event.sender_id; s = await self._get(uid)
        if not s: return
        data = event.data.decode()
        try: await event.answer()
        except: pass

        nav = {
            "menu":   lambda: event.edit("🤖 *ROBIN BOT v6.1*", buttons=self._bts_menu()),
            "status": lambda: event.edit(self._resumo_status(s), buttons=self._bts_voltar()),
            "stats":  lambda: event.edit(self._resumo_status(s), buttons=self._bts_voltar()),
            "config": lambda: event.edit(self._resumo_cfg(s),    buttons=self._bts_cfg()),
        }
        if data in nav:
            await nav[data](); return

        if data == "ligar":
            if not s.iq.ok:
                await event.edit("⚠️ Conecte à IQ Option primeiro.", buttons=self._bts_voltar()); return
            s.modo_auto = True; s.config.set("modo_auto", True)
            await event.edit("▶️ *Bot ligado!*", buttons=self._bts_voltar())
        elif data == "parar":
            s.modo_auto = False; s.config.set("modo_auto", False)
            await event.edit("⏹️ *Bot parado.*", buttons=self._bts_voltar())
        elif data == "resetstats":
            s.stats.resetar()
            await event.edit("✅ Estatísticas zeradas.", buttons=self._bts_voltar())
        elif data == "cancelar":
            s.estado = Est.IDLE; s.tmp = {}
            await event.edit("❌ Cancelado.", buttons=self._bts_voltar())
        elif data == "ajuda":
            await event.edit(
                "📚 /start /menu /config /conectar /ligar /parar /status /ping /resetstats",
                buttons=self._bts_voltar()
            )
        elif data == "ping":
            await event.edit("📶 Testando IQ Option...")
            ok, saldo = await s.iq.ping()
            if ok:
                await event.edit(
                    f"✅ IQ Option online!\n"
                    f"📧 Conta: `{s.config.get('email') or '—'}`\n"
                    f"💰 Saldo: ${saldo:,.2f}",
                    buttons=self._bts_voltar()
                )
            else:
                await event.edit("🔴 IQ offline. Use Conectar IQ.", buttons=self._bts_voltar())
        elif data == "conectar":
            await event.edit("🔄 Conectando à IQ Option...")
            email = s.config.get("email"); senha = s.config.get("senha")
            conta = s.config.get("tipo_conta", "PRACTICE")
            if not email or not senha:
                await event.edit("⚠️ Configure email e senha primeiro.", buttons=self._bts_voltar()); return
            ok, msg = await s.iq.conectar(email, senha, conta)
            await self._send(uid, msg)
            await event.edit(self._resumo_status(s), buttons=self._bts_voltar())
        elif data in ("conta_practice", "conta_real"):
            s.tmp["tipo_conta"] = "PRACTICE" if "practice" in data else "REAL"
            await event.edit("🕯️ Sincronizar com o *horário exato do sinal?*", buttons=self._bts_sinc())
        elif data in ("sinc_sim", "sinc_nao"):
            s.tmp["sincronizar_vela"] = (data == "sinc_sim")
            s.config.set_many({
                "email"           : s.tmp.get("email",          s.config.get("email")),
                "senha"           : s.tmp.get("senha",          s.config.get("senha")),
                "valor_entrada"   : s.tmp.get("valor_entrada",  s.config.get("valor_entrada",  2.0)),
                "gales"           : s.tmp.get("gales",          s.config.get("gales",          2)),
                "multiplicador"   : s.tmp.get("multiplicador",  s.config.get("multiplicador",  2.0)),
                "antecipacao"     : s.tmp.get("antecipacao",    s.config.get("antecipacao",    2.0)),
                "stop_win"        : s.tmp.get("stop_win",       s.config.get("stop_win",       100.0)),
                "stop_loss"       : s.tmp.get("stop_loss",      s.config.get("stop_loss",      50.0)),
                "tipo_conta"      : s.tmp.get("tipo_conta",     s.config.get("tipo_conta",     "PRACTICE")),
                "sincronizar_vela": s.tmp["sincronizar_vela"],
                "configurado"     : True,
            })
            s.tmp = {}; s.estado = Est.CANAL
            await event.edit(
                "✅ *Configurações salvas!*\n\n"
                "📡 *Último passo* — ID do **canal de sinais**:\n"
                "_Ex: `-1001234567890`_\n\n"
                "💡 Dica: encaminhe uma mensagem do canal para @userinfobot para descobrir o ID."
            )
            asyncio.create_task(self._conectar(uid, s))
        elif data == "e_email":  s.estado = Est.EDIT_EMAIL; await event.edit("📧 Novo email:")
        elif data == "e_senha":  s.estado = Est.EDIT_SENHA; await event.edit("🔐 Nova senha:")
        elif data == "e_valor":  s.estado = Est.EDIT_VALOR; await event.edit("💵 Novo valor ($):")
        elif data == "e_gales":  s.estado = Est.EDIT_GALES; await event.edit("🎯 Gales (0–5):")
        elif data == "e_mult":   s.estado = Est.EDIT_MULT;  await event.edit("✖️ Multiplicador (1.1–5.0):")
        elif data == "e_ant":    s.estado = Est.EDIT_ANT;   await event.edit("⏱️ Antecipação (0–60s):")
        elif data == "e_sw":     s.estado = Est.EDIT_SW;    await event.edit("🟢 Stop Win ($):")
        elif data == "e_sl":     s.estado = Est.EDIT_SL;    await event.edit("🔴 Stop Loss ($):")
        elif data == "e_canal":  s.estado = Est.EDIT_CANAL; await event.edit("📡 ID do canal:")
        elif data == "e_conta":
            await event.edit("🏦 Tipo de conta:", buttons=self._bts_conta())
        elif data in ("conta_practice_e", "conta_real_e"):
            tipo  = "PRACTICE" if "practice" in data else "REAL"
            label = "Treinamento" if tipo == "PRACTICE" else "Real"
            s.config.set("tipo_conta", tipo); s.estado = Est.IDLE
            asyncio.create_task(s.iq.trocar_conta(tipo))
            await event.edit(f"✅ Conta: {label}", buttons=self._bts_voltar())

    @staticmethod
    def _ids_equivalentes(id_cfg, id_evento) -> bool:
        try:
            a = int(id_cfg)
            b = int(id_evento)
            if a == b: return True
            def _puro(x): return abs(x) % 10**10
            return _puro(a) == _puro(b)
        except Exception:
            return str(id_cfg) == str(id_evento)

    async def _h_sinal(self, event):
        if event.message.out: return
        canal_id = event.chat_id
        texto    = (event.message.raw_text or "").strip()
        if not texto: return

        sinal = parse_sinal(texto)
        if not sinal:
            return

        log.info(f"[SINAL] ✅ {sinal['ativo']} {sinal['direcao']} M{sinal['tempo']}")

        disparado = 0
        for uid, s in list(self.sessions.items()):
            cfg_canal = s.config.get("canal_id")
            match     = self._ids_equivalentes(cfg_canal, canal_id)
            if match and s.modo_auto and not s.operando and s.iq.ok:
                asyncio.create_task(executar_operacao(s, sinal, self._sender(uid)))
                disparado += 1

    # ══════════════════════════════════════════
    # WATCHDOG - Versão agressiva para Railway
    # ══════════════════════════════════════════

    async def _watchdog(self):
        while True:
            await asyncio.sleep(WATCHDOG_INT)
            agora  = datetime.now()
            limite = timedelta(hours=SESSAO_LIMITE)

            for uid in list(self.sessions.keys()):
                s = self.sessions.get(uid)
                if not s: continue

                # Limpeza de sessão inativa
                ultima = s.config.get("ultima_interacao")
                if ultima:
                    try:
                        if agora - datetime.fromisoformat(ultima) > limite:
                            log.info(f"Sessão inativa removida uid={uid}")
                            s.encerrar()
                            del self.sessions[uid]
                            continue
                    except: pass

                if s.config.ok:
                    proc_vivo = s.iq.is_alive()
                    
                    # Se processo morreu, reconecta
                    if not proc_vivo and s.iq.ok:
                        log.warning(f"Processo IQ morreu uid={uid}, reiniciando...")
                        s.iq.ok = False
                        # Força recriação do processo
                        s.iq._proc = None
                        asyncio.create_task(s.iq.conectar(
                            s.config.get("email",""),
                            s.config.get("senha",""),
                            s.config.get("tipo_conta","PRACTICE"),
                        ))
                        continue
                    
                    # Se processo vivo, testa ping
                    if proc_vivo and s.iq.ok:
                        try:
                            ok, _ = await asyncio.wait_for(s.iq.ping(), timeout=15)
                            if not ok:
                                log.warning(f"IQ desconectada uid={uid}, reconectando...")
                                s.iq.ok = False
                                s.iq._kill_process()  # Mata processo travado
                                asyncio.create_task(s.iq.conectar(
                                    s.config.get("email",""),
                                    s.config.get("senha",""),
                                    s.config.get("tipo_conta","PRACTICE"),
                                ))
                        except asyncio.TimeoutError:
                            log.warning(f"Ping timeout uid={uid}, matando processo...")
                            s.iq._kill_process()
                            s.iq.ok = False
                            asyncio.create_task(s.iq.conectar(
                                s.config.get("email",""),
                                s.config.get("senha",""),
                                s.config.get("tipo_conta","PRACTICE"),
                            ))

    # ══════════════════════════════════════════
    # RESTAURAR SESSÕES
    # ══════════════════════════════════════════

    async def _restaurar_sessoes(self):
        restaurados = 0
        for cfg_file in sorted(DIR_CONFIG.glob("*.json")):
            try:
                uid = int(cfg_file.stem)
                d   = json.loads(cfg_file.read_text(encoding="utf-8"))
                if not d.get("configurado"): continue

                s = UserSession(uid)
                self.sessions[uid] = s

                email = d.get("email",""); senha = d.get("senha","")
                conta = d.get("tipo_conta","PRACTICE")

                if email and senha:
                    log.info(f"Restaurando uid={uid} ({email})...")
                    ok, _ = await s.iq.conectar(email, senha, conta)
                    if ok and d.get("modo_auto"):
                        s.modo_auto = True
                        await self._send(uid,
                            "🔄 *ROBIN BOT reiniciado!*\n\n"
                            "✅ Reconectado à IQ Option.\n"
                            "▶️ Modo automático reativado."
                        )
                    restaurados += 1

                if len(self.sessions) >= MAX_USUARIOS:
                    break
            except Exception as e:
                log.warning(f"Erro ao restaurar {cfg_file}: {e}")

        log.info(f"✅ {restaurados} sessão(ões) restaurada(s)")

    # ══════════════════════════════════════════
    # RUN
    # ══════════════════════════════════════════

    async def run(self):
        self._token, self._api_id, self._api_hash = _carregar_credenciais()

        print("""\
\033[95m\033[1m╔══════════════════════════════════════════════╗
║       🤖  R O B I N  B O T  v6.1           ║
║  Otimizado para Railway · 8 usuários        ║
╚══════════════════════════════════════════════╝\033[0m
""")

        while True:
            try:
                self.client = TelegramClient(
                    "robin_v6_session", self._api_id, self._api_hash
                )
                await self.client.start(bot_token=self._token)
                log.info("✅ Bot conectado ao Telegram")

                await self._restaurar_sessoes()

                c     = self.client
                _priv = lambda e: e.is_private
                _npriv= lambda e: not e.is_private
                _txt  = lambda e: e.is_private and not (e.message.raw_text or "").startswith("/")

                c.add_event_handler(self._h_start,        events.NewMessage(pattern="/start",      func=_priv))
                c.add_event_handler(self._h_menu,         events.NewMessage(pattern="/menu",       func=_priv))
                c.add_event_handler(self._h_config,       events.NewMessage(pattern="/config",     func=_priv))
                c.add_event_handler(self._h_status,       events.NewMessage(pattern="/status",     func=_priv))
                c.add_event_handler(self._h_status,       events.NewMessage(pattern="/stats",      func=_priv))
                c.add_event_handler(self._h_conectar_cmd, events.NewMessage(pattern="/conectar",   func=_priv))
                c.add_event_handler(self._h_ligar,        events.NewMessage(pattern="/ligar",      func=_priv))
                c.add_event_handler(self._h_parar,        events.NewMessage(pattern="/parar",      func=_priv))
                c.add_event_handler(self._h_reset,        events.NewMessage(pattern="/resetstats", func=_priv))
                c.add_event_handler(self._h_ping,         events.NewMessage(pattern="/ping",       func=_priv))
                c.add_event_handler(self._h_ajuda,        events.NewMessage(pattern="/ajuda",      func=_priv))
                c.add_event_handler(self._h_admin,        events.NewMessage(pattern="/admin",      func=_priv))
                c.add_event_handler(self._h_broadcast,    events.NewMessage(pattern="/broadcast",  func=_priv))
                c.add_event_handler(self._h_kick,         events.NewMessage(pattern="/kick",       func=_priv))
                c.add_event_handler(self._h_info,         events.NewMessage(pattern="/info",       func=_priv))
                c.add_event_handler(self._h_text,         events.NewMessage(func=_txt))
                c.add_event_handler(self._h_callback,     events.CallbackQuery())
                c.add_event_handler(self._h_sinal,        events.NewMessage(func=_npriv))

                asyncio.create_task(self._watchdog())
                log.info(f"🚀 Pronto! {MAX_USUARIOS} usuários | watchdog {WATCHDOG_INT}s")

                await self.client.run_until_disconnected()

            except (ConnectionError, OSError) as e:
                log.error(f"Telegram perdido: {e}. Reconectando em 10s...")
                await asyncio.sleep(10)
            except KeyboardInterrupt:
                log.info("Encerrando subprocessos...")
                for s in self.sessions.values():
                    s.encerrar()
                log.info("Bot encerrado.")
                break
            except Exception as e:
                log.critical(f"Erro fatal: {e}\n{traceback.format_exc()}")
                await asyncio.sleep(10)


# ══════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════

if __name__ == "__main__":
    asyncio.run(RobinBot().run())
