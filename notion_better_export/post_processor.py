import csv
import json
import logging
import re
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger("notion_better_export")

UUID_REGEX = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)


class ExportPostProcessor:
    """Offline fixer for existing Notion export folders and CSV files.
    Resolves UUIDs to human-readable titles/wikilinks and links CSV files to notes.
    """

    def __init__(
        self,
        export_dir: Path,
        manifest_path: Optional[Path] = None,
        link_format: str = "wikilink",
    ):
        self.export_dir = Path(export_dir).resolve()
        self.manifest_path = (
            Path(manifest_path).resolve()
            if manifest_path
            else self.export_dir / "notion_export_manifest.json"
        )
        self.link_format = link_format.lower()
        self.id_to_path: Dict[str, str] = {}
        self.id_to_title: Dict[str, str] = {}

    def load_or_build_manifest(self) -> Dict[str, str]:
        """Loads manifest if exists, or builds one by scanning .md frontmatter."""
        if self.manifest_path.exists():
            try:
                data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
                for nid, relpath in data.items():
                    clean = nid.replace("-", "").lower()
                    title = relpath.split("/")[-1]
                    self.id_to_path[nid] = relpath
                    self.id_to_path[clean] = relpath
                    self.id_to_title[nid] = title
                    self.id_to_title[clean] = title
                    if len(clean) == 32:
                        hyphenated = f"{clean[:8]}-{clean[8:12]}-{clean[12:16]}-{clean[16:20]}-{clean[20:]}"
                        self.id_to_path[hyphenated] = relpath
                        self.id_to_title[hyphenated] = title
                logger.info("Loaded %d mappings from manifest %s", len(data), self.manifest_path)
                return self.id_to_path
            except Exception as e:
                logger.warning("Could not parse manifest %s: %s", self.manifest_path, e)

        # Build mapping by scanning all markdown files
        logger.info("Scanning markdown files in %s to build ID registry...", self.export_dir)
        id_pattern = re.compile(r'notion_id:\s*["\']?([0-9a-f-]+)["\']?', re.IGNORECASE)
        title_pattern = re.compile(r'title:\s*["\']?([^"\']+)["\']?', re.IGNORECASE)

        count = 0
        for md_file in self.export_dir.rglob("*.md"):
            try:
                content = md_file.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            id_match = id_pattern.search(content[:1000])
            if not id_match:
                continue

            notion_id = id_match.group(1).strip()
            clean_id = notion_id.replace("-", "").lower()
            title_match = title_pattern.search(content[:1000])
            title = title_match.group(1).strip() if title_match else md_file.stem

            rel_path = str(md_file.relative_to(self.export_dir).with_suffix(""))
            self.id_to_path[notion_id] = rel_path
            self.id_to_path[clean_id] = rel_path
            self.id_to_title[notion_id] = title
            self.id_to_title[clean_id] = title
            if len(clean_id) == 32:
                hyphenated = f"{clean_id[:8]}-{clean_id[8:12]}-{clean_id[12:16]}-{clean_id[16:20]}-{clean_id[20:]}"
                self.id_to_path[hyphenated] = rel_path
                self.id_to_title[hyphenated] = title
            count += 1

        logger.info("Built registry with %d notes from markdown scan.", count)
        return self.id_to_path

    def format_link(self, notion_id: str) -> str:
        """Format a Notion ID as a human title or link."""
        clean_id = notion_id.replace("-", "").lower()
        title = self.id_to_title.get(notion_id) or self.id_to_title.get(clean_id)
        rel_path = self.id_to_path.get(notion_id) or self.id_to_path.get(clean_id)

        if not title:
            return notion_id

        if self.link_format == "title":
            return title
        if self.link_format == "markdown":
            return f"[{title}]({rel_path}.md)" if rel_path else f"[{title}]"
        # Default wikilink
        if rel_path and "/" in rel_path:
            leaf = rel_path.split("/")[-1]
            return f"[[{rel_path}]]" if leaf == title else f"[[{rel_path}|{title}]]"
        return f"[[{title}]]"

    def process_csv_file(self, csv_file: Path) -> int:
        """Fixes raw UUIDs in a CSV file and ensures a Note Link column exists.
        Returns number of UUID cells replaced.
        """
        csv_file = Path(csv_file).resolve()
        try:
            with open(csv_file, "r", encoding="utf-8", errors="replace") as f:
                reader = csv.reader(f)
                rows = list(reader)
        except Exception as e:
            logger.error("Failed to read CSV %s: %s", csv_file, e)
            return 0

        if not rows:
            return 0

        headers = rows[0]
        has_note_link = "Note Link" in headers
        if not has_note_link:
            headers.insert(1, "Note Link")

        # Database folder is the parent folder or sibling folder
        db_folder = csv_file.parent / csv_file.stem
        try:
            db_rel_folder = str(db_folder.relative_to(self.export_dir))
        except ValueError:
            db_rel_folder = db_folder.name

        replacements_count = 0
        new_rows = [headers]

        for row in rows[1:]:
            if not row:
                continue

            title = row[0] if len(row) > 0 else ""
            cells = list(row)

            # Insert Note Link column if newly added
            if not has_note_link:
                # Find corresponding markdown note
                note_link = f"[[{db_rel_folder}/{title}]]"
                cells.insert(1, note_link)

            # Inspect each cell for Notion UUIDs
            for i in range(len(cells)):
                val = cells[i]
                uuids = UUID_REGEX.findall(val)
                if uuids:
                    new_val = val
                    for uid in uuids:
                        resolved = self.format_link(uid)
                        if resolved != uid:
                            new_val = new_val.replace(uid, resolved)
                            replacements_count += 1
                    cells[i] = new_val

            new_rows.append(cells)

        # Write updated CSV
        with open(csv_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerows(new_rows)

        return replacements_count

    def process_markdown_frontmatter(self, md_file: Path) -> int:
        """Fixes raw UUIDs inside YAML frontmatter relations line by line."""
        try:
            text = md_file.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return 0

        if not text.startswith("---"):
            return 0

        parts = text.split("---", 2)
        if len(parts) < 3:
            return 0

        fm_body = parts[1]
        body = parts[2]

        lines = fm_body.splitlines(keepends=True)
        new_lines = []
        count = 0

        for line in lines:
            stripped = line.strip()
            # Protect primary identity properties
            if stripped.startswith("notion_id:") or stripped.startswith("notion_url:"):
                new_lines.append(line)
                continue

            uuids = UUID_REGEX.findall(line)
            if uuids:
                new_line = line
                for uid in uuids:
                    resolved = self.format_link(uid)
                    if resolved != uid:
                        new_line = new_line.replace(uid, resolved)
                        count += 1
                new_lines.append(new_line)
            else:
                new_lines.append(line)

        if count > 0:
            new_fm = "".join(new_lines)
            md_file.write_text(f"---{new_fm}---{body}", encoding="utf-8")

        return count

    def process_base_file(self, base_file: Path) -> int:
        """Inspects an Obsidian Base (.base) file, resolving any raw UUIDs in filters or views."""
        try:
            text = base_file.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return 0

        uuids = UUID_REGEX.findall(text)
        if not uuids:
            return 0

        new_text = text
        count = 0
        for uid in set(uuids):
            title = self.id_to_title.get(uid) or self.id_to_title.get(uid.replace("-", "").lower())
            if title and title != uid:
                new_text = new_text.replace(uid, title)
                count += 1

        if count > 0:
            base_file.write_text(new_text, encoding="utf-8")

        return count

    def run_all(self) -> Dict[str, int]:
        """Runs the offline post-processor across all CSV, Markdown, and Base files."""
        self.load_or_build_manifest()

        csv_files = list(self.export_dir.rglob("*.csv"))
        md_files = list(self.export_dir.rglob("*.md"))
        base_files = list(self.export_dir.rglob("*.base"))

        total_csv_replacements = 0
        total_md_replacements = 0
        total_base_replacements = 0

        for csv_file in csv_files:
            replaces = self.process_csv_file(csv_file)
            total_csv_replacements += replaces

        for md_file in md_files:
            replaces = self.process_markdown_frontmatter(md_file)
            total_md_replacements += replaces

        for base_file in base_files:
            replaces = self.process_base_file(base_file)
            total_base_replacements += replaces

        logger.info(
            "Finished post-processing: %d CSV replacements, %d MD replacements, %d Base replacements across %d CSVs, %d MDs, and %d Bases.",
            total_csv_replacements,
            total_md_replacements,
            total_base_replacements,
            len(csv_files),
            len(md_files),
            len(base_files),
        )

        return {
            "csv_files": len(csv_files),
            "md_files": len(md_files),
            "base_files": len(base_files),
            "csv_replacements": total_csv_replacements,
            "md_replacements": total_md_replacements,
            "base_replacements": total_base_replacements,
        }
