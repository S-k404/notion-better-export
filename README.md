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

### Zero-Config Auto Mode (Recommended)
You don't need to specify any paths or flags. Auto Mode automatically reads your Notion token, detects your Obsidian Vault, enables Obsidian wikilinks, includes note links in CSVs, generates Obsidian Bases, prevents rate-limits, and deduplicates linked views:

```bash
# 1. Full Live Export (Zero-config into Obsidian Vault)
./run.sh

# 2. Preview export without writing any files
./run.sh -d       # or ./run.sh --dry-run

# 3. Quick test export (first 5 rows per database)
./run.sh -t       # or ./run.sh --test

# 4. Export including local asset/image downloads
./run.sh -a       # or ./run.sh --assets
```

---

### Manual Live Export (Custom Options)
```bash
# Preview export without writing files
./run.sh export --out ~/Vault/Notion --dry-run

# Run full export with wikilink relations in CSVs
./run.sh export --out "/Users/shamit/Documents/Docker/Obsidian/Obsidian Vault/Notion Better Export"

# Export with clean plain titles in CSVs (ideal for Excel / Google Sheets)
./run.sh export --out ./output --csv-link-format title
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
