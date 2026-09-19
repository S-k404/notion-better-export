import tempfile
import unittest
from pathlib import Path
import yaml
from notion_better_export.base_exporter import BaseExporter


class TestBaseExporter(unittest.TestCase):
    def test_write_base_file_schema_and_filters(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            base_file = tmp_path / "Transactions.base"

            exporter = BaseExporter(vault_subpath="Notion Better Export")
            prop_slugs = {
                "Amount": "amount",
                "Category": "category",
                "Date": "date",
                "Payee / Source": "payee_source",
            }

            exporter.write_base_file(
                base_path=base_file,
                database_title="Transactions",
                folder_leaf_name="Transactions",
                prop_slugs=prop_slugs,
                rel_folder="Transaction Tracker/Transactions",
            )

            self.assertTrue(base_file.exists())
            content = base_file.read_text(encoding="utf-8")
            data = yaml.safe_load(content)

            # Check filters
            self.assertIn("filters", data)
            self.assertIn("or", data["filters"])
            filter_list = data["filters"]["or"]

            # Must include dynamic context expression
            self.assertIn('file.inFolder(this.file.folder + "/Transactions")', filter_list)
            # Must include full vault relative path
            self.assertIn('file.inFolder("Notion Better Export/Transaction Tracker/Transactions")', filter_list)
            # Must include export relative path
            self.assertIn('file.inFolder("Transaction Tracker/Transactions")', filter_list)
            # Must include leaf folder
            self.assertIn('file.inFolder("Transactions")', filter_list)

            # Check properties
            props = data["properties"]
            self.assertEqual(props["file.name"]["displayName"], "Title")
            self.assertEqual(props["amount"]["displayName"], "Amount")
            self.assertEqual(props["category"]["displayName"], "Category")
            self.assertEqual(props["date"]["displayName"], "Date")
            self.assertEqual(props["payee_source"]["displayName"], "Payee / Source")

            # Check no 'note.' prefixes in properties
            for key in props:
                self.assertFalse(key.startswith("note."), f"Key {key} should not start with 'note.'")

            # Check views
            self.assertEqual(len(data["views"]), 1)
            view = data["views"][0]
            self.assertEqual(view["type"], "table")
            self.assertEqual(view["order"], ["file.name", "amount", "category", "date", "payee_source"])
            self.assertEqual(view["sort"][0]["property"], "file.name")

    def test_write_base_file_with_custom_views_and_sorts(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            base_file = tmp_path / "Schedule.base"

            exporter = BaseExporter(vault_subpath="Notion Better Export")
            prop_slugs = {
                "When": "when",
                "Type": "type",
                "Venue": "venue",
                "Faculty": "faculty",
            }

            custom_views = [
                {
                    "type": "table",
                    "name": "📆 This week",
                    "order": ["file.name", "when", "type", "venue", "faculty"],
                    "sort": [{"property": "when", "direction": "DESC"}],
                },
                {
                    "type": "table",
                    "name": "Bridge course",
                    "order": ["file.name", "when", "venue", "faculty"],
                    "sort": [{"property": "when", "direction": "ASC"}],
                }
            ]

            exporter.write_base_file(
                base_path=base_file,
                database_title="Schedule",
                folder_leaf_name="Schedule",
                prop_slugs=prop_slugs,
                rel_folder="ECE University Hub/University — backend/Schedule",
                views_config=custom_views,
            )

            self.assertTrue(base_file.exists())
            content = base_file.read_text(encoding="utf-8")
            data = yaml.safe_load(content)

            self.assertEqual(len(data["views"]), 2)
            v1 = data["views"][0]
            self.assertEqual(v1["name"], "📆 This week")
            self.assertEqual(v1["order"], ["file.name", "when", "type", "venue", "faculty"])
            self.assertEqual(v1["sort"], [{"property": "when", "direction": "DESC"}])

            v2 = data["views"][1]
            self.assertEqual(v2["name"], "Bridge course")
            self.assertEqual(v2["order"], ["file.name", "when", "venue", "faculty"])
            self.assertEqual(v2["sort"], [{"property": "when", "direction": "ASC"}])


if __name__ == "__main__":
    unittest.main()
