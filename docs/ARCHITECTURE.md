# Architecture

## Why this exists

Standard Notion exports (and most open-source exporters) have four flaws that hurt people moving to **Obsidian** or a local Markdown/CSV vault:

1. **Flattened folders.** Nested pages land in one flat directory with 32-character hash suffixes (`Untitled 3ce453...`).
2. **Raw UUIDs in CSV relations.** Relation columns export as `3ce453c2-1690-817e-...` instead of titles or links.
3. **Lost inline database views.** A page that embeds a filtered view of a database exports an empty block or a `📊 [[Untitled]]` placeholder.
4. **Disconnected rows and notes.** Row Markdown files have no link back to their CSV, and the CSV has none to the rows.

`nbe` keeps the real folder tree, generates Obsidian Bases (`.base`) that mirror the Notion views, embeds those views in the parent notes, and links CSV rows to their notes with `[[wikilinks]]`.

## Pipeline

```
Notion API
   │  paced at ≤ 2.8 req/s, Retry-After honoured, 404 databases↔data_sources recovery
   ▼
1. Discovery & canonical dedup        client.py, hierarchy.py
   crawl roots, databases, data sources; tell canonical databases from linked views
   ▼
2. Hierarchy resolution               hierarchy.py
   Page.md next to Page/; identical titles disambiguated with a short id suffix
   ▼
3. Schema & view extraction           database.py, exporter.py
   properties, formulas, rollups, dates; view column order, visibility, sorts
   ▼
4. Artifact generation                exporter.py, csv_exporter.py, base_exporter.py
   A. row notes   Parent/DB/Row.md            (optional YYYY-MM-DD prefix)
   B. linked CSV  DB.csv  (wikilinks + "Note Link" column)
   C. Bases       DB.base and "View of ….base" for linked views
   ▼
5. Embedded view insertion            markdown_exporter.py
   [↗ View Name]([[path.base]])  followed by  ![[path.base]]
   ▼
6. Two-pass link resolution           markdown_exporter.py
   [[__PENDING__:id|…]] and [[__EMBED_BASE__:id|…]] tokens rewritten once every
   path is known; notion_export_manifest.json records id → path for `nbe fix`
```

### Step notes

1. **Paced discovery** — `client.py` enforces Notion's average limit of 3 req/s with a proactive limiter (default **2.8**, configurable *down* with `--rate-limit`, clamped at 3.0). On HTTP 429 it sleeps for the `Retry-After` value; on 5xx and network errors it backs off exponentially. If a `databases` lookup 404s it retries against `data_sources` (and vice versa) for the 2025-09-03 API.
2. **Canonical dedup** — original databases are exported once at their true location. Linked views produce their own `.base` pointing at the canonical source instead of duplicate folders.
3. **Bases matching Notion views** — each Notion view becomes a Base view with the same column order and sort directions. Columns hidden in Notion are left out of the view's `order`. Obsidian only ships table/list/cards views, so Notion `board` and `gallery` become `cards`, and `calendar`/`timeline` become `table`. Every `.base` carries several folder-filter candidates so rows load wherever the folder sits in the vault.
4. **Live embeds** — a dashboard page that embeds a database view gets the link and the `![[…base]]` embed, so Obsidian renders the table in place.
5. **Linked CSVs** — relation columns become `[[wikilinks]]` (or plain titles / Markdown links via `--csv-link-format`), plus a `Note Link` column.
6. **Offline fix** — `nbe fix --dir <path>` repairs UUIDs in an existing export (CSVs, frontmatter, Base files) using the manifest, with no API access.

## Modules

| Module | Role |
| :--- | :--- |
| `cli.py` | `nbe` / `notion-better-export` entry point: `auto`, `export`, `fix`, `init`. Token discovery, output-dir resolution, friendly API errors. |
| `client.py` | Notion API wrapper: rate limiter, `Retry-After`, exponential backoff, database/data-source fallback. |
| `hierarchy.py` | Parent/child tree, canonical databases vs. linked views, filename sanitising and disambiguation. |
| `database.py` | Property parsing: dates, relations, rollups, formulas, files, verification. |
| `base_exporter.py` | Writes `.base` YAML; maps Notion view types and column visibility to Bases. |
| `csv_exporter.py` | Writes CSVs with resolved relations and `Note Link`. |
| `markdown_exporter.py` | Block → Markdown, `<details>` safety, base embeds, forward-link rewrite, hardened asset download. |
| `post_processor.py` | Offline UUID resolution for existing exports. |
| `safety.py` | Failsafes: atomic writes, output-folder checks, single-run lock, `ExportAborted`. |
| `exporter.py` | Orchestrates the walk, view extraction and file writing; writes the manifest. |

## Failsafes

- **Atomic writes** — every file goes through `safety.atomic_open` / `atomic_write_*` (temp file in the same folder, then `os.replace`). An interruption leaves the previous file intact.
- **Output checks** — `assert_safe_output_dir` hard-refuses `/`, the home folder, system trees (checked both as typed and after symlink resolution) and the tool's own source folder. `output_dir_warnings` (non-empty folder nbe didn't create, low disk) are soft and overridable with `--force`.
- **Run lock** — `.nbe.lock` (pid) prevents concurrent runs; stale locks from dead pids are cleared. On Windows it uses lock age, because `os.kill(pid, 0)` would terminate the process there.
- **Circuit breaker** — `client.retry` raises `ExportAborted` on a 401 or after 25 consecutive real failures (404/403 are expected and ignored). `ExportAborted` is a `BaseException` on purpose: the per-page `except Exception` handlers must not swallow it.
- **Reporting** — per-page errors are collected, saved to `notion_export_errors.log`, and the CLI exits 2.
- **`fix`** — `--dry-run`, first-original backups in `.nbe-fix-backup/`, atomic writes.

## Security properties

- The token is read from `$NOTION_TOKEN`, `./.env`, or the per-user file written by `nbe init` (mode `0600`). It is never logged or written into the export.
- The only host the tool talks to with the token is `api.notion.com` (via `notion-client`). There is no telemetry.
- Asset downloads (`--assets`) accept only `http(s)` URLs, have a 30 s timeout and a 200 MB cap, and redact signed query strings from log output.
- Exported filenames are sanitised (no separators, `..`, or reserved characters).
