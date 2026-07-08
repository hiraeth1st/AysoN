from __future__ import annotations

import urllib.parse

FINAL_HOSTS = {
    "cloud.mail.ru", "mega.nz", "mega.co.nz", "drive.google.com",
    "docs.google.com", "disk.yandex.ru", "disk.yandex.com", "yadi.sk",
    "dropbox.com", "mediafire.com", "pixeldrain.com", "gofile.io",
    "terabox.com", "1fichier.com", "workupload.com", "send.cm",
    "krakenfiles.com",
}

INTERMEDIATE_HOSTS = {
    "lnk.news", "link.tl", "tulink.fun", "ay.live", "aylink.co",
    "cpmlink.pro", "cpmlink.co", "ouo.io", "ouo.press",
    "bildirim.online", "bildirim.vip",
}

AD_WORDS = (
    "popcent", "ppcnt", "popcash", "adsterra", "onclickads",
    "propellerads", "ad-maven", "doubleclick", "googlesyndication",
    "google-analytics", "googletagmanager", "mc.yandex",
    "cloudflareinsights", "facebook",
)

JS_PROBE = r"""
(function() {
    function send(kind, value) {
        try {
            if (!value) return;
            AYSBridge.onEvent(String(kind), String(value));
        } catch (e) {}
    }

    function abs(u) {
        try { return new URL(u, location.href).href; }
        catch (e) { return ""; }
    }

    function scan() {
        try { send("url", location.href); } catch (e) {}

        var selectors = [
            "a[href]", "form[action]", "[data-url]", "[data-href]",
            "[data-link]", "[data-target]", "[data-destination]"
        ];

        selectors.forEach(function(sel) {
            try {
                document.querySelectorAll(sel).forEach(function(el) {
                    ["href","action","data-url","data-href","data-link","data-target","data-destination"].forEach(function(attr) {
                        var v = el.getAttribute && el.getAttribute(attr);
                        if (v) send("candidate", abs(v));
                    });
                });
            } catch (e) {}
        });
    }

    if (!window.__aysonHooked) {
        window.__aysonHooked = true;

        window.open = function(url, name, specs) {
            send("popup", abs(url || ""));
            return null;
        };

        try {
            var obs = new MutationObserver(function() { scan(); });
            obs.observe(document.documentElement || document.body, {childList:true, subtree:true, attributes:true});
        } catch (e) {}
    }

    scan();

    function clickLikelyButton() {
        var words = ["devam", "continue", "go", "get link", "link", "skip", "gec", "git"];
        var els = Array.prototype.slice.call(document.querySelectorAll("button, a, input[type=button], input[type=submit], .btn, [role=button]"));
        var best = null;

        for (var i=0; i<els.length; i++) {
            var el = els[i];
            var text = ((el.innerText || el.value || el.textContent || "") + " " + (el.className || "") + " " + (el.id || "")).toLowerCase();
            var rect = null;
            try { rect = el.getBoundingClientRect(); } catch (e) {}
            var visible = !rect || (rect.width > 5 && rect.height > 5);
            var disabled = !!(el.disabled || el.getAttribute("disabled") || el.classList.contains("disabled"));
            if (!visible || disabled) continue;

            for (var j=0; j<words.length; j++) {
                if (text.indexOf(words[j]) >= 0) {
                    best = el;
                    break;
                }
            }
            if (best) break;
        }

        if (!best) {
            for (var k=0; k<els.length; k++) {
                var el2 = els[k];
                try {
                    var r = el2.getBoundingClientRect();
                    if (r.width > 20 && r.height > 20 && !el2.disabled) {
                        best = el2;
                        break;
                    }
                } catch (e) {}
            }
        }

        if (best) {
            send("click", best.href || best.getAttribute("data-url") || best.innerText || best.value || "button");
            try { best.click(); } catch (e) {}
        }
    }

    setTimeout(scan, 1000);
    setTimeout(scan, 3000);
    setTimeout(clickLikelyButton, 5500);
    setTimeout(scan, 6500);
    setTimeout(clickLikelyButton, 8000);
    setTimeout(scan, 9000);
})();
"""


def normalize_cloud_mail(url: str) -> str:
    try:
        parsed = urllib.parse.urlparse(url)
        host = (parsed.hostname or "").lower().removeprefix("www.")
        parts = [urllib.parse.unquote(p) for p in (parsed.path or "").split("/") if p]
        if host == "thumb.cloud.mail.ru" and len(parts) >= 5 and parts[0] == "weblink" and parts[1] == "thumb":
            return "https://cloud.mail.ru/public/" + urllib.parse.quote(parts[-2]) + "/" + urllib.parse.quote(parts[-1])
    except Exception:
        pass
    return url


def host_of(url: str) -> str:
    try:
        return (urllib.parse.urlparse(url).hostname or "").lower().removeprefix("www.")
    except Exception:
        return ""


def is_final_url(url: str) -> bool:
    url = normalize_cloud_mail(url or "")
    host = host_of(url)
    if not host:
        return False
    return host in FINAL_HOSTS or host.endswith(".cloud.mail.ru")


def is_ad_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(url or "")
        host = (parsed.hostname or "").lower().removeprefix("www.")
        path = (parsed.path or "").lower()
        query = (parsed.query or "").lower()
    except Exception:
        return False

    if not host or host in INTERMEDIATE_HOSTS or is_final_url(url):
        return False
    if any(word in host for word in AD_WORDS):
        return True
    if any(word in path for word in ("beacon.min.js", "/watch", "counter", "pixel", "tracker")):
        return True
    if ("website_id" in query or "site_id" in query) and "token" in query:
        return True
    return False


class HiddenWebViewResolver:
    def __init__(self, app, start_url: str, timeout_seconds: int = 28):
        self.app = app
        self.start_url = start_url
        self.timeout_seconds = timeout_seconds
        self.webview = None
        self.container = None
        self.event = None
        self.timeout_event = None
        self.done = False

    def start(self):
        try:
            from android.runnable import run_on_ui_thread  # type: ignore
            from jnius import PythonJavaClass, autoclass, java_method  # type: ignore
        except Exception as exc:
            self.app.on_hidden_webview_error("Android WebView acilamadi: " + str(exc))
            return

        resolver = self

        class Bridge(PythonJavaClass):
            __javainterfaces__ = ["java/lang/Object"]
            __javacontext__ = "app"

            @java_method("(Ljava/lang/String;Ljava/lang/String;)V")
            def onEvent(self, kind, value):
                resolver.on_js_event(str(kind), str(value))

        @run_on_ui_thread
        def _open():
            try:
                PythonActivity = autoclass("org.kivy.android.PythonActivity")
                FrameLayout = autoclass("android.widget.FrameLayout")
                WebView = autoclass("android.webkit.WebView")
                WebViewClient = autoclass("android.webkit.WebViewClient")
                WebChromeClient = autoclass("android.webkit.WebChromeClient")
                LayoutParams = autoclass("android.widget.FrameLayout$LayoutParams")

                activity = PythonActivity.mActivity
                content = activity.findViewById(0x01020002)

                container = FrameLayout(activity)
                params = LayoutParams(2, 2)
                params.leftMargin = 0
                params.topMargin = 0

                webview = WebView(activity)
                webview.setAlpha(0.01)

                settings = webview.getSettings()
                settings.setJavaScriptEnabled(True)
                settings.setDomStorageEnabled(True)
                settings.setSupportMultipleWindows(False)
                settings.setJavaScriptCanOpenWindowsAutomatically(False)
                try:
                    settings.setUserAgentString(
                        "Mozilla/5.0 (Linux; Android 13; Mobile) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/122.0.0.0 Mobile Safari/537.36"
                    )
                except Exception:
                    pass

                webview.setWebViewClient(WebViewClient())
                webview.setWebChromeClient(WebChromeClient())

                try:
                    webview.addJavascriptInterface(Bridge(), "AYSBridge")
                except Exception:
                    pass

                container.addView(webview, params)
                content.addView(container)

                resolver.webview = webview
                resolver.container = container
                webview.loadUrl(resolver.start_url)

                from kivy.clock import Clock
                resolver.event = Clock.schedule_interval(lambda _dt: resolver.poll(), 1.0)
                resolver.timeout_event = Clock.schedule_once(lambda _dt: resolver.timeout(), resolver.timeout_seconds)
            except Exception as exc:
                resolver.app.on_hidden_webview_error("WebView baslatma hatasi: " + str(exc))

        _open()

    def on_js_event(self, kind: str, value: str):
        value = normalize_cloud_mail((value or "").strip())
        if value and is_final_url(value):
            self.finish(value)

    def poll(self):
        if self.done:
            return False
        webview = self.webview
        if webview is None:
            return True

        try:
            current = normalize_cloud_mail(str(webview.getUrl() or "").strip())
        except Exception:
            current = ""

        if current:
            if is_final_url(current):
                self.finish(current)
                return False

            if is_ad_url(current):
                try:
                    if webview.canGoBack():
                        webview.goBack()
                    else:
                        webview.loadUrl(self.start_url)
                except Exception:
                    pass
                return True

        try:
            webview.evaluateJavascript(JS_PROBE, None)
        except Exception:
            try:
                webview.loadUrl("javascript:" + JS_PROBE)
            except Exception:
                pass

        return True

    def timeout(self):
        if self.done:
            return
        self.done = True
        self.cleanup()
        self.app.on_hidden_webview_failed(self.start_url)

    def finish(self, final_url: str):
        if self.done:
            return
        self.done = True
        self.cleanup()
        self.app.on_hidden_webview_success(final_url, self.start_url)

    def cleanup(self):
        try:
            if self.event:
                self.event.cancel()
        except Exception:
            pass
        try:
            if self.timeout_event:
                self.timeout_event.cancel()
        except Exception:
            pass

        try:
            from android.runnable import run_on_ui_thread  # type: ignore
        except Exception:
            return

        resolver = self

        @run_on_ui_thread
        def _clean():
            try:
                if resolver.webview:
                    resolver.webview.stopLoading()
                    resolver.webview.destroy()
            except Exception:
                pass

            try:
                if resolver.container:
                    parent = resolver.container.getParent()
                    if parent:
                        parent.removeView(resolver.container)
            except Exception:
                pass

            resolver.webview = None
            resolver.container = None

        _clean()
