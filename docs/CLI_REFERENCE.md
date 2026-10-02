# CLI Reference

Full flag-by-flag reference for every `nbe` / `notion-better-export` subcommand. For a guided walkthrough with examples, see the [README](../README.md#-cli-usage).

## Global flags

| Flag | Description |
| :--- | :--- |
| `-V, --version` | Print the installed version and exit |
| `-v, --verbose` | Enable verbose debug logging |

Running `nbe` with no subcommand in a terminal opens the interactive menu; the same with no terminal (cron, CI, pipes) runs `nbe auto`. Running `nbe <flags>` with no recognised subcommand (e.g. `nbe --test`) is shorthand for `nbe auto <flags>`.

## `nbe interactive`

Guided menu: export, preview, fix, or set up a token by answering questions. Calls the same `run_auto` / `run_fix` / `cmd_init` functions as the flag commands below, so every safety net still applies. Takes no flags of its own — see the [README](../README.md#1-interactive-menu-easiest) for the question flow.

## `nbe auto`

Zero-config export: detects your Notion token and Obsidian vault, and applies the recommended settings (wikilinks, `Note Link` column, Bases on).

| Flag | Default | Description |
| :--- | :--- | :--- |
| `--test, -t` | `False` | Quick sample test: first 5 rows per database |
| `--dry-run, -d` | `False` | Preview the workspace hierarchy without writing files |
| `--assets, -a` | `False` | Download image/file attachments locally into `_assets/` |
| `--out, -o` | *(auto-detected)* | Override the output directory (defaults to `$EXPORT_OUT_DIR`, then `$VAULT_PATH/Notion Better Export`, then `./output`) |
| `--force` | `False` | Skip the confirmation for non-empty folders and low disk space |
| `--rate-limit RPS` | `2.8` | Max Notion API requests/second (ceiling `3.0`) |
| `--date-prefix-rows` | `False` | Prefix database row notes with `YYYY-MM-DD` |
| `-v, --verbose` | `False` | Enable verbose debug logging |

## `nbe export`

Full manual control over the export: custom directory, link format, skipped databases, row caps.

| Flag | Default | Description |
| :--- | :--- | :--- |
| `--out, -o` | *Required* | Target export directory |
| `--token, -t` | `$NOTION_TOKEN` / `.env` / `nbe init` | Notion API token. Prefer the env/`.env`/`nbe init` route — a token passed on the command line lands in shell history and `ps` |
| `--force` | `False` | Skip the confirmation for non-empty folders and low disk space |
| `--rate-limit RPS` | `2.8` | Max Notion API requests/second (ceiling `3.0`) |
| `--csv-link-format` | `wikilink` | Relation cell format in CSVs: `wikilink`, `title`, or `markdown` |
| `--no-note-link` | `False` | Omit the `Note Link` column from CSV files |
| `--no-csv` | `False` | Skip generating CSV files for databases |
| `--no-base` | `False` | Skip generating Obsidian `.base` files |
| `--download-assets` | `False` | Download image/file attachments into local `_assets/` folders |
| `--skip-database TITLE` | `[]` | Exact database title to skip (repeatable) |
| `--max-rows N` | `None` (all) | Maximum rows to export per database (useful for testing) |
| `--vault-subpath` | `""` | Relative path from the Obsidian vault root to `--out`, used for `.base` folder filters |
| `--date-prefix-rows` | `False` | Prefix database row filenames with their date (`YYYY-MM-DD Note.md`) |
| `--dry-run` | `False` | Walk and preview the export without writing files |

## `nbe init`

One-time setup: validates your Notion token and stores it privately (mode `0600`).

| Flag | Default | Description |
| :--- | :--- | :--- |
| `--vault` | *(prompted)* | Obsidian vault path to remember, skipping the prompt |

## `nbe fix`

Offline post-processor: repairs UUIDs in an existing export's CSVs, Markdown frontmatter, and `.base` files, without any API access.

| Flag | Default | Description |
| :--- | :--- | :--- |
| `--dir, -d` | *Required* | Path to an existing Notion export directory |
| `--manifest, -m` | `<dir>/notion_export_manifest.json` | Path to the export manifest, if not alongside the export |
| `--dry-run` | `False` | Report what would change without modifying any file |
| `--no-backup` | `False` | Do not keep originals of changed files in `.nbe-fix-backup/` |
| `--csv-link-format` | `wikilink` | Format for resolved relations in CSVs: `wikilink`, `title`, or `markdown` |

## Exit codes

`0` success · `1` refused or fatal error · `2` finished but some items failed (see `notion_export_errors.log`). These apply to `auto`, `export`, and `fix`; the interactive menu always exits `0` on quit, so scripts that need exit codes should use the flag commands directly.
