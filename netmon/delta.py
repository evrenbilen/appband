"""Compute deltas from cumulative counters, with discontinuity handling."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class _Anchor:
    value: int
    ts: int
    misses: int = 0


class DeltaTracker:
    """Per-key cumulative-counter tracker.

    update(key, value, now) returns:
      - delta (int) if a sane non-negative delta from the previous anchor
      - None if first observation, or if the new value indicates a
        discontinuity (counter reset, or delta exceeding max_delta_per_sec)
    """

    def __init__(self, max_delta_per_sec: int):
        self._max_dps = max_delta_per_sec
        self._state: dict[str, _Anchor] = {}

    def update(self, key: str, value: int, now: int) -> int | None:
        prev = self._state.get(key)
        if prev is None or value < prev.value:
            self._state[key] = _Anchor(value=value, ts=now)
            return None
        elapsed = max(now - prev.ts, 1)
        delta = value - prev.value
        if delta // elapsed > self._max_dps:
            # discontinuity — reset anchor
            self._state[key] = _Anchor(value=value, ts=now)
            return None
        self._state[key] = _Anchor(value=value, ts=now)
        return delta

    def evict_missing(self, present_keys: set[str], max_misses: int) -> None:
        """Increment a miss counter for keys not in present_keys; evict at max."""
        for key in list(self._state.keys()):
            if key in present_keys:
                self._state[key].misses = 0
            else:
                self._state[key].misses += 1
                if self._state[key].misses >= max_misses:
                    del self._state[key]
