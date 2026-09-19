import logging
from pathlib import Path
from typing import Dict, List, Optional
try:
    import yaml
except ImportError:
    yaml = None

logger = logging.getLogger("notion_better_export")


class BaseExporter:
    """Generates Obsidian Bases (.base) files with the correct schema and folder filters."""

    def __init__(self, vault_subpath: str = ""):
        self.vault_subpath = vault_subpath.strip("/") if vault_subpath else ""

    def write_base_file(
        self,
        base_path: Path,
        database_title: str,
        folder_leaf_name: str,
        prop_slugs: Dict[str, str],
    ) -> None:
        """Writes an Obsidian Base (.base) file.

        Args:
            base_path: Output file path (e.g. `.../Transactions.base`).
            database_title: Name of the database view.
            folder_leaf_name: Leaf folder name containing entry notes (matches Obsidian file.inFolder semantics).
            prop_slugs: Dict of original Notion property name -> safe slug identifier.
        """
        if yaml is None:
            logger.warning("pyyaml not installed — skipping .base file generation for %s", database_title)
            return

        order = ["file.name"] + [f"note.{slug}" for slug in prop_slugs.values()]

        properties_section = {
            "file.name": {"displayName": "Title"}
        }
        for orig_name, slug in prop_slugs.items():
            properties_section[f"note.{slug}"] = {"displayName": orig_name}

        # Obsidian's file.inFolder() takes the folder name (leaf) and recurses.
        filter_folder = Path(folder_leaf_name).name

        base_doc = {
            "filters": {
                "and": [f'file.inFolder("{filter_folder}")']
            },
            "properties": properties_section,
            "views": [
                {
                    "type": "table",
                    "name": database_title,
                    "order": order,
                }
            ],
        }

        base_path.parent.mkdir(parents=True, exist_ok=True)
        content = yaml.safe_dump(base_doc, sort_keys=False, allow_unicode=True)
        base_path.write_text(content, encoding="utf-8")
        logger.debug("Wrote Obsidian Base file: %s", base_path)
