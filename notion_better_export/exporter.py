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

        # Step 1.1: Identify canonical databases and register their titles
        for obj in all_objects:
            obj_type = obj.get("object")
            if obj_type in ("database", "data_source"):
                title = extract_database_title(obj)
                parent_info = obj.get("parent", {})
                notion_obj = NotionObject(
                    id=obj["id"],
                    object_type=obj_type,
                    title=title,
                    parent_type=parent_info.get("type", "workspace"),
                    parent_id=parent_info.get("page_id") or parent_info.get("database_id"),
                    created_time=obj.get("created_time", ""),
                    last_edited_time=obj.get("last_edited_time", ""),
                    url=obj.get("url", ""),
                )
                self.resolver.register_object(notion_obj)

        # -------------------------------------------------------------
        # Step 2: Determine root objects in workspace
        # -------------------------------------------------------------
        def is_workspace_root(obj: Dict[str, Any]) -> bool:
            parent = obj.get("parent", {})
            ptype = parent.get("type")
            if ptype == "workspace":
                return True
            parent_id = parent.get("page_id") or parent.get("database_id")
            # If parent object is not shared with integration, treat as root
            return parent_id not in objects_by_id

        roots = [obj for obj in all_objects if is_workspace_root(obj)]
        logger.info("%d top-level root object(s) found.", len(roots))

        # -------------------------------------------------------------
        # Step 3: Walk roots recursively to build folder tree & catalog
        # -------------------------------------------------------------
        for obj in roots:
            self._walk_object(obj, self.out_dir, parent_titles=[])

        # Walk any unvisited leftover items (park under _unsorted)
        leftovers = [
            obj for obj in all_objects if obj["id"] not in self.visited_ids
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
        properties_schema = db_obj.get("properties", {})
        if not properties_schema and is_ds:
            try:
                ds = self.client.retrieve_data_source(db_id)
                properties_schema = ds.get("properties", {})
            except Exception:
                pass

        prop_slugs = {
            pname: slugify_property_name(pname)
            for pname, pinfo in properties_schema.items()
            if isinstance(pinfo, dict) and pinfo.get("type") != "title"
        }

        # Query all rows
        rows_raw = []
        if not self.dry_run:
            query_id = data_source_refs[0]["id"] if data_source_refs else db_id
            rows_raw = self.client.query_database_rows(
                query_id,
                is_data_source=is_ds or bool(data_source_refs),
                max_rows=self.max_rows_per_db,
            )

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
                # Embedded database view
                block_title = block.get("child_database", {}).get("title", "")
                canonical = self.resolver.get_canonical_database(bid)

                if canonical:
                    # Already canonical somewhere else - do NOT duplicate export!
                    logger.debug(
                        "Skipping duplicate export for linked view of canonical database %s (%s)",
                        canonical.title,
                        bid,
                    )
                    continue

                if bid not in self.visited_ids:
                    try:
                        db = self.client.retrieve_database(bid)
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
