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

import argparse
import gzip
import html as html_lib
import http.cookiejar
import json
import os
import re
import shutil
import stat
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

APP_NAME = "ayson"
VERSION = "V2.5-auto-intermediates"
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


class Resolver:
    def __init__(self, timeout: int = DEFAULT_TIMEOUT, verbose: bool = False, sleep_seconds: float = 0.0):
        self.timeout = timeout
        self.verbose = verbose
        self.sleep_seconds = sleep_seconds
        self.cookiejar = http.cookiejar.CookieJar()
        context = ssl.create_default_context()
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
       
