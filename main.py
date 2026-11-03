# main.py | XAU/USD Bot | Python 3.10+ | Kivy 2.2.1
# Built by Olivia — https://discord.gg/ojailbreaks

import threading, time, json
from datetime import datetime
from collections import deque
from urllib.request import urlopen, Request
from urllib.error import URLError

try:
    from plyer import notification as pnotif
    from plyer import vibrator
    HAS_PLYER = True
except Exception:
    HAS_PLYER = False

from kivy.app               import App
from kivy.clock             import mainthread
from kivy.core.window       import Window
from kivy.lang              import Builder
from kivy.metrics           import dp, sp
from kivy.uix.boxlayout     import BoxLayout
from kivy.uix.gridlayout    import GridLayout
from kivy.uix.scrollview    import ScrollView
from kivy.uix.label         import Label
from kivy.uix.button        import Button
from kivy.uix.spinner       import Spinner
from kivy.uix.switch        import Switch
from kivy.uix.widget        import Widget
from kivy.uix.screenmanager import ScreenManager, Screen, SlideTransition
from kivy.graphics          import Color, RoundedRectangle, Rectangle

Window.clearcolor = (.07, .09, .13, 1)

BG     = (.07, .09, .13, 1)
CARD   = (.11, .14, .19, 1)
GOLD   = (.95, .78, .22, 1)
BUY_C  = (.14, .70, .40, 1)
SELL_C = (.82, .22, .28, 1)
NEU_C  = (.45, .52, .62, 1)
WHITE  = (.95, .96, .98, 1)
GREY   = (.40, .48, .60, 1)


# ══════════════ PURE PYTHON TA ═══════════════════════════════════════════════
def mean(lst): return sum(lst) / len(lst) if lst else 0.0
def std(lst):
    if len(lst) < 2: return 0.0
    m = mean(lst)
    return (sum((x-m)**2 for x in lst) / (len(lst)-1)) ** 0.5

def calc_rsi(closes, p=14):
    if len(closes) < p+1: return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i-1]
        gains.append(max(d, 0)); losses.append(max(-d, 0))
    ag = mean(gains[-p:]); al = mean(losses[-p:])
    return 100.0 - (100.0 / (1 + ag / al)) if al else 100.0

def calc_ema(closes, p):
    if not closes: return 0.0
    k = 2.0 / (p + 1)
    e = closes[0]
    for c in closes[1:]: e = c * k + e * (1 - k)
    return e

def calc_macd(closes):
    if len(closes) < 26: return 0.0, 0.0, 0.0
    ef = calc_ema(closes, 12)
    es = calc_ema(closes, 26)
    m  = ef - es
    # signal: ema9 of macd values
    macds = [calc_ema(closes[:i], 12) - calc_ema(closes[:i], 26)
             for i in range(26, len(closes)+1)]
    s = calc_ema(macds, 9) if len(macds) >= 9 else m
    return m, s, m - s

def calc_bb(closes, p=20):
    if len(closes) < p: return 0.0, 0.0, 0.0
    sl = closes[-p:]
    m  = mean(sl); sd = std(sl)
    return m + 2*sd, m, m - 2*sd

def calc_atr(highs, lows, closes, p=14):
    if len(closes) < 2: return 1.0
    trs = []
    for i in range(1, len(closes)):
        tr = max(highs[i]-lows[i],
                 abs(highs[i]-closes[i-1]),
                 abs(lows[i]-closes[i-1]))
        trs.append(tr)
    return mean(trs[-p:]) if trs else 1.0

def calc_stoch(highs, lows, closes, k=14):
    if len(closes) < k: return 50.0
    lm = min(lows[-k:]); hm = max(highs[-k:])
    return 100*(closes[-1]-lm)/(hm-lm) if hm != lm else 50.0


# ══════════════ SIGNAL ENGINE ════════════════════════════════════════════════
def run_signals(data):
    if not data or len(data['c']) < 50:
        return None
    C = data['c']; H = data['h']; L = data['l']
    score = 0; reasons = []

    rsi = calc_rsi(C)
    if   rsi < 30: score += 25; reasons.append(f"RSI {rsi:.1f} oversold ↑")
    elif rsi < 42: score += 12; reasons.append(f"RSI {rsi:.1f} soft long ↑")
    elif rsi > 70: score -= 25; reasons.append(f"RSI {rsi:.1f} overbought ↓")
    elif rsi > 58: score -= 12; reasons.append(f"RSI {rsi:.1f} soft short ↓")

    mc, ms, mh = calc_macd(C)
    if   mc > ms: score += 15; reasons.append("MACD bullish ↑")
    elif mc < ms: score -= 15; reasons.append("MACD bearish ↓")

    e20  = calc_ema(C, 20)
    e50  = calc_ema(C, 50)
    e200 = calc_ema(C[-200:] if len(C)>=200 else C, min(200,len(C)))
    p    = C[-1]
    if   p > e20 > e50: score += 20; reasons.append("EMA stack bull ↑")
    elif p < e20 < e50: score -= 20; reasons.append("EMA stack bear ↓")

    bu, bm, bl = calc_bb(C)
    if   p <= bl: score += 15; reasons.append("BB lower bounce ↑")
    elif p >= bu: score -= 15; reasons.append("BB upper reject ↓")

    sk = calc_stoch(H, L, C)
    pk = calc_stoch(H[:-1], L[:-1], C[:-1]) if len(C) > 14 else 50
    if   sk < 20 and sk > pk: score += 18; reasons.append(f"Stoch {sk:.0f} oversold ↑")
    elif sk > 80 and sk < pk: score -= 18; reasons.append(f"Stoch {sk:.0f} overbought ↓")

    score = max(-100, min(100, score))
    atr   = calc_atr(H, L, C)

    if   score >= 30:  d = "BUY";     sl = p-1.5*atr; tp = p+2.5*atr
    elif score <= -30: d = "SELL";    sl = p+1.5*atr; tp = p-2.5*atr
    else:              d = "NEUTRAL"; sl = p-1.5*atr; tp = p+2.5*atr

    chg = ((p - C[-2]) / C[-2]) * 100 if len(C) > 1 else 0

    return dict(
        direction=d, score=score,
        price=p, change=chg,
        sl=sl, tp=tp, atr=atr,
        rsi=rsi, macd=mc,
        ema20=e20, ema50=e50, ema200=e200,
        stoch_k=sk, reasons=reasons,
        time=datetime.now().strftime("%H:%M:%S"),
        date=datetime.now().strftime("%d.%m.%Y"),
    )


# ══════════════ DATA FEED ════════════════════════════════════════════════════
def fetch_data(interval="15m", period="5d"):
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/XAUUSD%3DX"
           f"?interval={interval}&range={period}")
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=15) as r:
            js = json.loads(r.read())
        q = js["chart"]["result"][0]["indicators"]["quote"][0]
        c = js["chart"]["result"][0]["indicators"]["adjclose"][0].get(
            "adjclose", q["close"])
        raw_c = [x for x in (c or q["close"]) if x is not None]
        raw_h = [x for x in q["high"]   if x is not None]
        raw_l = [x for x in q["low"]    if x is not None]
        if len(raw_c) < 20: return None
        return {"c": raw_c, "h": raw_h, "l": raw_l}
    except Exception as e:
        print(f"[Feed] {e}"); return None


# ══════════════ KV ═══════════════════════════════════════════════════════════
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
                                color: .45,.52,.62,1
                                halign: 'center'
                                text_size: self.size
                            Label:
                                id: lbl_ema200
                                text: '----'
                                font_size: sp(13)
                                bold: True
                                color: .95,.78,.22,1
                                halign: 'center'
                                text_size: self.size

                RCard:
                    size_hint_y: None
                    height: dp(52)
                    BoxLayout:
                        Label:
                            text: 'ATR (14):'
                            font_size: sp(12)
                            color: .45,.52,.62,1
                            halign: 'left'
                            valign: 'center'
                            text_size: self.size
                        Label:
                            id: lbl_atr
                            text: '--.-'
                            font_size: sp(15)
                            bold: True
                            color: .95,.78,.22,1
                            halign: 'center'
                            valign: 'center'
                            text_size: self.size
                        Label:
                            text: 'SL=1.5×ATR  TP=2.5×ATR'
                            font_size: sp(9)
                            color: .35,.42,.52,1
                            halign: 'right'
                            valign: 'center'
                            text_size: self.size

                BoxLayout:
                    size_hint_y: None
                    height: dp(46)
                    spacing: dp(8)
                    Button:
                        text: 'YENİLƏ'
                        font_size: sp(12)
                        bold: True
                        color: .95,.78,.22,1
                        background_normal: ''
                        background_color: .15,.19,.26,1
                        on_release: app.manual_refresh()
                    Button:
                        text: 'TARİXÇƏ'
                        font_size: sp(12)
                        bold: True
                        color: .95,.96,.98,1
                        background_normal: ''
                        background_color: .15,.19,.26,1
                        on_release: app.goto('history')
                    Button:
                        text: 'AYARLAR'
                        font_size: sp(12)
                        bold: True
                        color: .95,.96,.98,1
                        background_normal: ''
                        background_color: .15,.19,.26,1
                        on_release: app.goto('settings')

<HistoryScreen>:
    name: 'history'
    BoxLayout:
        orientation: 'vertical'
        canvas.before:
            Color:
                rgba: .07,.09,.13,1
            Rectangle:
                pos: self.pos
                size: self.size
        TopBar:
            Button:
                text: '← GERİ'
                size_hint_x: None
                width: dp(80)
                font_size: sp(12)
                bold: True
                color: .95,.78,.22,1
                background_color: 0,0,0,0
                background_normal: ''
                on_release: app.goto('dash')
            Label:
                text: 'TARİXÇƏ'
                font_size: sp(14)
                bold: True
                color: .95,.78,.22,1
                halign: 'center'
                valign: 'center'
                text_size: self.size
            Widget:
                size_hint_x: None
                width: dp(80)
        ScrollView:
            BoxLayout:
                id: history_box
                orientation: 'vertical'
                spacing: dp(8)
                padding: dp(12), dp(10)
                size_hint_y: None
                height: self.minimum_height

<SettingsScreen>:
    name: 'settings'
    BoxLayout:
        orientation: 'vertical'
        canvas.before:
            Color:
                rgba: .07,.09,.13,1
            Rectangle:
                pos: self.pos
                size: self.size
        TopBar:
            Button:
                text: '← GERİ'
                size_hint_x: None
                width: dp(80)
                font_size: sp(12)
                bold: True
                color: .95,.78,.22,1
                background_color: 0,0,0,0
                background_normal: ''
                on_release: app.goto('dash')
            Label:
                text: 'AYARLAR'
                font_size: sp(14)
                bold: True
                color: .95,.78,.22,1
                halign: 'center'
                valign: 'center'
                text_size: self.size
            Widget:
                size_hint_x: None
                width: dp(80)
        ScrollView:
            BoxLayout:
                orientation: 'vertical'
                spacing: dp(12)
                padding: dp(14), dp(14)
                size_hint_y: None
                height: self.minimum_height

                RCard:
                    size_hint_y: None
                    height: dp(80)
                    orientation: 'vertical'
                    spacing: dp(6)
                    Label:
                        text: 'ZAMAN DİLİMİ'
                        font_size: sp(10)
                        color: .45,.52,.62,1
                        halign: 'left'
                        text_size: self.size
                        valign: 'center'
                        size_hint_y: None
                        height: dp(20)
                    Spinner:
                        id: spin_tf
                        text: '15m'
                        values: ['5m','15m','30m','1h','1d']
                        font_size: sp(14)
                        color: .95,.96,.98,1
                        background_color: .20,.24,.32,1
                        background_normal: ''
                        size_hint_y: None
                        height: dp(42)
                        on_text: app.set_timeframe(self.text)

                RCard:
                    size_hint_y: None
                    height: dp(80)
                    orientation: 'vertical'
                    spacing: dp(6)
                    Label:
                        text: 'YENİLƏMƏ İNTERVALI'
                        font_size: sp(10)
                        color: .45,.52,.62,1
                        halign: 'left'
                        text_size: self.size
                        valign: 'center'
                        size_hint_y: None
                        height: dp(20)
                    Spinner:
                        id: spin_poll
                        text: '30s'
                        values: ['15s','30s','60s','120s','300s']
                        font_size: sp(14)
                        color: .95,.96,.98,1
                        background_color: .20,.24,.32,1
                        background_normal: ''
                        size_hint_y: None
                        height: dp(42)
                        on_text: app.set_poll(self.text)

                RCard:
                    size_hint_y: None
                    height: dp(64)
                    BoxLayout:
                        Label:
                            text: 'BİLDİRİŞLƏR'
                            font_size: sp(13)
                            color: .95,.96,.98,1
                            halign: 'left'
                            valign: 'center'
                            text_size: self.size
                        Switch:
                            id: sw_notif
                            active: True
                            size_hint_x: None
                            width: dp(80)
                            on_active: app.set_notif(self.active)

                RCard:
                    size_hint_y: None
                    height: dp(64)
                    BoxLayout:
                        Label:
                            text: 'VİBRASİYA'
                            font_size: sp(13)
                            color: .95,.96,.98,1
                            halign: 'left'
                            valign: 'center'
                            text_size: self.size
                        Switch:
                            id: sw_vib
                            active: True
                            size_hint_x: None
                            width: dp(80)
                            on_active: app.set_vib(self.active)

                RCard:
                    size_hint_y: None
                    height: dp(52)
                    Label:
                        text: 'Built by Olivia — discord.gg/ojailbreaks'
                        font_size: sp(11)
                        color: .40,.48,.60,1
                        halign: 'center'
                        valign: 'center'
                        text_size: self.size
"""


class DashScreen(Screen):    pass
class HistoryScreen(Screen): pass
class SettingsScreen(Screen):pass


class XAUBot(App):
    title = "XAU/USD Bot"

    def build(self):
        Builder.load_string(KV)
        self.sig_history = deque(maxlen=120)
        self.timeframe   = "15m"
        self.period      = "5d"
        self.poll_secs   = 30
        self.do_notif    = True
        self.do_vib      = True
        self._last_dir   = None
        self._running    = True

        sm = ScreenManager(transition=SlideTransition())
        sm.add_widget(DashScreen(name='dash'))
        sm.add_widget(HistoryScreen(name='history'))
        sm.add_widget(SettingsScreen(name='settings'))
        self.sm = sm

        threading.Thread(target=self._loop, daemon=True).start()
        return sm

    def goto(self, n): self.sm.current = n

    def set_timeframe(self, tf):
        self.timeframe = tf
        self.period = {'5m':'2d','15m':'5d','30m':'5d',
                       '1h':'10d','1d':'90d'}.get(tf,'5d')

    def set_poll(self, v): self.poll_secs = int(v.replace('s',''))
    def set_notif(self, v): self.do_notif = v
    def set_vib(self, v):   self.do_vib   = v
    def manual_refresh(self):
        threading.Thread(target=self._once, daemon=True).start()

    def _loop(self):
        while self._running:
            self._once()
            time.sleep(self.poll_secs)

    def _once(self):
        self._status("● YÜKLƏNIR...", GOLD)
        data = fetch_data(self.timeframe, self.period)
        if not data:
            self._status("● MƏLUMAT YOX", SELL_C); return
        r = run_signals(data)
        if not r:
            self._status("● AZ MƏLUMAT", SELL_C); return
        self._update(r)
        self._status("● CƏFƏRİ", BUY_C)
        d = r['direction']
        if d != "NEUTRAL" and d != self._last_dir:
            self._last_dir = d; self._alert(r)

    @mainthread
    def _update(self, r):
        ids = self.sm.get_screen('dash').ids
        ids.lbl_price.text  = f"{r['price']:,.2f}"
        ids.lbl_clock.text  = f"{r['date']}  {r['time']}"
        ids.lbl_entry.text  = f"{r['price']:,.2f}"
        chg = r['change']
        ids.lbl_change.text  = f"  {'▲' if chg>=0 else '▼'} {chg:+.2f}%"
        ids.lbl_change.color = BUY_C if chg >= 0 else SELL_C
        d = r['direction']
        c = BUY_C if d=="BUY" else SELL_C if d=="SELL" else NEU_C
        g = "▲  AL" if d=="BUY" else "▼  SAT" if d=="SELL" else "◆  NEYTRAL"
        ids.lbl_signal.text  = g
        ids.lbl_signal.color = c
        ids.lbl_score.text   = f"Xal: {r['score']:+d}"
        ids.lbl_score.color  = c
        ids.lbl_reason.text  = "  ·  ".join(r['reasons'][:3]) or "Analiz..."
        ids.lbl_sl.text      = f"{r['sl']:,.2f}"
        ids.lbl_tp.text      = f"{r['tp']:,.2f}"
        ids.lbl_tp.color     = BUY_C if d=="BUY" else SELL_C
        rsi = r['rsi']
        ids.lbl_rsi.text   = f"{rsi:.1f}"
        ids.lbl_rsi.color  = BUY_C if rsi<35 else SELL_C if rsi>65 else WHITE
        ids.lbl_macd.text  = f"{r['macd']:.2f}"
        ids.lbl_macd.color = BUY_C if r['macd']>0 else SELL_C
        sk = r['stoch_k']
        ids.lbl_stoch.text  = f"{sk:.1f}"
        ids.lbl_stoch.color = BUY_C if sk<25 else SELL_C if sk>75 else WHITE
        ids.lbl_ema20.text  = f"{r['ema20']:,.1f}"
        ids.lbl_ema50.text  = f"{r['ema50']:,.1f}"
        ids.lbl_ema200.text = f"{r['ema200']:,.1f}"
        ids.lbl_atr.text    = f"{r['atr']:.2f}"
        self.sig_history.appendleft(r)
        self._hist()

    @mainthread
    def _hist(self):
        box = self.sm.get_screen('history').ids.history_box
        box.clear_widgets()
        for r in self.sig_history:
            d   = r['direction']
            col = BUY_C if d=="BUY" else SELL_C if d=="SELL" else NEU_C
            g   = '▲ AL' if d=='BUY' else '▼ SAT' if d=='SELL' else '◆ NEYTRAL'
            row = BoxLayout(orientation='vertical',
                            size_hint_y=None, height=dp(72),
                            padding=dp(12), spacing=dp(4))
            def _draw(w, *_):
                w.canvas.before.clear()
                with w.canvas.before:
                    Color(rgba=CARD)
                    RoundedRectangle(pos=w.pos,size=w.size,radius=[dp(10)])
            row.bind(pos=_draw, size=_draw); _draw(row)
            top = BoxLayout(size_hint_y=None, height=dp(26))
            top.add_widget(Label(text=g, font_size=sp(14), bold=True,
                                 color=col, halign='left', text_size=(None,None)))
            top.add_widget(Label(text=f"{r['price']:,.2f}", font_size=sp(14),
                                 bold=True, color=WHITE, halign='right',
                                 text_size=(None,None)))
            bot = BoxLayout(size_hint_y=None, height=dp(18))
            bot.add_widget(Label(text=f"SL {r['sl']:,.2f}  |  TP {r['tp']:,.2f}",
                                 font_size=sp(10), color=GREY,
                                 halign='left', text_size=(None,None)))
            bot.add_widget(Label(text=f"{r['date']} {r['time']}",
                                 font_size=sp(10), color=GREY,
                                 halign='right', text_size=(None,None)))
            row.add_widget(top); row.add_widget(bot)
            box.add_widget(row)

    @mainthread
    def _status(self, t, c):
        self.sm.get_screen('dash').ids.lbl_status.text  = t
        self.sm.get_screen('dash').ids.lbl_status.color = c

    def _alert(self, r):
        d   = r['direction']
        lbl = "AL 🟢" if d=="BUY" else "SAT 🔴"
        msg = (f"{lbl} XAU/USD @ {r['price']:,.2f}\n"
               f"SL: {r['sl']:,.2f}  TP: {r['tp']:,.2f}\n"
               f"Xal: {r['score']:+d}")
        if self.do_notif and HAS_PLYER:
            try: pnotif.notify(title=f"⚡ {lbl} — XAU/USD",
                               message=msg, app_name="XAU/USD Bot", timeout=12)
            except: pass
        if self.do_vib and HAS_PLYER:
            try: vibrator.vibrate(.6)
            except: pass

    def on_stop(self): self._running = False


if __name__ == '__main__':
    XAUBot().run()
