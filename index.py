from __future__ import annotations
import os
import glob
import subprocess
import threading
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

LINUX_DB_FILENAME = "linux.db"
MNT_DBS_DIR = "dbs"

# Two independent indexing state flags
_indexing_linux = False
_indexing_mnt = False
_lock = threading.Lock()


# ── path helpers ──────────────────────────────────────────────────────────────

def get_linux_db_path(extension_dir: str) -> str:
    return os.path.join(extension_dir, LINUX_DB_FILENAME)


def get_mnt_dbs_dir(extension_dir: str) -> str:
    return os.path.join(extension_dir, MNT_DBS_DIR)


def get_mnt_db_paths(extension_dir: str) -> list[str]:
    """Return list of all per-drive DB files."""
    pattern = os.path.join(get_mnt_dbs_dir(extension_dir), "mnt_*.db")
    return glob.glob(pattern)


def safe_name(path: str) -> str:
    """Convert a path like /mnt/C: into a safe filename token like C_."""
    return os.path.basename(path).replace(":", "_").replace(" ", "_")


# ── existence / timestamps ────────────────────────────────────────────────────

def db_exists(db_path: str) -> bool:
    return os.path.isfile(db_path)


def db_last_updated(db_path: str) -> float | None:
    try:
        return os.path.getmtime(db_path)
    except OSError:
        return None


def db_last_updated_str(db_path: str) -> str:
    ts = db_last_updated(db_path)
    if ts is None:
        return "never"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def linux_db_exists(extension_dir: str) -> bool:
    return db_exists(get_linux_db_path(extension_dir))


def mnt_dbs_exist(extension_dir: str) -> bool:
    return len(get_mnt_db_paths(extension_dir)) > 0


# ── updatedb command ──────────────────────────────────────────────────────────

def build_updatedb_cmd(db_path: str, root_path: str) -> list[str]:
    return ["updatedb", "-l", "0", "-o", db_path, "-U", root_path]


# ── state ─────────────────────────────────────────────────────────────────────

def is_indexing_linux() -> bool:
    with _lock:
        return _indexing_linux


def is_indexing_mnt() -> bool:
    with _lock:
        return _indexing_mnt


# ── index builders ────────────────────────────────────────────────────────────

def start_linux_index(extension_dir: str, linux_path: str, on_complete=None) -> bool:
    """Index linux_path into linux.db. Returns False if already running."""
    global _indexing_linux
    with _lock:
        if _indexing_linux:
            return False
        _indexing_linux = True

    def _run():
        global _indexing_linux
        success = False
        try:
            db_path = get_linux_db_path(extension_dir)
            expanded = str(Path(linux_path).expanduser())
            cmd = build_updatedb_cmd(db_path, expanded)
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            success = result.returncode == 0
            if not success:
                logger.error(f"updatedb (linux) failed: {result.stderr}")
        except Exception as e:
            logger.error(f"updatedb (linux) exception: {e}")
        finally:
            with _lock:
                _indexing_linux = False
            if on_complete:
                on_complete(success)

    threading.Thread(target=_run, daemon=True).start()
    return True


def start_mnt_index(extension_dir: str, mnt_path: str, on_complete=None) -> bool:
    """
    Index each subdirectory of mnt_path into its own DB file.
    Handles colon-named directories (C:, D:, etc.) by indexing each separately.
    Returns False if already running.
    """
    global _indexing_mnt
    with _lock:
        if _indexing_mnt:
            return False
        _indexing_mnt = True

    def _run():
        global _indexing_mnt
        success = True
        try:
            dbs_dir = get_mnt_dbs_dir(extension_dir)
            os.makedirs(dbs_dir, exist_ok=True)

            try:
                subdirs = [
                    os.path.join(mnt_path, d)
                    for d in os.listdir(mnt_path)
                    if os.path.isdir(os.path.join(mnt_path, d))
                ]
            except OSError as e:
                logger.error(f"Cannot list {mnt_path}: {e}")
                success = False
                return

            for subdir in subdirs:
                db_path = os.path.join(dbs_dir, f"mnt_{safe_name(subdir)}.db")
                cmd = build_updatedb_cmd(db_path, subdir)
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
                if result.returncode != 0:
                    logger.warning(f"updatedb failed for {subdir}: {result.stderr}")
                    success = False
        except Exception as e:
            logger.error(f"mnt index exception: {e}")
            success = False
        finally:
            with _lock:
                _indexing_mnt = False
            if on_complete:
                on_complete(success)

    threading.Thread(target=_run, daemon=True).start()
    return True


# ── auto-update via systemd user timers ───────────────────────────────────────

def _systemd_user_dir() -> str:
    return os.path.join(Path.home(), ".config", "systemd", "user")


def timers_enabled() -> bool:
    """True if both everywhere timers are installed."""
    d = _systemd_user_dir()
    return (
        os.path.isfile(os.path.join(d, "everywhere-linux.timer")) and
        os.path.isfile(os.path.join(d, "everywhere-mnt.timer"))
    )


def setup_auto_update(extension_dir: str, linux_path: str, mnt_path: str) -> bool:
    """
    Write systemd user service+timer units and enable them.
    linux.db: every hour. mnt drives: daily at 03:00.
    """
    try:
        unit_dir = _systemd_user_dir()
        os.makedirs(unit_dir, exist_ok=True)

        expanded_linux = str(Path(linux_path).expanduser())
        dbs_dir = get_mnt_dbs_dir(extension_dir)
        linux_db = get_linux_db_path(extension_dir)

        # Generate the mnt update shell script (handles colon-named dirs like C:)
        mnt_script = os.path.join(extension_dir, "update-mnt-index.sh")
        with open(mnt_script, "w") as f:
            f.write("#!/bin/bash\n")
            f.write(f'MNT_PATH="{mnt_path}"\n')
            f.write(f'DBS_DIR="{dbs_dir}"\n')
            f.write('mkdir -p "$DBS_DIR"\n')
            f.write('for drive in "$MNT_PATH"/*/; do\n')
            f.write('  [ -d "$drive" ] || continue\n')
            f.write('  safe=$(basename "$drive" | tr ":" "_" | tr " " "_")\n')
            f.write('  updatedb -l 0 -o "$DBS_DIR/mnt_${safe}.db" -U "$drive"\n')
            f.write('done\n')
        os.chmod(mnt_script, 0o755)

        _write_unit(unit_dir, "everywhere-linux.service",
            "[Unit]\nDescription=Everywhere: update home index\n\n"
            "[Service]\nType=oneshot\n"
            f"ExecStart=updatedb -l 0 -o {linux_db} -U {expanded_linux}\n")

        _write_unit(unit_dir, "everywhere-linux.timer",
            "[Unit]\nDescription=Everywhere: update home index hourly\n\n"
            "[Timer]\nOnBootSec=2min\nOnUnitActiveSec=1h\n\n"
            "[Install]\nWantedBy=timers.target\n")

        _write_unit(unit_dir, "everywhere-mnt.service",
            "[Unit]\nDescription=Everywhere: update drives index\n\n"
            "[Service]\nType=oneshot\n"
            f"ExecStart={mnt_script}\n")

        _write_unit(unit_dir, "everywhere-mnt.timer",
            "[Unit]\nDescription=Everywhere: update drives index daily\n\n"
            "[Timer]\nOnCalendar=03:00\nPersistent=true\n\n"
            "[Install]\nWantedBy=timers.target\n")

        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "--user", "enable", "--now",
                        "everywhere-linux.timer", "everywhere-mnt.timer"], check=True)
        return True
    except Exception as e:
        logger.error(f"setup_auto_update failed: {e}")
        return False


def _write_unit(unit_dir: str, filename: str, content: str) -> None:
    with open(os.path.join(unit_dir, filename), "w") as f:
        f.write(content)
