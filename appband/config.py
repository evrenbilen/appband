"""appband config: dataclass with defaults + optional JSON override."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


def _default_db_path() -> Path:
    return Path.home() / "Library" / "Application Support" / "appband" / "appband.db"


def _default_log_dir() -> Path:
    return Path.home() / "Library" / "Logs" / "appband"


@dataclass
class Config:
    bind_host: str = "127.0.0.1"
    port: int = 8765
    interface_poll_sec: int = 5
    process_poll_sec: int = 10
    connection_poll_sec: int = 30
    session_poll_sec: int = 2
    retention_days: int = 30
    dns_cache_retention_days: int = 90
    dns_lookup_timeout_sec: float = 2.0
    dns_concurrency: int = 5
    discontinuity_threshold_bps: int = 100 * 1024 * 1024  # 100 MB/sec
    process_eviction_misses: int = 3
    log_level: str = "INFO"
    db_path: Path = field(default_factory=_default_db_path)
    log_dir: Path = field(default_factory=_default_log_dir)


def load_config(override_path: Path | None = None) -> Config:
    """Load defaults, optionally merging keys from a JSON file."""
    cfg = Config()
    if override_path is None or not override_path.exists():
        return cfg
    data = json.loads(override_path.read_text())
    for key, value in data.items():
        if hasattr(cfg, key):
            # Coerce path-typed fields
            current = getattr(cfg, key)
            if isinstance(current, Path):
                value = Path(value).expanduser()
            setattr(cfg, key, value)
    return cfg
