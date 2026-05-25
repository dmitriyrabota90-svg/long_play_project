from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit


def mask_database_url(database_url: str) -> str:
    parts = urlsplit(database_url)
    if not parts.password:
        return database_url

    username = parts.username or ""
    hostname = parts.hostname or ""
    port = f":{parts.port}" if parts.port is not None else ""
    credentials = f"{username}:***@" if username else "***@"
    netloc = f"{credentials}{hostname}{port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
