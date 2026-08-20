#!/usr/bin/env python3
"""
⚛️ QUANTUM IA M5 - FOREX REAL (MERCADO ABERTO)
📊 Estratégias: Formiga, Fortaleza, Raio Negro, Tsunami
🎯 Confluência de 2+ estratégias + tendência SMA20 + pavio 50%
📰 Filtro de notícias de 3 touros (apenas eventos de alta importância)
📊 Filtro de volatilidade (ATR) calibrado para Forex real
🔄 Placar diário automático
"""
import asyncio, time, requests, numpy as np, signal, sys, json, os
from datetime import datetime, timedelta, timezone
from collections import deque, defaultdict
from pathlib import Path

signal.signal(signal.SIGCHLD, signal.SIG_IGN)
FUSO_BR = timezone(timedelta(hours=-3))

# Configurações
INTERVALO_MINIMO = 600       # 10 min entre sinais
USAR_GALE = True
ANTECEDENCIA = 30            # segundos antes da entrada
CONFIANCA_MINIMA = 65

# Volatilidade ATR (valores típicos Forex real)
ATR_MIN = 0.0003
ATR_MAX = 0.0015

def banner():
    print("⚛️ QUANTUM IA M5 - Forex Real | Filtro de Notícias 3 Touros")

def carregar_config():
    token = os.environ.get('TELEGRAM_TOKEN')
    chat = os.environ.get('TELEGRAM_CHAT_ID')
    if token and chat:
        banner()
        print("✅ Modo CLOUD detectado!")
        return {"token": token, "chat": chat}
    print("❌ Configure TELEGRAM_TOKEN e TELEGRAM_CHAT_ID")
    sys.exit(1)

cfg = carregar_config()
TOKEN, CHAT = cfg['token'], cfg['chat']

# Pares Forex reais (sem -OTC)
ATIVOS = {
    "EURUSD": "EURUSD",
    "GBPUSD": "GBPUSD",
    "USDJPY": "USDJPY"
}

class Telegram:
    def __init__(self, t, c):
        self.url = f"https://api.telegram.org/bot{t}"
        self.c = c
    def send(self, txt):
        try: requests.post(f"{self.url}/sendMessage", json={"chat_id": self.c, "text": txt, "parse_mode": "Markdown"}, timeout=10)
        except: pass

# Estratégias
class Formiga:
    def ema(self, p, pe):
        if len(p) < pe: return sum(p)/len(p) if p else 0
        return np.mean(p[-pe:])
    def analisar(self, v):
        try:
            if len(v) < 15: return None, 0
            precos = np.array([x['close'] for x in v])
            ema5 = self.ema(precos, 5); ema10 = self.ema(precos, 10)
            dif = ((ema5-ema10)/ema10)*100 if ema10 > 0 else 0
            sc, sp = 0, 0
            if dif > 0.02: sc += 3
            elif dif > 0.005: sc += 1
            elif dif < -0.02: sp += 3
            elif dif < -0.005: sp += 1
            if sc >= 2 and sc > sp: return 'CALL', min(50+sc*4, 85)
            if sp >= 2 and sp > sc: return 'PUT', min(50+sp*4, 85)
            return None, 0
        except: return None, 0

class Fortaleza:
    def rsi(self, p, pe=7):
        if len(p) < pe+1: return 50
        d = np.diff(list(p[-pe-1:]))
        g = np.where(d > 0, d, 0); l = np.where(d < 0, -d, 0)
        mg = np.mean(g) if len(g) > 0 else 0
        mp = np.mean(l) if len(l) > 0 else 0
        if mp == 0: return 100
        return 100 - (100/(1+mg/mp))
    def analisar(self, v):
        try:
            if len(v) < 18: return None, 0
            precos = np.array([x['close'] for x in v])
            rsi_val = self.rsi(precos)
            m = np.mean(precos[-10:])
            s = np.std(precos[-10:])
            bs = m + 2*s; bi = m - 2*s
            sc, sp = 0, 0
            if rsi_val < 30: sc += 3
            elif rsi_val < 40: sc += 2
            if rsi_val > 70: sp += 3
            elif rsi_val > 60: sp += 2
            if precos[-1] <= bi*1.0004: sc += 3
            if precos[-1] >= bs*0.9996: sp += 3
            if sc >= 4 and sc > sp: return 'CALL', min(60+sc*3, 90)
            if sp >= 4 and sp > sc: return 'PUT', min(60+sp*3, 90)
            return None, 0
        except: return None, 0

class RaioNegro:
    def analisar(self, v):
        try:
            if len(v) < 12: return None, 0
            precos = np.array([x['close'] for x in v])
            ema5 = np.mean(precos[-5:]); ema13 = np.mean(precos[-13:])
            macd = ema5 - ema13
            sinal = macd * 0.5
            mom = precos[-1] - precos[-3]
            sc, sp = 0, 0
            if macd > sinal and macd > 0: sc += 3
            elif macd > sinal: sc += 1
            elif macd < sinal and macd < 0: sp += 3
            elif macd < sinal: sp += 1
            if mom > 0.00003: sc += 3
            elif mom > 0: sc += 1
            elif mom < -0.00003: sp += 3
            elif mom < 0: sp += 1
            if sc >= 2 and sc > sp: return 'CALL', min(48+sc*4, 85)
            if sp >= 2 and sp > sc: return 'PUT', min(48+sp*4, 85)
            return None, 0
        except: return None, 0

class Tsunami:
    def analisar(self, v):
        try:
            if len(v) < 12: return None, 0
            precos = [x['close'] for x in v]
            altas = sum(1 for i in range(-min(5,len(v)-1), 0) if precos[i] > precos[i-1])
            sc, sp = 0, 0
            if altas >= 3: sc += 3
            elif altas <= 2: sp += 3
            if sc >= 2 and sc > sp: return 'CALL', min(50+sc*3, 85)
            if sp >= 2 and sp > sc: return 'PUT', min(50+sp*3, 85)
            return None, 0
        except: return None, 0

# Bot
class BotM5Forex:
    def __init__(self):
        self.tg = Telegram(TOKEN, CHAT)
        self.velas = {nome: deque(maxlen=100) for nome in ATIVOS}
        self.estrategias = [
            ('🐜 Formiga', Formiga()),
            ('🏰 Fortaleza', Fortaleza()),
            ('⚡ Raio Negro', RaioNegro()),
            ('🌊 Tsunami', Tsunami())
        ]
        self.iq_api = None
        self.placar = {'w': 0, 'g1': 0, 'l': 0}
        self.ult_sinal = 0
        self.ultimo_dia = datetime.now(FUSO_BR).day

    def conectar_iq(self):
        from iqoptionapi.stable_api import IQ_Option
        email = os.environ.get('IQ_EMAIL')
        senha = os.environ.get('IQ_SENHA')
        if not email or not senha:
            return None
        try:
            if self.iq_api:
                try: self.iq_api.close()
                except: pass
            self.iq_api = IQ_Option(email, senha)
            check, _ = self.iq_api.connect()
            if check:
                print("✅ Conectado à IQ Option.")
                return self.iq_api
            else:
                print("❌ Falha na conexão.")
                return None
        except Exception as e:
            print(f"❌ Erro: {e}")
            return None

    async def reconectar_se_necessario(self):
        if self.iq_api is None or not self.iq_api.check_connect():
            print("🔄 Reconectando...")
            return self.conectar_iq()
        return self.iq_api

    async def atualizar_velas(self):
        api = await self.reconectar_se_necessario()
        if not api:
            return
        for nome, ativo_id in ATIVOS.items():
            for retry in range(3):
                try:
                    if not api.check_connect():
                        api = await self.reconectar_se_necessario()
                        if not api:
                            break
                    c = api.get_candles(ativo_id, 300, 80, time.time())  # M5
                    if c and len(c) > 0:
                        self.velas[nome].clear()
                        for x in c[-80:]:
                            if isinstance(x, dict):
                                self.velas[nome].append({
                                    'time': datetime.fromtimestamp(x.get('from',0), FUSO_BR),
                                    'open': float(x['open']), 'high': float(x['max']),
                                    'low': float(x['min']), 'close': float(x['close']),
                                    'volume': int(x.get('volume',0))
                                })
                        break
                    time.sleep(2)
                except Exception as e:
                    print(f"Erro velas {nome}: {e}")
                    time.sleep(2)
                    if "need reconnect" in str(e):
                        api = await self.reconectar_se_necessario()
                        if not api:
                            break

    def calcular_atr(self, velas, periodo=14):
        if len(velas) < periodo + 1:
            return None
        trs = []
        for i in range(-periodo, 0):
            h = velas[i]['high']
            l = velas[i]['low']
            c_prev = velas[i-1]['close']
            tr = max(h - l, abs(h - c_prev), abs(l - c_prev))
            trs.append(tr)
        return np.mean(trs)

    def buscar_sinal_consenso(self):
        if not horario_ok() or noticias_3_touros():
            return None

        for par, velas in self.velas.items():
            if len(velas) < 30:
                continue
            atr = self.calcular_atr(velas, 14)
            if atr is None or atr < ATR_MIN or atr > ATR_MAX:
                continue
            precos = [v['close'] for v in velas]
            sma20 = sum(precos[-20:]) / 20
            atual = precos[-1]

            votos_call = []
            votos_put = []
            for nome_est, est in self.estrategias:
                resultado = est.analisar(velas)
                if resultado:
                    direcao, conf = resultado
                    if conf >= CONFIANCA_MINIMA:
                        if direcao == 'CALL':
                            votos_call.append(conf)
                        else:
                            votos_put.append(conf)

            if len(votos_call) >= 2 and atual > sma20:
                conf_media = sum(votos_call) / len(votos_call)
                vela = velas[-1]
                corpo = abs(vela['close'] - vela['open'])
                if corpo > 0:
                    pavio_sup = vela['high'] - max(vela['close'], vela['open'])
                    if pavio_sup > corpo * 0.5:
                        continue
                return {'ativo': par, 'direcao': 'CALL', 'confianca': conf_media}

            if len(votos_put) >= 2 and atual < sma20:
                conf_media = sum(votos_put) / len(votos_put)
                vela = velas[-1]
                corpo = abs(vela['close'] - vela['open'])
                if corpo > 0:
                    pavio_inf = min(vela['close'], vela['open']) - vela['low']
                    if pavio_inf > corpo * 0.5:
                        continue
                return {'ativo': par, 'direcao': 'PUT', 'confianca': conf_media}
        return None

    def calcular_horario_entrada(self):
        agora = datetime.now(FUSO_BR)
        minuto = agora.minute
        resto = minuto % 5
        if resto == 0 and agora.second == 0:
            return agora.replace(second=0, microsecond=0)
        else:
            return agora.replace(second=0, microsecond=0) + timedelta(minutes=5 - resto)

    def formatar_sinal(self, sinal, horario):
        ativo = sinal['ativo']
        direcao = sinal['direcao']
        hora = horario.strftime('%H:%M')
        return f"""🚨SINAL AO VIVO🚨

✳️ QUANTUM IA M5 ✅
⏲ EXPIRAÇÃO: M5

👉🏼 HORARIO: {hora}

🏳ATIVO: {ativo} {direcao}

🍀🍀BOA SORTE 🍀 🍀"""

    async def monitorar_resultado(self, sinal, horario_entrada):
        ativo = sinal['ativo']
        direcao = sinal['direcao']

        agora = datetime.now(FUSO_BR)
        espera = (horario_entrada + timedelta(minutes=5) - agora).total_seconds()
        if espera > 0:
            await asyncio.sleep(espera)
        await asyncio.sleep(10)
        await self.atualizar_velas()
        velas = self.velas[ativo]

        ganhou = False
        for v in velas:
            if v['time'].replace(second=0, microsecond=0) == horario_entrada.replace(second=0, microsecond=0):
                ganhou = v['close'] > v['open'] if direcao == 'CALL' else v['close'] < v['open']
                break

        if ganhou:
            self.placar['w'] += 1
            resultado = "✅ WIN"
        else:
            if USAR_GALE:
                proxima_vela = horario_entrada + timedelta(minutes=5)
                agora = datetime.now(FUSO_BR)
                espera = (proxima_vela + timedelta(minutes=5) - agora).total_seconds()
                if espera > 0:
                    await asyncio.sleep(espera)
                await asyncio.sleep(10)
                await self.atualizar_velas()
                velas = self.velas[ativo]
                ganhou_gale = False
                for v in velas:
                    if v['time'].replace(second=0, microsecond=0) == proxima_vela.replace(second=0, microsecond=0):
                        ganhou_gale = v['close'] > v['open'] if direcao == 'CALL' else v['close'] < v['open']
                        break
                if ganhou_gale:
                    self.placar['g1'] += 1
                    resultado = "✅ WIN GALE 1"
                else:
                    self.placar['l'] += 1
                    resultado = "❌ LOSS"
            else:
                self.placar['l'] += 1
                resultado = "❌ LOSS"

        total = self.placar['w'] + self.placar['g1'] + self.placar['l']
        tx = round(((self.placar['w'] + self.placar['g1']) / total) * 100, 1) if total > 0 else 0.0
        msg = f"""{resultado}
📊 {ativo} | {direcao} {'🟢' if direcao=='CALL' else '🔴'}
📊 Placar: 🟢{self.placar['w']}W 🟡{self.placar['g1']}G1 🔴{self.placar['l']}L
🎯 Assertividade: {tx}%"""
        self.tg.send(msg)

    def verificar_zeramento_diario(self):
        agora = datetime.now(FUSO_BR)
        if agora.day != self.ultimo_dia:
            self.ultimo_dia = agora.day
            self.placar = {'w': 0, 'g1': 0, 'l': 0}
            self.tg.send("🔄 *PLACAR ZERADO AUTOMATICAMENTE PARA O NOVO DIA*")
            print("🔄 Placar zerado para o novo dia.")

    async def executar(self):
        banner()
        print("⚛️ Bot Forex Real M5 iniciando...")
        self.tg.send("🔥 *QUANTUM IA M5 FOREX ATIVADO*\n📊 Estratégias: Formiga, Fortaleza, Raio Negro, Tsunami\n📰 Filtro de notícias 3 touros\n🛡️ Volatilidade e horário\n🔄 Placar diário automático")
        while True:
            try:
                self.verificar_zeramento_diario()
                await self.atualizar_velas()
                sinal = self.buscar_sinal_consenso()
                if sinal and time.time() - self.ult_sinal > INTERVALO_MINIMO:
                    horario_entrada = self.calcular_horario_entrada()
                    horario_envio = horario_entrada - timedelta(seconds=ANTECEDENCIA)
                    agora = datetime.now(FUSO_BR)
                    espera = (horario_envio - agora).total_seconds()
                    if espera > 0:
                        await asyncio.sleep(espera)
                    self.ult_sinal = time.time()
                    msg = self.formatar_sinal(sinal, horario_entrada)
                    self.tg.send(msg)
                    asyncio.create_task(self.monitorar_resultado(sinal, horario_entrada))
                await asyncio.sleep(1)
            except KeyboardInterrupt:
                print("🛑 Encerrado.")
                break
            except Exception as e:
                print(f"Erro: {e}")
                await asyncio.sleep(10)

if __name__ == "__main__":
    bot = BotM5Forex()
    asyncio.run(bot.executar())
