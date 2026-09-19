# Notion Better Export

High-fidelity Notion workspace exporter preserving folder hierarchy, Obsidian Bases, and linked CSV databases.

## Key Features

1. **True Folder Hierarchy**:
   - Mirrors Notion's parent-child tree: `Page.md` alongside `Page/` directory containing all its subpages and child databases.
   - Deeply nested subpages (e.g., `Travel > Vietnam > Trip Plans`) mirror cleanly on disk.
2. **Linked Database View Deduplication**:
   - Notion pages frequently embed views of databases stored elsewhere (e.g., `ECE University Hub` embedding views of `📅 Schedule` and `📚 Courses` from `University — backend`).
   - `notion-better-export` identifies canonical databases, exports them once to their true home, and links to them from parent pages rather than dumping duplicate `Untitled (hash)` folders.
3. **Correctly Linked CSV Files**:
   - Relation columns (e.g., `Budget Month`, `Transactions`, `Course`, `Year`) are resolved from raw UUIDs into human-readable titles, Obsidian `[[wikilinks]]`, or Markdown links.
   - Adds a `Note Link` column linking every row directly to its corresponding Markdown note file (`[[Database/Row.md]]`).
4. **Obsidian Bases (.base) Generation**:
   - Generates native table views compatible with Obsidian 1.9+ using the official `properties.<key>.displayName` schema and leaf-folder filters.
5. **Dual Modes**:
   - **`export`**: Full live crawl from the Notion integration API.
   - **`fix`**: Offline post-processor that updates existing Notion export folders, resolving broken UUIDs in CSV files and Markdown frontmatter.

---

## Quick Start

### 1. Configure Notion Integration Token
Copy `.env.sample` to `.env` or set `NOTION_TOKEN`:
```bash
cp .env.sample .env
# Edit .env and set your NOTION_TOKEN (or it automatically reads from ../Notoma/.env)
```

### 2. Run Live Export
```bash
# Preview export without writing files
./run.sh export --out ~/Vault/Notion --dry-run

# Run full export with wikilink relations in CSVs
./run.sh export --out "/Users/shamit/Documents/Docker/Obsidian/Obsidian Vault/Notion Export"

# Export with clean plain titles in CSVs (ideal for Excel / Google Sheets)
./run.sh export --out ./output --csv-link-format title

# Download images and file attachments locally
./run.sh export --out ./output --download-assets
```

### 3. Run Offline Fixer on Existing Exports
If you already have a Notion export directory with raw UUIDs in CSVs:
```bash
./run.sh fix --dir "/Users/shamit/Documents/Docker/Obsidian/Obsidian Vault/Notion Export"
```

---

## Docker Usage

```bash
# Build the docker container
docker compose build

# Run the export via container
docker compose up
```

---

## Running Tests

```bash
python3 -m unittest discover -s tests -p "test_*.py" -v
```
