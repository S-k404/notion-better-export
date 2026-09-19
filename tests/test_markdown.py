import unittest
from pathlib import Path
from notion_better_export.hierarchy import HierarchyResolver
from notion_better_export.markdown_exporter import MarkdownExporter
from notion_better_export.models import DatabaseRow, NotionObject


class TestMarkdownExporter(unittest.TestCase):
    def setUp(self):
        self.out_root = Path("/tmp/test_md_export")
        self.resolver = HierarchyResolver(self.out_root)
        self.md_exporter = MarkdownExporter(self.resolver)

        # Register a canonical database
        db_canonical = NotionObject(
            id="db-schedule-999",
            object_type="database",
            title="📅 Schedule",
            parent_type="page_id",
            rel_path="University Backend/📅 Schedule",
        )
        self.resolver.register_object(db_canonical)

    def test_block_callout_and_headings(self):
        blocks = [
            {
                "type": "heading_1",
                "heading_1": {"rich_text": [{"plain_text": "Overview"}]},
            },
            {
                "type": "callout",
                "callout": {
                    "icon": {"emoji": "⚡"},
                    "rich_text": [{"plain_text": "Important note here"}],
                },
            },
        ]
        md = self.md_exporter.blocks_to_markdown(blocks, target_dir=self.out_root)
        self.assertIn("# Overview", md)
        self.assertIn("> [!note]\n> ⚡ Important note here", md)

    def test_linked_database_view_rendering(self):
        # When a page embeds a view of the canonical schedule database
        blocks = [
            {
                "type": "child_database",
                "id": "db-schedule-999",
                "child_database": {"title": "Mark Attendance"},
            }
        ]
        md = self.md_exporter.blocks_to_markdown(blocks, target_dir=self.out_root)
        # Must resolve to canonical database link, NEVER "[[Untitled]]"
        self.assertIn("[[University Backend/📅 Schedule|Mark Attendance]]", md)
        self.assertNotIn("Untitled", md)

    def test_row_frontmatter_relations(self):
        # Register target page
        self.resolver.id_to_title["sept-2026"] = "September 2026"
        self.resolver.id_to_relpath["sept-2026"] = "Budget/September 2026"

        row = DatabaseRow(
            id="row-10",
            title="Grocery Shopping",
            date_prefix="2026-09-10",
            database_id="db-transactions",
            plain_properties={"Amount": "450", "Budget Month": "sept-2026"},
            relations={"Budget Month": ["sept-2026"]},
        )
        fm = self.md_exporter.build_row_frontmatter(
            row, prop_slugs={"Budget Month": "budget_month", "Amount": "amount"}
        )
        self.assertEqual(fm["amount"], "450")
        self.assertEqual(fm["budget_month"], "[[Budget/September 2026|September 2026]]")

    def test_rewrite_forward_links(self):
        test_dir = self.out_root / "forward_link_test"
        test_dir.mkdir(parents=True, exist_ok=True)
        md_file = test_dir / "note.md"
        md_file.write_text("Here is a link: [[__PENDING__:sept-2026|September 2026]]", encoding="utf-8")

        self.resolver.id_to_relpath["sept-2026"] = "Budget/September 2026"
        self.md_exporter.rewrite_forward_links(test_dir)

        updated_text = md_file.read_text(encoding="utf-8")
        self.assertEqual(updated_text, "Here is a link: [[Budget/September 2026|September 2026]]")


if __name__ == "__main__":
    unittest.main()
