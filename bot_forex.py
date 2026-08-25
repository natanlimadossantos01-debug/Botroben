#!/usr/bin/env python3
"""
⚛️ QUANTUM IA M15 - SEM GALE
📊 Estratégia: Tendência Forte + Pullback + Confirmação
🎯 Timeframe: M15 (15 minutos)
🛡️ Sem martingale (entrada única)
📡 Yahoo Finance (Forex) ou IQ Option (OTC)
✅ Correção: close vs open
"""
import asyncio, time, requests, numpy as np, signal, sys, json, os
from datetime import datetime, timedelta, timezone
from collections import deque
from pathlib import Path
import yfinance as yf

signal.signal(signal.SIGCHLD, signal.SIG_IGN)
FUSO_BR = timezone(timedelta(hours=-3))

# Configurações
INTERVALO_MINIMO = 900       # 15 min entre sinais
USAR_GALE = False            # SEM GALE
ANTECEDENCIA = 30
CONFIANCA_MINIMA = 70        # Alta confiança (sem gale)

# Volatilidade
ATR_MIN = 0.0001
ATR_MAX = 0.0030

def banner():
    print("⚛️ QUANTUM IA M15 - Sem Gale")

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

# Pares (Yahoo Finance - Forex real)
ATIVOS = {
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "USDJPY": "USDJPY=X",
    "AUDUSD": "AUDUSD=X",
}

class Telegram:
    def __init__(self, t, c):
        self.url = f"https://api.telegram.org/bot{t}"
        self.c = c
    def send(self, txt):
        try: requests.post(f"{self.url}/sendMessage", json={"chat_id": self.c, "text": txt, "parse_mode": "Markdown"}, timeout=10)
        except: pass

class EstrategiaM15SemGale:
    """
    Estratégia M15 sem gale:
    - Tendência forte (EMA 21 e EMA 50)
    - Pullback na EMA 21
    - Confirmação com vela de rejeição
    - RSI entre 40-60 (não sobrecomprado/sobrevendido)
    """
    
    def __init__(self):
        self.ema_rapida = 21
        self.ema_lenta = 50
        self.rsi_periodo = 14
    
    def _ema(self, dados, periodo):
        if len(dados) < periodo:
            return np.mean(dados) if len(dados) > 0 else 0
        alpha = 2 / (periodo + 1)
        ema = dados[0]
        for i in range(1, len(dados)):
            ema = alpha * dados[i] + (1 - alpha) * ema
        return ema
    
    def _rsi(self, precos, periodo=14):
        if len(precos) < periodo + 1:
            return 50
        deltas = np.diff(precos[-periodo-1:])
        ganhos = np.where(deltas > 0, deltas, 0)
        perdas = np.where(deltas < 0, -deltas, 0)
        media_ganho = np.mean(ganhos)
        media_perda = np.mean(perdas)
        if media_perda == 0:
            return 100
        rs = media_ganho / media_perda
        return 100 - (100 / (1 + rs))
    
    def analisar(self, velas):
        if len(velas) < 55:
            return None, 0, {}
        
        precos = [v['close'] for v in velas]
        
        ema21 = self._ema(precos, 21)
        ema50 = self._ema(precos, 50)
        rsi = self._rsi(precos, 14)
        
        atual = precos[-1]
        vela = velas[-1]
        corpo = abs(vela['close'] - vela['open'])
        
        if corpo == 0:
            return None, 0, {}
        
        pavio_sup = vela['high'] - max(vela['close'], vela['open'])
        pavio_inf = min(vela['close'], vela['open']) - vela['low']
        
        detalhes = {}
        score_call = 0
        score_put = 0
        
        # CALL: Tendência alta forte
        if ema21 > ema50 and atual > ema21:
            score_call += 30
            detalhes['tendencia'] = 'ALTA FORTE'
            
            # Pullback próximo da EMA21
            distancia_ema = abs(atual - ema21) / ema21
            if distancia_ema <= 0.001:
                score_call += 20
                detalhes['pullback'] = 'PRÓXIMO EMA21'
            
            # Vela de rejeição (pavio inferior)
            if pavio_inf >= corpo * 1.2:
                score_call += 25
                detalhes['rejeicao'] = 'PAVIO INFERIOR'
            
            # RSI favorável
            if 40 <= rsi <= 65:
                score_call += 15
                detalhes['rsi'] = f'FAVORÁVEL ({rsi:.1f})'
        
        # PUT: Tendência baixa forte
        if ema21 < ema50 and atual < ema21:
            score_put += 30
            detalhes['tendencia'] = 'BAIXA FORTE'
            
            # Pullback próximo da EMA21
            distancia_ema = abs(atual - ema21) / ema21
            if distancia_ema <= 0.001:
                score_put += 20
                detalhes['pullback'] = 'PRÓXIMO EMA21'
            
            # Vela de rejeição (pavio superior)
            if pavio_sup >= corpo * 1.2:
                score_put += 25
                detalhes['rejeicao'] = 'PAVIO SUPERIOR'
            
            # RSI favorável
            if 35 <= rsi <= 60:
                score_put += 15
                detalhes['rsi'] = f'FAVORÁVEL ({rsi:.1f})'
        
        if score_call > score_put and score_call >= CONFIANCA_MINIMA:
            return 'CALL', score_call, detalhes
        elif score_put > score_call and score_put >= CONFIANCA_MINIMA:
            return 'PUT', score_put, detalhes
        
        return None, 0, detalhes

class BotM15:
    def __init__(self):
        self.tg = Telegram(TOKEN, CHAT)
        self.velas = {nome: deque(maxlen=100) for nome in ATIVOS}
        self.estrategia = EstrategiaM15SemGale()
        self.placar = {'w': 0, 'l': 0}  # Sem gale
        self.ult_sinal = 0
        self.sinais = 0
        self.ultimo_dia = datetime.now(FUSO_BR).day
    
    def atualizar_velas(self):
        """Busca velas M15 do Yahoo Finance"""
        for nome, symbol in ATIVOS.items():
            try:
                ticker = yf.Ticker(symbol)
                df = ticker.history(period="1d", interval="15m")
                
                if df is not None and len(df) > 0:
                    self.velas[nome].clear()
                    for index, row in df.iterrows():
                        self.velas[nome].append({
                            'time': index.to_pydatetime().astimezone(FUSO_BR),
                            'open': float(row['Open']),
                            'high': float(row['High']),
                            'low': float(row['Low']),
                            'close': float(row['Close']),
                            'volume': int(row['Volume']) if 'Volume' in row else 0
                        })
                    print(f"✅ {nome}: {len(self.velas[nome])} velas")
                else:
                    print(f"⚠️ {nome}: sem dados")
            except Exception as e:
                print(f"❌ {nome}: {e}")
        
        print()
    
    def calcular_atr(self, velas, periodo=14):
        if len(velas) < periodo + 1:
            return None
        trs = []
        for i in range(-periodo, 0):
            h = velas[i]['high']
            l = velas[i]['low']
            c_prev = velas[i-1]['close'] if i > -periodo else velas[i]['open']
            tr = max(h - l, abs(h - c_prev), abs(l - c_prev))
            trs.append(tr)
        return np.mean(trs)
    
    def buscar_sinal(self):
        melhor_sinal = None
        melhor_score = 0
        
        for par, velas in self.velas.items():
            if len(velas) < 55:
                continue
            
            atr = self.calcular_atr(velas, 14)
            if atr is None or atr < ATR_MIN or atr > ATR_MAX:
                continue
            
            direcao, confianca, detalhes = self.estrategia.analisar(velas)
            if direcao and confianca >= CONFIANCA_MINIMA:
                if confianca > melhor_score:
                    melhor_score = confianca
                    melhor_sinal = {
                        'ativo': par,
                        'direcao': direcao,
                        'confianca': confianca,
                        'detalhes': detalhes
                    }
        
        return melhor_sinal
    
    def calcular_horario_entrada(self):
        agora = datetime.now(FUSO_BR)
        minuto = agora.minute
        resto = minuto % 15
        if resto == 0 and agora.second == 0:
            return agora.replace(second=0, microsecond=0)
        else:
            return agora.replace(second=0, microsecond=0) + timedelta(minutes=15 - resto)
    
    def formatar_sinal(self, sinal, horario):
        ativo = sinal['ativo']
        direcao = sinal['direcao']
        conf = sinal['confianca']
        detalhes = sinal.get('detalhes', {})
        hora = horario.strftime('%H:%M')
        detalhes_txt = "\n".join([f"• {k}: {v}" for k, v in detalhes.items()])
        
        return f"""🚨SINAL M15 SEM GALE🚨

⚛️ QUANTUM IA M15
⏲ EXPIRAÇÃO: 15 MINUTOS

👉🏼 HORARIO: {hora}

🏳 ATIVO: {ativo} {'🟢' if direcao == 'CALL' else '🔴'}
📊 DIREÇÃO: {direcao}
🎯 CONFIANÇA: {conf:.0f}%

📈 ANÁLISE:
{detalhes_txt}

🛡️ SEM GALE - ENTRADA ÚNICA

🍀🍀 BOA SORTE 🍀🍀"""
    
    async def monitorar_resultado(self, sinal, horario_entrada):
        ativo = sinal['ativo']
        direcao = sinal['direcao']
        
        agora = datetime.now(FUSO_BR)
        espera = (horario_entrada + timedelta(minutes=15) - agora).total_seconds()
        if espera > 0:
            await asyncio.sleep(espera)
        await asyncio.sleep(30)
        self.atualizar_velas()
        velas = self.velas[ativo]
        
        ganhou = False
        for v in velas:
            if v['time'].replace(second=0, microsecond=0) == horario_entrada.replace(second=0, microsecond=0):
                if direcao == 'CALL':
                    ganhou = v['close'] > v['open']
                else:
                    ganhou = v['close'] < v['open']
                break
        
        if ganhou:
            self.placar['w'] += 1
            resultado = "✅ WIN"
        else:
            self.placar['l'] += 1
            resultado = "❌ LOSS"
        
        total = self.placar['w'] + self.placar['l']
        tx = round((self.placar['w'] / total) * 100, 1) if total > 0 else 0.0
        msg = f"""{resultado}
📊 {ativo} | {direcao} {'🟢' if direcao=='CALL' else '🔴'}
📊 Placar: 🟢{self.placar['w']}W 🔴{self.placar['l']}L
🎯 Assertividade: {tx}%"""
        self.tg.send(msg)
    
    def verificar_zeramento_diario(self):
        agora = datetime.now(FUSO_BR)
        if agora.day != self.ultimo_dia:
            self.ultimo_dia = agora.day
            self.placar = {'w': 0, 'l': 0}
            self.tg.send("🔄 *PLACAR ZERADO*")
            print("🔄 Placar zerado.")
    
    async def executar(self):
        banner()
        print("⚛️ Bot M15 sem gale iniciando...")
        self.tg.send(f"""🔥 *QUANTUM IA M15 SEM GALE*

📊 Estratégia: Tendência + Pullback + Confirmação
🎯 Confiança mínima: {CONFIANCA_MINIMA}%
⏱️ Timeframe: M15
🛡️ SEM GALE - Entrada única
📡 Yahoo Finance""")
        
        while True:
            try:
                self.verificar_zeramento_diario()
                self.atualizar_velas()
                
                horario_entrada = self.calcular_horario_entrada()
                horario_envio = horario_entrada - timedelta(seconds=ANTECEDENCIA)
                
                agora = datetime.now(FUSO_BR)
                tempo_ate_envio = (horario_envio - agora).total_seconds()
                
                if 0 <= tempo_ate_envio <= 35:
                    sinal = self.buscar_sinal()
                    
                    if sinal and time.time() - self.ult_sinal > INTERVALO_MINIMO:
                        if tempo_ate_envio > 0:
                            await asyncio.sleep(tempo_ate_envio)
                        
                        self.ult_sinal = time.time()
                        self.sinais += 1
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
    asyncio.run(BotM15().executar())
