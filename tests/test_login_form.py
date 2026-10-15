from do_audit_scraper import browser
from do_audit_scraper.config import Settings


class FakeLocator:
    def __init__(self, page: "FakePage", kind: str) -> None:
        self.page, self.kind = page, kind

    @property
    def first(self) -> "FakeLocator":
        return self

    def count(self) -> int:
        return int(self.page.present(self.kind))

    def is_visible(self) -> bool:
        return self.page.present(self.kind)

    def click(self, timeout: int) -> None:
        self.page.clicked_switch = True
        self.page.state = "email"


class FakePage:
    """state: 'email' = e-mail form, 'remembered' = password-only form with a switch link."""

    def __init__(self, state: str, has_switch_link: bool = True) -> None:
        self.state = state
        self.has_switch_link = has_switch_link
        self.clicked_switch = False

    def present(self, kind: str) -> bool:
        if kind == "email":
            return self.state == "email"
        if kind == "switch":
            return self.state == "remembered" and self.has_switch_link
        return False

    def wait_for_selector(self, selector: str, **kwargs) -> None:
        pass

    def locator(self, selector: str) -> FakeLocator:
        return FakeLocator(self, "email")

    def get_by_text(self, pattern) -> FakeLocator:  # noqa: ANN001
        assert pattern.search("Login with a different account")
        return FakeLocator(self, "switch")


def _cfg() -> Settings:
    return Settings(_env_file=None)


def test_email_form_is_used_directly():
    page = FakePage("email")
    assert browser._ensure_email_form(_cfg(), page) is True
    assert not page.clicked_switch


def test_remembered_user_switches_to_email_form():
    page = FakePage("remembered")
    assert browser._ensure_email_form(_cfg(), page) is True
    assert page.clicked_switch


def test_remembered_user_without_switch_link_falls_back_to_password_only():
    page = FakePage("remembered", has_switch_link=False)
    assert browser._ensure_email_form(_cfg(), page) is False
    assert not page.clicked_switch
