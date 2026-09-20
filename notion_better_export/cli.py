import argparse
import getpass
import os
import stat
import sys
import logging
from pathlib import Path
from typing import Optional
from notion_client.errors import APIResponseError
from rich.console import Console
from rich.logging import RichHandler

from notion_better_export.client import (
    DEFAULT_REQUESTS_PER_SECOND,
    NOTION_MAX_REQUESTS_PER_SECOND,
    NotionApiClient,
)
from notion_better_export.exporter import NotionBetterExporter
from notion_better_export.post_processor import ExportPostProcessor

console = Console()

TOKEN_PREFIXES = ("ntn_", "secret_")
DEFAULT_VAULT_FOLDER = "Notion Better Export"


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, rich_tracebacks=True, show_path=False)],
    )
    # httpx logs full request URLs at INFO; keep them out of the output.
    logging.getLogger("httpx").setLevel(logging.WARNING)


def user_config_path() -> Path:
    """Per-user file where `nbe init` stores the token (works for pipx/pip installs)."""
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "notion-better-export" / "env"


def read_token_from_file(path: Path) -> str:
    """Read NOTION_TOKEN=... from a dotenv-style file; returns '' if absent."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    for line in lines:
        line = line.strip()
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if line.startswith("NOTION_TOKEN="):
            value = line.split("=", 1)[1].strip().strip('"').strip("'")
            # An unedited copy of .env.sample is "no token", not a bad token.
            return "" if "your_notion_integration_token_here" in value else value
    return ""


def find_default_token() -> str:
    """Find the Notion token: $NOTION_TOKEN, then ./.env, then the `nbe init` config."""
    token = os.environ.get("NOTION_TOKEN")
    if token:
        return token.strip()
    return read_token_from_file(Path(".env")) or read_token_from_file(user_config_path())


def resolve_auto_out_dir(custom_out: str = "") -> Path:
    """Determine where `auto` mode writes.

    Priority: --out, $EXPORT_OUT_DIR, $VAULT_PATH (exports into a
    "Notion Better Export" folder inside the vault), then ./output.
    """
    if custom_out:
        return Path(custom_out).expanduser().resolve()

    env_out = os.environ.get("EXPORT_OUT_DIR")
    if env_out:
        return Path(env_out).expanduser().resolve()

    vault_path = os.environ.get("VAULT_PATH")
    if vault_path:
        vp = Path(vault_path).expanduser().resolve()
        return vp if vp.name == DEFAULT_VAULT_FOLDER else vp / DEFAULT_VAULT_FOLDER

    return Path("./output").resolve()


def check_token_or_exit(token: str) -> None:
    """Warn about odd-looking tokens without ever echoing the value."""
    if not token.startswith(TOKEN_PREFIXES):
        console.print(
            "[yellow]Warning: token does not start with ntn_ or secret_; "
            "double-check you copied the Internal Integration Secret.[/yellow]"
        )


def run_export(exporter: NotionBetterExporter) -> dict:
    """Run an exporter, turning the common failures into actionable messages."""
    try:
        return exporter.run()
    except APIResponseError as err:
        if err.status == 401:
            console.print(
                "[red]Notion rejected the token (401 unauthorized). "
                "Re-run `nbe init` or check NOTION_TOKEN.[/red]"
            )
        elif err.status == 403:
            console.print(
                "[red]The integration lacks permission (403). Make sure it has "
                "'Read content' capability and is connected to your pages.[/red]"
            )
        else:
            console.print(f"[red]Notion API error ({err.status}): {err.message}[/red]")
        sys.exit(1)
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted. Partial output may remain on disk.[/yellow]")
        sys.exit(130)


def cmd_init(vault: Optional[str] = None) -> None:
    """Interactively store the token in a private per-user config file."""
    console.rule("[bold cyan]Notion Better Export — Setup[/bold cyan]")
    console.print(
        "1. Create an integration at https://www.notion.so/profile/integrations\n"
        "   (Internal, [bold]Read content[/bold] only — the exporter never writes to Notion).\n"
        "2. In Notion, open each top-level page → ••• → Connections → add your integration.\n"
        "3. Paste the Internal Integration Secret below (input is hidden).\n"
    )
    token = getpass.getpass("Notion token: ").strip()
    if not token:
        console.print("[red]No token entered; nothing saved.[/red]")
        sys.exit(1)
    check_token_or_exit(token)

    try:
        bot = NotionApiClient(token).whoami()
    except APIResponseError as err:
        console.print(f"[red]Notion rejected that token ({err.status}). Nothing saved.[/red]")
        sys.exit(1)
    name = bot.get("name") or "integration"
    console.print(f"[green]✓ Token works — connected as '{name}'.[/green]")

    if vault is None:
        vault = input("Obsidian vault path (optional, press Enter to skip): ").strip()

    cfg = user_config_path()
    cfg.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"NOTION_TOKEN={token}"]
    if vault:
        lines.append(f"VAULT_PATH={Path(vault).expanduser()}")
    # Create with owner-only permissions from the start (no world-readable window).
    fd = os.open(cfg, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    console.print(f"[green]Saved to {cfg} (owner-only permissions).[/green]")
    console.print("Next: [bold]nbe auto --dry-run[/bold] to preview, then [bold]nbe auto[/bold].")


def load_saved_vault_path() -> None:
    """Let `nbe init` supply VAULT_PATH without overriding the real environment."""
    if os.environ.get("VAULT_PATH"):
        return
    try:
        lines = user_config_path().read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        if line.startswith("VAULT_PATH="):
            os.environ["VAULT_PATH"] = line.split("=", 1)[1].strip()
            return


def main() -> None:
    known_subcommands = {"auto", "export", "fix", "init"}
    if len(sys.argv) == 1:
        sys.argv.append("auto")
    elif len(sys.argv) > 1 and sys.argv[1] == "test":
        sys.argv[1] = "auto"
        sys.argv.insert(2, "--test")
    elif len(sys.argv) > 1 and sys.argv[1] not in known_subcommands and sys.argv[1] not in ("-h", "--help"):
        sys.argv.insert(1, "auto")

    parser = argparse.ArgumentParser(
        prog="notion-better-export",
        description="High-fidelity Notion workspace exporter preserving folder hierarchy & linked CSVs",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose debug logging")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # ------------------ Command: auto (smart zero-config) ------------------
    auto_parser = subparsers.add_parser(
        "auto",
        help="Smart zero-config auto mode: automatically detects vault path, token, and applies optimal flags",
    )
    auto_parser.add_argument(
        "--test",
        "-t",
        action="store_true",
        help="Run quick sample test (first 5 rows per database)",
    )
    auto_parser.add_argument(
        "--dry-run",
        "-d",
        action="store_true",
        help="Preview workspace hierarchy without writing files",
    )
    auto_parser.add_argument(
        "--assets",
        "-a",
        action="store_true",
        help="Download image and file attachments locally into _assets",
    )
    auto_parser.add_argument(
        "--out",
        "-o",
        default="",
        help="Override output directory (defaults to Obsidian Vault/Notion Better Export)",
    )
    auto_parser.add_argument(
        "--rate-limit",
        type=float,
        default=DEFAULT_REQUESTS_PER_SECOND,
        metavar="RPS",
        help="Max Notion API requests per second (default: %s, ceiling: %s)" % (DEFAULT_REQUESTS_PER_SECOND, NOTION_MAX_REQUESTS_PER_SECOND),
    )
    auto_parser.add_argument(
        "--date-prefix-rows",
        action="store_true",
        help="Prefix database row notes with date (YYYY-MM-DD)",
    )
    auto_parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose debug logging",
    )

    # ------------------ Command: export ------------------
    export_parser = subparsers.add_parser("export", help="Run live export from Notion API")
    export_parser.add_argument(
        "--out",
        "-o",
        required=True,
        help="Target output directory (e.g. ~/Vault/Notion)",
    )
    export_parser.add_argument(
        "--token",
        "-t",
        default="",
        help="Notion token. Prefer $NOTION_TOKEN, .env or `nbe init`: a token on the command line lands in shell history and `ps`.",
    )
    export_parser.add_argument(
        "--rate-limit",
        type=float,
        default=DEFAULT_REQUESTS_PER_SECOND,
        metavar="RPS",
        help="Max Notion API requests per second (default: %s, ceiling: %s)" % (DEFAULT_REQUESTS_PER_SECOND, NOTION_MAX_REQUESTS_PER_SECOND),
    )
    export_parser.add_argument(
        "--csv-link-format",
        choices=["wikilink", "title", "markdown"],
        default="wikilink",
        help="Format for relation values in CSVs (default: wikilink)",
    )
    export_parser.add_argument(
        "--no-note-link",
        action="store_true",
        help="Do not add 'Note Link' column to CSV files",
    )
    export_parser.add_argument(
        "--no-csv",
        action="store_true",
        help="Skip generating CSV files for databases",
    )
    export_parser.add_argument(
        "--no-base",
        action="store_true",
        help="Skip generating Obsidian .base files",
    )
    export_parser.add_argument(
        "--download-assets",
        action="store_true",
        help="Download image and file attachments into local _assets folders",
    )
    export_parser.add_argument(
        "--skip-database",
        action="append",
        default=[],
        help="Exact database title to skip (repeatable)",
    )
    export_parser.add_argument(
        "--max-rows",
        type=int,
        default=None,
        help="Maximum rows to export per database (for testing)",
    )
    export_parser.add_argument(
        "--vault-subpath",
        default="",
        help="Relative path from Obsidian vault root to --out (for .base filters)",
    )
    export_parser.add_argument(
        "--date-prefix-rows",
        action="store_true",
        help="Prefix database row markdown filenames with their date or creation date (e.g. YYYY-MM-DD Note.md)",
    )
    export_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Walk and preview the export without writing files",
    )

    # ------------------ Command: init ------------------
    init_parser = subparsers.add_parser(
        "init",
        help="One-time setup: validate your Notion token and store it privately",
    )
    init_parser.add_argument(
        "--vault",
        default=None,
        help="Obsidian vault path to remember (skips the prompt)",
    )

    # ------------------ Command: fix (post-processor) ------------------
    fix_parser = subparsers.add_parser(
        "fix",
        help="Post-process an existing export folder to resolve CSV UUIDs and links",
    )
    fix_parser.add_argument(
        "--dir",
        "-d",
        required=True,
        help="Path to existing Notion export directory",
    )
    fix_parser.add_argument(
        "--manifest",
        "-m",
        default=None,
        help="Path to notion_export_manifest.json (defaults to manifest inside --dir)",
    )
    fix_parser.add_argument(
        "--csv-link-format",
        choices=["wikilink", "title", "markdown"],
        default="wikilink",
        help="Format for resolved relations in CSVs (default: wikilink)",
    )

    args = parser.parse_args()
    setup_logging(args.verbose)

    if args.command == "init":
        cmd_init(args.vault)
        return

    if args.command == "auto":
        token = find_default_token()
        if not token:
            console.print(
                "[red]No Notion token found. Run [bold]nbe init[/bold] or set NOTION_TOKEN.[/red]"
            )
            sys.exit(1)
        check_token_or_exit(token)
        load_saved_vault_path()

        out_path = resolve_auto_out_dir(args.out)
        max_rows = 5 if args.test else None
        mode_desc = (
            "Dry Run (Preview Only)"
            if args.dry_run
            else ("Quick Sample Test (5 rows/db)" if args.test else "Full Live Export")
        )

        console.rule("[bold cyan]🚀 Notion Better Export — Auto Mode[/bold cyan]")
        console.print(f"[bold]Vault Destination:[/bold] [green]{out_path}[/green]")
        console.print(f"[bold]Execution Mode:[/bold]    [yellow]{mode_desc}[/yellow]")
        console.print(f"[bold]Pacing Rate:[/bold]       {min(args.rate_limit, NOTION_MAX_REQUESTS_PER_SECOND):g} requests/sec (proactive rate limit)")
        console.print("[bold]CSV Linking:[/bold]       Obsidian [[wikilinks]] + Note Links")
        console.print("[bold]Obsidian Bases:[/bold]    Enabled (.base files)")
        console.print("[bold]Linked Views:[/bold]      Auto-deduplicated to canonical databases")
        if args.assets:
            console.print("[bold]Asset Downloads:[/bold]   Enabled (local _assets folders)")
        console.rule()

        exporter = NotionBetterExporter(
            token=token,
            out_dir=out_path,
            max_rows_per_db=max_rows,
            download_assets=args.assets,
            dry_run=args.dry_run,
            csv_link_format="wikilink",
            include_csv_note_link=True,
            write_csv=True,
            write_base=True,
            date_prefix_rows=args.date_prefix_rows,
            requests_per_second=args.rate_limit,
        )
        summary = run_export(exporter)
        console.print(
            f"\n[bold green]✓ Done! Processed {summary['exported_objects']} objects with {len(summary['errors'])} errors.[/bold green]"
        )
        if not args.dry_run:
            console.print(
                f"[cyan]You can now open Obsidian to view your vault at:[/cyan]\n  [bold]{out_path}[/bold]"
            )

    elif args.command == "export":
        token = args.token or find_default_token()
        if not token:
            console.print(
                "[red]No Notion token found. Run [bold]nbe init[/bold], set NOTION_TOKEN, or add it to .env.[/red]"
            )
            sys.exit(1)
        check_token_or_exit(token)

        out_path = Path(args.out).expanduser().resolve()
        console.print(f"[bold cyan]Notion Better Export[/bold cyan] → [green]{out_path}[/green]")

        exporter = NotionBetterExporter(
            token=token,
            out_dir=out_path,
            skip_databases=args.skip_database,
            max_rows_per_db=args.max_rows,
            download_assets=args.download_assets,
            dry_run=args.dry_run,
            vault_subpath=args.vault_subpath,
            csv_link_format=args.csv_link_format,
            include_csv_note_link=not args.no_note_link,
            write_csv=not args.no_csv,
            write_base=not args.no_base,
            date_prefix_rows=args.date_prefix_rows,
            requests_per_second=args.rate_limit,
        )
        summary = run_export(exporter)
        console.print(
            f"[bold green]✓ Done! Processed {summary['exported_objects']} objects with {len(summary['errors'])} errors.[/bold green]"
        )

    elif args.command == "fix":
        target_dir = Path(args.dir).expanduser().resolve()
        console.print(f"[bold cyan]Fixing existing export in:[/bold cyan] {target_dir}")

        manifest_file = Path(args.manifest).expanduser().resolve() if args.manifest else None
        processor = ExportPostProcessor(
            export_dir=target_dir,
            manifest_path=manifest_file,
            link_format=args.csv_link_format,
        )
        res = processor.run_all()
        base_info = f", and {res.get('base_replacements', 0)} Base relations across {res.get('base_files', 0)} Bases" if res.get("base_files", 0) > 0 else ""
        console.print(
            f"[bold green]✓ Complete! Replaced {res['csv_replacements']} CSV relations across {res['csv_files']} CSVs, {res['md_replacements']} markdown frontmatter relations across {res['md_files']} notes{base_info}.[/bold green]"
        )


if __name__ == "__main__":
    main()
