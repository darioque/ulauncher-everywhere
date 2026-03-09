from __future__ import annotations
import subprocess
from shutil import which

MNT_DB_FILENAME = "mnt.db"


def build_plocate_cmd(
    tokens: list[str],
    db_path: str | None,
    limit: int,
) -> list[str] | None:
    """Build the plocate command list. Returns None if tokens is empty."""
    if not tokens:
        return None
    cmd = ["plocate", "-i", "-l", str(limit)]
    if db_path:
        cmd += ["-d", db_path]
    cmd += tokens
    return cmd


def search_plocate(
    tokens: list[str],
    db_path: str | None,
    limit: int,
) -> list[str]:
    """Run plocate and return matching paths. Returns [] on any error."""
    cmd = build_plocate_cmd(tokens, db_path, limit)
    if cmd is None:
        return []
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        return result.stdout.splitlines()
    except Exception:
        return []


def plocate_available() -> bool:
    return which("plocate") is not None


def updatedb_available() -> bool:
    return which("updatedb") is not None
