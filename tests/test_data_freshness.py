import sys
import os
import tempfile
from datetime import datetime, timedelta

sys.path.append(os.path.abspath('src'))

from fidelity_scraper import is_data_stale, mark_fetched, refresh_if_stale

NOW = datetime(2026, 9, 27, 18, 0)


def _touch(path, when):
    with open(path, 'w') as f:
        f.write("x")
    ts = when.timestamp()
    os.utime(path, (ts, ts))


def test_stale_when_nothing_fetched():
    with tempfile.TemporaryDirectory() as d:
        assert is_data_stale(now=NOW, data_dir=d)


def test_fresh_after_fetch_today():
    with tempfile.TemporaryDirectory() as d:
        mark_fetched(now=NOW.replace(hour=8), data_dir=d)
        assert not is_data_stale(now=NOW, data_dir=d)


def test_stale_when_last_fetch_was_yesterday():
    with tempfile.TemporaryDirectory() as d:
        mark_fetched(now=NOW - timedelta(days=1), data_dir=d)
        assert is_data_stale(now=NOW, data_dir=d)


def test_falls_back_to_newest_export_file_without_marker():
    with tempfile.TemporaryDirectory() as d:
        _touch(os.path.join(d, "Accounts_History (a).csv"), NOW - timedelta(days=3))
        _touch(os.path.join(d, "Accounts_History (b).csv"), NOW.replace(hour=7))
        assert not is_data_stale(now=NOW, data_dir=d)


def test_refresh_runs_fetch_only_when_stale():
    calls = []
    with tempfile.TemporaryDirectory() as d:
        assert refresh_if_stale(fetch=lambda: calls.append(1), now=NOW, data_dir=d)
        mark_fetched(now=NOW, data_dir=d)
        assert not refresh_if_stale(fetch=lambda: calls.append(1), now=NOW, data_dir=d)
    assert calls == [1]


def test_refresh_survives_fetch_failure():
    def boom():
        raise RuntimeError("login timed out")
    with tempfile.TemporaryDirectory() as d:
        assert not refresh_if_stale(fetch=boom, now=NOW, data_dir=d)


def test_refresh_survives_ctrl_c():
    def interrupted():
        raise KeyboardInterrupt
    with tempfile.TemporaryDirectory() as d:
        assert not refresh_if_stale(fetch=interrupted, now=NOW, data_dir=d)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"{name} passed")
