import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from notion_client.errors import APIResponseError

from notion_better_export import cli
from notion_better_export.client import NotionApiClient
from notion_better_export.exporter import NotionBetterExporter
from notion_better_export.hierarchy import sanitize_filename
from notion_better_export.post_processor import BACKUP_DIR_NAME, ExportPostProcessor
from notion_better_export.safety import (
    LOCK_NAME,
    MARKER_NAME,
    ExportAborted,
    UnsafeOutputDir,
    assert_safe_output_dir,
    atomic_open,
    atomic_write_text,
    output_dir_warnings,
    run_lock,
)


class TempDirCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name).resolve()


def api_error(status: int) -> APIResponseError:
    err = APIResponseError.__new__(APIResponseError)
    err.status, err.code, err.message, err.headers, err.args = status, "x", "boom", {}, ("boom",)
    return err


class AtomicWriteTests(TempDirCase):
    def test_success_replaces_file(self):
        f = self.dir / "a.md"
        atomic_write_text(f, "one")
        atomic_write_text(f, "two")
        self.assertEqual(f.read_text(), "two")

    def test_failure_keeps_original_and_leaves_no_temp_files(self):
        f = self.dir / "a.md"
        f.write_text("original")
        with self.assertRaises(RuntimeError):
            with atomic_open(f) as fh:
                fh.write("half-written")
                raise RuntimeError("crash mid-write")
        self.assertEqual(f.read_text(), "original")
        self.assertEqual([p.name for p in self.dir.iterdir()], ["a.md"])

    def test_keyboard_interrupt_is_also_cleaned_up(self):
        f = self.dir / "a.md"
        with self.assertRaises(KeyboardInterrupt):
            with atomic_open(f) as fh:
                fh.write("x")
                raise KeyboardInterrupt
        self.assertEqual(list(self.dir.iterdir()), [])

    def test_new_file_gets_normal_permissions(self):
        f = self.dir / "a.md"
        atomic_write_text(f, "x")
        self.assertNotEqual(f.stat().st_mode & 0o777, 0o600)


class OutputDirTests(TempDirCase):
    def test_refuses_dangerous_targets(self):
        for bad in ("/", str(Path.home()), "/etc", "/usr/local", "/System/x"):
            with self.subTest(bad=bad), self.assertRaises(UnsafeOutputDir):
                assert_safe_output_dir(Path(bad))

    def test_refuses_a_file_and_the_projects_own_source(self):
        f = self.dir / "note.txt"
        f.write_text("x")
        with self.assertRaises(UnsafeOutputDir):
            assert_safe_output_dir(f)
        (self.dir / "pyproject.toml").write_text("")
        (self.dir / "notion_better_export").mkdir()
        with self.assertRaises(UnsafeOutputDir):
            assert_safe_output_dir(self.dir)

    def test_normal_folder_is_allowed(self):
        assert_safe_output_dir(self.dir / "Notion Better Export")

    def test_empty_or_new_folder_has_no_warning(self):
        self.assertEqual(output_dir_warnings(self.dir / "new", min_free_mb=1), [])
        self.assertEqual(output_dir_warnings(self.dir, min_free_mb=1), [])

    def test_foreign_files_trigger_warning_but_our_marker_does_not(self):
        (self.dir / "my notes.md").write_text("mine")
        self.assertTrue(any("did not create" in w for w in output_dir_warnings(self.dir, 1)))
        (self.dir / MARKER_NAME).write_text("")
        self.assertEqual(output_dir_warnings(self.dir, 1), [])

    def test_vault_root_is_called_out(self):
        (self.dir / ".obsidian").mkdir()
        self.assertTrue(any("Obsidian vault" in w for w in output_dir_warnings(self.dir, 1)))

    def test_low_disk_space_warns(self):
        fake = mock.Mock(free=10 * 1024 * 1024)
        with mock.patch("shutil.disk_usage", return_value=fake):
            self.assertTrue(any("MB free" in w for w in output_dir_warnings(self.dir, 200)))

    def test_cli_refuses_noninteractive_without_force(self):
        (self.dir / "mine.md").write_text("x")
        with mock.patch("sys.stdin.isatty", return_value=False), self.assertRaises(SystemExit) as ctx:
            cli.confirm_output_dir(self.dir, force=False, dry_run=False)
        self.assertEqual(ctx.exception.code, 1)
        cli.confirm_output_dir(self.dir, force=True, dry_run=False)
        cli.confirm_output_dir(self.dir, force=False, dry_run=True)


class RunLockTests(TempDirCase):
    def test_second_live_run_is_refused_and_lock_released_after(self):
        with run_lock(self.dir):
            (self.dir / LOCK_NAME).write_text(json.dumps({"pid": os.getppid()}))  # a live pid
            with self.assertRaises(UnsafeOutputDir):
                with run_lock(self.dir):
                    pass
        with run_lock(self.dir):  # free again
            pass
        self.assertFalse((self.dir / LOCK_NAME).exists())

    def test_stale_lock_from_dead_process_is_cleared(self):
        proc = subprocess.Popen([sys.executable, "-c", "pass"])
        proc.wait()
        (self.dir / LOCK_NAME).write_text(json.dumps({"pid": proc.pid}))
        with run_lock(self.dir):
            pass

    def test_corrupt_lock_is_treated_as_stale(self):
        (self.dir / LOCK_NAME).write_text("not json")
        with run_lock(self.dir):
            pass

    def test_lock_released_when_run_crashes(self):
        with self.assertRaises(RuntimeError), run_lock(self.dir):
            raise RuntimeError
        self.assertFalse((self.dir / LOCK_NAME).exists())


class CircuitBreakerTests(unittest.TestCase):
    def make(self, **kw):
        client = NotionApiClient("ntn_test", **kw)
        client.rate_limiter.wait = lambda: None
        return client

    def test_401_aborts_immediately(self):
        client = self.make()
        with self.assertRaises(ExportAborted) as ctx:
            client.retry(mock.Mock(side_effect=api_error(401)))
        self.assertEqual(ctx.exception.status, 401)

    def test_aborts_after_consecutive_failures(self):
        client = self.make(max_consecutive_failures=3)
        func = mock.Mock(side_effect=api_error(400))
        with self.assertRaises(APIResponseError):
            client.retry(func)
        with self.assertRaises(APIResponseError):
            client.retry(func)
        with self.assertRaises(ExportAborted):
            client.retry(func)

    def test_success_resets_the_counter(self):
        client = self.make(max_consecutive_failures=3)
        bad = mock.Mock(side_effect=api_error(400))
        for _ in range(2):
            with self.assertRaises(APIResponseError):
                client.retry(bad)
        client.retry(lambda: {"ok": 1})
        self.assertEqual(client.consecutive_failures, 0)
        for _ in range(2):
            with self.assertRaises(APIResponseError):
                client.retry(bad)

    def test_missing_or_unshared_pages_do_not_trip_the_breaker(self):
        client = self.make(max_consecutive_failures=2)
        for status in (404, 403, 404, 403):
            with self.assertRaises(APIResponseError):
                client.retry(mock.Mock(side_effect=api_error(status)))
        self.assertEqual(client.consecutive_failures, 0)

    def test_abort_is_not_swallowed_by_except_exception(self):
        try:
            try:
                raise ExportAborted("stop")
            except Exception:
                self.fail("ExportAborted must not be an Exception")
        except ExportAborted:
            pass


class ExporterSafetyTests(TempDirCase):
    def test_dry_run_creates_nothing(self):
        out = self.dir / "vault" / "Notion Better Export"
        exporter = NotionBetterExporter(token="ntn_x", out_dir=out, dry_run=True)
        exporter.client.search_all = lambda *a, **k: []
        exporter.run()
        self.assertFalse(out.exists())

    def test_real_run_writes_marker_releases_lock_and_refuses_bad_dir(self):
        out = self.dir / "vault"
        exporter = NotionBetterExporter(token="ntn_x", out_dir=out)
        exporter.client.search_all = lambda *a, **k: []
        exporter.run()
        self.assertTrue((out / MARKER_NAME).exists())
        self.assertFalse((out / LOCK_NAME).exists())
        with self.assertRaises(UnsafeOutputDir):
            NotionBetterExporter(token="ntn_x", out_dir=Path.home()).run()

    def test_aborted_run_releases_lock(self):
        out = self.dir / "vault"
        exporter = NotionBetterExporter(token="ntn_x", out_dir=out)
        exporter.client.search_all = mock.Mock(side_effect=ExportAborted("revoked", 401))
        with self.assertRaises(ExportAborted):
            exporter.run()
        self.assertFalse((out / LOCK_NAME).exists())


class SummaryTests(TempDirCase):
    def test_clean_run_returns_normally(self):
        cli.report_summary({"exported_objects": 3, "errors": []}, self.dir, dry_run=False)

    def test_errors_write_log_and_exit_2(self):
        with self.assertRaises(SystemExit) as ctx:
            cli.report_summary({"exported_objects": 3, "errors": ["a failed", "b failed"]}, self.dir, False)
        self.assertEqual(ctx.exception.code, 2)
        self.assertEqual((self.dir / "notion_export_errors.log").read_text(), "a failed\nb failed\n")

    def test_dry_run_errors_do_not_write_a_log(self):
        with self.assertRaises(SystemExit):
            cli.report_summary({"exported_objects": 1, "errors": ["x"]}, self.dir, True)
        self.assertFalse((self.dir / "notion_export_errors.log").exists())


class FilenameTests(unittest.TestCase):
    def test_windows_reserved_names_are_made_safe(self):
        for name in ("CON", "nul", "Aux.txt", "COM1", "lpt9"):
            with self.subTest(name=name):
                self.assertTrue(sanitize_filename(name).startswith("_"))

    def test_normal_names_are_untouched(self):
        for name in ("Console", "Notes", "COM10", "My Page"):
            self.assertEqual(sanitize_filename(name), name)


UUID = "3ce453c2-1690-817e-8b1a-0123456789ab"


class FixSafetyTests(TempDirCase):
    def setUp(self):
        super().setUp()
        self.note = self.dir / "Page.md"
        self.original = f"---\nrelated: {UUID}\nnotion_id: keep\n---\nbody\n"
        self.note.write_text(self.original)
        (self.dir / "notion_export_manifest.json").write_text(json.dumps({UUID: "Folder/Target"}))

    def test_dry_run_changes_nothing(self):
        res = ExportPostProcessor(self.dir, dry_run=True).run_all()
        self.assertGreater(res["md_replacements"], 0)
        self.assertEqual(self.note.read_text(), self.original)
        self.assertFalse((self.dir / BACKUP_DIR_NAME).exists())

    def test_fix_backs_up_original_and_keeps_first_backup(self):
        ExportPostProcessor(self.dir).run_all()
        self.assertNotIn(UUID, self.note.read_text())
        backup = self.dir / BACKUP_DIR_NAME / "Page.md"
        self.assertEqual(backup.read_text(), self.original)
        ExportPostProcessor(self.dir).run_all()  # second run must not clobber the backup
        self.assertEqual(backup.read_text(), self.original)

    def test_backup_folder_is_not_reprocessed(self):
        ExportPostProcessor(self.dir).run_all()
        res = ExportPostProcessor(self.dir).run_all()
        self.assertEqual(res["md_files"], 1)

    def test_no_backup_flag(self):
        ExportPostProcessor(self.dir, backup=False).run_all()
        self.assertFalse((self.dir / BACKUP_DIR_NAME).exists())

    def test_missing_folder_is_an_error_not_a_silent_success(self):
        with self.assertRaises(FileNotFoundError):
            ExportPostProcessor(self.dir / "nope").run_all()


if __name__ == "__main__":
    unittest.main()
