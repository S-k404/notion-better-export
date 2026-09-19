import argparse
import os
import sys
import logging
from pathlib import Path
from rich.console import Console
from rich.logging import RichHandler

from notion_better_export.exporter import NotionBetterExporter
from notion_better_export.post_processor import ExportPostProcessor

console = Console()


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, rich_tracebacks=True, show_path=False)],
    )


def find_default_token() -> str:
    """Find NOTION_TOKEN from environment, current .env, or adjacent Notoma/.env."""
    token = os.environ.get("NOTION_TOKEN")
    if token:
        return token

    # Check local .env
    local_env = Path(".env")
    if local_env.exists():
        for line in local_env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("NOTION_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")

    # Check ../Notoma/.env
    notoma_env = Path("../Notoma/.env")
    if notoma_env.exists():
        for line in notoma_env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("NOTION_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")

    return ""


def resolve_auto_out_dir(custom_out: str = "") -> Path:
    """Intelligently determine the optimal Obsidian vault export directory."""
    if custom_out:
        return Path(custom_out).expanduser().resolve()

    # 1. Check EXPORT_OUT_DIR env var
    env_out = os.environ.get("EXPORT_OUT_DIR")
    if env_out and env_out != "./output":
        return Path(env_out).expanduser().resolve()

    # 2. Check VAULT_PATH env var
    vault_path = os.environ.get("VAULT_PATH")
    if vault_path:
        vp = Path(vault_path).expanduser().resolve()
        # If pointing to a test folder or general vault, export to "Notion Better Export"
        if vp.name in ("Noma Test", "Notion Export"):
            return vp.parent / "Notion Better Export"
        if "Obsidian Vault" in str(vp):
            return vp if vp.name == "Notion Better Export" else vp / "Notion Better Export"
        return vp

    # 3. Standard default for user's obsidian vault
    candidate = Path("/Users/shamit/Documents/Docker/Obsidian/Obsidian Vault/Notion Better Export")
    if candidate.parent.exists():
        return candidate

    return Path("./output").resolve()


def main() -> None:
    known_subcommands = {"auto", "export", "fix"}
    if len(sys.argv) == 1:
        sys.argv.append("auto")
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
        help="Notion integration token (starts with ntn_ or secret_). Defaults to $NOTION_TOKEN or .env",
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

    if args.command == "auto":
        token = find_default_token()
        if not token:
            console.print(
                "[red]Error: No Notion token found in environment or .env.[/red]"
            )
            sys.exit(1)

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
        console.print("[bold]Pacing Rate:[/bold]       2.8 requests/sec (proactive rate limit)")
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
        )
        summary = exporter.run()
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
                "[red]Error: No Notion token found. Pass --token, set $NOTION_TOKEN, or add to .env.[/red]"
            )
            sys.exit(1)

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
        )
        summary = exporter.run()
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
        console.print(
            f"[bold green]✓ Complete! Replaced {res['csv_replacements']} CSV relations across {res['csv_files']} CSVs, and {res['md_replacements']} markdown frontmatter relations across {res['md_files']} notes.[/bold green]"
        )


if __name__ == "__main__":
    main()
