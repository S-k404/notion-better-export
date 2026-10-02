<div align="center">

# 🚀 Notion Better Export

**High-fidelity Notion workspace exporter preserving folder hierarchy, Obsidian Bases, and linked CSV databases.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10%2B-brightgreen.svg)](https://www.python.org/)
[![CI](https://github.com/S-k404/notion-better-export/actions/workflows/ci.yml/badge.svg)](https://github.com/S-k404/notion-better-export/actions/workflows/ci.yml)

*Export your entire Notion workspace into Obsidian without flat directory dumps, broken relation UUIDs, or empty database placeholders.*

</div>

---

## ⚡ The Problem with Default Notion Exports

When exporting large workspaces containing nested pages and relational databases, Notion's standard export:
1. **Flattens your hierarchy**: Subpages and databases often end up in random top-level folders with long hash suffixes (`Untitled 3ce453...`).
2. **Breaks database relations**: Relation columns in CSVs contain unreadable raw UUIDs (`3ce453c2-1690-817e-...`) instead of titles or notes.
3. **Loses inline database views**: Pages embedding database views (e.g. attendance boards, course task lists) are exported as empty or missing blocks.
4. **Disconnects table rows from notes**: Row markdown files have no backlinks to their parent CSV or vice-versa.

**Notion Better Export** solves all of these problems automatically.

---

## ✨ Key Features

- 📁 **True Nested Hierarchy**: Mirrors Notion's parent-child tree. `Page.md` is stored directly alongside `Page/` directory containing all its subpages and child databases.
- 📊 **Native Obsidian Bases (`.base`)**: Generates official Obsidian Bases files matching Notion's exact view configurations (column order, hidden columns left out, and sort direction).
- 🔗 **Embedded Interactive Tables**: Inline database views render inside markdown notes as live Obsidian Bases embeds (`![[View.base]]`), reproducing Notion's reading and dashboard experience 1:1.
- 🗃️ **Linked CSV Databases**:
  - Automatically resolves UUID relation cells into human-readable titles or Obsidian `[[wikilinks]]`.
  - Injects a `Note Link` column linking every row directly to its Markdown note file (`[[Database/2026-09-16 Note.md]]`).
- 🧠 **Smart Linked View Deduplication**: Recognizes linked views across different pages, pointing them to their single canonical home rather than generating duplicated orphaned folders.
- ⏱️ **Proactive Rate Limiting**: Built-in 2.8 req/sec pacing (Notion allows an average of 3) that avoids HTTP 429s, honours `Retry-After`, and backs off on transient errors. See [Notion rate limits](#-notion-rate-limits).
- 💬 **Interactive Menu**: run `nbe` and answer a few questions; no flags to remember. Guided sample run, preview, full export, offline fix and token setup, with a plan shown before anything starts. It runs on the same code (and safety nets) as the flag commands, and scripts keep using `nbe auto` / `nbe export` unchanged. See [Interactive Menu](#1-interactive-menu-easiest).
- 🛠️ **Dual Operation Modes**:
  - **Live Crawl**: Full workspace export directly via the Notion API.
  - **Offline Fixer**: Post-processes existing Notion export folders, resolving broken UUIDs in CSVs, Markdown frontmatter, and Base files.

---

## 📦 Installation

Requires Python 3.10+. The easiest, safest way is **pipx** (it gives the tool its own isolated environment and puts `nbe` on your PATH):

```bash
# macOS:            brew install pipx
# Linux / Windows:  python3 -m pip install --user pipx
pipx ensurepath        # one-time; then open a NEW terminal window
pipx install git+https://github.com/S-k404/notion-better-export.git
nbe --help             # check it worked
```

Prefer `uv`? `uv tool install git+https://github.com/S-k404/notion-better-export.git`

**From source** (for development):
```bash
git clone https://github.com/S-k404/notion-better-export.git
cd notion-better-export
uv sync && uv run nbe --help        # or: python3 -m venv .venv && .venv/bin/pip install -e .
```

Both `notion-better-export` and the shorthand `nbe` are installed.

> ⚠️ **Don't use plain `pip install` on macOS/Linux system Python.** Homebrew and most Linux distros refuse it (`externally-managed-environment`). Use `pipx` or `uv` as above, or a virtual environment.

**Upgrade:** `pipx upgrade notion-better-export` &nbsp;·&nbsp; **Uninstall:** `pipx uninstall notion-better-export`

---

## 🔑 Getting started (5 minutes)

Every user exports **their own** workspace with **their own** Notion integration. Nothing is shared and nothing leaves your machine except calls to `api.notion.com`.

1. Go to [Notion Developers: My Integrations](https://www.notion.so/profile/integrations) → **+ New integration** (type: *Internal*).
2. Under **Capabilities** tick **Read content** only. The exporter never writes to Notion, so don't grant more.
3. Copy the **Internal Integration Secret** (`ntn_...` or `secret_...`).
4. **Give the integration access to your pages.** An integration sees *only* what you connect: open each top-level page in Notion → `•••` → **Connections** → add your integration. Child pages and databases inherit access.
5. Store the token privately:
   ```bash
   nbe init          # hidden prompt, validates the token, saves it with 0600 permissions
   ```
   Or run `nbe` and choose **Set up** in the menu (it also offers this by itself when no token is found). Or, if you prefer a file: `cp .env.sample .env` and set `NOTION_TOKEN=...` (`.env` is git-ignored).
6. Preview, then export. The easiest way is the guided menu, which asks you what it needs:
   ```bash
   nbe                  # opens the interactive menu (token setup, sample run, preview, export, fix)
   ```
   Or use the flags directly:
   ```bash
   nbe auto --dry-run   # nothing is written
   nbe auto             # full export
   ```

> 🔒 **Keep your token secret.** Never commit `.env`, never paste the token into issues, and prefer `nbe init`/`.env` over `--token` (command-line arguments end up in shell history). See [SECURITY.md](SECURITY.md).

---

## ⏱️ Notion rate limits

Notion allows an **average of 3 requests per second** per integration and answers with HTTP 429 beyond that. `nbe` paces itself at **2.8 req/s**, so large workspaces run steadily instead of stalling on throttling. If Notion still returns 429, `nbe` waits for the `Retry-After` time it sends and retries, with exponential backoff on 5xx/network errors.

- Expect roughly **1 request per page/block-level fetch**: a workspace with thousands of pages takes minutes to hours. Use `nbe auto --test` (5 rows per database) first.
- Sharing the integration with other tools? Lower the pace: `nbe auto --rate-limit 1.5`. The rate can go *down* but never above Notion's limit of 3.
- `Ctrl-C` is safe; re-running overwrites the same files.

---

## 🛡️ Built-in safety nets

| Situation | What `nbe` does |
| :--- | :--- |
| Ctrl-C, crash or power loss mid-export | Every file is written to a temp file and swapped in only when complete, so you never get half-written notes. Re-running is safe. |
| You point `--out` at your home folder, `/`, or a system folder | Refused outright. |
| You point `--out` at a folder with your own notes in it | Asks first (or refuses when not interactive) unless you pass `--force`. Folders `nbe` created before don't ask. |
| Low disk space (< 200 MB) | Warns before starting. |
| Two exports at once into the same folder | The second one refuses (`.nbe.lock`). A crashed run's stale lock is cleared automatically. |
| Token revoked or wrong mid-run | Stops at once with a clear message instead of logging thousands of errors. |
| Notion or your network is down | Stops after 25 consecutive failures. Pages that simply aren't shared with the integration (404/403) never count. |
| Some pages fail | The rest still export. Failures are listed at the end and saved to `notion_export_errors.log`, and `nbe` exits with code **2** so scripts can notice. |
| `nbe fix` rewriting an existing export | `--dry-run` previews; originals of changed files are kept in `.nbe-fix-backup/` (`--no-backup` to skip). |
| Page titled `CON`, `NUL`, `COM1`… | Renamed with a leading `_` so the vault still syncs to Windows. |
| Menu: you type `/`, your home folder or a system folder as the destination | Refused with the reason, then asked again. The folder is never created. |
| Menu: you decline the plan or press `Ctrl-C` before "Start now?" | Nothing is written; you are back at the menu. |
| Menu: an export fails or is interrupted | The error is explained and you return to the menu instead of getting a traceback. |
| Menu: fixing an existing export | Previews first by default. "Apply now?" defaults to **no** unless you just saw the preview, skips itself when there is nothing to fix, and always keeps backups (the menu never offers `--no-backup`). |
| Menu: request pace | Anything above Notion's limit of 3/s is rejected, not silently clamped. |
| `nbe` with no arguments, but no terminal (cron, CI, pipes) | Never prompts; runs `nbe auto` as before. `nbe interactive` refuses to start. |

Exit codes for the flag commands: `0` success, `1` refused or fatal error, `2` finished but some items failed. The interactive menu keeps running after an error and exits `0` when you quit, so use `nbe auto` / `nbe export` in scripts that need exit codes.

---

## 🔐 Your files & privacy

- Exports are written **only** to the folder you choose (`--out`, `EXPORT_OUT_DIR`, or `VAULT_PATH`; default `./output`).
- The token is never written into the export, logs, or manifest. Signed file URLs are stripped of their credentials before being logged.
- `--assets` downloads attachments over `http(s)` only, with a 30 s timeout and 200 MB cap per file. Notion's file links expire after about an hour, so download assets in the same run rather than later.
- Your export contains private notes: don't commit `output/`, your vault, or `notion_export_manifest.json` to a public repo.

---

## 🚀 CLI Usage

The CLI provides two command names: `notion-better-export` and `nbe`.

| Command | Use it for |
| :--- | :--- |
| `nbe` / `nbe interactive` | Guided menu: answer questions instead of remembering flags (a bare `nbe` opens it in a terminal) |
| `nbe auto` | Zero-config export for scripts and repeat runs |
| `nbe export` | Full control: custom folder, link format, skipped databases, row caps |
| `nbe fix` | Repair relations in an existing export, offline |
| `nbe init` | Store your Notion token (and optionally your vault) privately |

### 1. Interactive Menu (easiest)
Run `nbe` with no arguments in a terminal (or `nbe interactive`) and answer the questions:

```
? What would you like to do?
  1) Quick sample test: first 5 rows of every database (recommended first run)
  2) Preview the workspace hierarchy (writes nothing)
  3) Export my whole Notion workspace to Obsidian
  4) Fix relation links in an existing export
  5) Set up or change my Notion token and vault
  6) Quit
```

Each menu option is a guided version of a command you already know:

| Option | Same as | What it asks |
| :--- | :--- | :--- |
| 1. Quick sample test | `nbe auto --test` | Destination folder, attachments, date-prefixed row notes, request pace |
| 2. Preview | `nbe auto --dry-run` | Same, without the attachments question. Writes nothing and never creates the folder |
| 3. Export | `nbe auto` | Same as option 1, for the whole workspace |
| 4. Fix | `nbe fix` | Export folder, CSV link format, then preview → apply |
| 5. Set up | `nbe init` | Token (hidden input, validated) and optional vault path |

Options 1–3 end with a plan and a **Start now?** confirmation, for example:

```
                          Here is the plan
  Mode              Quick sample test (5 rows per database)
  Destination       /Users/you/Obsidian Vault/Notion Better Export
  Attachments       left as Notion links
  Row note names    plain titles
  Request pace      2.8 requests/sec
? Start now? (Y/n):
```

How it behaves:

- Type a number (or the option's name) and press Enter; **Enter alone accepts the default** shown in each question. Dragging a folder into the terminal or pasting a quoted path works. `Ctrl-C` cancels the current question flow and returns to the menu, and quits from the menu itself.
- It finds your token and vault the same way `auto` does (`$NOTION_TOKEN`, `./.env`, `nbe init`; `$EXPORT_OUT_DIR` / `$VAULT_PATH`), and offers to run setup when no token is found. The token is never printed.
- It runs the same code as the flag commands, so every safety net still applies. Unsafe folders are refused and you are asked again, the pace can't exceed Notion's limit, and `fix` previews first and keeps backups.
- The menu's export uses the same settings as `nbe auto` (wikilinks plus a `Note Link` column, Bases on). For other link formats, skipped databases or row caps, use `nbe export`.
- It only opens in a real terminal. `nbe` with no arguments in a script, cron job or CI still runs `nbe auto`, exactly as before, and `nbe interactive` there exits with a message instead of hanging.

### 2. Smart Auto Mode (for scripts and repeat runs)
Automatically detects your Notion token, locates your Obsidian Vault, and applies optimal settings:

```bash
# Full live export directly into your Obsidian Vault
nbe auto

# Preview workspace hierarchy without writing files
nbe auto --dry-run    # or: nbe auto -d

# Quick sample test (exports first 5 rows per database)
nbe auto --test       # or: nbe auto -t

# Download image and file attachments locally into _assets/
nbe auto --assets     # or: nbe auto -a

# Prefix database row notes with date (YYYY-MM-DD)
nbe auto --date-prefix-rows

# Slow down to share the API budget with other integrations
nbe auto --rate-limit 1.5
```

Where `auto` writes: `--out`, else `$EXPORT_OUT_DIR`, else `$VAULT_PATH/Notion Better Export`, else `./output`.

> **Tip**: You can also use the included `./run.sh` script:
> ```bash
> ./run.sh            # Opens the interactive menu in a terminal (uses uv or .venv if present)
> ./run.sh test       # Runs auto --test
> ./run.sh --dry-run  # Runs auto --dry-run
> ```

---

### 3. Manual Export Mode (Custom Configuration)
Specify exact target directories, custom link formats, and filters:

```bash
# Export to a custom directory
nbe export --out ~/Documents/Vault/Notion

# Export with clean plain titles in CSVs (great for Excel / Google Sheets)
nbe export --out ./output --csv-link-format title

# Export with standard markdown links in CSVs
nbe export --out ./output --csv-link-format markdown

# Skip specific large databases
nbe export --out ./output --skip-database "Archived Logs" --skip-database "Old Invoices"

# Set max rows per database for testing
nbe export --out ./output --max-rows 10
```

Full flag list (including `--skip-database`, `--vault-subpath`, and every default) is in [docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md#nbe-export).

---

### 4. Offline Post-Processor (`fix`)
If you already have a Notion export directory with raw UUIDs in CSV files or frontmatter:

```bash
# Automatically resolve UUIDs in CSVs, Markdown frontmatter, and Bases
nbe fix --dir "/path/to/Obsidian Vault/Notion Export" --dry-run   # preview first
nbe fix --dir "/path/to/Obsidian Vault/Notion Export"             # originals go to .nbe-fix-backup/
```

---

## 🐳 Docker Support

```bash
cp .env.sample .env                    # add your NOTION_TOKEN
mkdir -p vault                         # create it yourself so it isn't root-owned on Linux
docker compose build
docker compose run --rm notion-export  # exports into ./vault/Notion Better Export
VAULT_DIR="$HOME/Obsidian Vault" docker compose run --rm notion-export   # or into your vault
docker compose run --rm notion-export auto --dry-run
```

The image runs as a non-root user and the token is passed at run time; it is never baked into the image (`.env` is excluded by `.dockerignore`).

---

## 🩹 Troubleshooting

| Symptom | Fix |
| :--- | :--- |
| `command not found: nbe` | It isn't installed, or your PATH is stale. Install with `pipx` (see above), run `pipx ensurepath`, and open a **new** terminal. If you used a venv, activate it first. |
| `externally-managed-environment` | Your system Python blocks `pip install`. Use `pipx` or `uv tool install` instead. |
| `No Notion token found` | Run `nbe init` (or choose **Set up** in the `nbe` menu), or set `NOTION_TOKEN` / create `.env`. |
| `Interactive mode needs a terminal` | You ran `nbe interactive` from a pipe, cron or CI. Use `nbe auto` or `nbe export --out <folder>` there. |
| `nbe` starts a full export instead of the menu | It is running without a terminal (redirected input/output, cron, CI), where a bare `nbe` deliberately means `nbe auto`. Run it in a normal terminal, or use `nbe interactive`. |
| The menu shows the wrong default destination | It comes from `$EXPORT_OUT_DIR`, then `$VAULT_PATH`, then the vault saved by `nbe init`, else `./output`. Type another folder at the question, or choose **Set up** to change the saved vault. |
| `401 unauthorized` | Token is wrong or was rotated. Run `nbe init` again. |
| Export is empty / pages missing | The integration only sees connected pages: page → `•••` → **Connections**. |
| `403` | The integration lacks **Read content**; edit its capabilities. |
| `Another export … is already writing` | A run is active in that folder. If none is, delete `.nbe.lock` inside it. |
| `Export stopped: N consecutive Notion API failures` | Network or Notion outage; wait and re-run. Nothing is corrupted. |
| Very slow | That's the 3 req/s limit; try `nbe auto --test` first, run large exports overnight. |
| Tables don't render in Obsidian | `.base` files need Obsidian **1.9+** with the Bases core plugin enabled. |

More (Docker, `fix`, and development issues) in [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).

---

## 🧪 Running Tests

Run the complete test suite:

```bash
# Run with Python unittest
python3 -m unittest discover tests -v

# Or using uv
uv run python -m unittest discover tests -v
```

The interactive menu is tested by scripting whole sessions with canned answers (`tests/test_interactive.py`, `tests/test_cli_modes.py`), so no terminal and no Notion token are needed.

---

## 📚 Documentation

| Doc | Covers |
| :--- | :--- |
| [docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md) | Every flag for `auto`, `export`, `init`, and `fix`, with defaults |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Pipeline, module map, failsafes, and security properties |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | Install, auth, Docker, `fix`, and development issues beyond the table above |
| [CONTRIBUTING.md](CONTRIBUTING.md) | How to get involved |
| [SECURITY.md](SECURITY.md) | Reporting a vulnerability |

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
