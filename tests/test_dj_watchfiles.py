from __future__ import annotations

import logging
import tempfile
import time
from pathlib import Path

import pytest
from django.utils import autoreload
from django.utils.autoreload import BaseReloader
from parameterized import parameterized
from watchfiles import Change

from dj_watchfiles.watch import (
    MutableWatcher,
    WatchfilesReloader,
    replaced_run_with_reloader,
)
from tests.compat import SimpleTestCase
from tests.filters import only_added


class MutableWatcherTests(SimpleTestCase):
    def setUp(self):
        self.watchfiles_settings = {}
        self.watcher = MutableWatcher(lambda *args: True, self.watchfiles_settings)
        self.addCleanup(self.watcher.stop)

        temp_dir = self.enterContext(tempfile.TemporaryDirectory())
        self.temp_path = Path(temp_dir)

    def test_set_roots_unchanged(self):
        assert not self.watcher.change_event.is_set()
        self.watcher.set_roots(set())
        assert not self.watcher.change_event.is_set()

    def test_set_roots_changed(self):
        assert not self.watcher.change_event.is_set()
        self.watcher.set_roots({Path("/tmp")})
        assert self.watcher.change_event.is_set()

    def test_stop(self):
        (self.temp_path / "test.txt").touch()
        self.watcher.set_roots({self.temp_path})
        iterator = iter(self.watcher)
        # Flush initial events
        next(iterator)

        self.watcher.stop()

        with pytest.raises(StopIteration):
            next(iterator)

        # Not possible to restart
        with pytest.raises(StopIteration):
            next(iter(self.watcher))

    def test_iter_no_changes(self):
        (self.temp_path / "test.txt").touch()
        self.watcher.set_roots({self.temp_path})
        iterator = iter(self.watcher)
        # flush initial events
        next(iterator)
        time.sleep(0.1)  # 100ms Rust timeout

        changes = next(iterator)

        assert changes == set()

    def test_iter_yields_changes(self):
        (self.temp_path / "test.txt").touch()
        self.watcher.set_roots({self.temp_path})
        iterator = iter(self.watcher)
        # flush initial events
        next(iterator)

        (self.temp_path / "test.txt").touch()
        changes = next(iterator)

        assert isinstance(changes, set)
        assert len(changes) == 1
        _, path = changes.pop()
        assert path == str(self.temp_path.resolve() / "test.txt")

    def test_iter_respects_change_event(self):
        (self.temp_path / "test.txt").touch()
        self.watcher.set_roots({self.temp_path})
        iterator = iter(self.watcher)
        # flush initial events
        next(iterator)

        self.watcher.set_roots(set())
        self.watcher.set_roots({self.temp_path})
        changes = next(iterator)

        assert isinstance(changes, set)
        assert len(changes) == 0


class WatchfilesReloaderTests(SimpleTestCase):
    def setUp(self):
        temp_dir = self.enterContext(tempfile.TemporaryDirectory())
        self.temp_path = Path(temp_dir)
        self.watchfiles_settings = {}
        self.reloader = WatchfilesReloader(self.watchfiles_settings)

    def test_file_filter_watched_file(self):
        test_txt = self.temp_path / "test.txt"
        self.reloader.watched_files_set = {test_txt}

        result = self.reloader.file_filter(Change.modified, str(test_txt))

        assert result is True

    def test_file_filter_unwatched_file(self):
        test_txt = self.temp_path / "test.txt"

        result = self.reloader.file_filter(Change.modified, str(test_txt))

        assert result is False

    def test_file_filter_glob_matched(self):
        self.reloader.watch_dir(self.temp_path, "*.txt")

        result = self.reloader.file_filter(
            Change.modified, str(self.temp_path / "test.txt")
        )

        assert result is True

    def test_file_filter_glob_multiple_globs_unmatched(self):
        self.reloader.watch_dir(self.temp_path, "*.css")
        self.reloader.watch_dir(self.temp_path, "*.html")

        result = self.reloader.file_filter(
            Change.modified, str(self.temp_path / "test.py")
        )

        assert result is False

    def test_file_filter_glob_multiple_dirs_unmatched(self):
        self.reloader.watch_dir(self.temp_path, "*.css")
        temp_dir2 = self.enterContext(tempfile.TemporaryDirectory())
        self.reloader.watch_dir(Path(temp_dir2), "*.html")

        result = self.reloader.file_filter(
            Change.modified, str(self.temp_path / "test.py")
        )

        assert result is False

    def test_file_filter_glob_relative_path_impossible(self):
        temp_dir2 = self.enterContext(tempfile.TemporaryDirectory())

        self.reloader.watch_dir(Path(temp_dir2), "*.txt")

        result = self.reloader.file_filter(
            Change.modified, str(self.temp_path / "test.txt")
        )

        assert result is False

    def test_tick(self):
        test_txt = self.temp_path / "test.txt"
        self.reloader.extra_files = {test_txt}

        iterator = self.reloader.tick()
        result = next(iterator)
        assert result is None

        result = self.reloader.file_filter(Change.modified, str(test_txt))
        assert result is True

    def test_tick_non_existent_directory_watched(self):
        does_not_exist = self.temp_path / "nope"
        self.reloader.watch_dir(does_not_exist, "*.txt")

        iterator = self.reloader.tick()
        result = next(iterator)
        assert result is None


class ReplacedRunWithReloaderTests(SimpleTestCase):
    def test_replaced_run_with_reloader_default_settings(self):
        def mock_main():
            pass

        with self.settings(WATCHFILES={}):
            reloader = autoreload.get_reloader()
            assert isinstance(reloader, WatchfilesReloader)
            assert reloader.watchfiles_settings == {}

    def test_replaced_run_with_reloader_custom_settings(self):
        def mock_filter(*args):
            return True

        custom_settings = {
            "watch_filter": mock_filter,
            "debug": True,
        }

        with self.settings(WATCHFILES=custom_settings):
            reloader = autoreload.get_reloader()
            assert isinstance(reloader, WatchfilesReloader)
            assert reloader.watchfiles_settings["debug"] is True
            assert callable(reloader.watchfiles_settings["watch_filter"])

        @parameterized.expand(
            [
                ("error_level", 0, logging.ERROR),
                ("warning_level", 1, logging.WARNING),
                ("info_level", 2, logging.INFO),
                ("debug_level", 3, logging.DEBUG),
            ]
        )
        def test_replaced_run_with_reloader_verbosity(
            self, name, verbosity, expected_level
        ):
            with self.settings(VERBOSITY=verbosity, WATCHFILES={}):
                reloader = autoreload.get_reloader()
                assert isinstance(reloader, WatchfilesReloader)
                log_level = logging.getLogger("watchfiles").level
                assert log_level == expected_level

    def test_replaced_run_with_reloader_with_watch_filter(self):
        """Test the watch_filter import functionality and debug settings"""

        filter_path = "tests.filters.only_added_factory"
        custom_settings = {"watch_filter": filter_path, "debug": True}

        def mock_run_with_reloader(*args, **kwargs):
            return None

        with self.settings(WATCHFILES=custom_settings):
            original_run = autoreload.run_with_reloader
            autoreload.run_with_reloader = mock_run_with_reloader
            try:
                # call the function with different verbosity levels
                replaced_run_with_reloader(lambda: None, verbosity=1)

                watchfiles_logger = logging.getLogger("watchfiles")
                self.assertEqual(watchfiles_logger.level, logging.DEBUG)

                reloader = autoreload.get_reloader()
                self.assertIsInstance(reloader, WatchfilesReloader)
                self.assertTrue(callable(reloader.watchfiles_settings["watch_filter"]))
                self.assertTrue(reloader.watchfiles_settings["debug"])

                filter_func = reloader.watchfiles_settings["watch_filter"]
                self.assertTrue(filter_func(Change.added, "test.py"))
                self.assertFalse(filter_func(Change.modified, "test.py"))

            finally:
                # restore original run_with_reloader
                autoreload.run_with_reloader = original_run

    def test_replaced_run_with_reloader_no_debug(self):
        """Test the log level calculation without debug mode"""

        def mock_run_with_reloader(*args, **kwargs):
            return None

        with self.settings(WATCHFILES={}):
            original_run = autoreload.run_with_reloader
            autoreload.run_with_reloader = mock_run_with_reloader
            try:
                # test with different verbosity levels
                for verbosity, expected_level in [
                    (0, logging.ERROR),  # 40 - 10 * 0 = 40 (ERROR)
                    (1, logging.WARNING),  # 40 - 10 * 1 = 30 (WARNING)
                    (2, logging.INFO),  # 40 - 10 * 2 = 20 (INFO)
                    (3, logging.DEBUG),  # 40 - 10 * 3 = 10 (DEBUG)
                ]:
                    replaced_run_with_reloader(lambda: None, verbosity=verbosity)
                    watchfiles_logger = logging.getLogger("watchfiles")
                    self.assertEqual(
                        watchfiles_logger.level,
                        expected_level,
                        f"Expected level {expected_level} for verbosity {verbosity}",
                    )

            finally:
                autoreload.run_with_reloader = original_run


class CustomFilterTests(SimpleTestCase):
    def setUp(self):
        temp_dir = self.enterContext(tempfile.TemporaryDirectory())
        self.temp_path = Path(temp_dir)
        self.src_dir = self.temp_path / "my_src"
        self.src_dir.mkdir()

        self._original_notify = BaseReloader.notify_file_changed
        BaseReloader.notify_file_changed = lambda self, path: None

    def tearDown(self):
        BaseReloader.notify_file_changed = self._original_notify

    def wait_for_changes(self, watcher_iter, timeout=3.0, retry_count=5):
        """Helper method to wait for changes with improved reliability"""
        for attempt in range(retry_count):
            start_time = time.time()

            try:
                while time.time() - start_time < timeout:
                    if changes := next(watcher_iter):
                        return changes
                    time.sleep(0.2)
            except StopIteration:
                return None

            # If we didn't get changes and have retries left, try again
            if attempt < retry_count - 1:
                time.sleep(1.0)

        return None

    @parameterized.expand(
        [
            ("js_file", "test.js", "console.log('watch!')"),
            ("html_file", "test.html", "<h1>hello world!</h1>"),
            ("css_file", "test.css", "body { color: blue; }"),
        ]
    )
    @pytest.mark.flaky(reruns=3, reruns_delay=1)
    def test_only_added_filter_file_types(self, name, file_name, file_content):
        watcher = MutableWatcher(only_added, {})
        test_file = self.src_dir / file_name
        watcher.set_roots({self.src_dir})
        watcher_iter = iter(watcher)

        try:
            next(watcher_iter)
            time.sleep(0.5)

            test_file.write_text(file_content)
            changes = self.wait_for_changes(watcher_iter, timeout=3.0, retry_count=5)

            self.assertIsNotNone(changes, f"No changes detected for {test_file}")

            change_paths = [path for _, path in changes]
            real_test_path = str(test_file.resolve())
            self.assertIn(real_test_path, change_paths)
            self.assertTrue(all(change == Change.added for change, _ in changes))

        finally:
            watcher.stop()

        watchfiles_settings = {"watch_filter": only_added}
        reloader = WatchfilesReloader(watchfiles_settings)

        # get both the regular and resolved paths
        regular_path = str(test_file)
        resolved_path = str(test_file.resolve())

        reloader.watch_dir(self.src_dir, "*.*")

        # test file filter with both paths
        regular_result = reloader.file_filter(Change.added, regular_path)

        self.assertTrue(
            regular_result, f"File filter should accept regular path: {regular_path}"
        )

        reloader.file_filter(Change.added, resolved_path)
