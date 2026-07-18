#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║          🤖  R O B I N  B O T  v6.0                        ║
║  Railway · Background Worker · Sem input()                   ║
╚══════════════════════════════════════════════════════════════╝
"""

import asyncio, json, logging, multiprocessing as mp, os, re, sys, time, traceback
from datetime import datetime, timedelta
from enum import Enum, auto
from pathlib import Path
from typing import Optional, Dict, Any

from telethon import TelegramClient, events, Button

# ══════════════════════════════════════════════
# 🔑 SUAS CREDENCIAIS (SUBSTITUA PELOS VALORES CORRETOS)
# ══════════════════════════════════════════════
BOT_TOKEN   = "8233598336:AAHUtMg14-2hcOFObRhrBGsO4JIEyyA7gtI"   # token do BotFather
TG_API_ID   = 22453120                          # seu api_id
TG_API_HASH = "89826a4104518e9ed650cdb451ad8b53"  # seu api_hash

MAX_USUARIOS  = 5
TIMEOUT_ORDEM = 180
WATCHDOG_INT  = 60
SESSAO_LIMITE = 2

DIR_CONFIG = Path("dados/configs")
DIR_STATS  = Path("dados/stats")
DIR_CONFIG.mkdir(parents=True, exist_ok=True)
DIR_STATS.mkdir(parents=True, exist_ok=True)

# ══════════════════════════════════════════════
# LOGGER (mantido como original)
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
# IQ WORKER (subprocesso) – IGUAL ao seu script
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
# IQProcess — wrapper async do subprocesso (igual)
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
# FSM, CONFIG, STATS, MAPEADOR, PARSER, MOTOR (copiados do seu script)
# ══════════════════════════════════════════════
# (mantenha exatamente como você já tem)

# ... (todo o restante do código até a classe RobinBot, inclusive os handlers)

# ⚠️  Por brevidade, não repeti aqui todo o código que você já possui.
#      O importante é que você SUBSTITUA o método run() pelo abaixo
#      e remova a função _carregar_credenciais().

# ══════════════════════════════════════════════
# NOVO RUN (sem input)
# ══════════════════════════════════════════════

    async def run(self):
        # Remove sessão antiga para evitar conflitos
        session_file = "robin_v6_session.session"
        if Path(session_file).exists():
            Path(session_file).unlink()
            log.info("Sessão antiga removida.")

        if not BOT_TOKEN or not TG_API_ID or not TG_API_HASH:
            log.critical("Credenciais não definidas no código!")
            sys.exit(1)

        print(f"""\
\033[95m\033[1m╔══════════════════════════════════════════════╗
║       🤖  R O B I N  B O T  v6.0           ║
║  Hardcoded · {MAX_USUARIOS} usuários · Subprocesso        ║
╚══════════════════════════════════════════════╝\033[0m
""")

        while True:
            try:
                self.client = TelegramClient(
                    session_file, TG_API_ID, TG_API_HASH
                )
                await self.client.start(bot_token=BOT_TOKEN)
                log.info("✅ Bot conectado ao Telegram")

                # Restaura sessões se desejar (opcional)
                # await self._restaurar_sessoes()

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
