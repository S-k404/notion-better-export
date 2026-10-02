"""Tests for the guided `nbe interactive` menu (notion_better_export/interactive.py)."""

import io
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from rich.console import Console

from notion_better_export import cli, interactive
from notion_better_export.client import DEFAULT_REQUESTS_PER_SECOND

TOKEN = "ntn_your_notion_integration_token_here"

# Menu numbers, in the order of interactive.MENU_OPTIONS.
SAMPLE, PREVIEW, EXPORT, FIX, SETUP, QUIT = "1", "2", "3", "4", "5", "6"

OK_SUMMARY = {"exported_objects": 0, "errors": []}
FIX_FOUND_CHANGES = {"csv_replacements": 4, "md_replacements": 2}


class Script:
    """Stands in for interactive._read: replays canned answers; None means Ctrl-C."""

    def __init__(self, answers):
        self.answers = list(answers)

    def __call__(self, prompt):
        if not self.answers:
            raise AssertionError(f"unexpected extra prompt: {prompt!r}")
        answer = self.answers.pop(0)
        if answer is None:
            raise interactive.Cancelled
        return answer


class InteractiveTestCase(unittest.TestCase):
    def setUp(self):
        self.output = io.StringIO()
        patcher = mock.patch.object(cli, "console", Console(file=self.output, width=240))
        patcher.start()
        self.addCleanup(patcher.stop)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.out_dir = Path(tmp.name).resolve() / "vault"

    def run_menu(
        self,
        answers,
        token=TOKEN,
        tty=True,
        run_auto_effect=None,
        init_error=None,
        token_after_init=None,
        fix_result=FIX_FOUND_CHANGES,
    ):
        """Run the whole menu against scripted answers; every answer must be consumed."""
        script = Script(answers)
        holder = {"token": token}

        def fake_init(*_args, **_kwargs):
            if init_error is not None:
                raise init_error
            if token_after_init is not None:
                holder["token"] = token_after_init

        with ExitStack() as stack:
            enter = stack.enter_context
            enter(mock.patch.object(interactive, "_read", script))
            enter(mock.patch.object(cli, "is_interactive_terminal", return_value=tty))
            enter(mock.patch.object(cli, "find_default_token", side_effect=lambda: holder["token"]))
            enter(mock.patch.object(cli, "resolve_auto_out_dir", return_value=self.out_dir))
            mocks = SimpleNamespace(
                load_vault=enter(mock.patch.object(cli, "load_saved_vault_path")),
                run_auto=enter(mock.patch.object(cli, "run_auto", side_effect=run_auto_effect)),
                run_fix=enter(mock.patch.object(cli, "run_fix", return_value=dict(fix_result))),
                cmd_init=enter(mock.patch.object(cli, "cmd_init", side_effect=fake_init)),
            )
            interactive.run_interactive()
        self.assertEqual(script.answers, [], "the flow ended before using every scripted answer")
        return mocks

    def text(self):
        return self.output.getvalue()


class PromptHelperTests(InteractiveTestCase):
    def ask(self, func, answers, *args, **kwargs):
        with mock.patch.object(interactive, "_read", Script(answers)):
            return func(*args, **kwargs)

    def test_choice_accepts_number_key_and_default(self):
        options = (("a", "Alpha"), ("b", "Beta"))
        self.assertEqual(self.ask(interactive.ask_choice, ["2"], "Pick", options), "b")
        self.assertEqual(self.ask(interactive.ask_choice, ["a"], "Pick", options), "a")
        self.assertEqual(self.ask(interactive.ask_choice, [""], "Pick", options, default="b"), "b")

    def test_choice_reasks_on_bad_input(self):
        options = (("a", "Alpha"), ("b", "Beta"))
        # An empty answer with no default, an out-of-range number and garbage are all refused.
        self.assertEqual(self.ask(interactive.ask_choice, ["", "9", "0", "zzz", "1"], "Pick", options), "a")
        self.assertIn("Please enter a number from 1 to 2", self.text())

    def test_yes_no_defaults_and_reasks(self):
        self.assertTrue(self.ask(interactive.ask_yes_no, [""], "Ok?", default=True))
        self.assertFalse(self.ask(interactive.ask_yes_no, [""], "Ok?", default=False))
        self.assertTrue(self.ask(interactive.ask_yes_no, ["maybe", "YES"], "Ok?"))
        self.assertFalse(self.ask(interactive.ask_yes_no, ["No"], "Ok?", default=True))

    def test_rate_limit_never_exceeds_notion_ceiling(self):
        self.assertEqual(self.ask(interactive.ask_rate_limit, [""]), DEFAULT_REQUESTS_PER_SECOND)
        self.assertEqual(self.ask(interactive.ask_rate_limit, ["1.5"]), 1.5)
        # 0, negatives, garbage and anything above 3 are refused, never clamped silently.
        self.assertEqual(self.ask(interactive.ask_rate_limit, ["0", "-1", "abc", "3.5", "10", "2"]), 2.0)

    def test_clean_path_handles_quotes_and_tilde(self):
        self.assertEqual(interactive.clean_path("  '/tmp/My Vault'  "), Path("/tmp/My Vault").resolve())
        self.assertEqual(interactive.clean_path('"/tmp/My Vault"'), Path("/tmp/My Vault").resolve())
        self.assertEqual(interactive.clean_path("~/notes"), (Path.home() / "notes").resolve())

    def test_output_dir_refuses_dangerous_folders_and_asks_again(self):
        with mock.patch.object(cli, "resolve_auto_out_dir", return_value=self.out_dir):
            chosen = self.ask(interactive.ask_output_dir, ["/", str(Path.home()), str(self.out_dir)])
        self.assertEqual(chosen, self.out_dir)
        self.assertFalse(self.out_dir.exists(), "asking must never create the folder")

    def test_output_dir_enter_accepts_default(self):
        with mock.patch.object(cli, "resolve_auto_out_dir", return_value=self.out_dir):
            self.assertEqual(self.ask(interactive.ask_output_dir, [""]), self.out_dir)

    def test_existing_folder_must_exist(self):
        self.out_dir.mkdir()
        answers = ["", str(self.out_dir / "missing"), str(self.out_dir)]
        self.assertEqual(self.ask(interactive.ask_existing_folder, answers, "Folder"), self.out_dir)
        self.assertIn("is not a folder", self.text())


class ExportFlowTests(InteractiveTestCase):
    def test_quit_right_away_runs_nothing(self):
        mocks = self.run_menu([QUIT])
        mocks.run_auto.assert_not_called()
        mocks.run_fix.assert_not_called()
        self.assertIn("Bye!", self.text())

    def test_ctrl_c_at_the_menu_quits(self):
        mocks = self.run_menu([None])
        mocks.run_auto.assert_not_called()

    def test_refuses_without_a_terminal(self):
        with self.assertRaises(SystemExit) as stop:
            self.run_menu([], tty=False)
        self.assertEqual(stop.exception.code, 1)
        self.assertIn("needs a terminal", self.text())

    def test_sample_run_uses_typed_answers(self):
        # sample, folder, assets=y, date prefix=y, change pace=y -> 1.5, start=y
        mocks = self.run_menu([SAMPLE, str(self.out_dir), "y", "y", "y", "1.5", "y", QUIT])
        mocks.run_auto.assert_called_once_with(
            TOKEN,
            self.out_dir,
            test=True,
            dry_run=False,
            assets=True,
            date_prefix_rows=True,
            rate_limit=1.5,
            exit_on_errors=False,
        )

    def test_full_export_with_all_defaults(self):
        # Enter on the folder question takes the default destination; every yes/no is its default.
        mocks = self.run_menu([EXPORT, "", "", "", "", "", QUIT])
        mocks.run_auto.assert_called_once_with(
            TOKEN,
            self.out_dir,
            test=False,
            dry_run=False,
            assets=False,
            date_prefix_rows=False,
            rate_limit=DEFAULT_REQUESTS_PER_SECOND,
            exit_on_errors=False,
        )

    def test_preview_is_a_dry_run_and_skips_the_assets_question(self):
        # No assets question here: folder, date prefix, pace, start.
        mocks = self.run_menu([PREVIEW, str(self.out_dir), "", "", "y", QUIT])
        kwargs = mocks.run_auto.call_args.kwargs
        self.assertTrue(kwargs["dry_run"])
        self.assertFalse(kwargs["assets"])
        self.assertFalse(kwargs["test"])
        self.assertFalse(self.out_dir.exists(), "a preview must never create the folder")

    def test_dangerous_folder_is_reasked_not_used(self):
        mocks = self.run_menu([SAMPLE, "/", str(self.out_dir), "", "", "", "y", QUIT])
        self.assertEqual(mocks.run_auto.call_args.args[1], self.out_dir)

    def test_declining_the_plan_writes_nothing(self):
        mocks = self.run_menu([EXPORT, str(self.out_dir), "", "", "", "n", QUIT])
        mocks.run_auto.assert_not_called()
        self.assertIn("Nothing was written", self.text())

    def test_plan_summary_is_shown_before_starting(self):
        self.run_menu([SAMPLE, str(self.out_dir), "", "", "", "n", QUIT])
        self.assertIn("Here is the plan", self.text())
        self.assertIn("Quick sample test", self.text())

    def test_token_saved_by_inline_setup_is_used(self):
        mocks = self.run_menu(
            [SAMPLE, "y", str(self.out_dir), "", "", "", "y", QUIT],
            token="",
            token_after_init=TOKEN,
        )
        mocks.cmd_init.assert_called_once_with()
        self.assertEqual(mocks.run_auto.call_args.args[0], TOKEN)

    def test_inline_setup_that_stores_no_token_starts_nothing(self):
        mocks = self.run_menu([SAMPLE, "y", QUIT], token="")
        mocks.cmd_init.assert_called_once_with()
        mocks.run_auto.assert_not_called()
        self.assertIn("A Notion token is needed first", self.text())

    def test_declining_setup_returns_to_menu(self):
        mocks = self.run_menu([SAMPLE, "n", QUIT], token="")
        mocks.cmd_init.assert_not_called()
        mocks.run_auto.assert_not_called()

    def test_token_is_checked_before_use(self):
        with mock.patch.object(cli, "check_token_or_exit") as check:
            mocks = self.run_menu([SAMPLE, str(self.out_dir), "", "", "", "y", QUIT])
        check.assert_called_with(TOKEN)
        mocks.run_auto.assert_called_once()


class SessionResilienceTests(InteractiveTestCase):
    def test_a_failed_export_returns_to_the_menu(self):
        # run_export / confirm_output_dir call sys.exit on errors; the menu must survive that.
        one_run = [SAMPLE, str(self.out_dir), "", "", "", "y"]
        mocks = self.run_menu(
            one_run + one_run + [QUIT],
            run_auto_effect=[SystemExit(1), OK_SUMMARY],
        )
        self.assertEqual(mocks.run_auto.call_count, 2)
        self.assertIn("Back to the menu", self.text())
        self.assertIn("Bye!", self.text())

    def test_ctrl_c_inside_a_flow_goes_back_to_the_menu(self):
        mocks = self.run_menu([SAMPLE, None, QUIT])
        mocks.run_auto.assert_not_called()
        self.assertIn("Cancelled", self.text())

    def test_ctrl_c_at_the_final_confirmation_starts_nothing(self):
        mocks = self.run_menu([SAMPLE, str(self.out_dir), "", "", "", None, QUIT])
        mocks.run_auto.assert_not_called()

    def test_failed_setup_keeps_the_session_alive(self):
        mocks = self.run_menu([SETUP, QUIT], init_error=SystemExit(1))
        mocks.cmd_init.assert_called_once_with()
        self.assertIn("Bye!", self.text())


class FixFlowTests(InteractiveTestCase):
    def setUp(self):
        super().setUp()
        self.out_dir.mkdir()

    def test_preview_then_apply_runs_dry_run_first_with_backup(self):
        # folder, link format=title (2), preview=Enter(yes), apply=Enter(yes after a preview)
        mocks = self.run_menu([FIX, str(self.out_dir), "2", "", "", QUIT])
        self.assertEqual(
            mocks.run_fix.call_args_list,
            [
                mock.call(self.out_dir, dry_run=True, link_format="title"),
                mock.call(self.out_dir, dry_run=False, backup=True, link_format="title"),
            ],
        )

    def test_preview_then_decline_changes_nothing(self):
        mocks = self.run_menu([FIX, str(self.out_dir), "1", "", "n", QUIT])
        mocks.run_fix.assert_called_once_with(self.out_dir, dry_run=True, link_format="wikilink")
        self.assertIn("No files were changed", self.text())

    def test_preview_that_finds_nothing_skips_the_apply_question(self):
        # No answer is scripted for "Apply now?": asking it would fail the test.
        mocks = self.run_menu([FIX, str(self.out_dir), "1", "", QUIT], fix_result={})
        mocks.run_fix.assert_called_once_with(self.out_dir, dry_run=True, link_format="wikilink")
        self.assertIn("Nothing needs fixing", self.text())

    def test_base_only_changes_still_count(self):
        mocks = self.run_menu(
            [FIX, str(self.out_dir), "1", "", "y", QUIT], fix_result={"base_replacements": 1}
        )
        self.assertEqual(mocks.run_fix.call_count, 2)

    def test_skipping_preview_defaults_to_not_applying(self):
        # Without a preview the apply question defaults to "no": Enter must not edit files.
        mocks = self.run_menu([FIX, str(self.out_dir), "1", "n", "", QUIT])
        mocks.run_fix.assert_not_called()

    def test_skipping_preview_can_still_apply_explicitly_with_backup(self):
        mocks = self.run_menu([FIX, str(self.out_dir), "1", "n", "y", QUIT])
        mocks.run_fix.assert_called_once_with(self.out_dir, dry_run=False, backup=True, link_format="wikilink")

    def test_missing_folder_is_reasked(self):
        mocks = self.run_menu([FIX, str(self.out_dir / "nope"), str(self.out_dir), "1", "n", "n", QUIT])
        mocks.run_fix.assert_not_called()
        self.assertIn("is not a folder", self.text())


class SetupFlowTests(InteractiveTestCase):
    def test_setup_runs_init_and_reloads_the_saved_vault(self):
        mocks = self.run_menu([SETUP, QUIT])
        mocks.cmd_init.assert_called_once_with()
        mocks.load_vault.assert_any_call(force=True)


class WelcomeTests(InteractiveTestCase):
    def test_welcome_reports_token_status_without_printing_the_token(self):
        self.run_menu([QUIT])
        self.assertIn("Notion token: found", self.text())
        self.assertNotIn(TOKEN, self.text())

    def test_welcome_flags_a_missing_token(self):
        self.run_menu([QUIT], token="")
        self.assertIn("not set", self.text())


if __name__ == "__main__":
    unittest.main()
