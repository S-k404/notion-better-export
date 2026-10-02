# Troubleshooting

The most common issues are also listed in the [README](../README.md#-troubleshooting). This page adds the less common ones, plus Docker and development-environment issues.

## Installation

| Symptom | Fix |
| :--- | :--- |
| `command not found: nbe` | Not installed, or your PATH is stale. Install with `pipx` (see [README](../README.md#-installation)), run `pipx ensurepath`, and open a **new** terminal. If you used a venv, activate it first. |
| `externally-managed-environment` | Your system Python refuses `pip install`. Use `pipx install` or `uv tool install` instead of plain `pip`. |
| `uv sync` fails on an old Python | `nbe` requires Python 3.10+. Check with `python3 --version`; install a newer Python (e.g. via `uv python install 3.12`) and retry. |

## Authentication & access

| Symptom | Fix |
| :--- | :--- |
| `No Notion token found` | Run `nbe init` (or choose **Set up** in the `nbe` menu), or set `NOTION_TOKEN` / create `.env`. |
| `401 unauthorized` | Token is wrong or was rotated. Run `nbe init` again. |
| `403` on a page | The integration lacks **Read content**; edit its capabilities under [My Integrations](https://www.notion.so/profile/integrations). |
| Export is empty, or specific pages are missing | The integration only sees pages explicitly connected to it: open the page → `•••` → **Connections** → add the integration. Child pages inherit access from their parent. |

## Running the export

| Symptom | Fix |
| :--- | :--- |
| `Interactive mode needs a terminal` | You ran `nbe interactive` from a pipe, cron, or CI. Use `nbe auto` or `nbe export --out <folder>` instead. |
| `nbe` starts a full export instead of the menu | Running without a terminal (redirected input/output, cron, CI) deliberately maps a bare `nbe` to `nbe auto`. Run it in a normal terminal, or use `nbe interactive` explicitly. |
| The menu shows the wrong default destination | Resolved in order: `$EXPORT_OUT_DIR`, then `$VAULT_PATH`, then the vault saved by `nbe init`, else `./output`. Type a different folder at the prompt, or choose **Set up** to change the saved vault. |
| `Another export … is already writing` | A run is active in that folder. If none actually is, delete the stale `.nbe.lock` inside it. |
| `Export stopped: N consecutive Notion API failures` | Network or Notion outage (401s and the 25-consecutive-failure circuit breaker both raise this; 404/403 on individual pages don't count). Wait and re-run — nothing written so far is corrupted. |
| Export is very slow | Expected — the limiter paces at ~2.8 req/s with roughly one request per page/block fetch. Use `nbe auto --test` to validate on a small sample first, and run large workspaces overnight. |
| Tables don't render in Obsidian | `.base` files need Obsidian **1.9+** with the Bases core plugin enabled. |

## `nbe fix`

| Symptom | Fix |
| :--- | :--- |
| `fix` reports nothing to change | The export's CSVs/frontmatter/Bases don't contain unresolved UUIDs — nothing to do. |
| Need to undo a `fix` run | Restore the originals from `.nbe-fix-backup/` inside the export directory (skip this safety net only with `--no-backup`, which is not recommended). |
| `fix` can't find the manifest | Pass `--manifest <path>` explicitly if `notion_export_manifest.json` isn't directly inside `--dir` (e.g. it was moved). |

## Docker

| Symptom | Fix |
| :--- | :--- |
| Exported files are owned by `root` (Linux) | Create the output folder yourself before running (`mkdir -p vault`), as the README's Docker section shows — the container then writes into a folder you already own instead of creating one as root. |
| `docker compose run` can't find `NOTION_TOKEN` | Copy `.env.sample` to `.env` and set `NOTION_TOKEN` first; `.env` is excluded from the image build context but is read at container run time via `docker compose`. |
| Export lands in the wrong host folder | `docker compose run --rm notion-export` writes into `./vault/Notion Better Export` by default; set `VAULT_DIR` to point elsewhere, e.g. `VAULT_DIR="$HOME/Obsidian Vault" docker compose run --rm notion-export`. |

## Development

| Symptom | Fix |
| :--- | :--- |
| Tests fail after a local change | Run `uv run python -m unittest discover tests -v` (or the plain `python3` form) and read the first failure — the interactive-menu tests script whole sessions with canned answers, so no terminal or real token is needed. |
| Want to test against a fake export instead of live Notion | `tests/` includes fixtures for `post_processor.py`; there's no need for a real `NOTION_TOKEN` to run the suite. |

Still stuck? Check [CONTRIBUTING.md](../CONTRIBUTING.md) for how to open an issue with useful detail (command run, `-v` output, and your OS).
