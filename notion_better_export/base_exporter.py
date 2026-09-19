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
        rel_folder: str = "",
    ) -> None:
        """Writes an Obsidian Base (.base) file conforming to Obsidian's Bases specification.

        Args:
            base_path: Output file path (e.g. `.../Transactions.base`).
            database_title: Name of the database view.
            folder_leaf_name: Leaf folder name containing entry notes.
            prop_slugs: Dict of original Notion property name -> safe slug identifier.
            rel_folder: Folder relative to the export root (e.g. `Transaction Tracker/Transactions`).
        """
        if yaml is None:
            logger.warning("pyyaml not installed — skipping .base file generation for %s", database_title)
            return

        leaf = Path(folder_leaf_name).name

        # Build candidate folder paths for the filter:
        # In Obsidian's core Bases implementation:
        # file.inFolder(arg) checks e.file.path.startsWith(arg + "/")
        # where e.file.path is the file path relative to the Obsidian vault root.
        # We supply all valid candidate representations using 'or':
        # 1. Dynamic context expression: this.file.folder + "/" + leaf
        # 2. Vault-relative path: e.g. Notion Better Export/Transaction Tracker/Transactions
        # 3. Export-relative path: e.g. Transaction Tracker/Transactions
        # 4. Bare leaf folder: e.g. Transactions
        filter_candidates: List[str] = []

        filter_candidates.append(f'file.inFolder(this.file.folder + "/{leaf}")')

        if self.vault_subpath and rel_folder:
            full_vault_rel = f"{self.vault_subpath}/{rel_folder}".replace("//", "/")
            if f'file.inFolder("{full_vault_rel}")' not in filter_candidates:
                filter_candidates.append(f'file.inFolder("{full_vault_rel}")')

        if rel_folder and f'file.inFolder("{rel_folder}")' not in filter_candidates:
            filter_candidates.append(f'file.inFolder("{rel_folder}")')

        if f'file.inFolder("{leaf}")' not in filter_candidates:
            filter_candidates.append(f'file.inFolder("{leaf}")')

        # Property mappings without 'note.' prefix (Obsidian Bases schema)
        properties_section: Dict[str, Dict[str, str]] = {
            "file.name": {"displayName": "Title"}
        }
        for orig_name, slug in prop_slugs.items():
            properties_section[slug] = {"displayName": orig_name}

        order = ["file.name"] + list(prop_slugs.values())

        base_doc = {
            "filters": {
                "or": filter_candidates
            },
            "properties": properties_section,
            "views": [
                {
                    "type": "table",
                    "name": "Table",
                    "order": order,
                    "sort": [
                        {
                            "property": "file.name",
                            "direction": "ASC",
                        }
                    ],
                }
            ],
        }

        base_path.parent.mkdir(parents=True, exist_ok=True)
        content = yaml.safe_dump(base_doc, sort_keys=False, allow_unicode=True)
        base_path.write_text(content, encoding="utf-8")
        logger.debug("Wrote Obsidian Base file: %s", base_path)
