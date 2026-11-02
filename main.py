# xauusd_bot/main.py  |  Python 3.10+  |  Kivy 2.3.0
# Built by Olivia — https://discord.gg/ojailbreaks

import threading, time
from datetime import datetime
from collections import deque

import numpy  as np
import pandas as pd

try:
    import yfinance as yf
    HAS_YF = True
except Exception:
    HAS_YF = False

try:
    from plyer import notification as pnotif
    from plyer import vibrator
    HAS_PLYER = True
except Exception:
    HAS_PLYER = False

from kivy.app                  import App
from kivy.clock                import Clock, mainthread
from kivy.core.window          import Window
from kivy.lang                 import Builder
from kivy.metrics              import dp, sp
from kivy.uix.boxlayout        import BoxLayout
from kivy.uix.gridlayout       import GridLayout
from kivy.uix.scrollview       import ScrollView
from kivy.uix.label            import Label
from kivy.uix.button           import Button
from kivy.uix.spinner          import Spinner
from kivy.uix.switch           import Switch
from kivy.uix.widget           import Widget
from kivy.uix.screenmanager    import ScreenManager, Screen, SlideTransition
from kivy.graphics             import Color, RoundedRectangle, Rectangle

Window.clearcolor = (.07, .09, .13, 1)

# ══════════════ COLOURS ══════════════════════════════════════════════════════
BG     = (.07, .09, .13, 1)
CARD   = (.11, .14, .19, 1)
GOLD   = (.95, .78, .22, 1)
BUY_C  = (.14, .70, .40, 1)
SELL_C = (.82, .22, .28, 1)
NEU_C  = (.45, .52, .62, 1)
WHITE  = (.95, .96, .98, 1)
GREY   = (.40, .48, .60, 1)

# ══════════════ TECHNICAL ANALYSIS ══════════════════════════════════════════
class TA:
    @staticmethod
    def rsi(c: pd.Series, p=14):
        d  = c.diff()
        g  = d.clip(lower=0).rolling(p).mean()
        l  = (-d.clip(upper=0)).rolling(p).mean()
        return 100 - (100 / (1 + g / l.replace(0, 1e-9)))

    @staticmethod
    def macd(c, fast=12, slow=26, sig=9):
        ef = c.ewm(span=fast, adjust=False).mean()
        es = c.ewm(span=slow, adjust=False).mean()
        m  = ef - es
        s  = m.ewm(span=sig, adjust=False).mean()
        return m, s, m - s

    @staticmethod
    def ema(c, p):
        return c.ewm(span=p, adjust=False).mean()

    @staticmethod
    def atr(h, l, c, p=14):
        tr = pd.concat(
            [h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1
        ).max(1)
        return tr.rolling(p).mean()

    @staticmethod
    def bb(c, p=20, s=2.0):
        m  = c.rolling(p).mean()
        sd = c.rolling(p).std()
        return m + s * sd, m, m - s * sd

    @staticmethod
    def stoch(h, l, c, k=14, d=3):
        lm = l.rolling(k).min()
        hm = h.rolling(k).max()
        kl = 100 * (c - lm) / (hm - lm + 1e-9)
        return kl, kl.rolling(d).mean()


# ══════════════ SIGNAL ENGINE ════════════════════════════════════════════════
class Signals:
    BUY_THRESH  =  30
    SELL_THRESH = -30

    def run(self, df: pd.DataFrame):
        if df is None or len(df) < 210:
            return None

        C, H, L    = df['Close'], df['High'], df['Low']
        score      = 0
        reasons    = []

        # RSI
        rsi_s = TA.rsi(C, 14)
        rsi   = rsi_s.iloc[-1]
        if   rsi < 30: score += 25; reasons.append(f"RSI {rsi:.1f} — oversold ↑")
        elif rsi < 42: score += 12; reasons.append(f"RSI {rsi:.1f} — soft long ↑")
        elif rsi > 70: score -= 25; reasons.append(f"RSI {rsi:.1f} — overbought ↓")
        elif rsi > 58: score -= 12; reasons.append(f"RSI {rsi:.1f} — soft short ↓")

        # MACD
        mc, ms, mh = TA.macd(C)
        hist, ph   = mh.iloc[-1], mh.iloc[-2]
        if   mc.iloc[-1] > ms.iloc[-1] and ph < 0 < hist:
            score += 22; reasons.append("MACD bullish cross ↑")
        elif mc.iloc[-1] > ms.iloc[-1]:
            score +=  9; reasons.append("MACD bullish ↑")
        elif mc.iloc[-1] < ms.iloc[-1] and ph > 0 > hist:
            score -= 22; reasons.append("MACD bearish cross ↓")
        elif mc.iloc[-1] < ms.iloc[-1]:
            score -=  9; reasons.append("MACD bearish ↓")

        # EMA stack
        e20, e50, e200 = [TA.ema(C, p).iloc[-1] for p in (20, 50, 200)]
        p = C.iloc[-1]
        if   p > e20 > e50 > e200: score += 20; reasons.append("EMA stack bull ↑")
        elif p > e50 > e200:       score += 10; reasons.append("Above EMA50/200 ↑")
        elif p < e20 < e50 < e200: score -= 20; reasons.append("EMA stack bear ↓")
        elif p < e50 < e200:       score -= 10; reasons.append("Below EMA50/200 ↓")

        # Bollinger Bands
        bu, bm, bl = TA.bb(C, 20, 2.0)
        if   p <= bl.iloc[-1]: score += 15; reasons.append("BB lower bounce ↑")
        elif p >= bu.iloc[-1]: score -= 15; reasons.append("BB upper reject ↓")

        # Stochastic
        kl, dl = TA.stoch(H, L, C)
        k, pk  = kl.iloc[-1], kl.iloc[-2]
        if   k < 20 and k > pk: score += 18; reasons.append(f"Stoch {k:.0f} oversold ↑")
        elif k > 80 and k < pk: score -= 18; reasons.append(f"Stoch {k:.0f} overbought ↓")

        score = max(-100, min(100, score))
        atr   = TA.atr(H, L, C, 14).iloc[-1]

        if   score >= self.BUY_THRESH:  direction = "BUY";     sl = p - 1.5*atr; tp = p + 2.5*atr
        elif score <= self.SELL_THRESH: direction = "SELL";    sl = p + 1.5*atr; tp = p - 2.5*atr
        else:                           direction = "NEUTRAL";  sl = p - 1.5*atr; tp = p + 2.5*atr

        chg = ((p - C.iloc[-2]) / C.iloc[-2]) * 100

        return dict(
            direction=direction, score=score,
            price=p, change=chg,
            sl=sl, tp=tp, atr=atr,
            rsi=rsi, macd=mc.iloc[-1],
            ema20=e20, ema50=e50, ema200=e200,
            stoch_k=k, reasons=reasons,
            time=datetime.now().strftime("%H:%M:%S"),
            date=datetime.now().strftime("%d.%m.%Y"),
        )


# ══════════════ DATA FEED ════════════════════════════════════════════════════
class Feed:
    SYM = "XAUUSD=X"

    def fetch(self, period="5d", interval="15m"):
        if not HAS_YF:
            return None
        try:
            df = yf.Ticker(self.SYM).history(period=period, interval=interval)
            if df.empty:
                return None
            return df[["Open", "High", "Low", "Close", "Volume"]].dropna()
        except Exception as e:
            print(f"[Feed] {e}")
            return None


# ══════════════ KV LAYOUT ════════════════════════════════════════════════════
KV = """
#:import dp kivy.metrics.dp
#:import sp kivy.metrics.sp

<RCard@BoxLayout>:
    padding: dp(14)
    canvas.before:
        Color:
            rgba: .11,.14,.19,1
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(14)]

<Pill@Label>:
    size_hint: None, None
    size: dp(90), dp(30)
    font_size: sp(11)
    bold: True
    halign: 'center'
    valign: 'center'
    text_size: self.size

<TopBar@BoxLayout>:
    size_hint_y: None
    height: dp(56)
    padding: dp(14), dp(8)
    canvas.before:
        Color:
            rgba: .09,.11,.16,1
        Rectangle:
            pos: self.pos
            size: self.size

<DashScreen>:
    name: 'dash'
    BoxLayout:
        orientation: 'vertical'
        canvas.before:
            Color:
                rgba: .07,.09,.13,1
            Rectangle:
                pos: self.pos
                size: self.size

        # Header
        TopBar:
            Label:
                text: '⚡  XAU/USD  GOLD BOT'
                font_size: sp(16)
                bold: True
                color: .95,.78,.22,1
                halign: 'left'
                valign: 'center'
                text_size: self.size
            Label:
                id: lbl_status
                text: '● BAĞLANIR'
                font_size: sp(11)
                color: .45,.52,.62,1
                halign: 'right'
                valign: 'center'
                text_size: self.size

        ScrollView:
            do_scroll_x: False
            BoxLayout:
                orientation: 'vertical'
                spacing: dp(10)
                padding: dp(12), dp(10), dp(12), dp(14)
                size_hint_y: None
                height: self.minimum_height

                # ── Qiymət
                RCard:
                    size_hint_y: None
                    height: dp(108)
                    orientation: 'vertical'
                    spacing: dp(4)
                    BoxLayout:
                        Label:
                            text: 'XAU/USD  (GOLD)'
                            font_size: sp(11)
                            color: .45,.52,.62,1
                            halign: 'left'
                            valign: 'center'
                            text_size: self.size
                        Label:
                            id: lbl_clock
                            text: '--.--.----  --:--:--'
                            font_size: sp(10)
                            color: .35,.42,.52,1
                            halign: 'right'
                            valign: 'center'
                            text_size: self.size
                    Label:
                        id: lbl_price
                        text: '-----.--'
                        font_size: sp(36)
                        bold: True
                        color: .95,.96,.98,1
                        halign: 'left'
                        valign: 'center'
                        text_size: self.size
                        size_hint_y: None
                        height: dp(48)
                    Label:
                        id: lbl_change
                        text: '  ▲ +0.00%'
                        font_size: sp(13)
                        color: .14,.70,.40,1
                        halign: 'left'
                        valign: 'center'
                        text_size: self.size

                # ── Siqnal
                RCard:
                    size_hint_y: None
                    height: dp(118)
                    orientation: 'vertical'
                    spacing: dp(6)
                    BoxLayout:
                        size_hint_y: None
                        height: dp(22)
                        Label:
                            text: 'SİQNAL'
                            font_size: sp(10)
                            color: .45,.52,.62,1
                            halign: 'left'
                            valign: 'center'
                            text_size: self.size
                        Label:
                            id: lbl_score
                            text: 'Xal: 0'
                            font_size: sp(11)
                            color: .45,.52,.62,1
                            halign: 'right'
                            valign: 'center'
                            text_size: self.size
                    BoxLayout:
                        size_hint_y: None
                        height: dp(42)
                        Label:
                            id: lbl_signal
                            text: '◆  NEYTRAL'
                            font_size: sp(28)
                            bold: True
                            color: .45,.52,.62,1
                            halign: 'left'
                            valign: 'center'
                            text_size: self.size
                    Label:
                        id: lbl_reason
                        text: 'Məlumat gözlənilir...'
                        font_size: sp(11)
                        color: .55,.62,.72,1
                        halign: 'left'
                        text_size: self.width, None
                        size_hint_y: None
                        height: self.texture_size[1]

                # ── Giriş / SL / TP
                RCard:
                    size_hint_y: None
                    height: dp(100)
                    orientation: 'vertical'
                    spacing: dp(8)
                    Label:
                        text: 'LEVELLAR  (ATR əsaslı)'
                        font_size: sp(10)
                        color: .45,.52,.62,1
                        halign: 'left'
                        text_size: self.size
                        valign: 'center'
                        size_hint_y: None
                        height: dp(18)
                    GridLayout:
                        cols: 3
                        spacing: dp(6)
                        BoxLayout:
                            orientation: 'vertical'
                            Label:
                                text: 'GİRİŞ'
                                font_size: sp(9)
                                color: .45,.52,.62,1
                                halign: 'center'
                                text_size: self.size
                            Label:
                                id: lbl_entry
                                text: '-.--'
                                font_size: sp(15)
                                bold: True
                                color: .95,.96,.98,1
                                halign: 'center'
                                text_size: self.size
                        BoxLayout:
                            orientation: 'vertical'
                            Label:
                                text: 'STOP LOSS'
                                font_size: sp(9)
                                color: .82,.22,.28,1
                                halign: 'center'
                                text_size: self.size
                            Label:
                                id: lbl_sl
                                text: '-.--'
                                font_size: sp(15)
                                bold: True
                                color: .82,.22,.28,1
                                halign: 'center'
                                text_size: self.size
                        BoxLayout:
                            orientation: 'vertical'
                            Label:
                                text: 'TAKE PROFIT'
                                font_size: sp(9)
                                color: .14,.70,.40,1
                                halign: 'center'
                                text_size: self.size
                            Label:
                                id: lbl_tp
                                text: '-.--'
                                font_size: sp(15)
                                bold: True
                                color: .14,.70,.40,1
                                halign: 'center'
                                text_size: self.size

                # ── İndikatorlar
                RCard:
                    size_hint_y: None
                    height: dp(108)
                    orientation: 'vertical'
                    spacing: dp(8)
                    Label:
                        text: 'İNDİKATORLAR'
                        font_size: sp(10)
                        color: .45,.52,.62,1
                        halign: 'left'
                        text_size: self.size
                        valign: 'center'
                        size_hint_y: None
                        height: dp(18)
                    GridLayout:
                        cols: 3
                        spacing: dp(8)
                        BoxLayout:
                            orientation: 'vertical'
                            Label:
                                text: 'RSI (14)'
                                font_size: sp(9)
                                color: .45,.52,.62,1
                                halign: 'center'
                                text_size: self.size
                            Label:
                                id: lbl_rsi
                                text: '--.-'
                                font_size: sp(18)
                                bold: True
                                color: .95,.96,.98,1
                                halign: 'center'
                                text_size: self.size
                        BoxLayout:
                            orientation: 'vertical'
                            Label:
                                text: 'MACD'
                                font_size: sp(9)
                                color: .45,.52,.62,1
                                halign: 'center'
                                text_size: self.size
                            Label:
                                id: lbl_macd
                                text: '--.-'
                                font_size: sp(18)
                                bold: True
                                color: .95,.96,.98,1
                                halign: 'center'
                                text_size: self.size
                        BoxLayout:
                            orientation: 'vertical'
                            Label:
                                text: 'STOCH'
                                font_size: sp(9)
                                color: .45,.52,.62,1
                                halign: 'center'
                                text_size: self.size
                            Label:
                                id: lbl_stoch
                                text: '--.-'
                                font_size: sp(18)
                                bold: True
                                color: .95,.96,.98,1
                                halign: 'center'
                                text_size: self.size

                # ── EMA
                RCard:
                    size_hint_y: None
                    height: dp(88)
                    orientation: 'vertical'
                    spacing: dp(6)
                    Label:
                        text: 'EMA STACK'
                        font_size: sp(10)
                        color: .45,.52,.62,1
                        halign: 'left'
                        text_size: self.size
                        valign: 'center'
                        size_hint_y: None
                        height: dp(18)
                    GridLayout:
                        cols: 3
                        spacing: dp(8)
                        BoxLayout:
                            orientation: 'vertical'
                            Label:
                                text: 'EMA 20'
                                font_size: sp(9)
                                color: .45,.52,.62,1
                                halign: 'center'
                                text_size: self.size
                            Label:
                                id: lbl_ema20
                                text: '----'
                                font_size: sp(13)
                                bold: True
                                color: .95,.78,.22,1
                                halign: 'center'
                                text_size: self.size
                        BoxLayout:
                            orientation: 'vertical'
                            Label:
                                text: 'EMA 50'
                                font_size: sp(9)
                                color: .45,.52,.62,1
                                halign: 'center'
                                text_size: self.size
                            Label:
                                id: lbl_ema50
                                text: '----'
                                font_size: sp(13)
                                bold: True
                                color: .95,.78,.22,1
                                halign: 'center'
                                text_size: self.size
                        BoxLayout:
                            orientation: 'vertical'
                            Label:
                                text: 'EMA 200'
                                font_size: sp(9)
                            
