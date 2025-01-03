from __future__ import annotations

import logging
import tempfile
import time
from pathlib import Path
from unittest import mock

import pytest
from django.core.exceptions import ImproperlyConfigured
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

    @pytest.mark.flaky(reruns=3, reruns_delay=1)
    def test_iter_no_changes(self):
        test_file = self.temp_path / "test.txt"
        test_file.write_text("initial content")

        self.watcher.set_roots({self.temp_path})
        iterator = iter(self.watcher)

        # Flush initial events
        next(iterator)
        time.sleep(0.5)
        changes = next(iterator)

        assert changes == set(), f"Expected empty set, got changes: {changes}"

    @pytest.mark.flaky(reruns=3, reruns_delay=1)
    def test_iter_yields_changes(self):
        test_file = self.temp_path / "test.txt"
        test_file.write_text("initial content")

        self.watcher.set_roots({self.temp_path})
        iterator = iter(self.watcher)

        # Flush initial events
        next(iterator)
        time.sleep(0.5)

        test_file.write_text("modified content")
        time.sleep(0.5)
        changes = next(iterator)

        assert isinstance(changes, set)
        assert (
            len(changes) == 1
        ), f"Expected 1 change, got {len(changes)} changes: {changes}"
        change, path = changes.pop()
        assert path == str(test_file.resolve())

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
    def setUp(self):
        self.original_run_with_reloader = autoreload.run_with_reloader
        self.original_tick = WatchfilesReloader.tick

        self.exit_patcher = mock.patch("sys.exit")
        self.mock_exit = self.exit_patcher.start()

        def mock_run_with_reloader(main_func, *args, **kwargs):
            return main_func(*args, **kwargs)

        def mock_tick(self):
            # Return an empty iterator that doesn't start the watcher
            yield None

        self.mock_run_with_reloader = mock_run_with_reloader
        autoreload.run_with_reloader = self.mock_run_with_reloader
        WatchfilesReloader.tick = mock_tick

    def tearDown(self):
        autoreload.run_with_reloader = self.original_run_with_reloader
        WatchfilesReloader.tick = self.original_tick
        self.exit_patcher.stop()

    def test_replaced_run_with_reloader_default_settings(self):
        with self.settings(WATCHFILES={}):
            replaced_run_with_reloader(lambda *args, **kwargs: None, verbosity=1)
            reloader = autoreload.get_reloader()
            assert isinstance(reloader, WatchfilesReloader)
            expected_settings = {
                "debug": False,
            }
            assert reloader.watchfiles_settings == expected_settings

    def test_replaced_run_with_reloader_custom_settings(self):
        custom_settings = {
            "watch_filter": "tests.filters.only_added_factory",
            "debug": True,
        }

        with self.settings(WATCHFILES=custom_settings):
            replaced_run_with_reloader(lambda *args, **kwargs: None, verbosity=1)
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
        with self.settings(WATCHFILES={}):
            replaced_run_with_reloader(
                lambda *args, **kwargs: None, verbosity=verbosity
            )
            watchfiles_logger = logging.getLogger("watchfiles")
            assert watchfiles_logger.level == expected_level

    def test_replaced_run_with_reloader_with_watch_filter(self):
        filter_path = "tests.filters.only_added_factory"
        custom_settings = {"watch_filter": filter_path, "debug": True}

        with self.settings(WATCHFILES=custom_settings):
            replaced_run_with_reloader(lambda *args, **kwargs: None, verbosity=1)

            watchfiles_logger = logging.getLogger("watchfiles")
            assert watchfiles_logger.level == logging.DEBUG

            reloader = autoreload.get_reloader()
            assert isinstance(reloader, WatchfilesReloader)
            assert callable(reloader.watchfiles_settings["watch_filter"])
            assert reloader.watchfiles_settings["debug"]

            filter_func = reloader.watchfiles_settings["watch_filter"]
            assert filter_func(Change.added, "test.py")
            assert not filter_func(Change.modified, "test.py")

    @parameterized.expand(
        [
            ("error_level", 0, logging.ERROR),
            ("warning_level", 1, logging.WARNING),
            ("info_level", 2, logging.INFO),
            ("debug_level", 3, logging.DEBUG),
        ]
    )
    def test_replaced_run_with_reloader_no_debug(self, name, verbosity, expected_level):
        """Test the log level calculation without debug mode"""
        with self.settings(WATCHFILES={}):
            replaced_run_with_reloader(
                lambda *args, **kwargs: None, verbosity=verbosity
            )
            watchfiles_logger = logging.getLogger("watchfiles")
            assert watchfiles_logger.level == expected_level

    def test_replaced_run_with_reloader_watch_filter_attribute_error(self):
        """Test handling of watch_filter attribute error"""
        mock_settings = mock.Mock()
        mock_settings.USE_I18N = False
        mock_settings.LOCALE_PATHS = []
        mock_settings.WATCHFILES = {"watch_filter": "tests.filters.NonExistentFilter"}

        def mock_run_with_reloader(*args, **kwargs):
            args[0]()
            return None

        with (
            mock.patch("django.conf.settings", mock_settings),
            mock.patch(
                "django.utils.autoreload.run_with_reloader", mock_run_with_reloader
            ),
        ):
            replaced_run_with_reloader(lambda: None)
            reloader = autoreload.get_reloader()
            assert "watch_filter" not in reloader.watchfiles_settings

    def test_replaced_run_with_reloader_watch_filter_value_error(self):
        """Test handling of watch_filter value error"""
        mock_settings = mock.Mock()
        mock_settings.USE_I18N = False
        mock_settings.LOCALE_PATHS = []
        mock_settings.WATCHFILES = {"watch_filter": "invalid:format:path"}

        def mock_run_with_reloader(*args, **kwargs):
            args[0]()
            return None

        with (
            mock.patch("django.conf.settings", mock_settings),
            mock.patch(
                "django.utils.autoreload.run_with_reloader", mock_run_with_reloader
            ),
        ):
            replaced_run_with_reloader(lambda: None)
            reloader = autoreload.get_reloader()
            assert "watch_filter" not in reloader.watchfiles_settings

    def test_replaced_run_with_reloader_watch_filter_not_callable(self):
        """Test handling of watch_filter that exists but isn't callable"""
        mock_settings = mock.Mock()
        mock_settings.WATCHFILES = {
            "watch_filter": "tests.filters.NOT_CALLABLE",
            "debug": True,
        }
        mock_settings.LOCALE_PATHS = []

        def mock_run_with_reloader(*args, **kwargs):
            args[0]()
            return 0

        with (
            mock.patch(
                "django.utils.autoreload.run_with_reloader", mock_run_with_reloader
            ),
            mock.patch("django.conf.settings", mock_settings),
        ):
            replaced_run_with_reloader(lambda *args, **kwargs: None, verbosity=1)
            reloader = autoreload.get_reloader()
            self.assertNotIn("watch_filter", reloader.watchfiles_settings)

    def test_replaced_run_with_reloader_settings_attribute_error(self):
        """Test handling of AttributeError when accessing WATCHFILES"""
        mock_settings = mock.Mock(spec=[])
        mock_settings.LOCALE_PATHS = []
        mock_settings.USE_I18N = None

        def mock_run_with_reloader(*args, **kwargs):
            return None

        with (
            mock.patch(
                "django.utils.autoreload.run_with_reloader", mock_run_with_reloader
            ),
            mock.patch("django.conf.settings", mock_settings),
        ):
            replaced_run_with_reloader(lambda *args, **kwargs: None, verbosity=1)
            reloader = autoreload.get_reloader()
            self.assertEqual(reloader.watchfiles_settings, {"debug": False})

    def test_replaced_run_with_reloader_improperly_configured(self):
        """Test handling of ImproperlyConfigured when accessing WATCHFILES"""

        mock_settings = mock.Mock()
        mock_settings.USE_I18N = False
        mock_settings.LOCALE_PATHS = []
        type(mock_settings).WATCHFILES = mock.PropertyMock(
            side_effect=ImproperlyConfigured("Settings not configured")
        )

        def mock_run_with_reloader(*args, **kwargs):
            args[0]()
            return None

        with (
            mock.patch("django.conf.settings", mock_settings),
            mock.patch(
                "django.utils.autoreload.run_with_reloader", mock_run_with_reloader
            ),
        ):
            replaced_run_with_reloader(lambda: None)
            reloader = autoreload.get_reloader()
            assert reloader.watchfiles_settings == {"debug": False}

    def test_replaced_run_with_reloader_no_watchfiles_settings(self):
        """Test handling when settings doesn't have WATCHFILES attribute"""
        mock_settings = mock.Mock(spec=[])
        mock_settings.LOCALE_PATHS = []
        mock_settings.USE_I18N = None

        def mock_run_with_reloader(*args, **kwargs):
            return None

        with (
            mock.patch(
                "django.utils.autoreload.run_with_reloader", mock_run_with_reloader
            ),
            mock.patch("django.conf.settings", mock_settings),
        ):
            replaced_run_with_reloader(lambda *args, **kwargs: None, verbosity=1)
            reloader = autoreload.get_reloader()
            self.assertEqual(reloader.watchfiles_settings, {"debug": False})

    def test_replaced_run_with_reloader_invalid_watch_filter(self):
        """Test handling when watch_filter setting is invalid"""
        mock_settings = mock.Mock()
        mock_settings.WATCHFILES = {
            "watch_filter": "invalid.path.that.doesnt.exist",
            "debug": True,
        }
        mock_settings.LOCALE_PATHS = []

        def mock_run_with_reloader(*args, **kwargs):
            args[0]()
            return 0

        with (
            mock.patch(
                "django.utils.autoreload.run_with_reloader", mock_run_with_reloader
            ),
            mock.patch("django.conf.settings", mock_settings),
        ):
            replaced_run_with_reloader(lambda *args, **kwargs: None, verbosity=1)
            reloader = autoreload.get_reloader()
            self.assertNotIn("watch_filter", reloader.watchfiles_settings)

    def test_replaced_run_with_reloader_watch_filter_import_error(self):
        """Test handling of watch_filter import failure"""
        mock_settings = mock.Mock()
        mock_settings.WATCHFILES = {
            "watch_filter": "tests.filters.DOES_NOT_EXIST",
            "debug": True,
        }
        mock_settings.LOCALE_PATHS = []

        with (
            mock.patch(
                "django.utils.autoreload.run_with_reloader", self.mock_run_with_reloader
            ),
            mock.patch("django.conf.settings", mock_settings),
        ):
            replaced_run_with_reloader(lambda *args, **kwargs: None, verbosity=1)
            reloader = autoreload.get_reloader()
            self.assertNotIn("watch_filter", reloader.watchfiles_settings)

    def test_replaced_run_with_reloader_attribute_error(self):
        """Test handling of AttributeError when accessing WATCHFILES"""
        mock_settings = mock.Mock(spec=[])
        mock_settings.USE_I18N = False
        mock_settings.LOCALE_PATHS = []

        def mock_run_with_reloader(*args, **kwargs):
            args[0]()
            return None

        with (
            mock.patch("django.conf.settings", mock_settings),
            mock.patch(
                "django.utils.autoreload.run_with_reloader", mock_run_with_reloader
            ),
        ):
            replaced_run_with_reloader(lambda: None)
            reloader = autoreload.get_reloader()
            assert reloader.watchfiles_settings == {"debug": False}


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
