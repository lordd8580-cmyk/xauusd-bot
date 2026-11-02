name: Build XAU/USD Bot APK

on:
  push:
    branches: [ main ]
  workflow_dispatch:

jobs:
  build-apk:
    runs-on: ubuntu-20.04
    timeout-minutes: 60

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.10'

      - name: Install deps
        run: |
          sudo apt update -qq
          sudo apt install -y \
            zip unzip git \
            libffi-dev libssl-dev \
            build-essential zlib1g-dev \
            autoconf libtool pkg-config \
            cmake ccache openjdk-17-jdk
          pip install --upgrade pip
          pip install buildozer==1.5.0 cython==0.29.37

      - name: Build APK
        run: |
          export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
          yes | buildozer -v android debug 2>&1 | tee build.log
          ls -la bin/ 2>/dev/null || echo "bin/ yoxdur"

      - name: Upload APK
        uses: actions/upload-artifact@v4
        with:
          name: xauusd-bot-apk
          path: bin/*.apk
          if-no-files-found: warn
          retention-days: 30

      - name: Upload log
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: build-log
          path: build.log
          retention-days: 7
