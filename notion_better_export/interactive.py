"""Guided, menu-driven front end for `nbe`.

A bare `nbe` in a terminal (or `nbe interactive`) opens this menu. It only asks questions and
then calls the same functions the flag-based commands use (`cli.run_auto`, `cli.run_fix`,
`cli.cmd_init`), so every failsafe (safe-folder checks, run lock, dry run, fix backups, rate
limit ceiling) applies exactly as it does for `nbe auto` / `nbe fix`.

Plain numbered menus keep it dependency-free and working in Windows terminals as well.
"""

import os
import sys
from pathlib import Path
from typing import Callable, Dict, Optional, Sequence, Tuple

from rich.markup import escape
from rich.table import Table

from notion_better_export import cli
from notion_better_export.client import DEFAULT_REQUESTS_PER_SECOND, NOTION_MAX_REQUESTS_PER_SECOND
from notion_better_export.safety import UnsafeOutputDir, assert_safe_output_dir

Option = Tuple[str, str]

MENU_OPTIONS: Sequence[Option] = (
    ("sample", "Quick sample test: first 5 rows of every database (recommended first run)"),
    ("preview", "Preview the workspace hierarchy (writes nothing)"),
    ("export", "Export my whole Notion workspace to Obsidian"),
    ("fix", "Fix relation links in an existing export"),
    ("setup", "Set up or change my Notion token and vault"),
    ("quit", "Quit"),
)

LINK_FORMAT_OPTIONS: Sequence[Option] = (
    ("wikilink", "Obsidian wikilinks (recommended)"),
    ("title", "Plain titles (good for Excel / Google Sheets)"),
    ("markdown", "Markdown links"),
)

MODE_LABELS = {
    "sample": "Quick sample test (5 rows per database)",
    "preview": "Preview only (nothing is written)",
    "export": "Full live export",
}


class Cancelled(Exception):
    """The user pressed Ctrl-C / Ctrl-D at a prompt: back out of the current flow."""


def _read(prompt: str) -> str:
    """The one place that reads the keyboard, so tests can script a whole session."""
    try:
        return cli.console.input(prompt)
    except (EOFError, KeyboardInterrupt):
        cli.console.print()
        raise Cancelled from None


def ask_text(question: str, default: str = "") -> str:
    hint = f" (default: {escape(default)})" if default else ""
    return _read(f"[cyan]?[/cyan] {question}{hint}: ").strip() or default


def ask_yes_no(question: str, default: bool = False) -> bool:
    hint = "Y/n" if default else "y/N"
    while True:
        answer = _read(f"[cyan]?[/cyan] {question} ({hint}): ").strip().lower()
        if not answer:
            return default
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        cli.console.print("[red]Please answer y or n.[/red]")


def ask_choice(question: str, options: Sequence[Option], default: Optional[str] = None) -> str:
    """Show a numbered list and return the key of the chosen option."""
    keys = [key for key, _ in options]
    for number, (_, label) in enumerate(options, 1):
        cli.console.print(f"  [cyan]{number}[/cyan]) {escape(label)}")
    hint = f" (Enter = {keys.index(default) + 1})" if default in keys else ""
    while True:
        answer = _read(f"[cyan]?[/cyan] {question}{hint}: ").strip().lower()
        if not answer and default in keys:
            return default
        if answer.isdigit() and 1 <= int(answer) <= len(keys):
            return keys[int(answer) - 1]
        if answer in keys:
            return answer
        cli.console.print(f"[red]Please enter a number from 1 to {len(keys)}.[/red]")


def ask_rate_limit() -> float:
    """Ask for a request pace; refuse anything above Notion's limit instead of clamping quietly."""
    while True:
        answer = ask_text(
            f"Requests per second (0 to {NOTION_MAX_REQUESTS_PER_SECOND:g})",
            f"{DEFAULT_REQUESTS_PER_SECOND:g}",
        )
        try:
            value = float(answer)
        except ValueError:
            value = 0.0
        if 0 < value <= NOTION_MAX_REQUESTS_PER_SECOND:
            return value
        cli.console.print(
            f"[red]Enter a number above 0 and at most {NOTION_MAX_REQUESTS_PER_SECOND:g}; "
            "Notion allows about 3 requests per second.[/red]"
        )


def clean_path(raw: str) -> Path:
    """Turn typed, pasted or drag-and-dropped text into an absolute Path."""
    text = raw.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"":
        text = text[1:-1]
    elif os.name != "nt":
        text = text.replace("\\ ", " ")
    return Path(text).expanduser().resolve()


def ask_output_dir() -> Path:
    """Ask where to export, re-asking until the folder passes the hard safety check."""
    default = str(cli.resolve_auto_out_dir())
    while True:
        path = clean_path(ask_text("Where should the export go?", default))
        try:
            assert_safe_output_dir(path)
        except UnsafeOutputDir as problem:
            cli.console.print(f"[red]{escape(str(problem))}[/red]")
            continue
        return path


def ask_existing_folder(question: str) -> Path:
    while True:
        answer = ask_text(question)
        if not answer:
            cli.console.print("[red]Enter a folder path (Ctrl-C goes back to the menu).[/red]")
            continue
        path = clean_path(answer)
        if path.is_dir():
            return path
        cli.console.print(f"[red]{escape(str(path))} is not a folder.[/red]")


def ensure_token() -> Optional[str]:
    """Return the Notion token, offering to run setup when none is stored."""
    token = cli.find_default_token()
    if not token:
        cli.console.print("[yellow]No Notion token found yet.[/yellow]")
        if not ask_yes_no("Set one up now?", default=True):
            return None
        setup_flow()
        token = cli.find_default_token()
        if not token:
            return None
    cli.check_token_or_exit(token)
    return token


def setup_flow() -> None:
    cli.cmd_init()
    # A vault saved just now should win over one loaded earlier in this session.
    cli.load_saved_vault_path(force=True)


def show_plan(rows: Sequence[Tuple[str, str]]) -> None:
    table = Table(title="Here is the plan", show_header=False, box=None, padding=(0, 2))
    for name, value in rows:
        table.add_row(f"[bold]{name}[/bold]", escape(value))
    cli.console.print(table)


def export_flow(mode: str) -> None:
    token = ensure_token()
    if token is None:
        cli.console.print("[yellow]A Notion token is needed first. Choose 'Set up' from the menu.[/yellow]")
        return

    dry_run = mode == "preview"
    out_path = ask_output_dir()
    assets = False if dry_run else ask_yes_no("Download images and file attachments into _assets folders?")
    date_prefix_rows = ask_yes_no("Prefix database row note names with their date (YYYY-MM-DD)?")
    rate_limit = DEFAULT_REQUESTS_PER_SECOND
    if ask_yes_no(
        f"Change the request pace? (default {DEFAULT_REQUESTS_PER_SECOND:g}/s, maximum {NOTION_MAX_REQUESTS_PER_SECOND:g}/s)"
    ):
        rate_limit = ask_rate_limit()

    show_plan(
        [
            ("Mode", MODE_LABELS[mode]),
            ("Destination", str(out_path)),
            ("Attachments", "downloaded to _assets" if assets else "left as Notion links"),
            ("Row note names", "date-prefixed" if date_prefix_rows else "plain titles"),
            ("Request pace", f"{rate_limit:g} requests/sec"),
        ]
    )
    if not ask_yes_no("Start now?", default=True):
        cli.console.print("Nothing was written.")
        return

    cli.run_auto(
        token,
        out_path,
        test=mode == "sample",
        dry_run=dry_run,
        assets=assets,
        date_prefix_rows=date_prefix_rows,
        rate_limit=rate_limit,
        exit_on_errors=False,
    )


def count_replacements(result: dict) -> int:
    """Total relations `nbe fix` would rewrite, from the dict cli.run_fix returns."""
    return sum(result.get(key, 0) for key in ("csv_replacements", "md_replacements", "base_replacements"))


def fix_flow() -> None:
    target_dir = ask_existing_folder("Path to the existing export folder")
    link_format = ask_choice("How should relations look in CSVs?", LINK_FORMAT_OPTIONS, default="wikilink")

    previewed = ask_yes_no("Preview the changes first? (nothing is modified)", default=True)
    if previewed:
        preview = cli.run_fix(target_dir, dry_run=True, link_format=link_format)
        if not count_replacements(preview):
            cli.console.print("Nothing needs fixing. No files were changed.")
            return
    # Editing existing files: default to "no" unless the user has just seen what would change.
    if not ask_yes_no(
        "Apply the changes now? (originals are kept in .nbe-fix-backup/)",
        default=previewed,
    ):
        cli.console.print("No files were changed.")
        return
    cli.run_fix(target_dir, dry_run=False, backup=True, link_format=link_format)


def print_welcome() -> None:
    cli.console.rule("[bold cyan]Notion Better Export[/bold cyan]")
    token = "[green]found[/green]" if cli.find_default_token() else "[yellow]not set (choose 'Set up')[/yellow]"
    cli.console.print(f"Notion token: {token}")
    cli.console.print(f"Default destination: [green]{escape(str(cli.resolve_auto_out_dir()))}[/green]")
    cli.console.print("[dim]Type a number and press Enter. Ctrl-C goes back, or quits from this menu.[/dim]")


def run_interactive() -> None:
    if not cli.is_interactive_terminal():
        cli.console.print(
            "[red]Interactive mode needs a terminal. In scripts use "
            "[bold]nbe auto[/bold] or [bold]nbe export --out <folder>[/bold].[/red]"
        )
        sys.exit(1)

    flows: Dict[str, Callable[[], None]] = {
        "sample": lambda: export_flow("sample"),
        "preview": lambda: export_flow("preview"),
        "export": lambda: export_flow("export"),
        "fix": fix_flow,
        "setup": setup_flow,
    }

    cli.load_saved_vault_path()
    print_welcome()
    while True:
        cli.console.print()
        try:
            choice = ask_choice("What would you like to do?", MENU_OPTIONS)
        except Cancelled:
            break
        if choice == "quit":
            break
        try:
            flows[choice]()
        except Cancelled:
            cli.console.print("[yellow]Cancelled. Back to the menu.[/yellow]")
        except SystemExit:
            # The shared helpers print their own error and then exit; keep the session alive.
            cli.console.print("[yellow]Back to the menu.[/yellow]")
    cli.console.print("Bye!")
