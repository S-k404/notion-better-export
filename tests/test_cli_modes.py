"""Tests for how cli.main() picks a mode and for the run_auto / run_fix helpers it shares
with the interactive menu."""

import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from rich.console import Console

from notion_better_export import cli
from notion_better_export.safety import atomic_write_text

TOKEN = "ntn_your_notion_integration_token_here"


class CliTestCase(unittest.TestCase):
    def setUp(self):
        self.output = io.StringIO()
        patcher = mock.patch.object(cli, "console", Console(file=self.output, width=240))
        patcher.start()
        self.addCleanup(patcher.stop)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()

    def text(self):
        return self.output.getvalue()


class InteractiveTerminalTests(unittest.TestCase):
    def fake_stream(self, tty):
        return SimpleNamespace(isatty=lambda: tty)

    def test_needs_both_stdin_and_stdout_to_be_terminals(self):
        for stdin_tty, stdout_tty, expected in [(True, True, True), (True, False, False), (False, True, False)]:
            with self.subTest(stdin=stdin_tty, stdout=stdout_tty):
                with mock.patch.object(sys, "stdin", self.fake_stream(stdin_tty)), mock.patch.object(
                    sys, "stdout", self.fake_stream(stdout_tty)
                ):
                    self.assertIs(cli.is_interactive_terminal(), expected)

    def test_stream_without_isatty_counts_as_not_a_terminal(self):
        with mock.patch.object(sys, "stdin", object()):
            self.assertFalse(cli.is_interactive_terminal())


class MainDispatchTests(CliTestCase):
    def run_main(self, argv, tty):
        with mock.patch.object(sys, "argv", ["nbe", *argv]), mock.patch.object(
            cli, "is_interactive_terminal", return_value=tty
        ), mock.patch.object(cli, "setup_logging"), mock.patch.object(
            cli, "find_default_token", return_value=TOKEN
        ), mock.patch.object(cli, "load_saved_vault_path"), mock.patch.object(
            cli, "resolve_auto_out_dir", return_value=self.tmp / "vault"
        ), mock.patch.object(cli, "run_auto") as run_auto, mock.patch(
            "notion_better_export.interactive.run_interactive"
        ) as run_interactive:
            cli.main()
        return run_auto, run_interactive

    def test_bare_nbe_in_a_terminal_opens_the_menu(self):
        run_auto, run_interactive = self.run_main([], tty=True)
        run_interactive.assert_called_once_with()
        run_auto.assert_not_called()

    def test_bare_nbe_in_a_script_still_runs_auto(self):
        # Pipes, cron and CI have nobody to answer prompts: keep the old behaviour.
        run_auto, run_interactive = self.run_main([], tty=False)
        run_interactive.assert_not_called()
        run_auto.assert_called_once()
        self.assertEqual(run_auto.call_args.args, (TOKEN, self.tmp / "vault"))
        self.assertFalse(run_auto.call_args.kwargs["dry_run"])

    def test_explicit_interactive_subcommand(self):
        run_auto, run_interactive = self.run_main(["interactive"], tty=True)
        run_interactive.assert_called_once_with()
        run_auto.assert_not_called()

    def test_flags_without_a_subcommand_still_mean_auto(self):
        run_auto, run_interactive = self.run_main(["--dry-run"], tty=True)
        run_interactive.assert_not_called()
        self.assertTrue(run_auto.call_args.kwargs["dry_run"])

    def test_test_shortcut_still_means_auto_sample(self):
        run_auto, run_interactive = self.run_main(["test"], tty=True)
        run_interactive.assert_not_called()
        self.assertTrue(run_auto.call_args.kwargs["test"])

    def test_auto_passes_every_flag_through(self):
        run_auto, _ = self.run_main(
            ["auto", "--assets", "--date-prefix-rows", "--rate-limit", "1.5", "--force", "--out", "x"], tty=True
        )
        kwargs = run_auto.call_args.kwargs
        self.assertTrue(kwargs["assets"])
        self.assertTrue(kwargs["date_prefix_rows"])
        self.assertTrue(kwargs["force"])
        self.assertEqual(kwargs["rate_limit"], 1.5)


class RunAutoTests(CliTestCase):
    def run_auto(self, summary=None, **kwargs):
        exporter = mock.Mock()
        exporter.run.return_value = summary or {"exported_objects": 3, "errors": []}
        with mock.patch.object(cli, "confirm_output_dir") as confirm, mock.patch.object(
            cli, "NotionBetterExporter", return_value=exporter
        ) as exporter_cls:
            result = cli.run_auto(TOKEN, self.tmp / "vault", **kwargs)
        return result, exporter_cls, confirm

    def test_builds_the_same_exporter_as_the_old_auto_branch(self):
        result, exporter_cls, confirm = self.run_auto(
            test=True, assets=True, date_prefix_rows=True, rate_limit=1.5, force=True
        )
        exporter_cls.assert_called_once_with(
            token=TOKEN,
            out_dir=self.tmp / "vault",
            max_rows_per_db=5,
            download_assets=True,
            dry_run=False,
            csv_link_format="wikilink",
            include_csv_note_link=True,
            write_csv=True,
            write_base=True,
            date_prefix_rows=True,
            requests_per_second=1.5,
        )
        confirm.assert_called_once_with(self.tmp / "vault", True, False)
        self.assertEqual(result["exported_objects"], 3)

    def test_full_export_has_no_row_cap(self):
        _, exporter_cls, _ = self.run_auto()
        self.assertIsNone(exporter_cls.call_args.kwargs["max_rows_per_db"])
        self.assertIn("Full Live Export", self.text())

    def test_dry_run_is_labelled_and_does_not_point_at_a_vault(self):
        _, exporter_cls, confirm = self.run_auto(dry_run=True)
        self.assertTrue(exporter_cls.call_args.kwargs["dry_run"])
        confirm.assert_called_once_with(self.tmp / "vault", False, True)
        self.assertIn("Dry Run", self.text())
        self.assertNotIn("open Obsidian", self.text())

    def test_success_points_at_the_vault(self):
        self.run_auto()
        self.assertIn("open Obsidian", self.text())

    def test_errors_exit_2_by_default(self):
        (self.tmp / "vault").mkdir()
        with self.assertRaises(SystemExit) as stop:
            self.run_auto(summary={"exported_objects": 1, "errors": ["Page X: boom"]})
        self.assertEqual(stop.exception.code, 2)

    def test_errors_do_not_exit_when_run_from_the_menu(self):
        (self.tmp / "vault").mkdir()
        result, _, _ = self.run_auto(
            summary={"exported_objects": 1, "errors": ["Page X: boom"]}, exit_on_errors=False
        )
        self.assertEqual(result["errors"], ["Page X: boom"])
        log = (self.tmp / "vault" / "notion_export_errors.log").read_text(encoding="utf-8")
        self.assertIn("Page X: boom", log)
        self.assertNotIn("Exiting with code 2", self.text())


class ReportSummaryTests(CliTestCase):
    def test_dry_run_errors_never_write_a_log(self):
        summary = {"exported_objects": 1, "errors": ["Page X: boom"]}
        cli.report_summary(summary, self.tmp, dry_run=True, exit_on_errors=False)
        self.assertFalse((self.tmp / "notion_export_errors.log").exists())


class RunFixTests(CliTestCase):
    RESULT = {"csv_replacements": 4, "csv_files": 1, "md_replacements": 2, "md_files": 1}

    def run_fix(self, **kwargs):
        processor = mock.Mock()
        processor.run_all.return_value = dict(self.RESULT)
        with mock.patch.object(cli, "ExportPostProcessor", return_value=processor) as processor_cls:
            result = cli.run_fix(self.tmp, **kwargs)
        return result, processor_cls

    def test_passes_options_to_the_post_processor(self):
        result, processor_cls = self.run_fix(dry_run=True, backup=False, link_format="title")
        processor_cls.assert_called_once_with(
            export_dir=self.tmp,
            manifest_path=None,
            link_format="title",
            dry_run=True,
            backup=False,
        )
        self.assertEqual(result["csv_replacements"], 4)
        self.assertIn("dry run", self.text())

    def test_backup_hint_only_after_a_real_run_that_changed_files(self):
        self.run_fix()
        self.assertIn(".nbe-fix-backup", self.text())

    def test_no_backup_hint_for_a_dry_run(self):
        self.run_fix(dry_run=True)
        self.assertNotIn(".nbe-fix-backup", self.text())

    def test_backup_is_on_by_default(self):
        _, processor_cls = self.run_fix()
        self.assertTrue(processor_cls.call_args.kwargs["backup"])


class SavedVaultTests(CliTestCase):
    def setUp(self):
        super().setUp()
        config = self.tmp / "env"
        atomic_write_text(config, f"NOTION_TOKEN={TOKEN}\nVAULT_PATH=/saved/vault\n")
        patcher = mock.patch.object(cli, "user_config_path", return_value=config)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_real_environment_wins_by_default(self):
        with mock.patch.dict(os.environ, {"VAULT_PATH": "/from/env"}):
            cli.load_saved_vault_path()
            self.assertEqual(os.environ["VAULT_PATH"], "/from/env")

    def test_force_lets_a_freshly_saved_vault_win(self):
        with mock.patch.dict(os.environ, {"VAULT_PATH": "/stale/value"}):
            cli.load_saved_vault_path(force=True)
            self.assertEqual(os.environ["VAULT_PATH"], "/saved/vault")

    def test_fills_in_when_nothing_is_set(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("VAULT_PATH", None)
            cli.load_saved_vault_path()
            self.assertEqual(os.environ["VAULT_PATH"], "/saved/vault")


if __name__ == "__main__":
    unittest.main()
