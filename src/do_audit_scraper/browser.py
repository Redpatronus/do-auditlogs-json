"""Playwright layer: interactive login, session check, paginated page-HTML fetching."""

import os
import re
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pyotp
import structlog
from playwright.sync_api import BrowserContext, Page, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from .config import Settings

log = structlog.get_logger()


class SessionExpiredError(RuntimeError):
    """Stored cookies no longer authenticate; run `do-audit login` again."""


def interactive_login(cfg: Settings) -> None:
    """Headed browser: log in by hand (incl. 2FA), then the session is saved.

    Run this on a machine with a display, then copy the file to the server.
    """
    cfg.storage_state_path.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        ctx = browser.new_context()
        page = ctx.new_page()
        page.goto(cfg.audit_url)
        input("Log in (incl. 2FA) until the Security page shows, then press Enter... ")
        ctx.storage_state(path=str(cfg.storage_state_path))
        os.chmod(cfg.storage_state_path, 0o600)
        _mark_login(cfg)
        browser.close()
    log.info("session_saved", path=str(cfg.storage_state_path))


def _mark_login(cfg: Settings) -> None:
    cfg.session_meta_path.write_text(datetime.now(UTC).isoformat())
    os.chmod(cfg.session_meta_path, 0o600)


def _session_too_old(cfg: Settings) -> bool:
    try:
        started = datetime.fromisoformat(cfg.session_meta_path.read_text().strip())
    except (OSError, ValueError):
        _mark_login(cfg)  # unknown age: start counting now
        return False
    return datetime.now(UTC) - started > cfg.session_max_age


@contextmanager
def _display(cfg: Settings) -> Iterator[None]:
    """On Linux without a display, run the (headed) browser on a virtual Xvfb display."""
    if cfg.headless or sys.platform != "linux" or os.environ.get("DISPLAY"):
        yield
        return
    try:
        from pyvirtualdisplay import Display
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("pyvirtualdisplay missing; reinstall the package on Linux") from exc
    try:
        display = Display(visible=False, size=(1366, 768))
        display.start()
    except Exception as exc:
        raise RuntimeError("cannot start Xvfb; install it: sudo apt install xvfb") from exc
    log.info("virtual_display_started")
    try:
        yield
    finally:
        display.stop()


def _save_session(cfg: Settings, ctx: BrowserContext) -> None:
    try:
        cfg.storage_state_path.parent.mkdir(parents=True, exist_ok=True)
        ctx.storage_state(path=str(cfg.storage_state_path))
        os.chmod(cfg.storage_state_path, 0o600)
    except Exception:  # noqa: BLE001 - never fail the run over a cache write
        log.warning("session_save_failed")


@contextmanager
def _context(cfg: Settings) -> Iterator[BrowserContext]:
    have_state = cfg.storage_state_path.exists()
    if have_state and cfg.can_auto_login and _session_too_old(cfg):
        log.info("session_max_age_reached", max_age=str(cfg.session_max_age))
        cfg.storage_state_path.unlink()
        have_state = False
    if not have_state and not cfg.can_auto_login:
        raise SessionExpiredError(f"{cfg.storage_state_path} missing; run `do-audit login`")
    with _display(cfg), sync_playwright() as pw:
        browser = pw.chromium.launch(headless=cfg.headless)
        ctx = browser.new_context(
            storage_state=str(cfg.storage_state_path) if have_state else None
        )
        ctx.set_default_timeout(cfg.nav_timeout_ms)
        try:
            yield ctx
        finally:
            # Persist refreshed cookies even on errors / early exit, so the session is reused.
            if cfg.storage_state_path.exists():
                _save_session(cfg, ctx)
            browser.close()


def _on_login_page(page: Page) -> bool:
    return "/login" in page.url or page.locator("input[type=password]").count() > 0


_CONSENT_OVERLAYS = ".truste_cm_outerdiv, .trustarc_newcm_container, #truste-consent-track"


def _dismiss_consent(page: Page) -> None:
    """Click "Decline all" in the TrustArc cookie dialog (any frame); remove overlay as fallback."""
    for frame in page.frames:
        btn = frame.get_by_role("button", name=re.compile(r"decline all|reject all", re.I))
        try:
            if btn.count() and btn.first.is_visible():
                btn.first.click(timeout=3_000)
                page.wait_for_timeout(500)
                return
        except PlaywrightTimeout:
            continue
    page.evaluate(
        "sel => document.querySelectorAll(sel).forEach(e => e.remove())", _CONSENT_OVERLAYS
    )


_B32 = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")


def _totp_code(cfg: Settings) -> str:
    """Current TOTP code from a bare secret (spaces/dashes tolerated) or an otpauth:// URI."""
    assert cfg.totp_secret  # noqa: S101
    raw = cfg.totp_secret.get_secret_value().strip()
    if raw.lower().startswith("otpauth://"):
        raw = parse_qs(urlparse(raw).query).get("secret", [""])[0]
    secret = re.sub(r"[\s\-\"']", "", raw).upper().rstrip("=")
    bad = sum(1 for ch in secret if ch not in _B32)
    if not secret or bad:
        raise SessionExpiredError(
            f"DOAL_TOTP_SECRET is not valid base32 (length {len(secret)}, {bad} invalid chars). "
            "Use the text key shown under the QR code (letters A-Z and digits 2-7 only), "
            "not a recovery/backup code and not a 6-digit code."
        )
    return pyotp.TOTP(secret).now()


def _dump_debug(cfg: Settings, page: Page, name: str) -> str:
    """Save screenshot + HTML for diagnosing login problems. May contain your e-mail: keep local."""
    d = cfg.storage_state_path.parent / "debug"
    d.mkdir(parents=True, exist_ok=True)
    png, html = d / f"{name}.png", d / f"{name}.html"
    page.screenshot(path=str(png), full_page=True)
    html.write_text(page.content(), encoding="utf-8")
    for f in (png, html):
        os.chmod(f, 0o600)
    return str(d)


def auto_login(cfg: Settings, page: Page) -> None:
    """Headless email + password + TOTP login. Selectors are configurable via DOAL_*."""
    assert cfg.email and cfg.password and cfg.totp_secret  # noqa: S101
    log.info("auto_login_start")
    page.goto(cfg.base_url.rstrip("/") + cfg.login_path, wait_until="networkidle")
    _dismiss_consent(page)
    page.fill(cfg.email_selector, cfg.email)
    if page.locator(cfg.password_selector).count() == 0:  # two-step form
        page.press(cfg.email_selector, "Enter")
        page.wait_for_selector(cfg.password_selector)
    page.fill(cfg.password_selector, cfg.password.get_secret_value())
    _dismiss_consent(page)  # banner may re-appear after navigation
    page.press(cfg.password_selector, "Enter")
    try:
        page.wait_for_selector(cfg.totp_selector)
    except PlaywrightTimeout as exc:
        where = _dump_debug(cfg, page, "login_totp_step")
        if "just a moment" in page.title().lower() or "challenge" in page.url:
            raise SessionExpiredError(
                "Cloudflare bot challenge blocks automated login. Use a manual session "
                "(`do-audit login`, then copy storage_state.json) or the API-token collector."
            ) from exc
        log.error("totp_field_not_found", url=page.url, title=page.title(), debug_dir=where)
        raise SessionExpiredError(
            f"2FA field not shown (url={page.url}); see {where}. Possibly a bot challenge, "
            "wrong password or e-mail verification."
        ) from exc
    for attempt in (1, 2):
        page.fill(cfg.totp_selector, _totp_code(cfg))
        page.press(cfg.totp_selector, "Enter")
        try:  # wait for the 2FA step to go away (navigation after a valid code)
            page.wait_for_selector(cfg.totp_selector, state="detached", timeout=20_000)
            break
        except PlaywrightTimeout:
            log.warning("totp_not_accepted", attempt=attempt, url=page.url)
            if attempt == 2:
                where = _dump_debug(cfg, page, "login_totp_rejected")
                raise SessionExpiredError(
                    f"2FA code not accepted twice (url={page.url}); see {where}. "
                    "Check DOAL_TOTP_SECRET and the system clock."
                ) from None
            time.sleep(31)  # next 30 s window so the code differs from the rejected one
    try:
        page.wait_for_url(lambda u: "/login" not in u and "challenge" not in u, timeout=20_000)
    except PlaywrightTimeout:
        pass
    page.wait_for_load_state("networkidle")
    if _on_login_page(page):
        where = _dump_debug(cfg, page, "login_still_on_login")
        raise SessionExpiredError(f"still on login page after 2FA (url={page.url}); see {where}")
    _mark_login(cfg)
    log.info("auto_login_ok")


def _open_audit_page(cfg: Settings, ctx: BrowserContext) -> Page:
    page = ctx.new_page()
    page.goto(cfg.audit_url, wait_until="networkidle")
    if _on_login_page(page):
        if not cfg.can_auto_login:
            raise SessionExpiredError("redirected to login; session expired")
        auto_login(cfg, page)
        page.goto(cfg.audit_url, wait_until="networkidle")
        if _on_login_page(page):
            raise SessionExpiredError("still on login page after auto-login")
    try:
        page.wait_for_selector(cfg.table_selector)
    except PlaywrightTimeout as exc:
        where = _dump_debug(cfg, page, "audit_page_no_table")
        raise RuntimeError(
            f"audit table not found on {page.url} (selector {cfg.table_selector!r}); see {where}"
        ) from exc
    _save_session(cfg, ctx)  # authenticated: cache cookies now
    return page


def _attach_feed(ctx: BrowserContext) -> list[dict]:
    """Collect valid JSON of the page's own `GetAuditActions` GraphQL responses."""
    feed: list[dict] = []

    def on_response(resp) -> None:  # noqa: ANN001
        req = resp.request
        if req.method != "POST" or "GetAuditActions" not in (req.post_data or ""):
            return
        try:
            body = resp.json()
        except Exception:  # noqa: BLE001 - redirects / empty bodies
            log.warning("audit_response_unreadable", status=resp.status)
            return
        if ((body or {}).get("data") or {}).get("GetAuditActions"):
            feed.append(body)
        else:  # GraphQL error / rate limit: log message only, caller retries
            log.warning(
                "audit_graphql_error", status=resp.status, errors=str(body.get("errors"))[:300]
            )

    ctx.on("response", on_response)
    return feed


def _wait_feed(page: Page, feed: list[dict], count: int, timeout_ms: int) -> bool:
    waited = 0
    while len(feed) < count:
        if waited >= timeout_ms:
            return False
        page.wait_for_timeout(200)
        waited += 200
    return True


def login_test(cfg: Settings) -> str:
    """Login only (fresh session, ignores the cache). Returns the final URL; raises on failure."""
    if not cfg.can_auto_login:
        missing = [
            name
            for name, val in (
                ("DOAL_EMAIL", cfg.email),
                ("DOAL_PASSWORD", cfg.password),
                ("DOAL_TOTP_SECRET", cfg.totp_secret),
            )
            if not val
        ]
        raise SessionExpiredError(
            f"missing/empty: {', '.join(missing)} (looked in {Path('.env').resolve()}; "
            "format KEY=value, no spaces around '=')"
        )
    with _display(cfg), sync_playwright() as pw:
        browser = pw.chromium.launch(headless=cfg.headless)
        try:
            ctx = browser.new_context()
            ctx.set_default_timeout(cfg.nav_timeout_ms)
            page = ctx.new_page()
            try:
                auto_login(cfg, page)
                if _on_login_page(page):
                    _dump_debug(cfg, page, "login_test_failed")
                    raise SessionExpiredError(f"login failed, still on {page.url}")
                return page.url
            finally:
                if not cfg.headless:  # let the user inspect the window
                    input("Browser left open - press Enter here to close it... ")
        finally:
            browser.close()


def check_session(cfg: Settings) -> bool:
    try:
        with _context(cfg) as ctx:
            _open_audit_page(cfg, ctx)
            if not cfg.headless:
                input("Audit page open - press Enter to close the browser... ")
        return True
    except SessionExpiredError:
        return False


_CLICK_ATTEMPTS = 4


def iter_pages(cfg: Settings) -> Iterator[dict]:
    """Yield the GraphQL payload of each audit page (newest first) until the last page."""
    with _context(cfg) as ctx:
        feed = _attach_feed(ctx)
        page = _open_audit_page(cfg, ctx)
        if not _wait_feed(page, feed, 1, cfg.nav_timeout_ms):
            where = _dump_debug(cfg, page, "audit_no_graphql_response")
            raise RuntimeError(f"no valid GetAuditActions response; see {where}")
        for _ in range(cfg.max_pages):
            payload = feed[-1]
            pagination = payload["data"]["GetAuditActions"]["meta"]["pagination"]
            log.info("page_fetched", page=pagination["page"], pages=pagination["pages"])
            yield payload
            if pagination["page"] >= pagination["pages"]:
                return
            seen = len(feed)
            for attempt in range(1, _CLICK_ATTEMPTS + 1):
                time.sleep(cfg.page_delay_s * attempt)  # back off on retries
                page.locator(cfg.next_button_selector).first.click()
                if _wait_feed(page, feed, seen + 1, 15_000):
                    break
                log.warning("next_page_retry", attempt=attempt)
            else:
                where = _dump_debug(cfg, page, "audit_next_page_failed")
                raise RuntimeError(f"next page never loaded after retries; see {where}")
        log.warning("max_pages_reached", max_pages=cfg.max_pages)
