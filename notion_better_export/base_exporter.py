import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import yaml
except ImportError:
    yaml = None

logger = logging.getLogger("notion_better_export")


# Obsidian's core Bases only ship these view types; Notion's board/gallery/calendar/
# timeline layouts have no direct equivalent, so they map to the closest one.
_VIEW_TYPE_MAP = {
    "table": "table",
    "list": "list",
    "gallery": "cards",
    "board": "cards",
    "calendar": "table",
    "timeline": "table",
}


def map_view_type(notion_view_type: Optional[str]) -> str:
    """Map a Notion view type onto a view type Obsidian Bases can render."""
    return _VIEW_TYPE_MAP.get(notion_view_type or "table", "table")


def build_view_order(
    visible_slugs: List[str], hidden_slugs: List[str], all_slugs: List[str]
) -> List[str]:
    """Column order for a Bases view: `file.name` plus the columns Notion shows.

    Columns hidden in the Notion view are left out. If the view carried no
    property configuration at all, every property is shown rather than none.
    """
    if not visible_slugs and not hidden_slugs:
        return ["file.name"] + list(all_slugs)
    return ["file.name"] + list(visible_slugs)


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
        views_config: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Writes an Obsidian Base (.base) file conforming to Obsidian's Bases specification.

        Args:
            base_path: Output file path (e.g. `.../Transactions.base`).
            database_title: Name of the database view.
            folder_leaf_name: Leaf folder name containing entry notes.
            prop_slugs: Dict of original Notion property name -> safe slug identifier.
            rel_folder: Folder relative to the export root (e.g. `Transaction Tracker/Transactions`).
            views_config: Optional list of view configurations derived from Notion views.
        """
        if yaml is None:
            logger.warning("pyyaml not installed — skipping .base file generation for %s", database_title)
            return

        leaf = Path(folder_leaf_name).name

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

        if views_config and len(views_config) > 0:
            final_views = views_config
        else:
            order = ["file.name"] + list(prop_slugs.values())
            final_views = [
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
            ]

        base_doc = {
            "filters": {
                "or": filter_candidates
            },
            "properties": properties_section,
            "views": final_views,
        }

        base_path.parent.mkdir(parents=True, exist_ok=True)
        content = yaml.safe_dump(base_doc, sort_keys=False, allow_unicode=True)
        base_path.write_text(content, encoding="utf-8")
        logger.debug("Wrote Obsidian Base file: %s", base_path)
