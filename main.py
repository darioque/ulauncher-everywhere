import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import gi
gi.require_version("Gio", "2.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gio, Gtk  # type: ignore

from ulauncher.api.client.Extension import Extension
from ulauncher.api.client.EventListener import EventListener
from ulauncher.api.shared.event import KeywordQueryEvent, ItemEnterEvent
from ulauncher.api.shared.item.ExtensionResultItem import ExtensionResultItem
from ulauncher.api.shared.action.RenderResultListAction import RenderResultListAction
from ulauncher.api.shared.action.RunScriptAction import RunScriptAction
from ulauncher.api.shared.action.ExtensionCustomAction import ExtensionCustomAction

from search import search_plocate, plocate_available, updatedb_available
import index as idx

logger = logging.getLogger(__name__)

EXTENSION_DIR = os.path.dirname(os.path.abspath(__file__))

_icon_theme = None


def _get_icon_theme():
    global _icon_theme
    if _icon_theme is None:
        _icon_theme = Gtk.IconTheme.get_default()
    return _icon_theme


def _system_icon(path: str, size: int = 32) -> str:
    try:
        f = Gio.File.new_for_path(path)
        info = f.query_info("standard::icon", Gio.FileQueryInfoFlags.NONE, None)
        icon = info.get_icon()
        names = icon.get_names() if hasattr(icon, "get_names") else [icon.to_string()]
        theme = _get_icon_theme()
        for name in names:
            icon_info = theme.lookup_icon(name, size, 0)
            if icon_info:
                filename = icon_info.get_filename()
                if filename:
                    return filename
    except Exception as e:
        logger.debug(f"system icon lookup failed for {path}: {e}")
    return ""


def _default_icon(path: str) -> str:
    if Path(path).is_dir():
        return "images/folder.svg"
    return "images/file.svg"


def make_result_item(path: str, query_icons: bool) -> ExtensionResultItem:
    ppath = Path(path)
    icon = _system_icon(path) if query_icons else ""
    if not icon:
        icon = _default_icon(path)
    return ExtensionResultItem(
        icon=icon,
        name=ppath.name,
        description=str(ppath.parent),
        on_enter=RunScriptAction(f'xdg-open "{path}"', []),
        on_alt_enter=RunScriptAction(f'xdg-open "{str(ppath.parent)}"', []),
    )


def make_error_item(message: str) -> ExtensionResultItem:
    return ExtensionResultItem(icon="images/error.svg", name="Error", description=message)


def make_action_item(label: str, description: str, data: dict) -> ExtensionResultItem:
    return ExtensionResultItem(
        icon="images/index.svg",
        name=label,
        description=description,
        on_enter=ExtensionCustomAction(data, keep_app_open=True),
    )


def _search_dbs(tokens: list[str], db_paths: list[str], limit: int) -> list[str]:
    """Query multiple plocate DBs in parallel and merge results."""
    if not db_paths:
        return []
    results = []
    seen: set[str] = set()
    with ThreadPoolExecutor(max_workers=max(len(db_paths), 1)) as ex:
        futures = {ex.submit(search_plocate, tokens, db, limit): db for db in db_paths}
        for future in as_completed(futures):
            for r in future.result():
                if r not in seen:
                    seen.add(r)
                    results.append(r)
    return results[:limit]


# ── keyword handlers ──────────────────────────────────────────────────────────

def handle_system_search(pattern: str, num_results: int, query_icons: bool, linux_path: str) -> RenderResultListAction:
    """Search everywhere on Linux: system DB (for /etc, /usr, /opt…) + linux.db (for home)."""
    if not plocate_available():
        return RenderResultListAction([make_error_item("plocate is not installed")])

    tokens = pattern.strip().split()
    if not tokens:
        return RenderResultListAction([])

    # Always query the system DB (covers /etc, /usr, /opt, etc.)
    seen: set[str] = set()
    results: list[str] = []
    for r in search_plocate(tokens, db_path=None, limit=num_results):
        if r not in seen:
            seen.add(r)
            results.append(r)

    # Also query the home DB if available
    if idx.linux_db_exists(EXTENSION_DIR):
        for r in search_plocate(tokens, db_path=idx.get_linux_db_path(EXTENSION_DIR), limit=num_results):
            if r not in seen:
                seen.add(r)
                results.append(r)
    elif not idx.is_indexing_linux():
        items = [make_result_item(r, query_icons) for r in results[:num_results]]
        items.append(make_action_item(
            "Build home index",
            f"Home files not indexed yet — click to index {linux_path}",
            {"action": "build_linux"},
        ))
        return RenderResultListAction(items)

    return RenderResultListAction([make_result_item(r, query_icons) for r in results[:num_results]])


def handle_all_search(pattern: str, num_results: int, query_icons: bool, mnt_path: str) -> RenderResultListAction:
    """Search only /mnt/* drives."""
    if not plocate_available():
        return RenderResultListAction([make_error_item("plocate is not installed")])

    tokens = pattern.strip().split()
    if not tokens:
        return RenderResultListAction([])

    mnt_dbs = idx.get_mnt_db_paths(EXTENSION_DIR)

    if idx.is_indexing_mnt():
        return RenderResultListAction([make_action_item(
            "Indexing drives...",
            "Drive index build in progress",
            {"action": "noop"},
        )])

    if not mnt_dbs:
        return RenderResultListAction([make_action_item(
            "Build drives index",
            f"No drives index yet — click to index {mnt_path}",
            {"action": "build_mnt"},
        )])

    results = _search_dbs(tokens, mnt_dbs, num_results)
    return RenderResultListAction([make_result_item(r, query_icons) for r in results])


def handle_index_management(linux_path: str, mnt_path: str) -> RenderResultListAction:
    if not updatedb_available():
        return RenderResultListAction([make_error_item("updatedb is not installed")])

    items = []
    linux_db = idx.get_linux_db_path(EXTENSION_DIR)
    mnt_dbs = idx.get_mnt_db_paths(EXTENSION_DIR)

    # Home index
    if idx.is_indexing_linux():
        items.append(ExtensionResultItem(icon="images/index.svg", name="Indexing home...", description=f"Building index for {linux_path}"))
    elif idx.linux_db_exists(EXTENSION_DIR):
        items.append(ExtensionResultItem(icon="images/index.svg", name=f"Home OK — {idx.db_last_updated_str(linux_db)}", description=f"Covers: {linux_path}"))
        items.append(make_action_item("Rebuild home index", f"Re-index {linux_path}", {"action": "build_linux"}))
    else:
        items.append(make_action_item("Build home index", f"Click to index {linux_path}", {"action": "build_linux"}))

    # Drives index
    if idx.is_indexing_mnt():
        items.append(ExtensionResultItem(icon="images/index.svg", name="Indexing drives...", description=f"Building per-drive indexes for {mnt_path}"))
    elif mnt_dbs:
        from datetime import datetime
        oldest = min((idx.db_last_updated(p) or 0) for p in mnt_dbs)
        oldest_str = datetime.fromtimestamp(oldest).strftime("%Y-%m-%d %H:%M") if oldest else "unknown"
        items.append(ExtensionResultItem(icon="images/index.svg", name=f"Drives OK — {oldest_str} ({len(mnt_dbs)} drives)", description=f"Covers: {mnt_path}"))
        items.append(make_action_item("Rebuild drives index", f"Re-index all drives in {mnt_path}", {"action": "build_mnt"}))
    else:
        items.append(make_action_item("Build drives index", f"Click to index all drives in {mnt_path}", {"action": "build_mnt"}))

    # Auto-update setup
    if idx.timers_enabled():
        items.append(ExtensionResultItem(
            icon="images/index.svg",
            name="Auto-update: ON (home: hourly, drives: daily at 03:00)",
            description="Systemd user timers are active",
        ))
    else:
        items.append(make_action_item(
            "Enable auto-update",
            "Home index: every hour  |  Drives index: daily at 03:00",
            {"action": "setup_timers"},
        ))

    return RenderResultListAction(items)


# ── extension classes ─────────────────────────────────────────────────────────

class EverywhereExtension(Extension):

    def __init__(self):
        super().__init__()
        self.subscribe(KeywordQueryEvent, KeywordQueryEventListener())
        self.subscribe(ItemEnterEvent, ItemEnterEventListener())


class KeywordQueryEventListener(EventListener):

    def on_event(self, event: KeywordQueryEvent, extension: Extension) -> RenderResultListAction:
        keyword     = event.get_keyword()
        pattern     = event.get_argument() or ""
        key_system  = extension.preferences.get("key_system", "f")
        key_all     = extension.preferences.get("key_all", "fa")
        key_index   = extension.preferences.get("key_index", "fi")
        linux_path  = extension.preferences.get("linux_path", "~")
        mnt_path    = extension.preferences.get("mnt_path", "/mnt")
        num_results = int(extension.preferences.get("num_results", 10))
        query_icons = extension.preferences.get("query_icons", "no") == "yes"

        if keyword == key_system:
            return handle_system_search(pattern, num_results, query_icons, linux_path)
        elif keyword == key_all:
            return handle_all_search(pattern, num_results, query_icons, mnt_path)
        elif keyword == key_index:
            return handle_index_management(linux_path, mnt_path)

        return RenderResultListAction([])


class ItemEnterEventListener(EventListener):

    def on_event(self, event, extension: Extension) -> RenderResultListAction:
        data = event.get_data()
        if not isinstance(data, dict):
            return RenderResultListAction([])

        action     = data.get("action")
        linux_path = extension.preferences.get("linux_path", "~")
        mnt_path   = extension.preferences.get("mnt_path", "/mnt")

        if action == "build_linux":
            started = idx.start_linux_index(EXTENSION_DIR, linux_path)
            return RenderResultListAction([ExtensionResultItem(
                icon="images/index.svg",
                name="Indexing home..." if started else "Already indexing home",
                description=f"Indexing {linux_path} — type 'fi' to check progress",
            )])

        if action == "build_mnt":
            started = idx.start_mnt_index(EXTENSION_DIR, mnt_path)
            return RenderResultListAction([ExtensionResultItem(
                icon="images/index.svg",
                name="Indexing drives..." if started else "Already indexing drives",
                description=f"Indexing all drives in {mnt_path} — type 'fi' to check progress",
            )])

        if action == "setup_timers":
            ok = idx.setup_auto_update(EXTENSION_DIR, linux_path, mnt_path)
            msg = "Auto-update enabled!" if ok else "Failed to enable timers — check logs"
            desc = "Home: every hour  |  Drives: daily at 03:00" if ok else "Run ulauncher with -v for details"
            return RenderResultListAction([ExtensionResultItem(
                icon="images/index.svg", name=msg, description=desc,
            )])

        return RenderResultListAction([])


if __name__ == "__main__":
    EverywhereExtension().run()
