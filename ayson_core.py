#!/usr/bin/env python3
"""
ayson V1.1: single-file Termux resolver for ay.live/aylink/cpmlink and ouo.io links.

Supported chains:
1) ay.live / aylink.co / cpmlink.pro
   - GET the short-link page
   - extract _a, _t, _d, alias, csrf
   - POST /get/tk
   - POST /links/go2
   - if the returned URL uses bildirim.online / bildirim.vip, extract the embedded final URL
2) bildirim.online / bildirim.vip direct intermediate pages
   - extract the URL hidden behind the alert/notification page
3) ouo.io / ouo.press
   - submit the site forms normally
   - follow /go/<id> and /xreallcygo/<id> hops
   - return the Location header or final external URL

It does not solve CAPTCHA / Turnstile / reCAPTCHA challenges.
"""

from __future__ import annotations

import gzip
import html as html_lib
import http.cookiejar
import json
import re
import ssl
import sys

try:
    import certifi
except Exception:
    certifi = None
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

APP_NAME = "ayson"
VERSION = "V2.5.2-noise-filter"
TRLINK_HOSTS = {"aylink.co", "cpmlink.co", "cpmlink.pro", "ay.live"}
OUO_HOSTS = {"ouo.io", "ouo.press"}
BILDIRIM_HOSTS = {"bildirim.online", "bildirim.vip"}
# Ay.live sonrasi cikabilecek ara sistemler.
# Bu hostlar artik once otomatik cozulmeye calisilir; basarisiz olursa guvenli sekilde ara link olarak dondurulur.
INTERMEDIATE_HOSTS = {
    "tulink.fun",
    "lnk.news",
    "exe.io",
    "exey.io",
    "fc.lc",
    "fc-lc.xyz",
    "bc.vc",
    "shorte.st",
    "clk.sh",
    "shrinke.me",
    "linkvertise.com",
}
SUPPORTED_HOSTS = TRLINK_HOSTS | OUO_HOSTS | BILDIRIM_HOSTS | INTERMEDIATE_HOSTS
DEFAULT_TIMEOUT = 30
MAX_HTML_BYTES = 4 * 1024 * 1024

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

COMMON_HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Connection": "close",
}

AJAX_HEADERS_BASE = {
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
    "User-Agent": UA,
    "Connection": "close",
}

CAPTCHA_MARKERS = (
    "cf-turnstile",
    "turnstile-form",
    "g-recaptcha",
    "recaptcha-form",
    "google.com/recaptcha",
    "hcaptcha.com",
)

TARGET_QUERY_KEYS = (
    "url",
    "u",
    "to",
    "target",
    "dest",
    "destination",
    "redirect",
    "redirect_url",
    "redirect_uri",
    "r",
)


class ResolveError(Exception):
    pass


class CaptchaRequired(ResolveError):
    pass


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        return None


@dataclass
class HtmlForm:
    action: str
    method: str
    inputs: Dict[str, str]
    attrs: Dict[str, str]
    score: int = 0


@dataclass
class FetchResult:
    url: str
    final_url: str
    status: int
    headers: object
    text: str
    raw: bytes


def build_ssl_context():
    """Create an SSL context that works on Android/Kivy builds.

    Android python-for-android environments can miss the normal OS CA bundle.
    buildozer.spec already includes certifi, so prefer certifi's CA bundle.
    """
    try:
        if certifi is not None:
            return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        pass
    return ssl.create_default_context()


class Resolver:
    def __init__(self, timeout: int = DEFAULT_TIMEOUT, verbose: bool = False, sleep_seconds: float = 0.0):
        self.timeout = timeout
        self.verbose = verbose
        self.sleep_seconds = sleep_seconds
        self.cookiejar = http.cookiejar.CookieJar()
        context = build_ssl_context()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookiejar),
            urllib.request.HTTPSHandler(context=context),
            urllib.request.HTTPHandler(),
        )
        self.no_redirect_opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookiejar),
            urllib.request.HTTPSHandler(context=context),
            urllib.request.HTTPHandler(),
            NoRedirectHandler(),
        )

    def log(self, msg: str) -> None:
        if self.verbose:
            print(f"[{APP_NAME}] {msg}", file=sys.stderr)

    def fetch(
        self,
        url: str,
        method: str = "GET",
        data: Optional[Dict[str, str]] = None,
        headers: Optional[Dict[str, str]] = None,
        max_bytes: int = MAX_HTML_BYTES,
        read_body: bool = True,
        allow_redirects: bool = True,
    ) -> FetchResult:
        hdrs = dict(COMMON_HEADERS)
        if headers:
            hdrs.update(headers)

        body = None
        if data is not None:
            body = urllib.parse.urlencode(data).encode("utf-8")

        req = urllib.request.Request(url, data=body, headers=hdrs, method=method.upper())
        self.log(f"{method.upper()} {url}")

        try:
            opener = self.opener if allow_redirects else self.no_redirect_opener
            with opener.open(req, timeout=self.timeout) as resp:
                raw = b""
                if read_body:
                    raw = resp.read(max_bytes + 1)
                    if len(raw) > max_bytes:
                        raw = raw[:max_bytes]
                status = getattr(resp, "status", resp.getcode())
                final_url = resp.geturl()
                headers_obj = resp.headers
        except urllib.error.HTTPError as e:
            raw = b""
            if read_body:
                try:
                    raw = e.read(max_bytes + 1)
                    if len(raw) > max_bytes:
                        raw = raw[:max_bytes]
                except Exception:
                    raw = b""
            status = e.code
            final_url = e.geturl() if hasattr(e, "geturl") else url
            headers_obj = e.headers
        except urllib.error.URLError as e:
            raise ResolveError(f"Network error: {e}") from e

        text = decode_body(raw, headers_obj)
        if self.sleep_seconds > 0:
            time.sleep(self.sleep_seconds)
        return FetchResult(url=url, final_url=final_url, status=status, headers=headers_obj, text=text, raw=raw)

    def resolve(self, input_url: str, follow_final: bool = True) -> Tuple[str, Dict[str, str]]:
        start_url = normalize_url(input_url)
        info: Dict[str, str] = {"input": input_url, "normalized": start_url, "method": "unknown"}

        if is_intermediate_host(start_url):
            info["method"] = "intermediate-flow"
            target = self.resolve_intermediate_url(start_url)
            info["result_before_final_follow"] = target
            final = self.final_follow(target) if follow_final and target != start_url else target
            return final, info

        query_target = extract_target_from_query(start_url)
        if query_target:
            info["method"] = "query-param"
            final = self.final_follow(query_target) if follow_final else query_target
            info["result_before_final_follow"] = query_target
            return final, info

        if is_bildirim_host(start_url):
            info["method"] = "bildirim-intermediate"
            target = self.resolve_bildirim_url(start_url)
            info["result_before_final_follow"] = target
            final = self.final_follow(target) if follow_final else target
            return final, info

        if is_ouo_host(start_url):
            info["method"] = "ouo-flow"
            target = self.resolve_ouo_url(start_url)
            info["result_before_final_follow"] = target
            final = self.final_follow(target) if follow_final else target
            return final, info

        page = self.fetch(start_url, "GET")
        current_url = page.final_url
        current_host = host_of(current_url)
        info["landing_url"] = current_url
        info["landing_status"] = str(page.status)

        if current_host in BILDIRIM_HOSTS:
            info["method"] = "bildirim-intermediate"
            target = self.resolve_bildirim_url(current_url, page=page)
            info["result_before_final_follow"] = target
            final = self.final_follow(target) if follow_final else target
            return final, info

        if current_host in OUO_HOSTS or looks_like_ouo_page(page.text):
            info["method"] = "ouo-flow"
            target = self.resolve_ouo_url(current_url, page=page)
            info["result_before_final_follow"] = target
            final = self.final_follow(target) if follow_final else target
            return final, info

        if current_host in INTERMEDIATE_HOSTS:
            info["method"] = "intermediate-flow"
            target = self.resolve_intermediate_url(current_url, page=page)
            info["result_before_final_follow"] = target
            final = self.final_follow(target) if follow_final and target != current_url else target
            return final, info

        if current_host not in SUPPORTED_HOSTS and current_url != start_url:
            info["method"] = "http-redirect"
            final = self.final_follow(current_url) if follow_final else current_url
            return final, info

        if current_host in TRLINK_HOSTS or looks_like_trlink_page(page.text):
            try:
                final_candidate = self.resolve_trlink_page(page)
                info["method"] = "trlink-flow"
                info["result_before_final_follow"] = final_candidate
                final = self.final_follow(final_candidate) if follow_final else final_candidate
                return final, info
            except CaptchaRequired:
                raise
            except ResolveError as e:
                self.log(f"TRLink flow failed: {e}")
                info["trlink_error"] = str(e)

        html_target = extract_redirect_from_html(page.text, current_url)
        if html_target:
            info["method"] = "html-redirect"
            info["result_before_final_follow"] = html_target
            final = self.final_follow(html_target) if follow_final else html_target
            return final, info

        info["method"] = "fallback-final-url"
        final = self.final_follow(current_url) if follow_final else current_url
        return final, info

    def resolve_trlink_page(self, page: FetchResult) -> str:
        html = page.text
        if has_captcha(html):
            raise CaptchaRequired(
                "This page contains CAPTCHA/Turnstile/reCAPTCHA. CLI mode will not solve it. "
                "Open the link in a browser, pass verification, then try again if the site allows it."
            )

        current_url = page.final_url
        parsed = urllib.parse.urlparse(current_url)
        host = (parsed.hostname or "").lower().removeprefix("www.")
        netloc = parsed.netloc
        if not host or not netloc:
            raise ResolveError("Could not detect host.")
        base = f"{parsed.scheme or 'https'}://{netloc}"

        a, t, d = extract_atd(html)
        alias = extract_input_value(html, "alias")
        csrf = extract_input_value(html, "csrf")

        self.log(f"extracted alias={alias!r}; csrf length={len(csrf)}")

        ajax_headers = dict(AJAX_HEADERS_BASE)
        ajax_headers["Referer"] = current_url
        ajax_headers["Origin"] = base
        ajax_headers["Sec-Fetch-Dest"] = "empty"
        ajax_headers["Sec-Fetch-Mode"] = "cors"
        ajax_headers["Sec-Fetch-Site"] = "same-origin"

        tk_resp = self.fetch(
            f"{base}/get/tk",
            "POST",
            data={"_a": a, "_t": t, "_d": d},
            headers=ajax_headers,
        )
        tk_data = parse_json_object(tk_resp.text, "token response")
        if not bool(tk_data.get("status")):
            raise ResolveError(f"Token request failed: {tk_data}")
        tkn = str(tk_data.get("th") or tk_data.get("tkn") or tk_data.get("token") or "")
        if not tkn:
            raise ResolveError(f"Token was not found in response: {tk_data}")

        go_payload = {"alias": alias, "csrf": csrf, "tkn": tkn}
        visitor_token = extract_visitor_token(html)
        if visitor_token:
            go_payload["visitor_token"] = visitor_token
        go_payload["signal"] = build_browser_signal()

        go_resp = self.fetch(
            f"{base}/links/go2",
            "POST",
            data=go_payload,
            headers=ajax_headers,
        )
        go_data = parse_json_object(go_resp.text, "go2 response")
        url = str(go_data.get("url") or "").strip()
        if not url:
            url = first_url_in_text(go_resp.text) or ""
        if not url:
            raise ResolveError(f"No URL returned by /links/go2: {go_data}")
        url = absolutize(url, current_url)
        url = html_lib.unescape(url)

        if is_intermediate_host(url):
            self.log(f"intermediate URL detected: {host_of(url)}")
            return self.resolve_intermediate_url(url, referer=current_url)

        if is_bildirim_host(url):
            self.log(f"resolving bildirim intermediate URL: {host_of(url)}")
            return self.resolve_bildirim_url(url, referer=current_url)

        return url

    def resolve_bildirim_url(self, url: str, referer: Optional[str] = None, page: Optional[FetchResult] = None) -> str:
        url = normalize_url(url)
        if page is None:
            headers = {
                "Referer": referer or "https://aylink.co/",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "cross-site",
                "Upgrade-Insecure-Requests": "1",
            }
            page = self.fetch(url, "GET", headers=headers)

        if has_captcha(page.text):
            raise CaptchaRequired(
                "bildirim ara sayfasında CAPTCHA/Turnstile/reCAPTCHA görünüyor. "
                "Bu CLI aracı doğrulama çözmez."
            )

        target = extract_bildirim_url(page.text, page.final_url)
        if not target:
            target = extract_redirect_from_html(page.text, page.final_url)

        if target:
            target = html_lib.unescape(target).strip()
            if target and not is_bildirim_host(target):
                return target
            if target and target != url:
                return target

        if page.final_url and page.final_url != url and not is_bildirim_host(page.final_url):
            return page.final_url

        path_target = extract_bildirim_encoded_target(url)
        if path_target:
            return path_target

        snippet = strip_html(page.text)[:220].replace("\n", " ").strip()
        raise ResolveError(
            "bildirim.online/vip ara sayfasından gerçek URL çıkarılamadı. "
            f"HTTP status={page.status}; final_url={page.final_url}; body={snippet!r}"
        )

    def resolve_ouo_url(self, url: str, page: Optional[FetchResult] = None, referer: Optional[str] = None) -> str:
        """Resolve ouo.io/ouo.press by following its normal form and redirect hops.

        This routine intentionally does not attempt to solve CAPTCHA challenges.
        It submits only fields already present in the HTML and follows HTTP redirects.
        """
        start_url = normalize_url(url)
        if page is None:
            page = self.fetch(
                start_url,
                "GET",
                headers={
                    "Referer": referer or "https://www.google.com/",
                    "Sec-Fetch-Dest": "document",
                    "Sec-Fetch-Mode": "navigate",
                    "Sec-Fetch-Site": "cross-site",
                    "Upgrade-Insecure-Requests": "1",
                },
                allow_redirects=True,
            )

        if page.final_url and not is_ouo_host(page.final_url):
            return page.final_url

        current = page
        current_url = current.final_url or start_url
        slug = extract_ouo_slug(current_url) or extract_ouo_slug(start_url)
        seen: set[str] = set()

        for step in range(10):
            current_url = current.final_url or current_url
            if current_url in seen:
                break
            seen.add(current_url)
            self.log(f"ouo step {step + 1}: {current_url} status={current.status}")

            if current_url and not is_ouo_host(current_url):
                return current_url

            loc_target = header_location(current.headers, current_url)
            if loc_target:
                if not is_ouo_host(loc_target):
                    return loc_target
                current = self.fetch(
                    loc_target,
                    "GET",
                    headers={"Referer": current_url},
                    allow_redirects=False,
                )
                continue

            query_target = extract_target_from_query(current_url)
            if query_target and not is_ouo_host(query_target):
                return query_target

            html_target = extract_redirect_from_html(current.text, current_url)
            if html_target:
                if not is_ouo_host(html_target):
                    return html_target
                current = self.fetch(
                    html_target,
                    "GET",
                    headers={"Referer": current_url},
                    allow_redirects=False,
                )
                continue

            forms = extract_forms(current.text, current_url)
            forms = sorted(forms, key=lambda f: f.score, reverse=True)
            useful_forms = [f for f in forms if is_ouo_form(f) or f.score > 0]
            if useful_forms:
                form = useful_forms[0]
                self.log(f"ouo submit {form.method} {form.action} fields={list(form.inputs.keys())}")
                submitted = self.submit_form(form, referer=current_url)
                loc = header_location(submitted.headers, form.action)
                if loc:
                    if not is_ouo_host(loc):
                        return loc
                    current = self.fetch(
                        loc,
                        "GET",
                        headers={"Referer": current_url},
                        allow_redirects=False,
                    )
                    continue
                if submitted.final_url and not is_ouo_host(submitted.final_url):
                    return submitted.final_url
                current = submitted
                current_url = submitted.final_url or form.action
                continue

            next_links = extract_ouo_next_links(current.text, current_url)
            if slug:
                base = ouo_base_url(current_url)
                for suffix in (f"/go/{slug}", f"/xreallcygo/{slug}"):
                    candidate = urllib.parse.urljoin(base, suffix)
                    if candidate not in next_links:
                        next_links.append(candidate)

            advanced = False
            for next_url in next_links:
                if not next_url or next_url in seen:
                    continue
                self.log(f"ouo next {next_url}")
                next_page = self.fetch(
                    next_url,
                    "GET",
                    headers={"Referer": current_url},
                    allow_redirects=False,
                )
                loc = header_location(next_page.headers, next_url)
                if loc:
                    if not is_ouo_host(loc):
                        return loc
                    next_page = self.fetch(
                        loc,
                        "GET",
                        headers={"Referer": next_url},
                        allow_redirects=False,
                    )
                if next_page.final_url and not is_ouo_host(next_page.final_url):
                    return next_page.final_url
                current = next_page
                current_url = next_page.final_url or next_url
                advanced = True
                break
            if advanced:
                continue

            # Only now report CAPTCHA. Some ouo pages include CAPTCHA-related strings
            # even when a normal redirect form is still available, so we avoid failing early.
            if has_captcha(current.text):
                raise CaptchaRequired(
                    "ouo.io/ouo.press sayfasında CAPTCHA/Turnstile/reCAPTCHA gerekiyor gibi görünüyor. "
                    "Bu CLI aracı doğrulama çözmez."
                )
            break

        snippet = strip_html(current.text)[:220].replace("\n", " ").strip()
        raise ResolveError(
            "ouo.io/ouo.press akışından gerçek URL çıkarılamadı. "
            f"final_url={current.final_url}; status={current.status}; body={snippet!r}"
        )

    def resolve_intermediate_url(self, url: str, page: Optional[FetchResult] = None, referer: Optional[str] = None) -> str:
        """Best-effort resolver for simple intermediate/link-shortener pages.

        It tries normal browser-like redirects, query targets, meta/JS redirects,
        hidden forms, and literal external URLs. If the host uses CAPTCHA or a
        heavy JavaScript challenge, it returns the intermediate URL instead of
        inventing a wrong final URL.
        """
        start_url = normalize_url(url)
        current_url = start_url
        current = page
        seen: set[str] = set()

        for step in range(8):
            if current_url in seen:
                break
            seen.add(current_url)

            if current is None:
                current = self.fetch(
                    current_url,
                    "GET",
                    headers={
                        "Referer": referer or "https://www.google.com/",
                        "Sec-Fetch-Dest": "document",
                        "Sec-Fetch-Mode": "navigate",
                        "Sec-Fetch-Site": "cross-site",
                        "Upgrade-Insecure-Requests": "1",
                    },
                    allow_redirects=False,
                )

            loc = header_location(current.headers, current_url)
            if loc:
                if not is_known_intermediate_or_supported(loc):
                    return loc
                current_url = loc
                current = None
                continue

            if current.final_url and current.final_url != current_url:
                if not is_known_intermediate_or_supported(current.final_url):
                    return current.final_url
                current_url = current.final_url

            query_target = extract_target_from_query(current_url)
            if query_target and not is_known_intermediate_or_supported(query_target):
                return query_target

            html_target = extract_intermediate_target(current.text, current_url)
            if html_target:
                if not is_known_intermediate_or_supported(html_target):
                    return html_target
                current_url = html_target
                current = None
                continue

            forms = extract_forms(current.text, current_url)
            forms = sorted(forms, key=lambda f: score_intermediate_form(f), reverse=True)
            useful_forms = [f for f in forms if score_intermediate_form(f) > 0]
            if useful_forms:
                form = useful_forms[0]
                submitted = self.submit_form(form, referer=current_url)
                loc = header_location(submitted.headers, form.action)
                if loc:
                    if not is_known_intermediate_or_supported(loc):
                        return loc
                    current_url = loc
                    current = None
                    continue
                if submitted.final_url and not is_known_intermediate_or_supported(submitted.final_url):
                    return submitted.final_url
                target = extract_intermediate_target(submitted.text, submitted.final_url or form.action)
                if target:
                    if not is_known_intermediate_or_supported(target):
                        return target
                    current_url = target
                    current = None
                    continue
                current = submitted
                current_url = submitted.final_url or form.action
                continue

            # Last safe attempt: follow the document URL with normal redirects enabled.
            try:
                followed = self.fetch(
                    current_url,
                    "GET",
                    headers={"Referer": referer or "https://www.google.com/"},
                    max_bytes=65536,
                    allow_redirects=True,
                )
                if followed.final_url and not is_known_intermediate_or_supported(followed.final_url):
                    return followed.final_url
                target = extract_intermediate_target(followed.text, followed.final_url or current_url)
                if target and not is_known_intermediate_or_supported(target):
                    return target
            except ResolveError:
                pass
            break

        return start_url

    def submit_form(self, form: HtmlForm, referer: str) -> FetchResult:
        headers = dict(COMMON_HEADERS)
        headers.update(
            {
                "Referer": referer,
                "Origin": origin_of(form.action) or origin_of(referer),
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "same-origin" if same_site(form.action, referer) else "cross-site",
                "Upgrade-Insecure-Requests": "1",
            }
        )
        method = (form.method or "GET").upper()
        if method == "POST":
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            return self.fetch(
                form.action,
                "POST",
                data=form.inputs,
                headers=headers,
                allow_redirects=False,
            )

        target = form.action
        if form.inputs:
            sep = "&" if urllib.parse.urlparse(target).query else "?"
            target = target + sep + urllib.parse.urlencode(form.inputs)
        return self.fetch(target, "GET", headers=headers, allow_redirects=False)

    def final_follow(self, url: str) -> str:
        url = normalize_url(url)
        if is_intermediate_host(url):
            try:
                target = self.resolve_intermediate_url(url)
                if target and target != url:
                    url = target
                else:
                    return url
            except ResolveError as e:
                self.log(f"intermediate final-follow failed: {e}")
                return url
        query_target = extract_target_from_query(url)
        if query_target:
            url = query_target

        if is_bildirim_host(url):
            try:
                target = self.resolve_bildirim_url(url)
                if target and target != url:
                    url = target
                else:
                    return url
            except ResolveError as e:
                self.log(f"bildirim final-follow failed: {e}")
                return url

        if is_ouo_host(url):
            try:
                target = self.resolve_ouo_url(url)
                if target and target != url:
                    url = target
                else:
                    return url
            except ResolveError as e:
                self.log(f"ouo final-follow failed: {e}")
                return url

        # HEAD is cheap when accepted.
        try:
            r = self.fetch(url, "HEAD", read_body=False)
            if r.final_url:
                return r.final_url
        except ResolveError as e:
            self.log(f"HEAD final-follow failed: {e}")

        # GET with Range usually avoids downloading a full body. Some servers ignore Range,
        # but this function reads at most 64 KiB.
        try:
            hdrs = {"Range": "bytes=0-65535"}
            r = self.fetch(url, "GET", headers=hdrs, max_bytes=65536, read_body=True)
            html_target = extract_bildirim_url(r.text, r.final_url) or extract_redirect_from_html(r.text, r.final_url)
            return html_target or r.final_url or url
        except ResolveError as e:
            self.log(f"GET final-follow failed: {e}")
            return url


def decode_body(raw: bytes, headers_obj: object) -> str:
    if not raw:
        return ""
    encoding = ""
    try:
        encoding = (headers_obj.get("Content-Encoding") or "").lower()
    except Exception:
        encoding = ""
    try:
        if encoding == "gzip":
            raw = gzip.decompress(raw)
        elif encoding == "deflate":
            try:
                raw = zlib.decompress(raw)
            except zlib.error:
                raw = zlib.decompress(raw, -zlib.MAX_WBITS)
    except Exception:
        pass

    charset = None
    try:
        charset = headers_obj.get_content_charset()
    except Exception:
        charset = None
    if not charset:
        m = re.search(br"<meta[^>]+charset=[\"']?([A-Za-z0-9._-]+)", raw[:4096], re.I)
        if m:
            charset = m.group(1).decode("ascii", "ignore")
    if not charset:
        charset = "utf-8"
    return raw.decode(charset, "replace")


def normalize_url(value: str) -> str:
    u = value.strip().strip("'\"")
    replacements = {
        "hxxps://": "https://",
        "hxxp://": "http://",
        "(dot)": ".",
        "[dot]": ".",
        "{dot}": ".",
        "(nokta)": ".",
        "[nokta]": ".",
        "{nokta}": ".",
    }
    low = u.lower()
    for old, new in replacements.items():
        if old in low:
            u = re.sub(re.escape(old), new, u, flags=re.I)
            low = u.lower()
    u = re.sub(r"\s+", "", u)
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", u):
        u = "https://" + u
    return u


def host_of(url: str) -> str:
    try:
        return (urllib.parse.urlparse(url).hostname or "").lower().removeprefix("www.")
    except Exception:
        return ""


def is_bildirim_host(url_or_host: str) -> bool:
    value = url_or_host.strip().lower()
    if "://" in value:
        value = host_of(value)
    else:
        value = value.removeprefix("www.")
    return value in BILDIRIM_HOSTS


def is_ouo_host(url_or_host: str) -> bool:
    value = url_or_host.strip().lower()
    if "://" in value:
        value = host_of(value)
    else:
        value = value.removeprefix("www.")
    return value in OUO_HOSTS


def is_intermediate_host(url_or_host: str) -> bool:
    value = url_or_host.strip().lower()
    if "://" in value:
        value = host_of(value)
    else:
        value = value.removeprefix("www.")
    return value in INTERMEDIATE_HOSTS


def is_known_intermediate_or_supported(url_or_host: str) -> bool:
    return is_intermediate_host(url_or_host) or is_ouo_host(url_or_host) or is_bildirim_host(url_or_host) or host_of(url_or_host) in TRLINK_HOSTS


def looks_like_ouo_page(text: str) -> bool:
    low = (text or "").lower()
    return (
        "ouo.io" in low
        or "ouo.press" in low
        or "/xreallcygo/" in low
        or "/go/" in low and ("form" in low or "csrf" in low or "token" in low)
    )


def extract_ouo_slug(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    parts = [urllib.parse.unquote(p) for p in parsed.path.split("/") if p]
    if not parts:
        return ""
    if parts[0].lower() in {"go", "xreallcygo", "s", "qs"} and len(parts) >= 2:
        return parts[1]
    return parts[-1]


def ouo_base_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return "https://ouo.io/"
    return f"{parsed.scheme}://{parsed.netloc}/"


def header_location(headers_obj: object, base: str) -> Optional[str]:
    loc = None
    try:
        loc = headers_obj.get("Location")
    except Exception:
        loc = None
    if not loc:
        return None
    return absolutize(str(loc), base)


def origin_of(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def same_site(a: str, b: str) -> bool:
    return host_of(a) == host_of(b) and bool(host_of(a))


def parse_tag_attrs(attr_text: str) -> Dict[str, str]:
    attrs: Dict[str, str] = {}
    attr_re = re.compile(
        r"([A-Za-z_:][-A-Za-z0-9_:.]*)"
        r'(?:\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s"\'>`]+)))?',
        re.S,
    )
    for m in attr_re.finditer(attr_text or ""):
        key = m.group(1).lower()
        val = m.group(2) if m.group(2) is not None else m.group(3) if m.group(3) is not None else m.group(4)
        attrs[key] = html_lib.unescape(val or "")
    return attrs


def extract_forms(text: str, base: str) -> List[HtmlForm]:
    forms: List[HtmlForm] = []
    for m in re.finditer(r"<form\b([^>]*)>(.*?)</form>", text or "", re.I | re.S):
        attrs = parse_tag_attrs(m.group(1))
        body = m.group(2)
        action = attrs.get("action") or base
        action = absolutize(action, base)
        method = (attrs.get("method") or "GET").upper()
        inputs: Dict[str, str] = {}
        for tag in re.findall(r"<(?:input|button|textarea)\b[^>]*>", body, re.I | re.S):
            iattrs = parse_tag_attrs(tag)
            name = iattrs.get("name")
            if not name:
                continue
            value = iattrs.get("value", "")
            typ = iattrs.get("type", "").lower()
            if typ in {"submit", "button", "image", "reset"}:
                # Submit buttons are not necessary for the normal hidden-token flow.
                continue
            inputs[name] = value
        score = score_ouo_form(action, method, inputs, body, attrs)
        forms.append(HtmlForm(action=action, method=method, inputs=inputs, attrs=attrs, score=score))
    return forms


def score_ouo_form(action: str, method: str, inputs: Dict[str, str], body: str, attrs: Dict[str, str]) -> int:
    hay = " ".join([action, method, body, " ".join(inputs.keys()), " ".join(attrs.values())]).lower()
    score = 0
    if is_ouo_host(action):
        score += 5
    if "/go/" in hay:
        score += 20
    if "/xreallcygo/" in hay:
        score += 25
    if "_token" in inputs or "csrf" in inputs or any("token" in k.lower() for k in inputs):
        score += 10
    if method.upper() == "POST":
        score += 4
    if "captcha" in hay or "recaptcha" in hay:
        score -= 3
    return score


def is_ouo_form(form: HtmlForm) -> bool:
    if is_ouo_host(form.action):
        return True
    hay = " ".join([form.action, " ".join(form.inputs.keys())]).lower()
    return "/go/" in hay or "/xreallcygo/" in hay


def score_intermediate_form(form: HtmlForm) -> int:
    hay = " ".join([form.action, form.method, " ".join(form.inputs.keys()), " ".join(form.inputs.values()), " ".join(form.attrs.values())]).lower()
    score = 0
    if is_intermediate_host(form.action):
        score += 8
    if form.method.upper() == "POST":
        score += 4
    if any(k.lower() in {"token", "_token", "csrf", "id", "alias", "url", "u", "go", "link"} for k in form.inputs):
        score += 6
    if any(x in hay for x in ("continue", "get link", "go", "redirect", "download", "short")):
        score += 3
    if "captcha" in hay or "recaptcha" in hay or "turnstile" in hay:
        score -= 6
    return score


def extract_intermediate_target(text: str, base: str) -> Optional[str]:
    text = html_lib.unescape(text or "")

    # First, common encoded or JS-held destinations.
    target = extract_bildirim_url(text, base) or extract_redirect_from_html(text, base)
    if target and not looks_like_asset_url(target):
        return target

    patterns = [
        r"\b(?:target|destination|redirect|redirect_url|go_url|final_url|url|u|link)\b\s*[:=]\s*(['\"])(.*?)\1",
        r"\b(?:data-url|data-href|data-target|data-link|data-destination)\s*=\s*(['\"])(.*?)\1",
        r"(?:location\.href|window\.location|location\.replace|location\.assign)\s*(?:=|\()\s*(['\"])(.*?)\1",
        r"window\.open\(\s*(['\"])(.*?)\1",
    ]
    for pat in patterns:
        for m in re.finditer(pat, text, re.I | re.S):
            raw = m.group(2) if m.lastindex and m.lastindex >= 2 else m.group(1)
            candidate = normalize_candidate_url(raw, base, allow_assets=False)
            if candidate and not same_site(candidate, base):
                return candidate

    for pat in [
        r"decodeURIComponent\(\s*(['\"])(.*?)\1\s*\)",
        r"decodeURI\(\s*(['\"])(.*?)\1\s*\)",
        r"unescape\(\s*(['\"])(.*?)\1\s*\)",
    ]:
        for m in re.finditer(pat, text, re.I | re.S):
            candidate = normalize_candidate_url(m.group(2), base, allow_assets=False)
            if candidate and not same_site(candidate, base):
                return candidate

    # Base64 encoded destinations.
    for m in re.finditer(r"(?:atob|b64DecodeUnicode)\(\s*(['\"])([A-Za-z0-9+/_=-]{16,})\1\s*\)", text, re.I | re.S):
        decoded = decode_base64_urlish(m.group(2))
        candidate = normalize_candidate_url(decoded or "", base, allow_assets=False)
        if candidate and not same_site(candidate, base):
            return candidate

    # Query string style destinations embedded in links.
    for m in re.finditer(r"https?://[^\s'\"<>\\)]+", text, re.I):
        candidate = normalize_candidate_url(m.group(0), base, allow_assets=False)
        if not candidate:
            continue
        qtarget = extract_target_from_query(candidate)
        if qtarget and not is_known_intermediate_or_supported(qtarget) and not looks_like_asset_url(qtarget):
            return qtarget

    # Final cautious fallback: literal external URL, excluding known assets and own-host links.
    for m in re.finditer(r"https?://[^\s'\"<>\\)]+", text, re.I):
        candidate = normalize_candidate_url(m.group(0), base, allow_assets=False)
        if candidate and not same_site(candidate, base) and not is_known_intermediate_or_supported(candidate):
            return candidate
    return None


def extract_ouo_next_links(text: str, base: str) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    patterns = [
        r'\b(?:href|action)\s*=\s*([\'"])(.*?)\1',
        r'location\.(?:href|assign|replace)\s*(?:=|\()\s*([\'"])(.*?)\1',
        r'window\.open\(\s*([\'"])(.*?)\1',
        r'https?://[^\s\'"<>\)]+',
    ]
    for pat in patterns:
        for m in re.finditer(pat, text or "", re.I | re.S):
            raw = m.group(2) if m.lastindex and m.lastindex >= 2 else m.group(0)
            candidate = normalize_candidate_url(raw, base, allow_assets=False)
            if not candidate:
                continue
            if is_ouo_host(candidate) and candidate not in seen:
                seen.add(candidate)
                out.append(candidate)
    out.sort(key=lambda u: (0 if "/xreallcygo/" in u else 1 if "/go/" in u else 2, u))
    return out


def absolutize(url: str, base: str) -> str:
    url = html_lib.unescape(url.strip())
    return urllib.parse.urljoin(base, url)


def has_captcha(text: str) -> bool:
    low = text.lower()
    return any(marker in low for marker in CAPTCHA_MARKERS)


def looks_like_trlink_page(text: str) -> bool:
    low = text.lower()
    return (
        "/get/tk" in low
        or "/links/go2" in low
        or "name=\"alias\"" in low
        or "name='alias'" in low
        or ("_a" in low and "_t" in low and "_d" in low)
    )


def extract_atd(text: str) -> Tuple[str, str, str]:
    patterns = [
        r"_a\s*=\s*['\"]([^'\"]+)['\"]\s*,\s*_t\s*=\s*['\"]([^'\"]+)['\"]\s*,\s*_d\s*=\s*['\"]([^'\"]+)['\"]",
        r"var\s+_a\s*=\s*['\"]([^'\"]+)['\"];?\s*var\s+_t\s*=\s*['\"]([^'\"]+)['\"];?\s*var\s+_d\s*=\s*['\"]([^'\"]+)['\"]",
        r"let\s+_a\s*=\s*['\"]([^'\"]+)['\"];?\s*let\s+_t\s*=\s*['\"]([^'\"]+)['\"];?\s*let\s+_d\s*=\s*['\"]([^'\"]+)['\"]",
        r"const\s+_a\s*=\s*['\"]([^'\"]+)['\"];?\s*const\s+_t\s*=\s*['\"]([^'\"]+)['\"];?\s*const\s+_d\s*=\s*['\"]([^'\"]+)['\"]",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.I | re.S)
        if m:
            return tuple(html_lib.unescape(x) for x in m.groups())  # type: ignore[return-value]
    # More tolerant fallback: find each variable separately.
    vals = []
    for name in ("_a", "_t", "_d"):
        m = re.search(rf"\b{name}\s*=\s*['\"]([^'\"]+)['\"]", text, re.I)
        if not m:
            raise ResolveError("Could not extract _a/_t/_d values from the page.")
        vals.append(html_lib.unescape(m.group(1)))
    return vals[0], vals[1], vals[2]


def extract_input_value(text: str, name: str) -> str:
    # Match an input tag containing name=... and value=... in any attribute order.
    input_tags = re.findall(r"<input\b[^>]*>", text, re.I | re.S)
    for tag in input_tags:
        nm = re.search(r"\bname\s*=\s*(['\"])(.*?)\1", tag, re.I | re.S)
        if not nm or nm.group(2) != name:
            continue
        val = re.search(r"\bvalue\s*=\s*(['\"])(.*?)\1", tag, re.I | re.S)
        if val:
            return html_lib.unescape(val.group(2))
    # Fallback for source that places alias/csrf in JS.
    js_patterns = [
        rf"\b{name}\b\s*[:=]\s*['\"]([^'\"]+)['\"]",
        rf"app\[['\"]{re.escape(name)}['\"]\]\s*=\s*['\"]([^'\"]+)['\"]",
    ]
    for pat in js_patterns:
        m = re.search(pat, text, re.I)
        if m:
            return html_lib.unescape(m.group(1))
    raise ResolveError(f"Could not extract input value: {name}")


def extract_visitor_token(text: str) -> str:
    try:
        return extract_input_value(text, "visitor_token")
    except ResolveError:
        pass
    patterns = [
        r"app\[['\"]token['\"]\]\s*=\s*['\"]([^'\"]+)['\"]",
        r"\bvisitor_token\b\s*[:=]\s*['\"]([^'\"]+)['\"]",
        r"\btoken\b\s*[:=]\s*['\"]([^'\"]{12,})['\"]",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            return html_lib.unescape(m.group(1))
    return ""


def build_browser_signal() -> str:
    return json.dumps(
        {
            "t": int(time.time()),
            "d": 5,
            "m": {"move": 5, "click": 1, "scroll": 1, "key": 0, "touch": 0, "focus": 1},
            "f": {"webdriver": False, "headless": False, "noPlugins": False, "mobile": False},
        },
        separators=(",", ":"),
    )


def parse_json_object(text: str, label: str) -> Dict[str, object]:
    cleaned = text.strip()
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
        raise ValueError("JSON is not an object")
    except Exception:
        m = re.search(r"\{.*\}", cleaned, re.S)
        if m:
            try:
                data = json.loads(m.group(0))
                if isinstance(data, dict):
                    return data
            except Exception:
                pass
    raise ResolveError(f"Could not parse {label} as JSON: {cleaned[:300]!r}")


def extract_bildirim_url(text: str, base: str) -> Optional[str]:
    # bildirim.online/vip usually displays an alert/notification prompt and keeps
    # the actual destination in a JavaScript variable such as: var url = 'https://...';
    text = html_lib.unescape(text or "")
    assignment_patterns = [
        r"\b(?:var|let|const)?\s*(?:url|uri|uri_full|go_url|target|destination|redirect|redirect_url)\s*[:=]\s*(['\"])(.*?)\1",
        r"(['\"])(?:url|uri|uri_full|go_url|target|destination|redirect|redirect_url)\1\s*:\s*(['\"])(.*?)\2",
        r"(?:window\.)?open\(\s*(['\"])(.*?)\1",
        r"\b(?:data-url|data-href|data-target)\s*=\s*(['\"])(.*?)\1",
    ]
    for pat in assignment_patterns:
        for m in re.finditer(pat, text, re.I | re.S):
            raw = m.group(m.lastindex or 1)
            # JSON style pattern has three groups: quote,keyquote,value.
            if m.lastindex and m.lastindex >= 3:
                raw = m.group(3)
            candidate = normalize_candidate_url(raw, base)
            if candidate:
                return candidate

    # A common JS form: location.href = decodeURIComponent('https%3A%2F%2F...')
    for pat in [
        r"decodeURIComponent\(\s*(['\"])(.*?)\1\s*\)",
        r"unescape\(\s*(['\"])(.*?)\1\s*\)",
    ]:
        for m in re.finditer(pat, text, re.I | re.S):
            candidate = normalize_candidate_url(m.group(2), base)
            if candidate:
                return candidate

    # Some pages hide the URL in atob('base64...').
    for m in re.finditer(r"atob\(\s*(['\"])([A-Za-z0-9+/_=-]{16,})\1\s*\)", text, re.I | re.S):
        decoded = decode_base64_urlish(m.group(2))
        candidate = normalize_candidate_url(decoded or "", base)
        if candidate:
            return candidate

    # Last cautious fallback: only use literal URLs that do not look like page assets.
    for m in re.finditer(r"https?://[^\s'\"<>\\)]+", text, re.I):
        candidate = normalize_candidate_url(m.group(0), base, allow_assets=False)
        if candidate and not is_bildirim_host(candidate):
            return candidate
    return None


def normalize_candidate_url(value: str, base: str, allow_assets: bool = True) -> Optional[str]:
    if not value:
        return None
    candidate = html_lib.unescape(value).strip().strip("`'\"")
    candidate = candidate.replace("\\/", "/")
    try:
        candidate = bytes(candidate, "utf-8").decode("unicode_escape")
    except Exception:
        pass
    candidate = candidate.strip()
    if not re.match(r"^https?://", candidate, re.I) and "%" in candidate:
        candidate = urllib.parse.unquote(candidate).strip()
    if not candidate or candidate.startswith(("#", "javascript:", "mailto:", "tel:")):
        return None
    if candidate.startswith("//"):
        parsed = urllib.parse.urlparse(base)
        candidate = f"{parsed.scheme or 'https'}:{candidate}"
    candidate = absolutize(candidate, base)
    if not re.match(r"^https?://", candidate, re.I):
        return None
    if not allow_assets and looks_like_asset_url(candidate):
        return None
    return candidate


def looks_like_asset_url(url: str) -> bool:
    """Return True for page resources / metadata URLs that must never be final links."""
    try:
        parsed = urllib.parse.urlparse(url)
        host = (parsed.hostname or "").lower().removeprefix("www.")
        path = (parsed.path or "").lower()
    except Exception:
        return False

    # Normal static assets.
    if re.search(r"\.(?:js|css|png|jpg|jpeg|gif|webp|svg|ico|woff2?|ttf|eot|mp4|webm|mp3|wav)(?:$|[?#])", path):
        return True

    # RDF/schema/library namespaces often appear in HTML as metadata links.
    # They are not user destinations, even though they look like normal HTTPS URLs.
    if host in {
        "web.resource.org",
        "schema.org",
        "www.w3.org",
        "w3.org",
        "ogp.me",
        "purl.org",
        "xmlns.com",
    }:
        return True

    noise_path_parts = (
        "/rss/1.0/modules/",
        "/1999/xhtml",
        "/2000/svg",
        "/2001/xmlschema",
        "/tr/",
        "/ajax/libs/",
    )
    if any(part in path for part in noise_path_parts):
        return True

    return False


def decode_base64_urlish(value: str) -> Optional[str]:
    try:
        s = value.strip().replace("-", "+").replace("_", "/")
        s += "=" * ((4 - len(s) % 4) % 4)
        return base64_bdecode_to_text(s)
    except Exception:
        return None


def base64_bdecode_to_text(value: str) -> str:
    import base64
    return base64.b64decode(value).decode("utf-8", "replace")


def extract_bildirim_encoded_target(url: str) -> Optional[str]:
    # The /ph/<token> segment is often encrypted, not plain base64. Still, handle
    # the simple base64 cases so direct bildirim links can resolve when possible.
    parsed = urllib.parse.urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    for part in reversed(parts):
        decoded = decode_base64_urlish(part)
        candidate = normalize_candidate_url(decoded or "", url)
        if candidate:
            return candidate
    return None


def strip_html(text: str) -> str:
    text = re.sub(r"<script\b.*?</script>", " ", text or "", flags=re.I | re.S)
    text = re.sub(r"<style\b.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_lib.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def extract_redirect_from_html(text: str, base: str) -> Optional[str]:
    patterns = [
        r"<meta[^>]+http-equiv\s*=\s*['\"]?refresh['\"]?[^>]+content\s*=\s*['\"][^'\"]*?url\s*=\s*([^'\";>\s]+)",
        r"window\.location\.href\s*=\s*['\"]([^'\"]+)['\"]",
        r"window\.location\s*=\s*['\"]([^'\"]+)['\"]",
        r"document\.location\s*=\s*['\"]([^'\"]+)['\"]",
        r"location\.href\s*=\s*['\"]([^'\"]+)['\"]",
        r"location\.replace\(\s*['\"]([^'\"]+)['\"]\s*\)",
        r"location\.assign\(\s*['\"]([^'\"]+)['\"]\s*\)",
        r"window\.open\(\s*['\"]([^'\"]+)['\"]",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.I | re.S)
        if m:
            candidate = html_lib.unescape(m.group(1).strip())
            if candidate:
                return absolutize(candidate, base)
    return None


def first_url_in_text(text: str) -> Optional[str]:
    m = re.search(r"https?://[^\s'\"<>\\)]+", text)
    if not m:
        return None
    return html_lib.unescape(m.group(0).rstrip(".,;"))


def extract_target_from_query(url: str) -> Optional[str]:
    parsed = urllib.parse.urlparse(url)
    qs = urllib.parse.parse_qs(parsed.query)
    for key in TARGET_QUERY_KEYS:
        if key in qs and qs[key]:
            val = qs[key][0].strip()
            val = html_lib.unescape(urllib.parse.unquote(val))
            if val.startswith("http://") or val.startswith("https://"):
                return val
    return None


def resolve_url(url: str) -> str:
    """Kivy app entrypoint used by main.py."""
    final, _info = Resolver(sleep_seconds=1.0).resolve(url, follow_final=True)
    return final
