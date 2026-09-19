import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from notion_better_export.base_exporter import BaseExporter
from notion_better_export.client import NotionApiClient
from notion_better_export.csv_exporter import CsvExporter
from notion_better_export.database import build_database_row
from notion_better_export.hierarchy import (
    HierarchyResolver,
    extract_database_title,
    extract_page_title,
    slugify_property_name,
)
from notion_better_export.markdown_exporter import MarkdownExporter
from notion_better_export.models import DatabaseRow, NotionObject

logger = logging.getLogger("notion_better_export")


class NotionBetterExporter:
    """Orchestrates high-fidelity Notion exports with hierarchy preservation and linked CSVs."""

    def __init__(
        self,
        token: str,
        out_dir: Path,
        skip_databases: Optional[List[str]] = None,
        max_rows_per_db: Optional[int] = None,
        download_assets: bool = False,
        dry_run: bool = False,
        vault_subpath: str = "",
        csv_link_format: str = "wikilink",
        include_csv_note_link: bool = True,
        write_csv: bool = True,
        write_base: bool = True,
        date_prefix_rows: bool = False,
    ):
        self.client = NotionApiClient(token)
        self.out_dir = Path(out_dir).resolve()
        self.skip_databases = set(skip_databases or [])
        self.max_rows_per_db = max_rows_per_db
        self.download_assets = download_assets
        self.dry_run = dry_run
        self.vault_subpath = vault_subpath
        self.write_csv = write_csv
        self.write_base = write_base
        self.date_prefix_rows = date_prefix_rows

        if not vault_subpath:
            parent = self.out_dir.parent
            if (parent / ".obsidian").exists():
                vault_subpath = self.out_dir.name
            elif (self.out_dir / ".obsidian").exists():
                vault_subpath = ""

        self.resolver = HierarchyResolver(self.out_dir)
        self.csv_exporter = CsvExporter(
            self.resolver,
            link_format=csv_link_format,
            include_note_link=include_csv_note_link,
        )
        self.md_exporter = MarkdownExporter(
            self.resolver, download_assets=download_assets
        )
        self.base_exporter = BaseExporter(vault_subpath=vault_subpath)

        self.visited_ids: Set[str] = set()
        self.database_rows_cache: Dict[str, List[DatabaseRow]] = {}
        self.errors: List[str] = []

    def run(self) -> Dict[str, Any]:
        """Execute the full export pipeline."""
        logger.info("Starting Notion export to: %s", self.out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)

        # -------------------------------------------------------------
        # Step 1: Discover all objects accessible to the integration
        # -------------------------------------------------------------
        logger.info("Discovering workspace pages and databases...")
        all_objects = self.client.search_all()
        logger.info("Found %d objects visible to integration.", len(all_objects))

        objects_by_id: Dict[str, Dict[str, Any]] = {
            obj["id"]: obj for obj in all_objects if "id" in obj
        }

        # Step 1.1: Identify canonical databases and register all object titles
        db_candidates = []
        for obj in all_objects:
            obj_id = obj.get("id")
            if not obj_id:
                continue
            obj_type = obj.get("object")
            if obj_type in ("database", "data_source"):
                title = extract_database_title(obj)
                parent_info = obj.get("parent", {})
                ds_refs = obj.get("data_sources") or []
                ds_ids = [d["id"] for d in ds_refs if isinstance(d, dict) and "id" in d]

                notion_obj = NotionObject(
                    id=obj_id,
                    object_type=obj_type,
                    title=title,
                    parent_type=parent_info.get("type", "workspace"),
                    parent_id=parent_info.get("page_id") or parent_info.get("database_id"),
                    created_time=obj.get("created_time", ""),
                    last_edited_time=obj.get("last_edited_time", ""),
                    url=obj.get("url", ""),
                )
                self.resolver.register_object(notion_obj)
                db_candidates.append((notion_obj, ds_ids, ds_refs))

            elif obj_type == "page":
                title = extract_page_title(obj)
                self.resolver.id_to_title[obj_id] = title
                self.resolver.id_to_title[obj_id.replace("-", "").lower()] = title

        # First pass: register databases with real titles as canonical
        for notion_obj, ds_ids, ds_refs in db_candidates:
            if notion_obj.title not in ("Untitled", "Untitled Database"):
                self.resolver.register_canonical_database(notion_obj, ds_ids)

        # Second pass: map untitled databases / linked views to their canonical database
        for notion_obj, ds_ids, ds_refs in db_candidates:
            if notion_obj.title in ("Untitled", "Untitled Database"):
                target = None
                for ds_id in ds_ids:
                    target = self.resolver.data_source_to_canonical.get(
                        ds_id
                    ) or self.resolver.data_source_to_canonical.get(
                        ds_id.replace("-", "").lower()
                    )
                    if target:
                        break
                if not target:
                    for ds in ds_refs:
                        name = ds.get("name")
                        if name and name in self.resolver.canonical_by_title:
                            target = self.resolver.canonical_by_title[name]
                            break
                if target:
                    notion_obj.is_linked_view = True
                    self.resolver.canonical_databases[notion_obj.id] = target
                    self.resolver.canonical_databases[
                        notion_obj.id.replace("-", "").lower()
                    ] = target
                    logger.debug(
                        "Mapped linked view %s to canonical database %s",
                        notion_obj.id,
                        target.title,
                    )

        # -------------------------------------------------------------
        # Step 2: Determine root objects in workspace
        # -------------------------------------------------------------
        def is_workspace_root(obj: Dict[str, Any]) -> bool:
            parent = obj.get("parent", {})
            ptype = parent.get("type")
            # Database rows and data source children are never workspace roots
            if ptype in ("data_source_id", "database_id"):
                return False
            if ptype == "workspace":
                return True
            parent_id = parent.get("page_id") or parent.get("block_id")
            # If parent object is not shared with integration, treat as root
            return bool(parent_id and parent_id not in objects_by_id)

        roots = [obj for obj in all_objects if is_workspace_root(obj)]
        logger.info("%d top-level root object(s) found.", len(roots))

        # -------------------------------------------------------------
        # Step 3: Walk roots recursively to build folder tree & catalog
        # -------------------------------------------------------------
        for obj in roots:
            self._walk_object(obj, self.out_dir, parent_titles=[])

        # Walk any unvisited standalone leftover pages (park under _unsorted)
        leftovers = [
            obj
            for obj in all_objects
            if obj["id"] not in self.visited_ids
            and obj.get("parent", {}).get("type") not in ("data_source_id", "database_id")
        ]
        if leftovers:
            logger.info("Exporting %d leftover object(s) into _unsorted/...", len(leftovers))
            for obj in leftovers:
                self._walk_object(
                    obj, self.out_dir / "_unsorted", parent_titles=["_unsorted"]
                )

        # -------------------------------------------------------------
        # Step 4: Rewrite forward links across markdown files
        # -------------------------------------------------------------
        if not self.dry_run:
            logger.info("Resolving cross-document forward links...")
            self.md_exporter.rewrite_forward_links(self.out_dir)

            manifest_path = self.out_dir / "notion_export_manifest.json"
            manifest_path.write_text(
                json.dumps(self.resolver.id_to_relpath, indent=2),
                encoding="utf-8",
            )
            logger.info("Saved export manifest to: %s", manifest_path)

        summary = {
            "exported_objects": len(self.visited_ids),
            "errors": self.errors,
            "out_dir": str(self.out_dir),
        }
        logger.info(
            "Export completed: %d objects processed, %d errors.",
            summary["exported_objects"],
            len(self.errors),
        )
        return summary

    def _walk_object(
        self, obj: Dict[str, Any], folder: Path, parent_titles: List[str]
    ) -> None:
        obj_id = obj["id"]
        if obj_id in self.visited_ids:
            return
        self.visited_ids.add(obj_id)

        obj_type = obj.get("object")
        try:
            if obj_type in ("database", "data_source"):
                self._export_database(obj, folder, parent_titles)
            else:
                self._export_page(obj, folder, parent_titles)
        except Exception as e:
            title = obj.get("id", "Unknown")
            self.errors.append(f"{title} ({obj_id}): {e}")
            logger.error("Error exporting %s (%s): %s", title, obj_id, e)

    def _export_page(
        self, page: Dict[str, Any], parent_folder: Path, parent_titles: List[str]
    ) -> None:
        page_id = page["id"]
        title = extract_page_title(page)

        md_file, child_folder, rel_path = self.resolver.compute_page_paths(
            page_id, title, parent_folder, parent_titles
        )
        logger.info("Page: %s", rel_path)

        if not self.dry_run:
            # Fetch blocks
            blocks = self.client.list_block_children(page_id)
            body_md = self.md_exporter.blocks_to_markdown(
                blocks,
                target_dir=child_folder,
                fetch_children_fn=self.client.list_block_children,
            )

            full_content = self.md_exporter.build_page_markdown(
                title=title,
                page_id=page_id,
                url=page.get("url", ""),
                created_time=page.get("created_time", ""),
                last_edited_time=page.get("last_edited_time", ""),
                body_markdown=body_md,
            )

            md_file.parent.mkdir(parents=True, exist_ok=True)
            md_file.write_text(full_content, encoding="utf-8")

        # Recurse into subpages and child databases
        self._walk_children_blocks(
            page_id, child_folder, parent_titles + [md_file.stem]
        )

    def _export_database(
        self,
        db_obj: Dict[str, Any],
        parent_folder: Path,
        parent_titles: List[str],
        block_title_hint: Optional[str] = None,
    ) -> None:
        db_id = db_obj["id"]
        title = extract_database_title(db_obj, block_title_hint=block_title_hint)

        if title in self.skip_databases:
            logger.info("Skipping database %s (--skip-database)", title)
            return

        # Check if this database has attached data sources (2025-09-03 API)
        data_source_refs = db_obj.get("data_sources") or []
        is_ds = db_obj.get("object") == "data_source"

        entries_folder, csv_file, base_file, rel_folder = (
            self.resolver.compute_database_paths(
                db_id, title, parent_folder, parent_titles
            )
        )
        logger.info("Database: %s/ (CSV & Base)", rel_folder)

        # Get schema properties
        properties_schema = db_obj.get("properties") or {}
        if not properties_schema:
            # In Notion API 2025-09-03, database properties reside on the data_source object
            target_ds_ids: List[str] = []
            if is_ds:
                target_ds_ids.append(db_id)
            for ds_ref in data_source_refs:
                if isinstance(ds_ref, dict) and ds_ref.get("id"):
                    target_ds_ids.append(ds_ref["id"])

            for ds_id in target_ds_ids:
                try:
                    ds = self.client.retrieve_data_source(ds_id)
                    ds_props = ds.get("properties") or {}
                    if ds_props:
                        properties_schema.update(ds_props)
                except Exception as e:
                    logger.debug("Could not retrieve properties for data source %s: %s", ds_id, e)

        # Query all rows
        rows_raw = []
        if not self.dry_run:
            query_id = data_source_refs[0]["id"] if data_source_refs else db_id
            rows_raw = self.client.query_database_rows(
                query_id,
                is_data_source=is_ds or bool(data_source_refs),
                max_rows=self.max_rows_per_db,
            )

        # Fallback: if properties_schema is still empty, derive it from row properties
        if not properties_schema and rows_raw:
            for r_dict in rows_raw:
                r_props = r_dict.get("properties") or {}
                for pname, pval in r_props.items():
                    if pname not in properties_schema and isinstance(pval, dict):
                        properties_schema[pname] = {"type": pval.get("type", "rich_text")}

        prop_slugs = {
            pname: slugify_property_name(pname)
            for pname, pinfo in properties_schema.items()
            if isinstance(pinfo, dict) and pinfo.get("type") != "title"
        }

        db_rows: List[DatabaseRow] = []
        for r_dict in rows_raw:
            row_obj = build_database_row(r_dict, db_id)
            prefix = (
                row_obj.date_prefix
                if (self.date_prefix_rows or row_obj.title == "Untitled")
                else ""
            )
            row_file, row_rel = self.resolver.compute_row_paths(
                row_obj.id,
                row_obj.title,
                prefix,
                entries_folder,
                parent_titles,
                entries_folder.name,
            )
            row_obj.rel_path = row_rel
            row_obj.file_name = row_file.name
            self.visited_ids.add(row_obj.id)
            db_rows.append(row_obj)

        self.database_rows_cache[db_id] = db_rows

        if not self.dry_run:
            # Write each row note
            for row_obj in db_rows:
                row_file = entries_folder / row_obj.file_name
                row_blocks = self.client.list_block_children(row_obj.id)
                row_body_md = self.md_exporter.blocks_to_markdown(
                    row_blocks,
                    target_dir=entries_folder / row_file.stem,
                    fetch_children_fn=self.client.list_block_children,
                )

                row_fm = self.md_exporter.build_row_frontmatter(
                    row_obj, prop_slugs
                )
                full_row_md = self.md_exporter.build_page_markdown(
                    title=row_obj.title,
                    page_id=row_obj.id,
                    url=row_obj.url,
                    created_time=row_obj.created_time,
                    last_edited_time=row_obj.last_edited_time,
                    body_markdown=row_body_md,
                    extra_frontmatter=row_fm,
                )
                row_file.parent.mkdir(parents=True, exist_ok=True)
                row_file.write_text(full_row_md, encoding="utf-8")

                # Recurse into subpages nested inside this row
                self._walk_children_blocks(
                    row_obj.id,
                    entries_folder / row_file.stem,
                    parent_titles + [entries_folder.name, row_file.stem],
                )

            # Write Base file
            if self.write_base:
                self.base_exporter.write_base_file(
                    base_file,
                    database_title=title,
                    folder_leaf_name=entries_folder.name,
                    prop_slugs=prop_slugs,
                    rel_folder=rel_folder,
                )

            # Write Linked CSV file
            if self.write_csv:
                self.csv_exporter.write_database_csv(
                    csv_file,
                    property_names=list(prop_slugs.keys()),
                    rows=db_rows,
                )

    def _walk_children_blocks(
        self, block_id: str, child_folder: Path, parent_titles: List[str]
    ) -> None:
        """Scan blocks of a page/row for child_page or child_database blocks."""
        try:
            children = self.client.list_block_children(block_id)
        except Exception as e:
            self.errors.append(f"listing children of block {block_id}: {e}")
            return

        for block in children:
            btype = block.get("type")
            bid = block.get("id")

            if btype == "child_page" and bid not in self.visited_ids:
                try:
                    page = self.client.retrieve_page(bid)
                    self._walk_object(page, child_folder, parent_titles)
                except Exception as e:
                    self.errors.append(f"retrieving child_page {bid}: {e}")

            elif btype == "child_database":
                # Embedded database view or canonical database
                block_title = block.get("child_database", {}).get("title", "")

                if bid in self.visited_ids:
                    continue

                try:
                    db = self.client.retrieve_database(bid)
                    db_title = extract_database_title(db, block_title_hint=block_title)
                    ds_refs = db.get("data_sources") or []
                    ds_ids = [d["id"] for d in ds_refs if isinstance(d, dict) and "id" in d]
                    ds_names = [d["name"] for d in ds_refs if isinstance(d, dict) and "name" in d]

                    # If the database has an empty or "Untitled" title, it is a linked database view!
                    if db_title in ("Untitled", "Untitled Database"):
                        canonical = self.resolver.get_canonical_database(
                            bid,
                            data_source_ids=ds_ids,
                            data_source_names=ds_names,
                            hint_title=block_title,
                        )
                        target_name = (
                            canonical.title
                            if canonical
                            else (ds_names[0] if ds_names else "Database")
                        )
                        if canonical:
                            self.resolver.canonical_databases[bid] = canonical
                            self.resolver.canonical_databases[bid.replace("-", "").lower()] = canonical
                        logger.info(
                            "Skipping duplicate export for linked view of canonical database '%s' (%s)",
                            target_name,
                            bid,
                        )
                        continue

                    # This is a canonical database with a real title!
                    notion_obj = NotionObject(
                        id=bid,
                        object_type="database",
                        title=db_title,
                        parent_type=db.get("parent", {}).get("type", "workspace"),
                        parent_id=db.get("parent", {}).get("page_id"),
                        created_time=db.get("created_time", ""),
                        last_edited_time=db.get("last_edited_time", ""),
                        url=db.get("url", ""),
                    )
                    self.resolver.register_canonical_database(notion_obj, ds_ids)

                    self._export_database(
                        db,
                        child_folder,
                        parent_titles,
                        block_title_hint=block_title,
                    )
                except Exception as e:
                    self.errors.append(f"retrieving child_database {bid}: {e}")

            elif btype == "link_to_page":
                # References to other pages or databases are already canonical elsewhere
                continue

            elif block.get("has_children"):
                # Descend into toggles, columns, callouts to find any nested subpages
                self._walk_children_blocks(bid, child_folder, parent_titles)
