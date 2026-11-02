[app]
title           = XAU/USD Bot
package.name    = xauusdbot
package.domain  = org.olivia
source.dir      = .
source.include_exts = py,png,jpg,kv,atlas,txt
version         = 1.0.0

requirements = \
    python3,\
    kivy==2.3.0,\
    yfinance,\
    pandas,\
    numpy,\
    plyer,\
    requests,\
    certifi,\
    urllib3,\
    charset-normalizer,\
    multitasking,\
    frozendict,\
    lxml,\
    pillow

orientation     = portrait
fullscreen      = 0

android.minapi  = 26
android.sdk     = 34
android.ndk     = 25b
android.archs   = arm64-v8a
android.accept_sdk_license = True
android.allow_backup        = False

android.permissions = \
    INTERNET,\
    VIBRATE,\
    WAKE_LOCK,\
    FOREGROUND_SERVICE,\
    POST_NOTIFICATIONS

[buildozer]
log_level    = 2
warn_on_root = 1
