import unittest
from pathlib import Path

from notion_better_export.hierarchy import (
    HierarchyResolver,
    extract_database_title,
    sanitize_filename,
    slugify_property_name,
)
from notion_better_export.models import NotionObject


class TestHierarchyResolver(unittest.TestCase):
    def setUp(self):
        self.out_root = Path("/tmp/test_notion_export")
        self.resolver = HierarchyResolver(self.out_root)

    def test_sanitize_filename(self):
        self.assertEqual(sanitize_filename("Valid Name"), "Valid Name")
        self.assertEqual(sanitize_filename("Has / Slash"), "Has — Slash")
        self.assertEqual(sanitize_filename("Has : Colon"), "Has Colon")
        self.assertEqual(sanitize_filename("  Trim Spaces  "), "Trim Spaces")
        self.assertEqual(sanitize_filename(""), "Untitled")

    def test_slugify_property_name(self):
        self.assertEqual(slugify_property_name("📅 Due Date"), "due_date")
        self.assertEqual(slugify_property_name("Budget Month"), "budget_month")
        self.assertEqual(slugify_property_name("Need / Want / Investment"), "need_want_investment")
        self.assertEqual(slugify_property_name(""), "prop")

    def test_nested_page_hierarchy(self):
        # Level 1: Root page "University Hub"
        md_file1, child_dir1, rel1 = self.resolver.compute_page_paths(
            page_id="root-1",
            title="University Hub",
            parent_folder=self.out_root,
            parent_titles=[],
        )
        self.assertEqual(rel1, "University Hub")
        self.assertEqual(md_file1, self.out_root / "University Hub.md")
        self.assertEqual(child_dir1, self.out_root / "University Hub")

        # Level 2: Subpage "Courses"
        md_file2, child_dir2, rel2 = self.resolver.compute_page_paths(
            page_id="sub-1",
            title="Courses",
            parent_folder=child_dir1,
            parent_titles=["University Hub"],
        )
        self.assertEqual(rel2, "University Hub/Courses")
        self.assertEqual(md_file2, self.out_root / "University Hub/Courses.md")
        self.assertEqual(child_dir2, self.out_root / "University Hub/Courses")

        # Level 3: Sub-subpage "Physics I"
        md_file3, child_dir3, rel3 = self.resolver.compute_page_paths(
            page_id="sub-2",
            title="Physics I",
            parent_folder=child_dir2,
            parent_titles=["University Hub", "Courses"],
        )
        self.assertEqual(rel3, "University Hub/Courses/Physics I")
        self.assertEqual(md_file3, self.out_root / "University Hub/Courses/Physics I.md")

    def test_canonical_database_tracking(self):
        db_obj = NotionObject(
            id="db-schedule-123",
            object_type="database",
            title="📅 Schedule",
            parent_type="page_id",
            parent_id="backend-page",
            rel_path="University Backend/📅 Schedule",
        )
        self.resolver.register_object(db_obj)

        canonical = self.resolver.get_canonical_database("db-schedule-123")
        self.assertIsNotNone(canonical)
        self.assertEqual(canonical.title, "📅 Schedule")
        self.assertEqual(canonical.rel_path, "University Backend/📅 Schedule")

    def test_extract_database_title_with_hint(self):
        # Database object with empty title, but block hint provided
        db_empty = {"object": "database", "title": []}
        title = extract_database_title(db_empty, block_title_hint="Attendance Schedule")
        self.assertEqual(title, "Attendance Schedule")

        # Data source with name
        ds_named = {"object": "data_source", "name": "Monthly Transactions"}
        title_ds = extract_database_title(ds_named)
        self.assertEqual(title_ds, "Monthly Transactions")


if __name__ == "__main__":
    unittest.main()
