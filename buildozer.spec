[app]
title = Ayson
package.name = aysonv23
package.domain = org.ayson
icon.filename = icon.png

android.add_intent_filters = intent_filters.xml

source.dir = .
source.include_exts = py,png,jpg,kv,atlas,xml

version = 2.3

requirements = python3,kivy,certifi

orientation = portrait
fullscreen = 0

android.permissions = INTERNET

android.accept_sdk_license = True
android.api = 35
android.minapi = 28
android.ndk = 25b
android.archs = arm64-v8a
android.numeric_version = 23

p4a.branch = master


[buildozer]
log_level = 2
warn_on_root = 1
