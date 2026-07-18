#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║          🤖  R O B I N  B O T  v6.0                        ║
║  Railway · Background Worker · Subprocesso por usuário      ║
║  Sessão limpa a cada início (sem travamentos)               ║
╚══════════════════════════════════════════════════════════════╝
"""

import asyncio, json, logging, multiprocessing as mp, os, re, sys, time, traceback
from datetime import datetime, timedelta
from enum import Enum, auto
from pathlib import Path
from typing import Optional, Dict, Any

from telethon import TelegramClient, events, Button

# ══════════════════════════════════════════════
# 🔑 SUAS NOVAS CREDENCIAIS (SUBSTITUA AQUI)
# ══════════════════════════════════════════════
BOT_TOKEN   = "8233598336:AAHUtMg14-2hcOFObRhrBGsO4JIEyyA7gtI"       # Obtido com @BotFather
TG_API_ID   = 22453120                    # Novo API ID de my.telegram.org
TG_API_HASH = "89826a4104518e9ed650cdb451ad8b53"    # Novo API Hash

MAX_USUARIOS  = 5                       # Ajuste conforme sua necessidade
TIMEOUT_ORDEM = 180
WATCHDOG_INT  = 60
SESSAO_LIMITE = 2                       # horas

DIR_CONFIG = Path("dados/configs")
DIR_STATS  = Path("dados/stats")
DIR_CONFIG.mkdir(parents=True, exist_ok=True)
DIR_STATS.mkdir(parents=True, exist_ok=True)

# ══════════════════════════════════════════════
# LOGGER COLORIDO
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
# IQ WORKER — roda em subprocesso isolado
# ══════════════════════════════════════════════

def _iq_worker_fn(uid: int, cmd_q: mp.Queue, res_q: mp.Queue):
    api = None
    conta_atual = "PRACTICE"

    def _send(data: dict):
        res_q.put(data)

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
                api_new = IQ_Option(email, senha)
                api_new.connect()
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
            except ImportError:
                _send({"ok": False, "erro": "❌ iqoptionapi não instalada."})
            except Exception as e:
                _send({"ok": False, "erro": f"❌ Erro: {e}"})

        elif action == "saldo":
            if not api:
                _send({"ok": False, "saldo": 0.0})
                continue
            try:
                saldo = float(api.get_balance())
                _send({"ok": True, "saldo": saldo})
            except Exception as e:
                _send({"ok": False, "saldo": 0.0, "erro": str(e)})

        elif action == "ping":
            try:
                alive = bool(api and api.check_connect())
                saldo = float(api.get_balance()) if alive else 0.0
                _send({"ok": alive, "saldo": saldo})
            except Exception:
                _send({"ok": False, "saldo": 0.0})

        elif action == "comprar":
            if not api:
                _send({"ok": False, "erro": "Não conectado"})
                continue
            try:
                ok, order_id = api.buy(
                    cmd["valor"], cmd["ativo"],
                    cmd["direcao"].lower(), cmd["tempo"]
                )
                _send({"ok": bool(ok), "order_id": order_id})
            except Exception as e:
                _send({"ok": False, "order_id": None, "erro": str(e)})

        elif action == "verificar":
            if not api:
                _send({"ok": False, "resultado": None})
                continue
            order_id = cmd["order_id"]
            deadline = time.time() + cmd.get("timeout", TIMEOUT_ORDEM)
            resultado = None
            while time.time() < deadline:
                try:
                    r = api.check_win_v3(order_id)
                    if r is not None:
                        resultado = float(r)
                        break
                except Exception:
                    pass
                time.sleep(0.5)
            _send({"ok": resultado is not None, "resultado": resultado})

        elif action == "trocar_conta":
            if api:
                try:
                    api.change_balance(cmd["conta"])
                    conta_atual = cmd["conta"]
                    saldo = float(api.get_balance())
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

# ══════════════════════════════════════════════
# IQProcess — wrapper async do subprocesso
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

    def _iniciar_processo(self):
        if self._proc and self._proc.is_alive():
            return
        self._cmd_q = mp.Queue()
        self._res_q = mp.Queue()
        self._proc  = mp.Process(
            target=_iq_worker_fn,
            args=(self.uid, self._cmd_q, self._res_q),
            daemon=True,
            name=f"iq-uid-{self.uid}"
        )
        self._proc.start()
        log.info(f"[IQProcess] Subprocesso iniciado uid={self.uid} pid={self._proc.pid}")

    async def _cmd(self, cmd: dict, timeout: float = 30) -> dict:
        async with self._lock:
            self._iniciar_processo()
            loop = asyncio.get_event_loop()
            self._cmd_q.put_nowait(cmd)
            try:
                res = await asyncio.wait_for(
                    loop.run_in_executor(None, self._res_q.get),
                    timeout=timeout
                )
                return res
            except asyncio.TimeoutError:
                log.error(f"[IQProcess] Timeout uid={self.uid} cmd={cmd['action']}")
                return {"ok": False, "erro": "Timeout no worker IQ"}

    async def conectar(self, email: str, senha: str, conta: str) -> tuple:
        res = await self._cmd(
            {"action": "conectar", "email": email, "senha": senha, "conta": conta},
            timeout=60
        )
        if res.get("ok"):
            self.ok    = True
            self.saldo = res.get("saldo", 0.0)
            self.conta = res.get("conta", conta)
            return True, f"✅ Conectado! Saldo: ${self.saldo:,.2f}"
        self.ok = False
        return False, res.get("erro", "❌ Erro desconhecido")

    async def get_saldo(self) -> float:
        res = await self._cmd({"action": "saldo"})
        return res.get("saldo", 0.0)

    async def ping(self) -> tuple:
        res = await self._cmd({"action": "ping"})
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
            timeout=timeout + 15
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
                self._proc.join(timeout=3)
            except Exception:
                pass
            if self._proc.is_alive():
                self._proc.terminate()
            log.info(f"[IQProcess] Subprocesso encerrado uid={self.uid}")

# ══════════════════════════════════════════════
# FSM
# ══════════════════════════════════════════════

class Est(Enum):
    IDLE=auto(); EMAIL=auto(); SENHA=auto(); VALOR=auto()
    GALES=auto(); MULTIPLICADOR=auto(); ANTECIPACAO=auto()
    STOP_WIN=auto(); STOP_LOSS=auto(); CANAL=auto()
    EDIT_EMAIL=auto(); EDIT_SENHA=auto(); EDIT_VALOR=auto()
    EDIT_GALES=auto(); EDIT_MULT=auto(); EDIT_ANT=auto()
    EDIT_SW=auto(); EDIT_SL=auto(); EDIT_CANAL=auto()

# ══════════════════════════════════════════════
# CONFIG (persistido por usuário)
# ══════════════════════════════════════════════

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

# ══════════════════════════════════════════════
# STATS (persistido por usuário)
# ══════════════════════════════════════════════

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

# ══════════════════════════════════════════════
# SESSÃO DO USUÁRIO
# ══════════════════════════════════════════════

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
    def encerrar(self): self.iq.encerrar()

# ══════════════════════════════════════════════
# MAPEADOR DE ATIVOS
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

# ══════════════════════════════════════════════
# PARSER DE SINAIS — 7 FORMATOS
# ══════════════════════════════════════════════

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
# MOTOR DE OPERAÇÃO
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

    # Helpers de mensageria
    async def _get(self, uid: int) -> Optional[UserSession]:
        if uid not in self.sessions:
            if len(self.sessions) >= MAX_USUARIOS:
                await self.client.send_message(uid, f"⚠️ Servidor lotado ({MAX_USUARIOS} usuários).")
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

    # Resumos
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

    # Botões
    def _bts_menu(self):
        return [
            [Button.inline("📊 Status", b"status"), Button.inline("📈 Stats", b"stats")],
            [Button.inline("⚙️ Configurar", b"config")],
            [Button.inline("▶️ Ligar Bot", b"ligar"), Button.inline("⏹️ Parar Bot", b"parar")],
            [Button.inline("🔗 Conectar IQ", b"conectar"), Button.inline("🔄 Reset Stats", b"resetstats")],
            [Button.inline("📶 Ping IQ", b"ping"), Button.inline("❓ Ajuda", b"ajuda")],
        ]

    def _bts_cfg(self):
        return [
            [Button.inline("📧 Email", b"e_email"), Button.inline("🔐 Senha", b"e_senha")],
            [Button.inline("💵 Entrada", b"e_valor"), Button.inline("🎯 Gales", b"e_gales")],
            [Button.inline("✖️ Multiplicador", b"e_mult"), Button.inline("⏱️ Antecipação", b"e_ant")],
            [Button.inline("🟢 Stop Win", b"e_sw"), Button.inline("🔴 Stop Loss", b"e_sl")],
            [Button.inline("🏦 Conta", b"e_conta"), Button.inline("📡 Canal", b"e_canal")],
            [Button.inline("🔗 Conectar IQ", b"conectar")],
            [Button.inline("📋 Menu", b"menu")],
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
    # HANDLERS (copiados do seu original)
    # ══════════════════════════════════════════

    # Para manter o exemplo completo, insira aqui todos os handlers que já existiam.
    # Como o código original é extenso, lembre-se de copiá-los integralmente.
    # Exemplo:
    async def _h_start(self, event):
        if not event.is_private: return
        uid = event.sender_id; s = await self._get(uid)
        if not s: return
        if not s.config.ok:
            s.estado = Est.EMAIL; s.tmp = {}
            await event.reply(
                "👋 Bem-vindo ao *ROBIN BOT v6.0*!\n\n"
                "📌 *PASSO 1/8* — Digite seu **email** da IQ Option:"
            )
        else:
            await event.reply("🤖 *ROBIN BOT v6.0*", buttons=self._bts_menu())

    async def _h_menu(self, event):
        if not event.is_private: return
        uid = event.sender_id; s = await self._get(uid)
        if not s: return
        await event.reply("🤖 *ROBIN BOT v6.0*", buttons=self._bts_menu())

    # ... (demais handlers: _h_config, _h_status, _h_conectar_cmd, _h_ligar, _h_parar,
    # _h_reset, _h_ping, _h_ajuda, _h_admin, _h_broadcast, _h_kick, _h_info,
    # _h_text, _h_callback, _h_sinal)

    # ── Watchdog ─────────────────────────────────────────────

    async def _watchdog(self):
        while True:
            await asyncio.sleep(WATCHDOG_INT)
            agora  = datetime.now()
            limite = timedelta(hours=SESSAO_LIMITE)
            for uid in list(self.sessions.keys()):
                s = self.sessions.get(uid)
                if not s: continue
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
                    if not proc_vivo and s.iq.ok:
                        log.warning(f"Subprocesso IQ morto uid={uid}, reconectando...")
                        s.iq.ok = False
                        asyncio.create_task(
                            s.iq.conectar(
                                s.config.get("email",""),
                                s.config.get("senha",""),
                                s.config.get("tipo_conta","PRACTICE"),
                            )
                        )
                    elif proc_vivo and s.iq.ok:
                        ok, _ = await s.iq.ping()
                        if not ok:
                            log.warning(f"IQ desconectada uid={uid}, reconectando...")
                            s.iq.ok = False
                            asyncio.create_task(
                                s.iq.conectar(
                                    s.config.get("email",""),
                                    s.config.get("senha",""),
                                    s.config.get("tipo_conta","PRACTICE"),
                                )
                            )

    # ── Run (CORRIGIDO) ─────────────────────────────────────
    async def run(self):
        # Remove sessão corrompida a cada início
        session_file = "robin_v6_session.session"
        if Path(session_file).exists():
            Path(session_file).unlink()
            log.info("Sessão antiga removida. Novo login será realizado.")

        if not BOT_TOKEN or not TG_API_ID or not TG_API_HASH:
            log.critical("Credenciais não definidas no código.")
            sys.exit(1)

        print(f"""\
\033[95m\033[1m╔══════════════════════════════════════════════╗
║       🤖  R O B I N  B O T  v6.0           ║
║  Subprocesso por usuário · {MAX_USUARIOS} usuários      ║
╚══════════════════════════════════════════════╝\033[0m
""")

        while True:
            try:
                self.client = TelegramClient(
                    session_file, TG_API_ID, TG_API_HASH
                )
                await self.client.start(bot_token=BOT_TOKEN)
                log.info("✅ Bot conectado ao Telegram")

                c     = self.client
                _priv = lambda e: e.is_private
                _npriv= lambda e: not e.is_private
                _txt  = lambda e: e.is_private and not (e.message.raw_text or "").startswith("/")

                # Registro dos handlers (exatamente como no original)
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
                log.info(f"🚀 Pronto! {MAX_USUARIOS} usuários | subprocesso por conta")

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
    mp.set_start_method("spawn", force=True)
    asyncio.run(RobinBot().run())
