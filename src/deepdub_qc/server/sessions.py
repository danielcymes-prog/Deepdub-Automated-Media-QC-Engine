"""GUI session tracking: best-effort operator coordination, not security.

Why: the service is designed for <=2 operators (ADR-014); the cap keeps it
honest about its envelope. The perimeter is the host (loopback bind + RDP
login); this tracker only prevents a third browser from silently degrading
the two operators' experience.

Inputs: session ids from the qc_session cookie. Outputs: admit/deny.
Side effects: an in-memory table (deliberately not persisted; a restart
clears slots, which is the desired behavior).
"""

from __future__ import annotations

import secrets
import threading
import time


class SessionTracker:
    """Fixed-capacity session table with idle TTL (spec section 7)."""

    def __init__(self, max_sessions: int, ttl_minutes: int) -> None:
        self._max = max_sessions
        self._ttl_seconds = ttl_minutes * 60
        self._last_seen: dict[str, float] = {}
        self._lock = threading.Lock()

    def _expire(self, now: float) -> None:
        cutoff = now - self._ttl_seconds
        for session_id, seen in list(self._last_seen.items()):
            if seen < cutoff:
                del self._last_seen[session_id]

    def touch(self, session_id: str | None) -> str | None:
        """Admit or refresh a session; None means the cap is reached (E12).

        Existing sessions are always refreshed (never evicted for newcomers).
        """
        now = time.monotonic()
        with self._lock:
            self._expire(now)
            if session_id is not None and session_id in self._last_seen:
                self._last_seen[session_id] = now
                return session_id
            if len(self._last_seen) >= self._max:
                return None
            new_id = session_id or secrets.token_urlsafe(16)
            self._last_seen[new_id] = now
            return new_id

    def active_count(self) -> int:
        with self._lock:
            self._expire(time.monotonic())
            return len(self._last_seen)
