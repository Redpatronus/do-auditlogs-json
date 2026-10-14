from playwright.sync_api import TimeoutError as PlaywrightTimeout

from do_audit_scraper import browser


class FakePage:
    url = "https://cloud.digitalocean.com/login"

    def __init__(self, idle_raises: bool = False) -> None:
        self.idle_raises = idle_raises
        self.calls: list[tuple] = []

    def goto(self, url: str, wait_until: str) -> None:
        self.calls.append(("goto", url, wait_until))

    def wait_for_load_state(self, state: str, timeout: int) -> None:
        self.calls.append(("wait", state, timeout))
        if self.idle_raises:
            raise PlaywrightTimeout("network never idle")


def test_goto_waits_for_domcontentloaded_not_networkidle():
    page = FakePage()
    browser._goto(page, "https://example.test/login")
    assert page.calls[0] == ("goto", "https://example.test/login", "domcontentloaded")


def test_goto_survives_page_that_never_gets_idle():
    page = FakePage(idle_raises=True)
    browser._goto(page, "https://example.test/login")  # must not raise
    assert page.calls[-1][:2] == ("wait", "networkidle")


def test_settle_uses_bounded_timeout():
    page = FakePage()
    browser._settle(page)
    assert page.calls == [("wait", "networkidle", 15_000)]
