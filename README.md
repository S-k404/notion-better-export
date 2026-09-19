<div align="center">

# 🚀 Notion Better Export

**High-fidelity Notion workspace exporter preserving folder hierarchy, Obsidian Bases, and linked CSV databases.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10%2B-brightgreen.svg)](https://www.python.org/)
[![CI](https://github.com/shamitkumar4/notion-better-export/actions/workflows/ci.yml/badge.svg)](https://github.com/shamitkumar4/notion-better-export/actions/workflows/ci.yml)
[![Code style: ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

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
- 📊 **Native Obsidian Bases (`.base`)**: Generates official Obsidian Bases files matching Notion's exact view configurations (column order, column visibility, and sort direction).
- 🔗 **Embedded Interactive Tables**: Inline database views render inside markdown notes as live Obsidian Bases embeds (`![[View.base]]`), reproducing Notion's reading and dashboard experience 1:1.
- 🗃️ **Linked CSV Databases**:
  - Automatically resolves UUID relation cells into human-readable titles or Obsidian `[[wikilinks]]`.
  - Injects a `Note Link` column linking every row directly to its Markdown note file (`[[Database/2026-09-16 Note.md]]`).
- 🧠 **Smart Linked View Deduplication**: Recognizes linked views across different pages, pointing them to their single canonical home rather than generating duplicated orphaned folders.
- ⏱️ **Proactive Rate Limiting**: Built-in 2.8 req/sec pacing preventing HTTP 429 throttling delays with exponential backoff on transient errors.
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

## 🔑 Notion API Setup

1. Go to [Notion Developers: My Integrations](https://www.notion.so/profile/integrations).
2. Click **+ New integration**, name it (e.g. *Obsidian Exporter*), and choose your workspace.
3. Copy your **Internal Integration Secret** (`ntn_...` or `secret_...`).
4. In Notion, open your top-level workspace pages, click `•••` (top right) → **Connect to** → Select your integration.
5. Create a `.env` file in the project directory:
   ```bash
   cp .env.sample .env
   # Edit .env and set NOTION_TOKEN=ntn_your_secret_here
   ```

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
```

> **Tip**: You can also use the included `./run.sh` script:
> ```bash
> ./run.sh            # Runs auto mode
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
| `--token, -t` | Notion API token | `$NOTION_TOKEN` or `.env` |
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

Run exports completely containerized using Docker:

```bash
# Build container image
docker compose build

# Run the export
docker compose up
```

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

```text
notion_better_export/
├── cli.py               # Rich CLI interface (auto, export, fix)
├── client.py            # Paced Notion API client with 404 data source recovery
├── hierarchy.py         # Folder tree resolver, canonical database catalog, and disambiguation
├── database.py          # Property value parsing (Formula 2.0, rollups, relations, dates)
├── base_exporter.py     # Obsidian Bases (.base) generator with Notion view configurations
├── csv_exporter.py      # Linked CSV generator with Note Link and resolved relation links
├── markdown_exporter.py # Notion block converter, toggle tag safety, and forward link rewrites
├── post_processor.py    # Offline UUID resolver for existing exports
└── exporter.py          # Main coordinator orchestrating tree walking and file export
```

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
