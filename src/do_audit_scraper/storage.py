import json
import os
from collections import deque
from collections.abc import Iterable
from pathlib import Path

from .models import AuditEvent


class Store:
    """Append-only NDJSON output plus a bounded dedup state (atomic writes)."""

    def __init__(self, output: Path, state: Path, cache_size: int) -> None:
        self.output, self.state, self.cache_size = output, state, cache_size
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self._seen: deque[str] = deque(self._load(), maxlen=cache_size)
        self._seen_set = set(self._seen)

    def _load(self) -> list[str]:
        if not self.state.exists():
            return []
        return json.loads(self.state.read_text()).get("seen", [])

    def is_seen(self, event_id: str) -> bool:
        return event_id in self._seen_set

    def append(self, events: Iterable[AuditEvent]) -> int:
        """Write only unseen events (oldest first); returns how many were written."""
        fresh = [e for e in events if e.event_id not in self._seen_set]
        if not fresh:
            return 0
        with self.output.open("a", encoding="utf-8") as fh:
            for e in fresh:
                fh.write(e.model_dump_json() + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        for e in fresh:
            if len(self._seen) == self.cache_size:
                self._seen_set.discard(self._seen[0])
            self._seen.append(e.event_id)
            self._seen_set.add(e.event_id)
        self._save()
        return len(fresh)

    def _save(self) -> None:
        tmp = self.state.with_suffix(".tmp")
        tmp.write_text(json.dumps({"seen": list(self._seen)}))
        os.replace(tmp, self.state)
