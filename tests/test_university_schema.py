import unittest
from pathlib import Path
from notion_better_export.database import build_database_row
from notion_better_export.csv_exporter import CsvExporter
from notion_better_export.hierarchy import HierarchyResolver
from notion_better_export.markdown_exporter import MarkdownExporter
from notion_better_export.models import NotionObject


class TestUniversityManagementSchema(unittest.TestCase):
    """Tests the exact Notion database schema seen in the University Management workspace screenshot."""

    def setUp(self):
        self.out_root = Path("/tmp/test_univ_export")
        self.resolver = HierarchyResolver(self.out_root)

        # 1. Register canonical databases under "University — backend"
        self.schedule_db = NotionObject(
            id="db-schedule-uuid",
            object_type="database",
            title="📅 Schedule",
            parent_type="page_id",
            parent_id="backend-page-uuid",
            rel_path="🏛️ University — backend/📅 Schedule",
        )
        self.faculty_page = NotionObject(
            id="faculty-jimin-uuid",
            object_type="page",
            title="Dr. Jimin George (GJI)",
            parent_type="database_id",
            parent_id="db-faculty-uuid",
            rel_path="🏛️ University — backend/🧑‍🏫 Faculty/Dr. Jimin George (GJI)",
        )
        self.faculty_shravani = NotionObject(
            id="faculty-shravani-uuid",
            object_type="page",
            title="Ms. Shravani N (V-SHN)",
            parent_type="database_id",
            parent_id="db-faculty-uuid",
            rel_path="🏛️ University — backend/🧑‍🏫 Faculty/Ms. Shravani N (V-SHN)",
        )

        self.resolver.register_object(self.schedule_db)
        self.resolver.register_object(self.faculty_page)
        self.resolver.register_object(self.faculty_shravani)

    def test_parse_schedule_row_and_csv_generation(self):
        # Raw Notion API payload matching the screenshot columns
        notion_row = {
            "id": "row-session-1",
            "url": "https://notion.so/row-session-1",
            "created_time": "2026-09-15T08:00:00.000Z",
            "last_edited_time": "2026-09-17T12:00:00.000Z",
            "properties": {
                "Session": {
                    "type": "title",
                    "title": [{"plain_text": "AP Lab - Ms. Shravani N (Batch B1)"}],
                },
                "When": {
                    "type": "date",
                    "date": {
                        "start": "2026-09-17T14:10:00.000+05:30",
                        "end": "2026-09-17T16:05:00.000+05:30",
                    },
                },
                "Type": {
                    "type": "select",
                    "select": {"name": "Lab"},
                },
                "Venue": {
                    "type": "rich_text",
                    "rich_text": [{"plain_text": "LT 110"}],
                },
                "Faculty": {
                    "type": "relation",
                    "relation": [{"id": "faculty-shravani-uuid"}],
                },
                "Attendance": {
                    "type": "select",
                    "select": {"name": "Cancelled"},
                },
            },
        }

        row = build_database_row(notion_row, database_id="db-schedule-uuid")
        self.assertEqual(row.title, "AP Lab - Ms. Shravani N (Batch B1)")
        self.assertEqual(row.plain_properties["When"], "2026-09-17T14:10:00.000+05:30 -> 2026-09-17T16:05:00.000+05:30")
        self.assertEqual(row.plain_properties["Type"], "Lab")
        self.assertEqual(row.plain_properties["Venue"], "LT 110")
        self.assertEqual(row.plain_properties["Attendance"], "Cancelled")
        self.assertIn("Faculty", row.relations)
        self.assertEqual(row.relations["Faculty"], ["faculty-shravani-uuid"])

        # Generate CSV row and check relation link resolution
        row.rel_path = "🏛️ University — backend/📅 Schedule/AP Lab - Ms. Shravani N (Batch B1)"
        csv_exporter = CsvExporter(self.resolver, link_format="wikilink", include_note_link=True)
        csv_file = self.out_root / "Schedule.csv"

        csv_exporter.write_database_csv(
            csv_file,
            property_names=["When", "Type", "Venue", "Faculty", "Attendance"],
            rows=[row],
        )

        content = csv_file.read_text(encoding="utf-8")
        # Ensure header is correct
        self.assertIn("Title,Note Link,When,Type,Venue,Faculty,Attendance", content)
        # Ensure note link points directly to markdown file
        self.assertIn("[[🏛️ University — backend/📅 Schedule/AP Lab - Ms. Shravani N (Batch B1)]]", content)
        # Ensure relation to Faculty was resolved to clean wikilink instead of raw UUID
        self.assertIn("[[Ms. Shravani N (V-SHN)]]", content)
        self.assertNotIn("faculty-shravani-uuid", content)

    def test_hub_dashboard_avoids_duplicate_untitled_folders(self):
        """Verify that linked database views inside ECE University Hub render as links
        to the canonical backend database rather than generating duplicate 'Untitled' databases."""
        md_exporter = MarkdownExporter(self.resolver)

        hub_blocks = [
            {
                "type": "heading_1",
                "heading_1": {"rich_text": [{"plain_text": "ECE University Hub"}]},
            },
            # A linked view of the Schedule database
            {
                "id": "db-schedule-uuid",
                "type": "child_database",
                "child_database": {"title": "View of 📅 Schedule"},
            },
            # A link_to_page block pointing to the Schedule database
            {
                "id": "link-block-1",
                "type": "link_to_page",
                "link_to_page": {
                    "type": "database_id",
                    "database_id": "db-schedule-uuid",
                },
            },
        ]

        rendered_md = md_exporter.blocks_to_markdown(hub_blocks, target_dir=self.out_root)

        # Both the linked view and link_to_page should cleanly link to the canonical Schedule database
        self.assertIn("![[🏛️ University — backend/📅 Schedule.base]]", rendered_md)
        self.assertIn("[↗ View of 📅 Schedule]([[🏛️ University — backend/📅 Schedule.base]])", rendered_md)
        self.assertIn("[[🏛️ University — backend/📅 Schedule|📅 Schedule]]", rendered_md)
        self.assertNotIn("__PENDING__", rendered_md)
        self.assertNotIn("Untitled", rendered_md)


if __name__ == "__main__":
    unittest.main()
