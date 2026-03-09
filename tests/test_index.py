import pytest
from index import (
    get_linux_db_path,
    get_mnt_dbs_dir,
    get_mnt_db_paths,
    safe_name,
    db_exists,
    db_last_updated,
    build_updatedb_cmd,
)


def test_get_linux_db_path():
    assert get_linux_db_path("/some/ext/dir") == "/some/ext/dir/linux.db"


def test_get_mnt_dbs_dir():
    assert get_mnt_dbs_dir("/some/ext/dir") == "/some/ext/dir/dbs"


def test_get_mnt_db_paths_empty_when_no_dbs(tmp_path):
    dbs_dir = tmp_path / "dbs"
    dbs_dir.mkdir()
    result = get_mnt_db_paths(str(tmp_path))
    assert result == []


def test_get_mnt_db_paths_finds_db_files(tmp_path):
    dbs_dir = tmp_path / "dbs"
    dbs_dir.mkdir()
    (dbs_dir / "mnt_C_.db").write_bytes(b"fake")
    (dbs_dir / "mnt_D_.db").write_bytes(b"fake")
    result = get_mnt_db_paths(str(tmp_path))
    assert len(result) == 2


def test_safe_name_strips_colon():
    assert safe_name("/mnt/C:") == "C_"


def test_safe_name_strips_space():
    assert safe_name("/mnt/my drive") == "my_drive"


def test_db_exists_false_when_missing():
    assert db_exists("/nonexistent/path/linux.db") is False


def test_db_exists_true_when_present(tmp_path):
    db = tmp_path / "linux.db"
    db.write_bytes(b"fake")
    assert db_exists(str(db)) is True


def test_db_last_updated_none_when_missing():
    assert db_last_updated("/nonexistent/linux.db") is None


def test_db_last_updated_returns_timestamp(tmp_path):
    db = tmp_path / "linux.db"
    db.write_bytes(b"fake")
    ts = db_last_updated(str(db))
    assert ts is not None
    assert isinstance(ts, float)


def test_build_updatedb_cmd():
    cmd = build_updatedb_cmd(db_path="/tmp/linux.db", root_path="/home/user")
    assert cmd == ["updatedb", "-l", "0", "-o", "/tmp/linux.db", "-U", "/home/user"]
