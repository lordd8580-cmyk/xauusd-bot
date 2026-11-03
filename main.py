# main.py | XAU/USD Bot | Python 3.10+ | Kivy 2.2.1
# Built by Olivia — https://discord.gg/ojailbreaks

import threading, time, json
from datetime import datetime
from collections import deque
from urllib.request import urlopen, Request

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

Window.clearcolor = (.07,.09,.13,1)
BG=(.07,.09,.13,1); CARD=(.11,.14,.19,1); GOLD=(.95,.78,.22,1)
BUY_C=(.14,.70,.40,1); SELL_C=(.82,.22,.28,1); NEU_C=(.45,.52,.62,1)
WHITE=(.95,.96,.98,1); GREY=(.40,.48,.60,1)

# ══ PURE PYTHON TA ══════════════════════════════════════════════════════════
def _mean(a): return sum(a)/len(a) if a else 0.0
def _std(a):
    if len(a)<2: return 0.0
    m=_mean(a); return (sum((x-m)**2 for x in a)/(len(a)-1))**.5

def calc_rsi(c,p=14):
    if len(c)<p+1: return 50.0
    g=[max(c[i]-c[i-1],0) for i in range(1,len(c))]
    l=[max(c[i-1]-c[i],0) for i in range(1,len(c))]
    ag=_mean(g[-p:]); al=_mean(l[-p:])
    return 100-(100/(1+ag/al)) if al else 100.0

def calc_ema(c,p):
    if not c: return 0.0
    k=2.0/(p+1); e=c[0]
    for x in c[1:]: e=x*k+e*(1-k)
    return e

def calc_macd(c):
    if len(c)<26: return 0.0,0.0
    return calc_ema(c,12)-calc_ema(c,26), calc_ema(c,9)

def calc_bb(c,p=20):
    if len(c)<p: return 0.0,0.0,0.0
    s=c[-p:]; m=_mean(s); sd=_std(s)
    return m+2*sd, m, m-2*sd

def calc_atr(h,l,c,p=14):
    if len(c)<2: return 1.0
    trs=[max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1]))
         for i in range(1,len(c))]
    return _mean(trs[-p:]) if trs else 1.0

def calc_stoch(h,l,c,k=14):
    if len(c)<k: return 50.0
    lm=min(l[-k:]); hm=max(h[-k:])
    return 100*(c[-1]-lm)/(hm-lm) if hm!=lm else 50.0

# ══ SIGNAL ENGINE ════════════════════════════════════════════════════════════
def run_signals(d):
    if not d or len(d['c'])<30: return None
    C=d['c']; H=d['h']; L=d['l']
    score=0; reasons=[]

    rsi=calc_rsi(C)
    if   rsi<30: score+=25; reasons.append(f"RSI {rsi:.1f} oversold ↑")
    elif rsi<42: score+=12; reasons.append(f"RSI {rsi:.1f} soft ↑")
    elif rsi>70: score-=25; reasons.append(f"RSI {rsi:.1f} overbought ↓")
    elif rsi>58: score-=12; reasons.append(f"RSI {rsi:.1f} soft ↓")

    mc,ms=calc_macd(C)
    if   mc>ms: score+=15; reasons.append("MACD bullish ↑")
    elif mc<ms: score-=15; reasons.append("MACD bearish ↓")

    e20=calc_ema(C,20); e50=calc_ema(C,50)
    p=C[-1]
    if   p>e20>e50: score+=20; reasons.append("EMA bull ↑")
    elif p<e20<e50: score-=20; reasons.append("EMA bear ↓")

    bu,bm,bl=calc_bb(C)
    if   p<=bl: score+=15; reasons.append("BB bounce ↑")
    elif p>=bu: score-=15; reasons.append("BB reject ↓")

    sk=calc_stoch(H,L,C)
    pk=calc_stoch(H[:-1],L[:-1],C[:-1]) if len(C)>14 else 50
    if   sk<20 and sk>pk: score+=18; reasons.append(f"Stoch {sk:.0f} ↑")
    elif sk>80 and sk<pk: score-=18; reasons.append(f"Stoch {sk:.0f} ↓")

    score=max(-100,min(100,score))
    atr=calc_atr(H,L,C)
    if   score>=30:  dr="BUY";     sl=p-1.5*atr; tp=p+2.5*atr
    elif score<=-30: dr="SELL";    sl=p+1.5*atr; tp=p-2.5*atr
    else:            dr="NEUTRAL"; sl=p-1.5*atr; tp=p+2.5*atr

    chg=((p-C[-2])/C[-2])*100 if len(C)>1 else 0
    return dict(direction=dr,score=score,price=p,change=chg,
                sl=sl,tp=tp,atr=atr,rsi=rsi,macd=mc,
                ema20=e20,ema50=e50,stoch_k=sk,reasons=reasons,
                time=datetime.now().strftime("%H:%M:%S"),
                date=datetime.now().strftime("%d.%m.%Y"))

# ══ DATA FEED ════════════════════════════════════════════════════════════════
def fetch_data(interval="15m",period="5d"):
    url=(f"https://query1.finance.yahoo.com/v8/finance/chart/XAUUSD%3DX"
         f"?interval={interval}&range={period}")
    try:
        req=Request(url,headers={"User-Agent":"Mozilla/5.0"})
        with urlopen(req,timeout=15) as r:
            js=json.loads(r.read())
        q=js["chart"]["result"][0]["indicators"]["quote"][0]
        raw_c=[x for x in q["close"] if x is not None]
        raw_h=[x for x in q["high"]  if x is not None]
        raw_l=[x for x in q["low"]   if x is not None]
        n=min(len(raw_c),len(raw_h),len(raw_l))
        if n<20: return None
        return {"c":raw_c[:n],"h":raw_h[:n],"l":raw_l[:n]}
    except Exception as e:
        print(f"[Feed] {e}"); return None

# ══ KV ═══════════════════════════════════════════════════════════════════════
KV="""
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
    padding: dp(14),dp(8)
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
                padding: dp(12),dp(10),dp(12),dp(14)
                size_hint_y: None
                height: self.minimum_height
                RCard:
                    size_hint_y: None
                    height: dp(108)
                    orientation: 'vertical'
                    spacing: dp(4)
                    BoxLayout:
                        Label:
                            text: 'XAU/USD (GOLD)'
                            font_size: sp(11)
                            color: .45,.52,.62,1
                            halign: 'left'
                            valign: 'center'
                            text_size: self.size
                        Label:
                            id: lbl_clock
                            text: '--.--.----'
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
                        text: 'LEVELLAR (ATR əsaslı)'
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
                    height: dp(90)
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
                                text: 'RSI'
                                font_size: sp(9)
                                color: .45,.52,.62,1
                                halign: 'center'
                                text_size: self.size
                            Label:
                                id: lbl_rsi
                                text: '--'
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
                                text: '--'
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
                                text: '--'
                                font_size: sp(18)
                                bold: True
                                color: .95,.96,.98,1
                                halign: 'center'
                                text_size: self.size
                RCard:
                    size_hint_y: None
                    height: dp(70)
                    orientation: 'vertical'
                    spacing: dp(4)
                    Label:
                        text: 'EMA'
                        font_size: sp(10)
                        color: .45,.52,.62,1
                        halign: 'left'
                        text_size: self.size
                        valign: 'center'
                        size_hint_y: None
                        height: dp(16)
                    GridLayout:
                        cols: 2
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
        
