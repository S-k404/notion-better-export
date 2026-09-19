# Contributing to Notion Better Export

Thank you for your interest in improving **Notion Better Export**! We welcome bug reports, feature requests, documentation improvements, and pull requests.

---

## Development Setup

We recommend using [`uv`](https://github.com/astral-sh/uv) or standard Python `venv`.

```bash
# 1. Clone the repository
git clone https://github.com/shamitkumar4/notion-better-export.git
cd notion-better-export

# 2. Create and activate a virtual environment
uv venv
source .venv/bin/activate

# 3. Install in editable mode with development dependencies
uv pip install -e ".[dev]"
```

---

## Running Tests

All changes must pass the test suite:

```bash
uv run python -m unittest discover tests -v
```

If adding new functionality or fixing edge cases, please add corresponding unit tests in `tests/`.

---

## Architecture Overview

- **`client.py`**: Rate-limited (2.8 req/sec) Notion API wrapper with exponential backoff on 429 and graceful database/data source 404 recovery.
- **`hierarchy.py`**: Disambiguates folders/filenames and maps global Notion UUIDs to true vault paths and titles.
- **`database.py`**: Parses rich text, dates, relations, rollups, and Formula 2.0 returns into clean representations.
- **`base_exporter.py`**: Generates Obsidian Bases (`.base`) files with Notion column ordering, visibility, and sorting.
- **`csv_exporter.py`**: Exports linked CSVs with resolved relation wikilinks and note links.
- **`markdown_exporter.py`**: Converts blocks into Obsidian-flavored Markdown and rewrites forward links.
- **`post_processor.py`**: Offline fixer for existing exports to repair broken UUIDs in CSVs, Markdown, and Bases.
- **`exporter.py`**: Main coordinator orchestrating tree walking, view extraction, and file generation.
- **`cli.py`**: Rich CLI entry points (`notion-better-export` and `nbe`).

---

## Pull Request Guidelines

1. Ensure all tests pass (`uv run python -m unittest discover tests`).
2. Follow PEP 8 and keep code clean and readable.
3. Keep pull requests focused on a single feature or bug fix.
4. Update the `README.md` documentation if introducing new CLI flags or features.
