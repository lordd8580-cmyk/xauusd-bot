      - name: Install buildozer
        run: |
          sudo apt update -qq
          sudo apt install -y \
            zip unzip git \
            libffi-dev libssl-dev \
            build-essential zlib1g-dev \
            autoconf libtool pkg-config \
            cmake ccache openjdk-17-jdk \
            gettext
          pip install --upgrade pip
          pip install buildozer==1.5.0 cython==0.29.37
