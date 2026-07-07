from __future__ import annotations

import threading
import webbrowser
from datetime import datetime

from kivy.app import App
from kivy.clock import Clock
from kivy.core.clipboard import Clipboard
from kivy.graphics import Color, RoundedRectangle
from kivy.metrics import dp
from kivy.storage.jsonstore import JsonStore
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput

from ayson_core import VERSION, resolve_url

BG = (0.045, 0.047, 0.065, 1)
CARD = (0.085, 0.090, 0.125, 1)
CARD_2 = (0.105, 0.112, 0.155, 1)
ACCENT = (0.365, 0.455, 1.000, 1)
ACCENT_DARK = (0.270, 0.345, 0.800, 1)
TEXT = (0.945, 0.950, 0.980, 1)
MUTED = (0.620, 0.650, 0.730, 1)
SUCCESS = (0.220, 0.760, 0.520, 1)
WARNING = (1.000, 0.710, 0.250, 1)
ERROR = (1.000, 0.370, 0.370, 1)
HISTORY_LIMIT = 50


class RoundedBox(BoxLayout):
    def __init__(self, bg_color=CARD, radius=18, **kwargs):
        super().__init__(**kwargs)
        self.bg_color = bg_color
        self.radius = dp(radius)
        with self.canvas.before:
            Color(*self.bg_color)
            self._rect = RoundedRectangle(pos=self.pos, size=self.size, radius=[self.radius])
        self.bind(pos=self._update_canvas, size=self._update_canvas)

    def _update_canvas(self, *_):
        self._rect.pos = self.pos
        self._rect.size = self.size


class PillButton(Button):
    def __init__(self, bg_color=ACCENT, down_color=ACCENT_DARK, **kwargs):
        super().__init__(**kwargs)
        self.bg_color = bg_color
        self.down_color = down_color
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
        self.bind(pos=self._update_canvas, size=self._update_canvas, state=self._update_canvas)

    def _update_canvas(self, *_):
        self.canvas.before.clear()
        color = self.down_color if self.state == "down" else self.bg_color
        with self.canvas.before:
            Color(*color)
            self._rect = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(14)])


class GhostButton(PillButton):
    def __init__(self, **kwargs):
        super().__init__(bg_color=CARD_2, down_color=(0.145, 0.155, 0.205, 1), **kwargs)


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
        self.size_hint_y = None
        self.height = dp(280)


class AysonApp(App):
    def build(self):
        self.title = "Ayson"
        self.icon = "icon.png"
        self.is_solving = False
        self.last_input = ""
        self.last_result = ""
        self.open_target = ""
        self.store = JsonStore("ayson_history.json")
        self.history = self._load_history()

        root = BoxLayout(orientation="vertical", padding=dp(18), spacing=dp(14))
        with root.canvas.before:
            Color(*BG)
            self._root_bg = RoundedRectangle(pos=root.pos, size=root.size, radius=[0])
        root.bind(pos=self._update_root_bg, size=self._update_root_bg)

        header = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(70), spacing=dp(12))
        title = Label(text=f"Ayson  {VERSION}", color=TEXT, bold=True, font_size=dp(22), halign="left", valign="middle")
        title.bind(size=lambda inst, *_: setattr(inst, "text_size", inst.size))
        history_btn = GhostButton(text="Gecmis", size_hint_x=None, width=dp(100), height=dp(48))
        history_btn.bind(on_press=self.open_history_popup)
        header.add_widget(title)
        header.add_widget(history_btn)

        card = RoundedBox(orientation="vertical", padding=dp(14), spacing=dp(12), size_hint_y=None, height=dp(180))
        label = Label(text="Kisa linki yapistir", color=TEXT, bold=True, font_size=dp(15), halign="left", size_hint_y=None, height=dp(24))
        label.bind(size=lambda inst, *_: setattr(inst, "text_size", inst.size))
        self.input = ModernInput(hint_text="ay.live / aylink / cpmlink / ouo / tulink / lnk...")
        buttons = BoxLayout(orientation="horizontal", spacing=dp(10), size_hint_y=None, height=dp(52))
        self.solve_btn = PillButton(text="Coz")
        self.solve_btn.bind(on_press=self.on_solve)
        paste_btn = GhostButton(text="Yapistir")
        paste_btn.bind(on_press=self.on_paste)
        buttons.add_widget(self.solve_btn)
        buttons.add_widget(paste_btn)
        card.add_widget(label)
        card.add_widget(self.input)
        card.add_widget(buttons)

        result_card = RoundedBox(orientation="vertical", padding=dp(14), spacing=dp(10), bg_color=(0.070, 0.075, 0.105, 1))
        top = BoxLayout(orientation="horizontal", spacing=dp(8), size_hint_y=None, height=dp(42))
        self.status = Label(text="Hazir", color=SUCCESS, bold=True, font_size=dp(14), halign="left", valign="middle")
        self.status.bind(size=lambda inst, *_: setattr(inst, "text_size", inst.size))
        self.open_btn = GhostButton(text="Ac", size_hint_x=None, width=dp(76), height=dp(42))
        self.open_btn.disabled = True
        self.open_btn.opacity = 0
        self.open_btn.bind(on_press=lambda *_: self.open_url(self.open_target))
        copy_btn = GhostButton(text="Kopyala", size_hint_x=None, width=dp(104), height=dp(42))
        copy_btn.bind(on_press=self.on_copy)
        top.add_widget(self.status)
        top.add_widget(self.open_btn)
        top.add_widget(copy_btn)

        scroll = ScrollView(do_scroll_x=False, do_scroll_y=True)
        self.output = OutputBox(text="Sonuc burada gorunecek.")
        self.output.bind(minimum_height=self.output.setter("height"))
        scroll.add_widget(self.output)
        result_card.add_widget(top)
        result_card.add_widget(scroll)

        footer = Label(text="Made By Black Corp.", color=MUTED, bold=True, font_size=dp(12), size_hint_y=None, height=dp(28))

        root.add_widget(header)
        root.add_widget(card)
        root.add_widget(result_card)
        root.add_widget(footer)
        return root

    def _update_root_bg(self, root, *_):
        self._root_bg.pos = root.pos
        self._root_bg.size = root.size

    def on_start(self):
        self.bind_android_share_intent()
        Clock.schedule_once(lambda _dt: self.read_android_intent(), 0.2)

    def set_status(self, text, color):
        self.status.text = text
        self.status.color = color

    def set_open_button(self, target):
        self.open_target = (target or "").strip()
        self.open_btn.disabled = not bool(self.open_target)
        self.open_btn.opacity = 1 if self.open_target else 0

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
        for part in (text or "").replace("\n", " ").split():
            cleaned = part.strip().strip("'\"<>()[]{}")
            if cleaned.startswith("http://") or cleaned.startswith("https://"):
                return cleaned
        return ""

    def on_paste(self, *_):
        text = ""
        try:
            text = Clipboard.paste().strip()
        except Exception:
            pass
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
        threading.Thread(target=self._solve_worker, args=(url,), daemon=True).start()

    def _solve_worker(self, url):
        try:
            final = resolve_url(url)
            Clock.schedule_once(lambda _dt, f=final: self._show_success(f), 0)
        except Exception as exc:
            Clock.schedule_once(lambda _dt, m=str(exc), u=url: self._show_error(m, u), 0)

    def _show_success(self, final):
        self.is_solving = False
        self.solve_btn.text = "Coz"
        self.last_result = final.strip()
        self.output.text = self.last_result
        self.set_status("Cozuldu", SUCCESS)
        self.set_open_button(self.last_result)
        self._add_history(self.last_input, self.last_result, "success")

    def _show_error(self, message, source_url):
        self.is_solving = False
        self.solve_btn.text = "Coz"
        self.last_result = ""
        self.output.text = "Hata:\n" + message + "\n\nAcilacak kaynak link:\n" + source_url
        self.set_status("Manuel devam gerekli", WARNING)
        self.set_open_button(source_url)
        self._add_history(source_url, source_url, "manual")

    def on_copy(self, *_):
        text = self.last_result or self.output.text.strip()
        if not text or text.startswith("Cozuluyor") or "Sonuc burada" in text:
            self.set_status("Kopyalanacak sonuc yok", WARNING)
            return
        Clipboard.copy(text)
        self.set_status("Kopyalandi", SUCCESS)

    def open_url(self, url):
        url = (url or "").strip()
        if not url:
            self.set_status("Acilacak link yok", WARNING)
            return
        try:
            webbrowser.open(url)
            self.set_status("Tarayici acildi", SUCCESS)
        except Exception as exc:
            self.output.text = "Tarayici acilamadi:\n" + str(exc)
            self.set_status("Acma hatasi", ERROR)

    def _load_history(self):
        try:
            if self.store.exists("items"):
                return self.store.get("items").get("value", [])
        except Exception:
            pass
        return []

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
            "time": datetime.now().strftime("%d.%m.%Y %H:%M"),
        }
        if not item["result"]:
            return
        self.history = [x for x in self.history if x.get("result") != item["result"]]
        self.history.insert(0, item)
        self.history = self.history[:HISTORY_LIMIT]
        self._save_history()

    def open_history_popup(self, *_):
        body = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(10))
        title = Label(text="Gecmis", color=TEXT, bold=True, font_size=dp(18), size_hint_y=None, height=dp(36))
        body.add_widget(title)
        scroll = ScrollView(do_scroll_x=False, do_scroll_y=True)
        box = BoxLayout(orientation="vertical", spacing=dp(8), size_hint_y=None)
        box.bind(minimum_height=box.setter("height"))
        if not self.history:
            box.add_widget(Label(text="Henuz gecmis yok.", color=MUTED, size_hint_y=None, height=dp(60)))
        for item in self.history:
            row = BoxLayout(orientation="vertical", size_hint_y=None, height=dp(88), padding=dp(6), spacing=dp(4))
            row.add_widget(Label(text=item.get("time", ""), color=MUTED, font_size=dp(11), size_hint_y=None, height=dp(20)))
            url = item.get("result", "")
            btn = GhostButton(text=url[:80], height=dp(48))
            btn.font_size = dp(11)
            btn.bind(on_press=lambda _btn, u=url: self.open_url(u))
            row.add_widget(btn)
            box.add_widget(row)
        scroll.add_widget(box)
        body.add_widget(scroll)
        Popup(title="", content=body, size_hint=(0.92, 0.82), background="", background_color=(0.050, 0.052, 0.074, 1), separator_height=0).open()


if __name__ == "__main__":
    AysonApp().run()
