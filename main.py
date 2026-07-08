from __future__ import annotations

import threading
import webbrowser
from datetime import datetime

from kivy.app import App
from kivy.clock import Clock
from kivy.core.clipboard import Clipboard
from kivy.graphics import Color, Line, RoundedRectangle
from kivy.metrics import dp
from kivy.properties import ListProperty
from kivy.storage.jsonstore import JsonStore
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput

from ayson_core import VERSION, resolve_url, resolve_url_details

WEBVIEW_REQUIRED_PREFIX = "__WEBVIEW_REQUIRED__:"
try:
    from webview_resolver import HiddenWebViewResolver
except Exception:
    HiddenWebViewResolver = None


BG = (0.045, 0.047, 0.065, 1)
CARD = (0.085, 0.090, 0.125, 1)
CARD_2 = (0.105, 0.112, 0.155, 1)
BORDER = (0.210, 0.225, 0.300, 1)
ACCENT = (0.365, 0.455, 1.000, 1)
ACCENT_DARK = (0.270, 0.345, 0.800, 1)
TEXT = (0.945, 0.950, 0.980, 1)
MUTED = (0.620, 0.650, 0.730, 1)
SUCCESS = (0.220, 0.760, 0.520, 1)
ERROR = (1.000, 0.370, 0.370, 1)
WARNING = (1.000, 0.710, 0.250, 1)
DANGER = (0.900, 0.250, 0.250, 1)

HISTORY_LIMIT = 50


class RoundedBox(BoxLayout):
    bg_color = ListProperty(CARD)
    border_color = ListProperty(BORDER)
    radius_value = dp(18)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        with self.canvas.before:
            Color(*self.border_color)
            self._border = RoundedRectangle(pos=self.pos, size=self.size, radius=[self.radius_value])
            Color(*self.bg_color)
            self._rect = RoundedRectangle(
                pos=(self.x + dp(1), self.y + dp(1)),
                size=(max(0, self.width - dp(2)), max(0, self.height - dp(2))),
                radius=[self.radius_value],
            )
        self.bind(
            pos=self._update_canvas,
            size=self._update_canvas,
            bg_color=self._update_canvas,
            border_color=self._update_canvas,
        )

    def _update_canvas(self, *_):
        self.canvas.before.clear()
        with self.canvas.before:
            Color(*self.border_color)
            self._border = RoundedRectangle(pos=self.pos, size=self.size, radius=[self.radius_value])
            Color(*self.bg_color)
            self._rect = RoundedRectangle(
                pos=(self.x + dp(1), self.y + dp(1)),
                size=(max(0, self.width - dp(2)), max(0, self.height - dp(2))),
                radius=[self.radius_value],
            )


class PillButton(Button):
    bg_color = ListProperty(ACCENT)
    bg_down = ListProperty(ACCENT_DARK)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.background_normal = ""
        self.background_down = ""
        self.background_color = (0, 0, 0, 0)
        self.color = TEXT
        self.bold = True
        self.font_size = dp(15)
        self.size_hint_y = None
        self.height = dp(52)
        with self.canvas.before:
            Color(*self.bg_color)
            self._rect = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(14)])
        self.bind(
            pos=self._update_canvas,
            size=self._update_canvas,
            state=self._update_canvas,
            bg_color=self._update_canvas,
        )

    def _update_canvas(self, *_):
        color = self.bg_down if self.state == "down" else self.bg_color
        self.canvas.before.clear()
        with self.canvas.before:
            Color(*color)
            self._rect = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(14)])


class GhostButton(PillButton):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bg_color = CARD_2
        self.bg_down = (0.145, 0.155, 0.205, 1)


class DangerButton(GhostButton):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bg_color = (0.170, 0.095, 0.115, 1)
        self.bg_down = (0.240, 0.110, 0.130, 1)


class CloseSquareButton(GhostButton):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.text = kwargs.get("text", "X")
        self.size_hint = (None, None)
        self.size = (dp(42), dp(42))
        self.height = dp(42)
        self.width = dp(42)
        self.font_size = dp(18)
        self.bold = True


class TitleLabel(Label):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.text = kwargs.get("text", "AysoN")
        self.color = TEXT
        self.bold = True
        self.font_size = dp(34)
        self.halign = "left"
        self.valign = "middle"
        try:
            self.font_name = "data/fonts/Roboto-BoldItalic.ttf"
        except Exception:
            pass
        self.bind(size=lambda inst, *_: setattr(inst, "text_size", inst.size))


class MenuButton(Button):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.text = ""
        self.background_normal = ""
        self.background_down = ""
        self.background_color = (0, 0, 0, 0)
        self.size_hint = (None, None)
        self.size = (dp(52), dp(52))

        with self.canvas.before:
            Color(*CARD_2)
            self._bg = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(14)])

        with self.canvas.after:
            Color(*TEXT)
            self._l1 = Line(points=[], width=dp(1.8))
            self._l2 = Line(points=[], width=dp(1.8))
            self._l3 = Line(points=[], width=dp(1.8))

        self.bind(pos=self._update_canvas, size=self._update_canvas, state=self._update_canvas)

    def _update_canvas(self, *_):
        self.canvas.before.clear()
        color = (0.145, 0.155, 0.205, 1) if self.state == "down" else CARD_2

        with self.canvas.before:
            Color(*color)
            self._bg = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(14)])

        cx1 = self.x + dp(16)
        cx2 = self.right - dp(16)
        y_mid = self.center_y
        self._l1.points = [cx1, y_mid + dp(8), cx2, y_mid + dp(8)]
        self._l2.points = [cx1, y_mid, cx2, y_mid]
        self._l3.points = [cx1, y_mid - dp(8), cx2, y_mid - dp(8)]


class ModernInput(TextInput):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.background_normal = ""
        self.background_active = ""
        self.background_color = CARD_2
        self.foreground_color = TEXT
        self.hint_text_color = MUTED
        self.cursor_color = ACCENT
        self.selection_color = (0.365, 0.455, 1.0, 0.35)
        self.padding = [dp(16), dp(15), dp(16), dp(15)]
        self.font_size = dp(15)
        self.multiline = False
        self.size_hint_y = None
        self.height = dp(56)


class OutputBox(TextInput):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.background_normal = ""
        self.background_active = ""
        self.background_color = (0, 0, 0, 0)
        self.foreground_color = TEXT
        self.cursor_color = ACCENT
        self.hint_text_color = MUTED
        self.padding = [dp(14), dp(12), dp(14), dp(12)]
        self.font_size = dp(14)
        self.readonly = True
        self.multiline = True


class AysonApp(App):
    def build(self):
        self.title = "Ayson"
        self.icon = "icon.png"
        self.is_solving = False
        self.last_result = ""
        self.last_input = ""
        self.open_target = ""
        self.hidden_webview_resolver = None
        self.webview_debug = ""
        self.visible_webview_started = False
        self.history = []
        self.history_query = ""
        self.store = JsonStore("ayson_history.json")
        self._load_history()

        root = BoxLayout(orientation="vertical", padding=[dp(18), dp(12), dp(18), dp(18)], spacing=dp(14))
        with root.canvas.before:
            Color(*BG)
            self._root_bg = RoundedRectangle(pos=root.pos, size=root.size, radius=[0])
        root.bind(pos=self._update_root_bg, size=self._update_root_bg)

        header = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(74), spacing=dp(12))
        title = TitleLabel(text="AysoN")

        menu_btn = MenuButton()
        menu_btn.size = (dp(54), dp(54))
        menu_btn.bind(on_press=self.open_history_popup)

        header.add_widget(title)
        header.add_widget(menu_btn)

        card = RoundedBox(
            orientation="vertical",
            padding=dp(14),
            spacing=dp(12),
            size_hint_y=None,
            height=dp(184),
        )

        input_label = Label(
            text="Kisa linki yapistir",
            color=TEXT,
            bold=True,
            font_size=dp(15),
            halign="left",
            size_hint_y=None,
            height=dp(24),
        )
        input_label.bind(size=lambda inst, *_: setattr(inst, "text_size", inst.size))

        self.input = ModernInput(hint_text="Linki buraya yapistir")

        buttons = BoxLayout(orientation="horizontal", spacing=dp(10), size_hint_y=None, height=dp(52))
        self.solve_btn = PillButton(text="Coz")
        self.solve_btn.bind(on_press=self.on_solve)

        paste_btn = GhostButton(text="Yapistir")
        paste_btn.bind(on_press=self.on_paste)

        buttons.add_widget(self.solve_btn)
        buttons.add_widget(paste_btn)

        card.add_widget(input_label)
        card.add_widget(self.input)
        card.add_widget(buttons)

        result_card = RoundedBox(
            orientation="vertical",
            padding=dp(14),
            spacing=dp(10),
            bg_color=(0.070, 0.075, 0.105, 1),
        )

        result_top = BoxLayout(orientation="horizontal", spacing=dp(8), size_hint_y=None, height=dp(42))

        self.status = Label(
            text="Hazir",
            color=SUCCESS,
            bold=True,
            font_size=dp(14),
            halign="left",
            valign="middle",
        )
        self.status.bind(size=lambda inst, *_: setattr(inst, "text_size", inst.size))

        self.open_btn = GhostButton(text="Ac", size_hint_x=None, width=dp(76), height=dp(42))
        self.open_btn.font_size = dp(13)
        self.open_btn.opacity = 0
        self.open_btn.disabled = True
        self.open_btn.bind(on_press=self.on_open_current)

        self.copy_btn = GhostButton(text="Kopyala", size_hint_x=None, width=dp(104), height=dp(42))
        self.copy_btn.font_size = dp(13)
        self.copy_btn.bind(on_press=self.on_copy)

        result_top.add_widget(self.status)
        result_top.add_widget(self.open_btn)
        result_top.add_widget(self.copy_btn)

        scroll = ScrollView(do_scroll_x=False, do_scroll_y=True)

        self.output = OutputBox(text="Sonuc burada gorunecek.")
        scroll.add_widget(self.output)
        self.output.bind(minimum_height=self.output.setter("height"))

        result_card.add_widget(result_top)
        result_card.add_widget(scroll)

        footer = Label(
            text="Made By Black Corp.",
            color=MUTED,
            bold=True,
            font_size=dp(12),
            size_hint_y=None,
            height=dp(28),
            halign="center",
        )
        footer.bind(size=lambda inst, *_: setattr(inst, "text_size", inst.size))

        root.add_widget(header)
        root.add_widget(card)
        root.add_widget(result_card)
        root.add_widget(footer)

        return root

    def on_start(self):
        self.bind_android_share_intent()
        Clock.schedule_once(lambda _dt: self.read_android_intent(), 0.2)

    def _update_root_bg(self, root, *_):
        self._root_bg.pos = root.pos
        self._root_bg.size = root.size

    def set_status(self, text, color):
        self.status.text = text
        self.status.color = color

    def set_open_button(self, target):
        self.open_target = (target or "").strip()
        active = bool(self.open_target)
        self.open_btn.disabled = not active
        self.open_btn.opacity = 1 if active else 0

    def bind_android_share_intent(self):
        try:
            from android import activity  # type: ignore
            activity.bind(on_new_intent=self.on_new_android_intent)
        except Exception:
            pass

    def on_new_android_intent(self, intent):
        self.read_android_intent(intent)

    def read_android_intent(self, intent=None):
        try:
            from jnius import autoclass  # type: ignore
            Intent = autoclass("android.content.Intent")
            PythonActivity = autoclass("org.kivy.android.PythonActivity")

            if intent is None:
                intent = PythonActivity.mActivity.getIntent()

            text = ""
            action = intent.getAction()

            if action == Intent.ACTION_SEND:
                extra = intent.getStringExtra(Intent.EXTRA_TEXT)
                if extra:
                    text = str(extra).strip()
            elif action == Intent.ACTION_VIEW:
                data = intent.getDataString()
                if data:
                    text = str(data).strip()

            if text:
                self.input.text = self.extract_first_url(text) or text
                self.set_status("Paylasimdan alindi", SUCCESS)
        except Exception:
            pass

    def extract_first_url(self, text):
        if not text:
            return ""

        for part in text.replace("\n", " ").split():
            cleaned = part.strip().strip("'\"<>()[]{}")
            if cleaned.startswith("http://") or cleaned.startswith("https://"):
                return cleaned

        return ""

    def on_paste(self, *_):
        try:
            text = Clipboard.paste().strip()
        except Exception:
            text = ""

        if text:
            self.input.text = self.extract_first_url(text) or text
            self.set_status("Yapistirildi", SUCCESS)
        else:
            self.set_status("Panoda link yok", WARNING)

    def on_solve(self, *_):
        if self.is_solving:
            return

        url = self.input.text.strip()

        if not url:
            self.output.text = "Link girmen lazim."
            self.set_status("Link bekleniyor", WARNING)
            self.set_open_button("")
            return

        self.is_solving = True
        self.last_input = url
        self.solve_btn.text = "Cozuluyor..."
        self.output.text = "Cozuluyor...\n\n" + url
        self.set_status("Cozuluyor", WARNING)
        self.set_open_button("")

        thread = threading.Thread(target=self._solve_worker, args=(url,), daemon=True)
        thread.start()

    def _solve_worker(self, url):
        try:
            def progress(current_url):
                Clock.schedule_once(lambda _dt, u=current_url: self._show_live_progress(u), 0)

            details = resolve_url_details(url, progress_callback=progress)
            Clock.schedule_once(lambda _dt, d=details: self._show_success(d), 0)
        except Exception as exc:
            message = str(exc)
            Clock.schedule_once(lambda _dt, m=message, u=url: self._show_error(m, u), 0)

    def _show_live_progress(self, current_url):
        if not self.is_solving:
            return
        current_url = (current_url or "").strip()
        if not current_url:
            return

        self.set_status("Cozuluyor", WARNING)
        self.output.text = (
            "Cozuluyor...\n\n"
            "Su an:\n"
            + current_url
        )

    def is_manual_intermediate_result(self, url):
        try:
            from urllib.parse import urlparse
            host = (urlparse(url).hostname or "").lower().removeprefix("www.")
        except Exception:
            host = ""
        return host in {
            "lnk.news",
            "tulink.fun",
            "link.tl",
            "ouo.io",
            "ouo.press",
            "bildirim.online",
            "bildirim.vip",
        }

    def _show_success(self, result):
        self.is_solving = False
        self.solve_btn.text = "Coz"

        if isinstance(result, dict):
            final = str(result.get("final_url") or "").strip()
            chain = result.get("chain") or []
        else:
            final = str(result or "").strip()
            chain = []

        self.last_result = final

        if isinstance(final, str) and final.startswith(WEBVIEW_REQUIRED_PREFIX):
            web_url = final[len(WEBVIEW_REQUIRED_PREFIX):].strip()
            self.last_result = web_url
            self.set_open_button(web_url)
            self.output.text = (
                "lnk.news kapisi bulundu.\n\n"
                "Gorunur WebView aciliyor...\n"
                "Robot/yesil buton cikarsa sen bas.\n"
                "Reklam acilmaya calisirsa uygulama yok sayacak.\n\n"
                + web_url
            )
            self.set_status("Gorunur WebView", WARNING)
            self.start_hidden_webview_resolver(web_url)
            return

        if chain:
            lines = ["Sonuc:", final, "", "Zincir:"]
            for idx, item in enumerate(chain, 1):
                lines.append(f"{idx}. {item}")
            self.output.text = "\n".join(lines)
        else:
            self.output.text = self.last_result

        if self.is_manual_intermediate_result(self.last_result):
            self.set_status("Manuel devam gerekli", WARNING)
            if chain:
                lines = [
                    "Ara link bulundu:",
                    self.last_result,
                    "",
                    "Bu link Link.TL / reklam / Cloudflare kapisinda kaldi.",
                    "Ac butonuna basip tarayicida devam et.",
                    "",
                    "Zincir:",
                ]
                for idx, item in enumerate(chain, 1):
                    lines.append(f"{idx}. {item}")
                self.output.text = "\n".join(lines)
            else:
                self.output.text = (
                    "Ara link bulundu:\n"
                    + self.last_result
                    + "\n\nAc butonuna basip tarayicida devam et."
                )
            self.set_open_button(self.last_result)
            self._add_history(self.last_input, self.last_result, "manual")
        else:
            self.set_status("Cozuldu", SUCCESS)
            self.set_open_button(self.last_result)
            self._add_history(self.last_input, self.last_result, "success")

    def _show_error(self, message, source_url):
        self.is_solving = False
        self.solve_btn.text = "Coz"
        self.last_result = ""

        msg_low = (message or "").lower()

        manual_needed = (
            "captcha" in msg_low
            or "turnstile" in msg_low
            or "recaptcha" in msg_low
            or "doğrulama" in msg_low
            or "dogrulama" in msg_low
            or "anti-bot" in msg_low
            or "cloudflare" in msg_low
            or "gerçek url döndürmedi" in msg_low
            or "gercek url dondurmedi" in msg_low
            or "/links/go2" in msg_low
            or "tulink.fun" in msg_low
            or "lnk.news" in msg_low
        )

        if manual_needed:
            self.output.text = (
                "Bu link otomatik tamamen cozulemedi.\n\n"
                "Uygulama yanlis link vermedi. Ac butonuna basinca link tarayicida acilir.\n"
                "Tarayici ay.live sonrasinda tulink.fun / lnk.news gibi ara sayfalara yonlendirebilir.\n\n"
                + source_url
            )
            self.set_status("Manuel devam gerekli", WARNING)
            self.set_open_button(source_url)
            self._add_history(source_url, source_url, "captcha")
        else:
            self.output.text = "Hata:\n" + message + "\n\nSurum:\n" + VERSION
            self.set_status("Hata", ERROR)
            self.set_open_button("")

    def on_copy(self, *_):
        text = self.last_result or self.output.text.strip()

        if not text or text.startswith("Hata") or "Sonuc burada" in text or text.startswith("Cozuluyor"):
            self.set_status("Kopyalanacak sonuc yok", WARNING)
            return

        Clipboard.copy(text)
        self.set_status("Kopyalandi", SUCCESS)

    def on_open_current(self, *_):
        self.open_url(self.open_target)

    def open_url(self, url):
        url = (url or "").strip()

        if not url:
            self.set_status("Acilacak link yok", WARNING)
            return

        try:
            webbrowser.open(url)
            self.set_status("Tarayici acildi", SUCCESS)
        except Exception as exc:
            self.set_status("Acma hatasi", ERROR)
            self.output.text = "Tarayici acilamadi:\n" + str(exc)

    def _load_history(self):
        try:
            if self.store.exists("items"):
                self.history = self.store.get("items").get("value", [])
            else:
                self.history = []
        except Exception:
            self.history = []

    def _save_history(self):
        try:
            self.store.put("items", value=self.history[:HISTORY_LIMIT])
        except Exception:
            pass

    def _add_history(self, source, result, status):
        item = {
            "source": (source or "").strip(),
            "result": (result or "").strip(),
            "status": status,
            "tag": "",
            "time": datetime.now().strftime("%d.%m.%Y %H:%M"),
        }

        if not item["result"]:
            return

        old_tag = ""
        for old in self.history:
            if old.get("result") == item["result"]:
                old_tag = old.get("tag", "")
                break

        item["tag"] = old_tag
        self.history = [x for x in self.history if x.get("result") != item["result"]]
        self.history.insert(0, item)
        self.history = self.history[:HISTORY_LIMIT]
        self._save_history()

    def clear_history(self, *_):
        self.history = []
        self._save_history()
        self.refresh_history_list()

    def delete_history_item(self, item):
        result = item.get("result", "")
        self.history = [x for x in self.history if x.get("result") != result]
        self._save_history()
        self.refresh_history_list()
        self.set_status("Gecmisten silindi", SUCCESS)

    def open_history_popup(self, *_):
        if hasattr(self, "history_popup") and self.history_popup:
            try:
                self.history_popup.dismiss()
            except Exception:
                pass

        body = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(10))

        top = BoxLayout(orientation="vertical", size_hint_y=None, height=dp(92), spacing=dp(8))

        close_row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(42), spacing=dp(8))

        close_btn = CloseSquareButton(text="X")
        close_btn.bind(on_press=lambda *_: self.history_popup.dismiss() if self.history_popup else None)

        clear_btn = GhostButton(text="Temizle", size_hint_x=None, width=dp(112), height=dp(42))
        clear_btn.font_size = dp(12)
        clear_btn.bind(on_press=self.clear_history)

        close_row.add_widget(close_btn)
        close_row.add_widget(Label(text=""))
        close_row.add_widget(clear_btn)

        title = Label(
            text="Gecmis",
            color=TEXT,
            bold=True,
            font_size=dp(18),
            halign="left",
            valign="middle",
            size_hint_y=None,
            height=dp(34),
        )
        title.bind(size=lambda inst, *_: setattr(inst, "text_size", inst.size))

        top.add_widget(close_row)
        top.add_widget(title)
        body.add_widget(top)

        self.history_search = ModernInput(hint_text="Gecmiste ara: link veya etiket")
        self.history_search.text = self.history_query
        self.history_search.bind(text=self.on_history_search)
        body.add_widget(self.history_search)

        scroll = ScrollView(do_scroll_x=False, do_scroll_y=True)

        self.history_items_box = BoxLayout(orientation="vertical", spacing=dp(10), size_hint_y=None)
        self.history_items_box.bind(minimum_height=self.history_items_box.setter("height"))

        scroll.add_widget(self.history_items_box)
        body.add_widget(scroll)

        self.history_popup = Popup(
            title="",
            content=body,
            size_hint=(0.92, 0.82),
            background="",
            background_color=(0.050, 0.052, 0.074, 1),
            separator_height=0,
        )

        self.refresh_history_list()
        self.history_popup.open()

    def on_history_search(self, _instance, value):
        self.history_query = (value or "").strip().lower()
        self.refresh_history_list()

    def _history_matches_query(self, item):
        q = (self.history_query or "").strip().lower()
        if not q:
            return True
        haystack = " ".join(
            [
                item.get("source", ""),
                item.get("result", ""),
                item.get("tag", ""),
                item.get("status", ""),
                item.get("time", ""),
            ]
        ).lower()
        return q in haystack

    def refresh_history_list(self, *_):
        if not hasattr(self, "history_items_box"):
            return

        self.history_items_box.clear_widgets()

        filtered = [item for item in self.history if self._history_matches_query(item)]

        if not filtered:
            empty = Label(
                text="Gecmis bos." if not self.history_query else "Eslesen kayit yok.",
                color=MUTED,
                font_size=dp(14),
                size_hint_y=None,
                height=dp(54),
                halign="center",
                valign="middle",
            )
            empty.bind(size=lambda inst, *_: setattr(inst, "text_size", inst.size))
            self.history_items_box.add_widget(empty)
            return

        for item in filtered:
            self.history_items_box.add_widget(self._build_history_card(item))

    def _build_history_card(self, item):
        card = RoundedBox(
            orientation="vertical",
            padding=dp(12),
            spacing=dp(8),
            size_hint_y=None,
            height=dp(172),
            bg_color=CARD,
            border_color=BORDER,
        )

        top = BoxLayout(orientation="horizontal", spacing=dp(8), size_hint_y=None, height=dp(38))

        result_text = item.get("result", "").strip() or item.get("source", "").strip()
        title = Label(
            text=result_text,
            color=TEXT,
            bold=True,
            font_size=dp(13),
            halign="left",
            valign="middle",
            shorten=True,
            shorten_from="right",
        )
        title.bind(size=lambda inst, *_: setattr(inst, "text_size", inst.size))

        delete_btn = DangerButton(text="Sil", size_hint_x=None, width=dp(74), height=dp(38))
        delete_btn.font_size = dp(12)
        delete_btn.bind(on_press=lambda _btn, it=item: self.delete_history_item(it))

        top.add_widget(title)
        top.add_widget(delete_btn)
        card.add_widget(top)

        tag = (item.get("tag") or "").strip()
        meta_text = f"{item.get('status', '')}  {item.get('time', '')}"
        if tag:
            meta_text += f"  #{tag}"

        meta = Label(
            text=meta_text,
            color=SUCCESS if item.get("status") == "success" else WARNING,
            font_size=dp(11),
            size_hint_y=None,
            height=dp(20),
            halign="left",
            valign="middle",
            shorten=True,
            shorten_from="right",
        )
        meta.bind(size=lambda inst, *_: setattr(inst, "text_size", inst.size))
        card.add_widget(meta)

        source_text = item.get("source", "").strip()
        source = Label(
            text=source_text,
            color=MUTED,
            font_size=dp(11),
            size_hint_y=None,
            height=dp(28),
            halign="left",
            valign="top",
            shorten=True,
            shorten_from="right",
        )
        source.bind(size=lambda inst, *_: setattr(inst, "text_size", inst.size))
        card.add_widget(source)

        actions = BoxLayout(orientation="horizontal", spacing=dp(8), size_hint_y=None, height=dp(42))

        open_btn = GhostButton(text="Ac", height=dp(42))
        open_btn.font_size = dp(12)
        open_btn.bind(on_press=lambda _btn, it=item: self.open_history_item(it))

        copy_btn = GhostButton(text="Kopyala", height=dp(42))
        copy_btn.font_size = dp(12)
        copy_btn.bind(on_press=lambda _btn, it=item: self.copy_history_item(it))

        tag_text = "Etiket" if not tag else "Etiketi Duzenle"
        tag_btn = GhostButton(text=tag_text, height=dp(42))
        tag_btn.font_size = dp(11)
        tag_btn.bind(on_press=lambda _btn, it=item: self.open_tag_popup(it))

        actions.add_widget(open_btn)
        actions.add_widget(copy_btn)
        actions.add_widget(tag_btn)
        card.add_widget(actions)

        return card

    def open_history_item(self, item):
        url = (item.get("result") or item.get("source") or "").strip()
        self.open_url(url)

    def copy_history_item(self, item):
        text = (item.get("result") or item.get("source") or "").strip()
        if text:
            Clipboard.copy(text)
            self.set_status("Gecmis kopyalandi", SUCCESS)
        else:
            self.set_status("Kopyalanacak link yok", WARNING)

    def open_tag_popup(self, item):
        body = BoxLayout(orientation="vertical", padding=dp(14), spacing=dp(12))

        title = Label(
            text="Etiket duzenle",
            color=TEXT,
            bold=True,
            font_size=dp(18),
            size_hint_y=None,
            height=dp(34),
            halign="left",
            valign="middle",
        )
        title.bind(size=lambda inst, *_: setattr(inst, "text_size", inst.size))
        body.add_widget(title)

        tag_input = ModernInput(hint_text="Orn: film, oyun, cloud, arsiv")
        tag_input.text = item.get("tag", "")
        body.add_widget(tag_input)

        buttons = BoxLayout(orientation="horizontal", spacing=dp(8), size_hint_y=None, height=dp(48))

        save_btn = PillButton(text="Kaydet", height=dp(48))
        clear_btn = GhostButton(text="Etiketi Sil", height=dp(48))
        cancel_btn = GhostButton(text="Iptal", height=dp(48))

        buttons.add_widget(save_btn)
        buttons.add_widget(clear_btn)
        buttons.add_widget(cancel_btn)
        body.add_widget(buttons)

        popup = Popup(
            title="",
            content=body,
            size_hint=(0.88, None),
            height=dp(230),
            background="",
            background_color=(0.050, 0.052, 0.074, 1),
            separator_height=0,
        )

        save_btn.bind(on_press=lambda _btn: self.save_history_tag(item, tag_input.text, popup))
        clear_btn.bind(on_press=lambda _btn: self.save_history_tag(item, "", popup))
        cancel_btn.bind(on_press=lambda _btn: popup.dismiss())

        popup.open()

    def save_history_tag(self, item, tag, popup=None):
        result = item.get("result", "")
        new_tag = (tag or "").strip()

        for old in self.history:
            if old.get("result") == result:
                old["tag"] = new_tag
                break

        self._save_history()
        self.refresh_history_list()

        if popup:
            popup.dismiss()

        self.set_status("Etiket kaydedildi" if new_tag else "Etiket silindi", SUCCESS)


    def start_hidden_webview_resolver(self, url):
        # Eski isim kalsin diye method adini degistirmiyoruz.
        # Artik gizli WebView yok; hiz icin direkt gorunur WebView acilir.
        url = (url or "").strip()
        if not url:
            self.set_status("WebView link yok", ERROR)
            return
        if HiddenWebViewResolver is None:
            self.output.text += "\n\nHiddenWebViewResolver yuklenemedi."
            self.set_status("WebView yok", ERROR)
            return

        self.visible_webview_started = True
        self.last_result = url
        self.set_open_button(url)
        self.output.text = (
            "lnk.news kapisi bulundu.\n\n"
            "Gorunur WebView aciliyor.\n"
            "Robot/yesil buton cikarsa sen bas.\n"
            "Reklam acilmaya calisirsa uygulama yok sayacak.\n"
            "Final link gorunur gorunmez ekrana yazilip gecmise kaydedilecek.\n\n"
            + url
        )
        self.set_status("Gorunur WebView", WARNING)

        try:
            self.hidden_webview_resolver = HiddenWebViewResolver(self, url, timeout_seconds=120)
            if hasattr(self.hidden_webview_resolver, "start_visible"):
                self.hidden_webview_resolver.start_visible()
            else:
                self.hidden_webview_resolver.start()
        except Exception as exc:
            self.output.text += "\n\nGorunur WebView baslatilamadi:\n" + str(exc)
            self.set_status("WebView hata", ERROR)

    def on_hidden_webview_success(self, final_url, source_url):
        final_url = (final_url or "").strip()
        source_url = (source_url or "").strip()
        if not final_url:
            self.on_hidden_webview_failed(source_url)
            return

        self.last_result = final_url
        self.open_target = final_url
        self.output.text = (
            "Sonuc:\n"
            + final_url
            + "\n\nOtomatik WebView resolver ile yakalandi ve gecmise kaydedildi."
        )
        self.set_status("Cozuldu", SUCCESS)
        self.set_open_button(final_url)
        self._add_history(source_url or self.last_input, final_url, "web-auto")

    def on_hidden_webview_failed(self, source_url):
        source_url = (source_url or self.last_result or "").strip()
        self.last_result = source_url
        self.output.text = (
            "Ara link bulundu:\n"
            + source_url
            + "\n\nWebView final linki yakalayamadi.\n"
            "Ac butonuyla tarayicida manuel devam etmen gerekebilir."
        )
        self.set_status("Manuel devam gerekli", WARNING)
        self.set_open_button(source_url)
        self._add_history(self.last_input, source_url, "manual")

    def on_hidden_webview_progress(self, source_url, ticks):
        source_url = (source_url or "").strip()
        try:
            sec = int(ticks)
        except Exception:
            sec = 0
        mode_text = (
            "Gorunur WebView acik. Robot/yesil buton cikarsa sen bas.\n"
            if self.visible_webview_started
            else "Gizli WebView resolver otomatik calisiyor...\nJS sayaci bekleniyor, buton otomatik tiklanacak, reklam sekmesi yok sayilacak.\n"
        )
        self.output.text = (
            "lnk.news kapisi bulundu.\n\n"
            + mode_text
            + "\nBekleme: "
            + str(sec)
            + " sn\n"
            + (self.webview_debug or "")
            + "\n\n"
            + source_url
        )

    def on_hidden_webview_debug(self, message):
        message = str(message or "").strip()
        if not message:
            return
        self.webview_debug = message

    def on_hidden_webview_error(self, message):
        message = str(message or "")
        self.output.text += "\n\n" + message
        self.set_status("WebView hata", ERROR)



if __name__ == "__main__":
    AysonApp().run()
