import csv
import json
import unittest
from pathlib import Path
from notion_better_export.post_processor import ExportPostProcessor


class TestExportPostProcessor(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path("/tmp/test_post_processor")
        self.test_dir.mkdir(parents=True, exist_ok=True)

        # Create sample manifest
        self.manifest_file = self.test_dir / "notion_export_manifest.json"
        manifest_data = {
            "3ce453c2-1690-817e-a5ed-c7889f188117": "Transaction Tracker/Monthly Budget/2026-09-01 2026-09 · September",
            "cc4453c2-1690-82d5-8e58-01edb701d0a7": "Transaction Tracker/Yearly Summary/2026-08-10 2026",
        }
        self.manifest_file.write_text(json.dumps(manifest_data), encoding="utf-8")

    def test_process_csv_file_resolves_uuids(self):
        csv_file = self.test_dir / "Transactions.csv"
        rows = [
            ["Title", "Budget Month", "Year"],
            ["Vendex", "3ce453c2-1690-817e-a5ed-c7889f188117", "cc4453c2-1690-82d5-8e58-01edb701d0a7"],
        ]
        with open(csv_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerows(rows)

        processor = ExportPostProcessor(self.test_dir, self.manifest_file, link_format="wikilink")
        processor.load_or_build_manifest()
        replacements = processor.process_csv_file(csv_file)

        self.assertEqual(replacements, 2)

        with open(csv_file, "r", encoding="utf-8") as f:
            updated_rows = list(csv.reader(f))

        headers = updated_rows[0]
        self.assertEqual(headers[0], "Title")
        self.assertEqual(headers[1], "Note Link")
        self.assertEqual(headers[2], "Budget Month")
        self.assertEqual(headers[3], "Year")

        data_row = updated_rows[1]
        self.assertEqual(data_row[0], "Vendex")
        self.assertIn("2026-09 · September", data_row[2])
        self.assertIn("2026", data_row[3])
        self.assertNotIn("3ce453c2", data_row[2])

    def test_process_markdown_frontmatter(self):
        md_file = self.test_dir / "sample_note.md"
        content = """---
title: "Sample Note"
notion_id: "3ce453c2-1690-817e-a5ed-c7889f188117"
budget_month: "3ce453c2-1690-817e-a5ed-c7889f188117"
year: "cc4453c2-1690-82d5-8e58-01edb701d0a7"
---
Note body here with notion_id 3ce453c2-1690-817e-a5ed-c7889f188117.
"""
        md_file.write_text(content, encoding="utf-8")

        processor = ExportPostProcessor(self.test_dir, self.manifest_file, link_format="wikilink")
        processor.load_or_build_manifest()
        replaces = processor.process_markdown_frontmatter(md_file)

        self.assertGreater(replaces, 0)
        updated_text = md_file.read_text(encoding="utf-8")

        # The notion_id line itself should be preserved
        self.assertIn('notion_id: "3ce453c2-1690-817e-a5ed-c7889f188117"', updated_text)
        # But relation fields should be resolved
        self.assertIn('budget_month: "[[Transaction Tracker/Monthly Budget/2026-09-01 2026-09 · September]]"', updated_text)
        self.assertIn('year: "[[Transaction Tracker/Yearly Summary/2026-08-10 2026]]"', updated_text)


if __name__ == "__main__":
    unittest.main()
