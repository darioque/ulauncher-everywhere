import pytest
from search import build_plocate_cmd, search_plocate, MNT_DB_FILENAME


def test_build_cmd_single_term():
    cmd = build_plocate_cmd(["foo"], db_path=None, limit=10)
    assert cmd == ["plocate", "-i", "-l", "10", "foo"]


def test_build_cmd_multi_term():
    cmd = build_plocate_cmd(["foo", "bar"], db_path=None, limit=5)
    assert cmd == ["plocate", "-i", "-l", "5", "foo", "bar"]


def test_build_cmd_custom_db():
    cmd = build_plocate_cmd(["foo"], db_path="/tmp/mnt.db", limit=10)
    assert cmd == ["plocate", "-i", "-l", "10", "-d", "/tmp/mnt.db", "foo"]


def test_build_cmd_empty_tokens_returns_none():
    assert build_plocate_cmd([], db_path=None, limit=10) is None


def test_mnt_db_filename_constant():
    assert MNT_DB_FILENAME == "mnt.db"
