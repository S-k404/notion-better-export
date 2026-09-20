# Notion Better Export — project guide for Claude

Python 3.10+ CLI (`nbe` / `notion-better-export`) that exports a Notion workspace into an Obsidian vault: true folder hierarchy, linked CSVs, and Obsidian Bases (`.base`) that mirror Notion views. See `docs/ARCHITECTURE.md` for the pipeline and module map.

## Commands

```bash
uv run python -m unittest discover tests -v   # run tests (must stay 100% green)
./run.sh --dry-run                            # preview hierarchy, writes nothing
./run.sh test                                 # first 5 rows per database
./run.sh                                      # full export
./run.sh --assets                             # also download images/files
nbe init                                      # store the Notion token privately
```

## Conventions

1. **Rate limiting.** Keep the proactive limiter in `client.py` (default 2.8 req/s, hard ceiling 3.0). Never remove it or raise the ceiling; honour `Retry-After` on 429.
2. **No dangling HTML.** Toggle blocks that emit `<details>` must always close it.
3. **UUIDs.** Look up ids in both hyphenated and unhyphenated form in `hierarchy.py` and `post_processor.py`.
4. **Bases schema.** `.base` files use `properties.<key>.displayName`, keep the multi-candidate `file.inFolder(...)` filters, and only use view types Obsidian ships (`table`, `list`, `cards`). Hidden Notion columns stay out of `order`.
5. **Tests.** Run the suite after every change and add a test for each fix or feature.
6. **Git.** Do NOT run `git push` unless explicitly asked.

## Failsafe rules (do not regress)

- Never write output with `Path.write_text` / `open(..., "w")`; use `safety.atomic_write_text`, `atomic_write_bytes` or `atomic_open`.
- `ExportAborted` must stay a `BaseException` so per-page `except Exception` blocks cannot swallow it.
- Never call `os.kill(pid, 0)` on Windows (it terminates the process); see `safety._pid_alive`.
- `--dry-run` must never create files or folders.
- Anything that edits existing user files (`fix`) needs dry-run, a first-original backup, and atomic writes.

## Security rules (do not regress)

- Never put a real token in any tracked file, test, fixture, log line or example. Use obvious placeholders like `ntn_your_notion_integration_token_here`.
- Never hardcode personal paths (`/Users/<name>/...`) or read env files from sibling projects.
- Never log a URL with its query string (Notion file links are pre-signed); use `redact_url`.
- Asset downloads stay `http(s)` only, with timeout and size cap.
- Keep `.env*` (except `.env.sample`) in `.gitignore` and `.dockerignore`.
