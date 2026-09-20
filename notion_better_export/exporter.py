import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from notion_better_export.base_exporter import BaseExporter, build_view_order, map_view_type
from notion_better_export.client import DEFAULT_REQUESTS_PER_SECOND, NotionApiClient
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
        requests_per_second: float = DEFAULT_REQUESTS_PER_SECOND,
    ):
        self.client = NotionApiClient(token, requests_per_second=requests_per_second)
        self.out_dir = Path(out_dir).resolve()
        self.skip_databases = set(skip_databases or [])
        self.max_rows_per_db = max_rows_per_db
        self.download_assets = download_assets
        self.dry_run = dry_run
        self.write_csv = write_csv
        self.write_base = write_base
        self.date_prefix_rows = date_prefix_rows
        if not vault_subpath:
            parent = self.out_dir.parent
            if (parent / ".obsidian").exists():
                vault_subpath = self.out_dir.name
            elif (self.out_dir / ".obsidian").exists():
                vault_subpath = ""
        self.vault_subpath = vault_subpath

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
        self.pending_linked_views: List[Dict[str, Any]] = []
        self.database_schemas: Dict[str, Tuple[Dict[str, Any], Dict[str, str]]] = {}
        self.errors: List[str] = []

    def _get_database_schema(
        self,
        db_id: str,
        data_source_refs: Optional[List[Dict[str, Any]]] = None,
        db_obj: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Dict[str, Any], Dict[str, str]]:
        """Retrieve and cache property schema and prop_slugs for a database or data source."""
        clean_id = db_id.replace("-", "").lower()
        if db_id in self.database_schemas:
            return self.database_schemas[db_id]
        if clean_id in self.database_schemas:
            return self.database_schemas[clean_id]

        properties_schema: Dict[str, Any] = {}
        if db_obj and isinstance(db_obj, dict):
            properties_schema = db_obj.get("properties") or {}
        else:
            try:
                db_obj = self.client.retrieve_database(db_id)
                properties_schema = db_obj.get("properties") or {}
            except Exception:
                db_obj = {}

        data_source_refs = (
            data_source_refs
            or (db_obj.get("data_sources") if isinstance(db_obj, dict) else [])
            or []
        )
        if not properties_schema and data_source_refs:
            for ds_ref in data_source_refs:
                if isinstance(ds_ref, dict) and ds_ref.get("id"):
                    try:
                        ds = self.client.retrieve_data_source(ds_ref["id"])
                        ds_props = ds.get("properties") or {}
                        if ds_props:
                            properties_schema.update(ds_props)
                    except Exception:
                        pass

        prop_slugs = {
            pname: slugify_property_name(pname)
            for pname, pinfo in properties_schema.items()
            if isinstance(pinfo, dict) and pinfo.get("type") != "title"
        }
        self.database_schemas[db_id] = (properties_schema, prop_slugs)
        self.database_schemas[clean_id] = (properties_schema, prop_slugs)
        return properties_schema, prop_slugs

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
        # Step 3.5: Export all pending linked database views as dedicated Bases
        # -------------------------------------------------------------
        if not self.dry_run:
            self._export_pending_linked_views()

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

            # Fetch view configurations and property ordering from Notion
            ordered_csv_props, views_config = self._fetch_notion_views(
                db_id, data_source_refs, prop_slugs, properties_schema
            )

            # Write Base file
            if self.write_base:
                self.base_exporter.write_base_file(
                    base_file,
                    database_title=title,
                    folder_leaf_name=entries_folder.name,
                    prop_slugs=prop_slugs,
                    rel_folder=rel_folder,
                    views_config=views_config,
                )

            # Write Linked CSV file
            if self.write_csv:
                self.csv_exporter.write_database_csv(
                    csv_file,
                    property_names=ordered_csv_props,
                    rows=db_rows,
                )

    def _fetch_notion_views(
        self,
        db_id: str,
        data_source_refs: List[Dict[str, Any]],
        prop_slugs: Dict[str, str],
        properties_schema: Dict[str, Any],
    ) -> Tuple[List[str], List[Dict[str, Any]]]:
        """Fetch views from Notion API and return:
        (ordered_property_names_for_csv, list_of_obsidian_view_dicts)
        """
        raw_views: List[Dict[str, Any]] = []
        if hasattr(self.client.client, "views"):
            try:
                v_res = self.client.retry(self.client.client.views.list, database_id=db_id)
                raw_views = v_res.get("results", [])
            except Exception:
                raw_views = []

            if not raw_views and data_source_refs:
                for ds_ref in data_source_refs:
                    if isinstance(ds_ref, dict) and ds_ref.get("id"):
                        try:
                            v_res = self.client.retry(
                                self.client.client.views.list,
                                data_source_id=ds_ref["id"],
                            )
                            raw_views = v_res.get("results", [])
                            if raw_views:
                                break
                        except Exception:
                            continue

        return self._parse_view_details(raw_views, prop_slugs, properties_schema)

    def _parse_view_details(
        self,
        raw_views: List[Dict[str, Any]],
        prop_slugs: Dict[str, str],
        properties_schema: Dict[str, Any],
    ) -> Tuple[List[str], List[Dict[str, Any]]]:
        """Convert a list of raw Notion view objects into Obsidian Bases views."""
        slug_to_orig = {slug: orig for orig, slug in prop_slugs.items()}

        id_to_slug: Dict[str, str] = {"title": "file.name"}
        for pname, pinfo in properties_schema.items():
            if isinstance(pinfo, dict) and pinfo.get("id"):
                id_to_slug[pinfo["id"]] = prop_slugs.get(pname, slugify_property_name(pname))

        obsidian_views: List[Dict[str, Any]] = []
        primary_ordered_prop_names: List[str] = []

        for v_stub in raw_views:
            try:
                if "configuration" in v_stub:
                    v_detail = v_stub
                else:
                    v_detail = self.client.retry(self.client.client.views.retrieve, v_stub["id"])

                v_name = v_detail.get("name") or "Table"
                v_config = v_detail.get("configuration", {})
                v_props = v_config.get("properties", [])

                for p_item in v_props:
                    pid = p_item.get("property_id")
                    pname = p_item.get("property_name")
                    if pid and pname:
                        id_to_slug[pid] = prop_slugs.get(pname, slugify_property_name(pname))

                visible_slugs: List[str] = []
                hidden_slugs: List[str] = []
                for p_item in v_props:
                    pname = p_item.get("property_name")
                    if not pname:
                        continue
                    slug = prop_slugs.get(pname, slugify_property_name(pname))
                    if slug == "file.name":
                        continue
                    if p_item.get("visible", True):
                        if slug not in visible_slugs and slug in prop_slugs.values():
                            visible_slugs.append(slug)
                    else:
                        if slug not in hidden_slugs and slug in prop_slugs.values():
                            hidden_slugs.append(slug)

                view_order = build_view_order(
                    visible_slugs, hidden_slugs, list(prop_slugs.values())
                )

                view_sorts: List[Dict[str, str]] = []
                for s in (v_detail.get("sorts") or []):
                    pid = s.get("property")
                    direction = "DESC" if s.get("direction") == "descending" else "ASC"
                    slug = id_to_slug.get(pid, pid)
                    if slug:
                        view_sorts.append({"property": slug, "direction": direction})

                vtype = map_view_type(v_detail.get("type"))

                obsidian_view: Dict[str, Any] = {
                    "type": vtype,
                    "name": v_name,
                    "order": view_order,
                }
                if view_sorts:
                    obsidian_view["sort"] = view_sorts
                obsidian_views.append(obsidian_view)

                if not primary_ordered_prop_names:
                    for s in view_order:
                        if s == "file.name":
                            continue
                        orig = slug_to_orig.get(s)
                        if orig and orig not in primary_ordered_prop_names:
                            primary_ordered_prop_names.append(orig)

            except Exception as e:
                logger.debug("Failed retrieving view details for %s: %s", v_stub.get("id"), e)

        if not obsidian_views:
            date_slug = None
            for pname, pinfo in properties_schema.items():
                if isinstance(pinfo, dict) and pinfo.get("type") in ("date", "created_time"):
                    date_slug = prop_slugs.get(pname)
                    break

            fallback_order = ["file.name"] + list(prop_slugs.values())
            fallback_view: Dict[str, Any] = {
                "type": "table",
                "name": "Table",
                "order": fallback_order,
            }
            if date_slug:
                fallback_view["sort"] = [{"property": date_slug, "direction": "DESC"}]
            obsidian_views.append(fallback_view)

        if not primary_ordered_prop_names:
            primary_ordered_prop_names = list(prop_slugs.keys())
        else:
            for p in prop_slugs.keys():
                if p not in primary_ordered_prop_names:
                    primary_ordered_prop_names.append(p)

        return primary_ordered_prop_names, obsidian_views

    def _export_pending_linked_views(self) -> None:
        """Generate dedicated .base files for linked database views discovered across pages."""
        if not self.write_base or not self.pending_linked_views:
            return

        logger.info(
            "Generating dedicated Bases for %d linked database view(s)...",
            len(self.pending_linked_views),
        )

        for item in self.pending_linked_views:
            bid = item["bid"]
            canonical = item["canonical"]
            child_folder: Path = item["child_folder"]
            parent_titles: List[str] = item["parent_titles"]
            raw_views: List[Dict[str, Any]] = item["raw_views"]
            ds_refs: List[Dict[str, Any]] = item["ds_refs"]

            latest_canonical = self.resolver.get_canonical_database(canonical.id) or canonical
            target_title = latest_canonical.title
            canonical_rel = (
                latest_canonical.rel_path
                or self.resolver.id_to_relpath.get(latest_canonical.id, "")
                or self.resolver.id_to_relpath.get(latest_canonical.id.replace("-", "").lower(), "")
            )
            if not canonical_rel:
                by_title = self.resolver.canonical_by_title.get(target_title)
                if by_title and by_title.rel_path:
                    canonical_rel = by_title.rel_path
                    latest_canonical = by_title

            if not canonical_rel:
                for rid, rpath in self.resolver.id_to_relpath.items():
                    if rpath.endswith(f"/{target_title}") or rpath == target_title:
                        canonical_rel = rpath
                        break

            view_base_name = self.resolver.disambiguate_name(
                child_folder, f"View of {target_title}", bid
            )
            view_base_file = child_folder / f"{view_base_name}.base"
            view_rel_path = "/".join(parent_titles + [view_base_name])

            self.resolver.register_linked_view_base(
                bid, view_rel_path, view_base_name, latest_canonical
            )

            props_schema, p_slugs = self._get_database_schema(
                latest_canonical.id, ds_refs
            )

            ordered_props, obsidian_views = self._parse_view_details(
                raw_views, p_slugs, props_schema
            )

            leaf_folder = Path(canonical_rel).name if canonical_rel else target_title
            self.base_exporter.write_base_file(
                view_base_file,
                database_title=view_base_name,
                folder_leaf_name=leaf_folder,
                prop_slugs=p_slugs,
                rel_folder=canonical_rel,
                views_config=obsidian_views,
            )
            logger.info("Exported linked view Base: %s -> %s", view_rel_path, canonical_rel)

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

                            raw_views = []
                            if hasattr(self.client.client, "views"):
                                try:
                                    v_res = self.client.retry(
                                        self.client.client.views.list, database_id=bid
                                    )
                                    raw_views = v_res.get("results", [])
                                except Exception as e:
                                    logger.debug("Failed listing views for %s: %s", bid, e)

                            self.pending_linked_views.append(
                                {
                                    "bid": bid,
                                    "canonical": canonical,
                                    "child_folder": child_folder,
                                    "parent_titles": parent_titles,
                                    "raw_views": raw_views,
                                    "ds_refs": ds_refs,
                                    "block_title": block_title,
                                }
                            )
                            logger.info(
                                "Enqueued linked view of canonical database '%s' (%s)",
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
