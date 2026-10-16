import structlog
from filelock import FileLock

from .browser import iter_pages
from .config import Settings
from .models import AuditEvent
from .parser import parse_events
from .storage import Store

log = structlog.get_logger()


def run_scrape(cfg: Settings) -> int:
    """Incremental scrape: stop at the first page containing only already-seen events."""
    cfg.lock_path.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(cfg.lock_path, timeout=1):  # prevents overlapping timer runs
        store = Store(cfg.output_path, cfg.state_path, cfg.seen_cache_size)
        collected: list[AuditEvent] = []
        for payload in iter_pages(cfg):
            events = parse_events(payload)
            if not events:
                log.warning("no_events_parsed_on_page")
                break
            new = [e for e in events if not store.is_seen(e.event_id)]
            collected.extend(new)
            if not new:
                break
        # Write only after a complete run: on failure nothing is stored, so the next run
        # retries from the newest page (a partial write would leave an unrecoverable gap).
        # Pages are newest-first; write oldest-first so the file stays chronological.
        written = store.append(reversed(collected))
        cfg.heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
        cfg.heartbeat_path.touch()  # only reached when the whole run succeeded
        log.info("scrape_done", new_events=written)
        return written
