import csv
import logging
from pathlib import Path
from typing import Dict, List, Optional
from notion_better_export.hierarchy import HierarchyResolver
from notion_better_export.models import DatabaseRow

logger = logging.getLogger("notion_better_export")


class CsvExporter:
    """Exports Notion databases to CSV files with relations and notes properly linked."""

    def __init__(
        self,
        resolver: HierarchyResolver,
        link_format: str = "wikilink",
        include_note_link: bool = True,
    ):
        """
        Args:
            resolver: HierarchyResolver containing global ID -> Title & RelPath mappings.
            link_format: Format for relation links: 'wikilink', 'title', or 'markdown'.
            include_note_link: If True, adds a 'Note Link' column linking to the row's .md file.
        """
        self.resolver = resolver
        self.link_format = link_format.lower()
        self.include_note_link = include_note_link

    def format_relation_link(
        self, target_id: str, base_csv_dir: Optional[Path] = None
    ) -> str:
        """Format a single Notion target ID into a resolved link."""
        clean_id = target_id.replace("-", "").lower()
        title = self.resolver.id_to_title.get(target_id) or self.resolver.id_to_title.get(clean_id)
        rel_path = self.resolver.id_to_relpath.get(target_id) or self.resolver.id_to_relpath.get(clean_id)

        if not title:
            # Not in registry (e.g. not shared or external)
            return target_id

        if self.link_format == "title":
            return title

        if self.link_format == "markdown":
            if rel_path:
                return f"[{title}]({rel_path}.md)"
            return f"[{title}]"

        # Default: wikilink
        if rel_path and "/" in rel_path:
            # Use [[rel_path|title]] if path has folders, or just [[title]]
            leaf = rel_path.split("/")[-1]
            if leaf == title:
                return f"[[{rel_path}]]"
            return f"[[{rel_path}|{title}]]"
        return f"[[{title}]]"

    def resolve_cell_relations(
        self, raw_value: str, relation_ids: List[str]
    ) -> str:
        """Resolves a relation cell containing one or more UUIDs into human/wikilink format."""
        if not relation_ids:
            return raw_value

        resolved_links = [self.format_relation_link(rid) for rid in relation_ids]
        return ", ".join(resolved_links)

    def write_database_csv(
        self,
        csv_path: Path,
        property_names: List[str],
        rows: List[DatabaseRow],
    ) -> None:
        """Writes the database rows to CSV with relations resolved and Note Link added."""
        csv_path.parent.mkdir(parents=True, exist_ok=True)

        fieldnames = ["Title"]
        if self.include_note_link:
            fieldnames.append("Note Link")
        fieldnames.extend(property_names)

        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f, fieldnames=fieldnames, extrasaction="ignore"
            )
            writer.writeheader()

            for row in rows:
                csv_row: Dict[str, str] = {"Title": row.title}

                if self.include_note_link:
                    # Provide link to the row's markdown note
                    row_rel = row.rel_path or row.title
                    if self.link_format == "markdown":
                        csv_row["Note Link"] = f"[{row.title}]({row_rel}.md)"
                    else:
                        csv_row["Note Link"] = f"[[{row_rel}]]"

                for pname in property_names:
                    val = row.plain_properties.get(pname, "")
                    rel_ids = row.relations.get(pname)
                    if rel_ids:
                        val = self.resolve_cell_relations(val, rel_ids)
                    csv_row[pname] = val

                writer.writerow(csv_row)

        logger.debug("Wrote linked CSV: %s (%d rows)", csv_path, len(rows))
