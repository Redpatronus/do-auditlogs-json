import logging
import sys

import structlog
import typer

from .browser import SessionExpiredError, check_session, interactive_login, login_test
from .config import Settings
from .scraper import run_scrape

app = typer.Typer(help="DigitalOcean audit-log scraper", no_args_is_help=True)

EXIT_SESSION_EXPIRED = 2


def _setup_logging(cfg: Settings) -> None:
    level = getattr(logging, cfg.log_level.upper(), logging.INFO)
    renderer = (
        structlog.processors.JSONRenderer() if cfg.log_json else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
    )


@app.command()
def login() -> None:
    """Interactive login in a visible browser; saves the session (run on a desktop)."""
    cfg = Settings()
    _setup_logging(cfg)
    interactive_login(cfg)


@app.command()
def check(headed: bool = typer.Option(False, "--headed", help="Show the browser")) -> None:
    """Verify that the stored session is still valid."""
    cfg = Settings()
    if headed:
        cfg.headless = False
    _setup_logging(cfg)
    ok = check_session(cfg)
    typer.echo("session OK" if ok else "session EXPIRED")
    raise typer.Exit(0 if ok else EXIT_SESSION_EXPIRED)


@app.command("login-test")
def login_test_cmd(
    headed: bool = typer.Option(False, "--headed", help="Show the browser window"),
) -> None:
    """Only test the login (password + TOTP) with a fresh session; no scraping."""
    cfg = Settings()
    if headed:
        cfg.headless = False
    _setup_logging(cfg)
    try:
        url = login_test(cfg)
    except SessionExpiredError as exc:
        typer.echo(f"LOGIN FAILED: {exc}")
        raise typer.Exit(EXIT_SESSION_EXPIRED) from exc
    typer.echo(f"LOGIN OK -> {url}")


@app.command()
def scrape(headed: bool = typer.Option(False, "--headed", help="Show the browser")) -> None:
    """Fetch new audit events and append them to the NDJSON file."""
    cfg = Settings()
    if headed:
        cfg.headless = False
    _setup_logging(cfg)
    try:
        run_scrape(cfg)
    except SessionExpiredError as exc:
        structlog.get_logger().error("session_expired", detail=str(exc))
        raise typer.Exit(EXIT_SESSION_EXPIRED) from exc


if __name__ == "__main__":
    app()
