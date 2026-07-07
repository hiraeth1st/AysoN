name: Build Android APK

on:
  workflow_dispatch:
  push:
    branches:
      - main

jobs:
  build:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install system dependencies
        run: |
          sudo apt-get update
          sudo apt-get install -y \
            build-essential \
            git \
            zip \
            unzip \
            openjdk-17-jdk \
            python3-pip \
            autoconf \
            libtool \
            pkg-config \
            zlib1g-dev \
            libncurses5-dev \
            libncursesw5-dev \
            libtinfo6 \
            cmake \
            libffi-dev \
            libssl-dev

      - name: Install Buildozer
        run: |
          python -m pip install --upgrade pip
          pip install buildozer cython==0.29.36 virtualenv

      - name: Build debug APK
        run: |
          buildozer android debug

      - name: Upload APK artifact
        uses: actions/upload-artifact@v4
        with:
          name: ayson-debug-apk
          path: bin/*.apk
