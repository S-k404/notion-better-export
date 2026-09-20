import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from notion_better_export.models import NotionObject


def sanitize_filename(name: str, maxlen: int = 120) -> str:
    """Make a Notion title safe as a filename/foldername on macOS/Windows/Linux."""
    name = unicodedata.normalize("NFKC", name or "Untitled")
    # Replace slashes and colons
    name = name.replace("/", " — ").replace("\\", " — ")
    name = re.sub(r'[<>:"|?*\x00-\x1f]', "", name)
    # Collapse multiple spaces or dashes
    name = re.sub(r"\s+", " ", name)
    name = name.strip().strip(".")
    if not name:
        name = "Untitled"
    return name[:maxlen].strip()


def slugify_property_name(name: str) -> str:
    """Turn a Notion property name (often with emoji/spaces, e.g. '📅 Due Date')
    into a clean identifier ('due_date') for frontmatter and Base property references."""
    name = unicodedata.normalize("NFKD", name or "")
    name = "".join(ch for ch in name if not unicodedata.combining(ch))
    name = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").lower()
    return name or "prop"


def extract_plain_text(rich_text_list: Any) -> str:
    """Extract concatenated plain text from a Notion rich text array."""
    if not rich_text_list or not isinstance(rich_text_list, list):
        return ""
    return "".join(rt.get("plain_text", "") for rt in rich_text_list if isinstance(rt, dict))


def extract_page_title(page: Dict[str, Any]) -> str:
    """Extract human-readable title from a Notion page dictionary."""
    properties = page.get("properties", {})
    if not isinstance(properties, dict):
        return "Untitled"

    for prop in properties.values():
        if isinstance(prop, dict) and prop.get("type") == "title":
            title = extract_plain_text(prop.get("title", []))
            if title.strip():
                return title.strip()
    return "Untitled"


def extract_database_title(
    db: Dict[str, Any], block_title_hint: Optional[str] = None
) -> str:
    """Extract human-readable title for a database or data source.
    Uses title rich text, name attribute, or the embedding block title hint.
    """
    # 1. Check title property
    title_rt = db.get("title", [])
    title = extract_plain_text(title_rt)
    if title.strip():
        return title.strip()

    # 2. Check name (common in data_sources API)
    name = db.get("name", "")
    if isinstance(name, str) and name.strip():
        return name.strip()

    # 3. Block title hint (e.g. from child_database block)
    if block_title_hint and block_title_hint.strip():
        return block_title_hint.strip()

    return "Untitled Database"


class HierarchyResolver:
    """Builds and resolves the true folder hierarchy of a Notion workspace."""

    def __init__(self, out_root: Path):
        self.out_root = Path(out_root).resolve()
        # id -> NotionObject
        self.registry: Dict[str, NotionObject] = {}
        # folder_path_str -> {base_name -> object_id}
        self.used_names: Dict[str, Dict[str, str]] = {}
        # database_id -> canonical NotionObject
        self.canonical_databases: Dict[str, NotionObject] = {}
        # data_source_id -> canonical NotionObject
        self.data_source_to_canonical: Dict[str, NotionObject] = {}
        # title -> canonical NotionObject
        self.canonical_by_title: Dict[str, NotionObject] = {}
        # Global ID -> Relative Path (without extension)
        self.id_to_relpath: Dict[str, str] = {}
        # Global ID -> Relative Base Path (without extension)
        self.id_to_base_path: Dict[str, str] = {}
        # Global ID -> Title
        self.id_to_title: Dict[str, str] = {}

    def register_linked_view_base(
        self, view_id: str, base_rel_path: str, title: str, canonical: NotionObject
    ) -> None:
        """Register a dedicated .base file for an inline/linked database view."""
        clean_id = view_id.replace("-", "").lower()
        self.id_to_base_path[view_id] = base_rel_path
        self.id_to_base_path[clean_id] = base_rel_path
        self.id_to_relpath[view_id] = base_rel_path
        self.id_to_relpath[clean_id] = base_rel_path
        self.id_to_title[view_id] = title
        self.id_to_title[clean_id] = title
        self.canonical_databases[view_id] = canonical
        self.canonical_databases[clean_id] = canonical

    def register_object(self, obj: NotionObject) -> None:
        """Register a Notion object in the global catalog."""
        self.registry[obj.id] = obj
        clean_id = obj.id.replace("-", "").lower()
        self.registry[clean_id] = obj
        self.id_to_title[obj.id] = obj.title
        self.id_to_title[clean_id] = obj.title
        if obj.object_type in ("database", "data_source") and not obj.is_linked_view:
            self.canonical_databases[obj.id] = obj
            self.canonical_databases[clean_id] = obj

    def register_canonical_database(
        self, obj: NotionObject, data_source_ids: Optional[List[str]] = None
    ) -> None:
        """Explicitly register a canonical database and all its data source aliases."""
        self.canonical_databases[obj.id] = obj
        clean_id = obj.id.replace("-", "").lower()
        self.canonical_databases[clean_id] = obj
        if obj.title and obj.title not in ("Untitled", "Untitled Database"):
            self.canonical_by_title[obj.title] = obj

        # Map its own ID as data source alias if it is a data_source
        if obj.object_type == "data_source":
            self.data_source_to_canonical[obj.id] = obj
            self.data_source_to_canonical[clean_id] = obj

        if data_source_ids:
            for ds_id in data_source_ids:
                self.data_source_to_canonical[ds_id] = obj
                self.data_source_to_canonical[ds_id.replace("-", "").lower()] = obj

    def get_canonical_database(
        self,
        db_id: str,
        data_source_ids: Optional[List[str]] = None,
        data_source_names: Optional[List[str]] = None,
        hint_title: Optional[str] = None,
    ) -> Optional[NotionObject]:
        clean_id = db_id.replace("-", "").lower()
        if db_id in self.canonical_databases:
            return self.canonical_databases[db_id]
        if clean_id in self.canonical_databases:
            return self.canonical_databases[clean_id]

        if data_source_ids:
            for ds_id in data_source_ids:
                c = self.data_source_to_canonical.get(ds_id) or self.data_source_to_canonical.get(
                    ds_id.replace("-", "").lower()
                )
                if c:
                    return c

        if data_source_names:
            for name in data_source_names:
                if name and name in self.canonical_by_title:
                    return self.canonical_by_title[name]

        if (
            hint_title
            and hint_title not in ("Untitled", "Untitled Database")
            and hint_title in self.canonical_by_title
        ):
            return self.canonical_by_title[hint_title]

        return None

    def disambiguate_name(self, folder: Path, base_name: str, object_id: str) -> str:
        """Ensure different Notion objects in the same directory never overwrite each other."""
        key = str(folder)
        used = self.used_names.setdefault(key, {})

        if base_name not in used or used[base_name] == object_id:
            used[base_name] = object_id
            return base_name

        # Append short hex id
        short_id = object_id.replace("-", "")[:6]
        candidate = f"{base_name} ({short_id})"
        n = 2
        while candidate in used and used[candidate] != object_id:
            candidate = f"{base_name} ({short_id}-{n})"
            n += 1

        used[candidate] = object_id
        return candidate

    def compute_page_paths(
        self,
        page_id: str,
        title: str,
        parent_folder: Path,
        parent_titles: List[str],
    ) -> Tuple[Path, Path, str]:
        """Compute the file path, child folder path, and relative path for a page.
        Returns:
            (page_md_file, child_subfolder, relative_path)
        """
        safe_name = sanitize_filename(title)
        safe_name = self.disambiguate_name(parent_folder, safe_name, page_id)

        md_file = parent_folder / f"{safe_name}.md"
        child_folder = parent_folder / safe_name
        rel_path = "/".join(parent_titles + [safe_name])

        clean_id = page_id.replace("-", "").lower()
        self.id_to_relpath[page_id] = rel_path
        self.id_to_relpath[clean_id] = rel_path
        self.id_to_title[page_id] = title
        self.id_to_title[clean_id] = title

        return md_file, child_folder, rel_path

    def compute_database_paths(
        self,
        db_id: str,
        title: str,
        parent_folder: Path,
        parent_titles: List[str],
    ) -> Tuple[Path, Path, Path, str]:
        """Compute the folder, .csv, and .base file paths for a database.
        Returns:
            (entries_folder, csv_file, base_file, relative_folder_path)
        """
        safe_name = sanitize_filename(title)
        safe_name = self.disambiguate_name(parent_folder, safe_name, db_id)

        entries_folder = parent_folder / safe_name
        csv_file = parent_folder / f"{safe_name}.csv"
        base_file = parent_folder / f"{safe_name}.base"
        rel_folder = "/".join(parent_titles + [safe_name])

        clean_id = db_id.replace("-", "").lower()
        self.id_to_relpath[db_id] = rel_folder
        self.id_to_relpath[clean_id] = rel_folder
        self.id_to_title[db_id] = title
        self.id_to_title[clean_id] = title

        if db_id in self.registry:
            self.registry[db_id].rel_path = rel_folder
        if clean_id in self.registry:
            self.registry[clean_id].rel_path = rel_folder
        if db_id in self.canonical_databases:
            self.canonical_databases[db_id].rel_path = rel_folder
        if clean_id in self.canonical_databases:
            self.canonical_databases[clean_id].rel_path = rel_folder
        if title in self.canonical_by_title:
            self.canonical_by_title[title].rel_path = rel_folder

        return entries_folder, csv_file, base_file, rel_folder

    def compute_row_paths(
        self,
        row_id: str,
        title: str,
        date_prefix: str,
        db_folder: Path,
        parent_titles: List[str],
        db_name: str,
    ) -> Tuple[Path, str]:
        """Compute file path and relative path for a database entry row.
        Returns:
            (row_md_file, relative_path)
        """
        base_title = f"{date_prefix} {title}".strip() if date_prefix else title
        safe_name = sanitize_filename(base_title)
        safe_name = self.disambiguate_name(db_folder, safe_name, row_id)

        md_file = db_folder / f"{safe_name}.md"
        rel_path = "/".join(parent_titles + [db_name, safe_name])

        clean_id = row_id.replace("-", "").lower()
        self.id_to_relpath[row_id] = rel_path
        self.id_to_relpath[clean_id] = rel_path
        self.id_to_title[row_id] = title
        self.id_to_title[clean_id] = title

        return md_file, rel_path
