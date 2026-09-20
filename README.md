<div align="center">

# 🚀 Notion Better Export

**High-fidelity Notion workspace exporter preserving folder hierarchy, Obsidian Bases, and linked CSV databases.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10%2B-brightgreen.svg)](https://www.python.org/)
[![CI](https://github.com/shamitkumar4/notion-better-export/actions/workflows/ci.yml/badge.svg)](https://github.com/shamitkumar4/notion-better-export/actions/workflows/ci.yml)

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
- 🛠️ **Dual Operation Modes**:
  - **Live Crawl**: Full workspace export directly via the Notion API.
  - **Offline Fixer**: Post-processes existing Notion export folders, resolving broken UUIDs in CSVs, Markdown frontmatter, and Base files.

---

## 📦 Installation

### Option 1: Using `pipx` (Recommended for CLI use)
```bash
pipx install git+https://github.com/shamitkumar4/notion-better-export.git
```

### Option 2: Using `pip` or `uv`
```bash
# Using standard pip
pip install git+https://github.com/shamitkumar4/notion-better-export.git

# Or with uv
uv tool install git+https://github.com/shamitkumar4/notion-better-export.git
```

### Option 3: From Source
```bash
git clone https://github.com/shamitkumar4/notion-better-export.git
cd notion-better-export
pip install -e .
```

Both `notion-better-export` and the shorthand alias `nbe` will be available in your terminal.

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
   Or, if you prefer a file: `cp .env.sample .env` and set `NOTION_TOKEN=...` (`.env` is git-ignored).
6. Preview, then export:
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

## 🔐 Your files & privacy

- Exports are written **only** to the folder you choose (`--out`, `EXPORT_OUT_DIR`, or `VAULT_PATH`; default `./output`).
- The token is never written into the export, logs, or manifest. Signed file URLs are stripped of their credentials before being logged.
- `--assets` downloads attachments over `http(s)` only, with a 30 s timeout and 200 MB cap per file. Notion's file links expire after about an hour, so download assets in the same run rather than later.
- Your export contains private notes: don't commit `output/`, your vault, or `notion_export_manifest.json` to a public repo.

---

## 🚀 CLI Usage

The CLI provides two command names: `notion-better-export` and `nbe`.

### 1. Smart Auto Mode (Recommended)
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
> ./run.sh            # Runs auto mode (uses uv or .venv if present)
> ./run.sh test       # Runs auto --test
> ./run.sh --dry-run  # Runs auto --dry-run
> ```

---

### 2. Manual Export Mode (Custom Configuration)
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

#### CLI Flags for `export`:
| Flag | Description | Default |
| :--- | :--- | :--- |
| `--out, -o` | Target export directory path | *Required* |
| `--token, -t` | Notion API token (prefer `nbe init`/`.env`; CLI args leak into shell history) | `$NOTION_TOKEN`, `.env`, or `nbe init` |
| `--rate-limit` | Max requests/second (capped at 3.0) | `2.8` |
| `--csv-link-format` | Relation cell format (`wikilink`, `title`, `markdown`) | `wikilink` |
| `--no-note-link` | Omit `Note Link` column in CSV files | `False` |
| `--no-csv` | Skip generating CSV files | `False` |
| `--no-base` | Skip generating Obsidian `.base` files | `False` |
| `--download-assets` | Download file/image attachments to local `_assets/` | `False` |
| `--date-prefix-rows` | Prefix entry filenames with `YYYY-MM-DD` | `False` |
| `--max-rows` | Cap rows queried per database | `None` (all) |
| `--dry-run, -d` | Crawl workspace without writing to disk | `False` |

---

### 3. Offline Post-Processor (`fix`)
If you already have a Notion export directory with raw UUIDs in CSV files or frontmatter:

```bash
# Automatically resolve UUIDs in CSVs, Markdown frontmatter, and Bases
nbe fix --dir "/path/to/Obsidian Vault/Notion Export"
```

---

## 🐳 Docker Support

```bash
cp .env.sample .env                    # add your NOTION_TOKEN
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
| `No Notion token found` | Run `nbe init`, or set `NOTION_TOKEN` / create `.env`. |
| `401 unauthorized` | Token is wrong or was rotated. Run `nbe init` again. |
| Export is empty / pages missing | The integration only sees connected pages: page → `•••` → **Connections**. |
| `403` | The integration lacks **Read content**; edit its capabilities. |
| Very slow | That's the 3 req/s limit; try `nbe auto --test` first, run large exports overnight. |
| Tables don't render in Obsidian | `.base` files need Obsidian **1.9+** with the Bases core plugin enabled. |

---

## 🧪 Running Tests

Run the complete test suite:

```bash
# Run with Python unittest
python3 -m unittest discover tests -v

# Or using uv
uv run python -m unittest discover tests -v
```

---

## 🏛️ Project Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the pipeline, module map and design notes, and [CONTRIBUTING.md](CONTRIBUTING.md) to get involved.

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
