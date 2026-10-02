import csv
import unittest
from pathlib import Path

from notion_better_export.csv_exporter import CsvExporter
from notion_better_export.hierarchy import HierarchyResolver
from notion_better_export.models import DatabaseRow


class TestCsvLinking(unittest.TestCase):
    def setUp(self):
        self.out_root = Path("/tmp/test_csv_export")
        self.resolver = HierarchyResolver(self.out_root)

        # Populate catalog with target pages
        self.resolver.id_to_title["month-sept-2026"] = "2026-09 · September"
        self.resolver.id_to_relpath["month-sept-2026"] = "Transaction Tracker/Monthly Budget/2026-09-01 2026-09 · September"

        self.resolver.id_to_title["vendex-snack-1"] = "Vendex — vending machine"
        self.resolver.id_to_relpath["vendex-snack-1"] = "Transaction Tracker/Transactions/2026-09-16 Vendex — vending machine"

        self.resolver.id_to_title["vendex-snack-2"] = "Vendex — coffee"
        self.resolver.id_to_relpath["vendex-snack-2"] = "Transaction Tracker/Transactions/2026-09-15 Vendex — coffee"

    def test_relation_resolution_wikilink(self):
        exporter = CsvExporter(self.resolver, link_format="wikilink")
        link = exporter.format_relation_link("month-sept-2026")
        self.assertEqual(
            link,
            "[[Transaction Tracker/Monthly Budget/2026-09-01 2026-09 · September|2026-09 · September]]",
        )

    def test_relation_resolution_title_format(self):
        exporter = CsvExporter(self.resolver, link_format="title")
        link = exporter.format_relation_link("month-sept-2026")
        self.assertEqual(link, "2026-09 · September")

    def test_multi_relation_cell(self):
        exporter = CsvExporter(self.resolver, link_format="wikilink")
        cell_val = exporter.resolve_cell_relations(
            raw_value="vendex-snack-1, vendex-snack-2",
            relation_ids=["vendex-snack-1", "vendex-snack-2"],
        )
        self.assertIn("[[Transaction Tracker/Transactions/2026-09-16 Vendex — vending machine|Vendex — vending machine]]", cell_val)
        self.assertIn("[[Transaction Tracker/Transactions/2026-09-15 Vendex — coffee|Vendex — coffee]]", cell_val)

    def test_write_database_csv_with_note_link(self):
        exporter = CsvExporter(self.resolver, link_format="wikilink", include_note_link=True)
        csv_path = self.out_root / "Transactions.csv"

        row1 = DatabaseRow(
            id="row-1",
            title="Vendex — vending machine",
            date_prefix="2026-09-16",
            database_id="db-transactions",
            plain_properties={
                "Amount": "130",
                "Budget Month": "month-sept-2026",
            },
            relations={"Budget Month": ["month-sept-2026"]},
            rel_path="Transaction Tracker/Transactions/2026-09-16 Vendex — vending machine",
            file_name="2026-09-16 Vendex — vending machine.md",
        )

        exporter.write_database_csv(
            csv_path=csv_path,
            property_names=["Amount", "Budget Month"],
            rows=[row1],
        )

        self.assertTrue(csv_path.exists())
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["Title"], "Vendex — vending machine")
        self.assertEqual(
            row["Note Link"],
            "[[Transaction Tracker/Transactions/2026-09-16 Vendex — vending machine]]",
        )
        self.assertEqual(row["Amount"], "130")
        self.assertEqual(
            row["Budget Month"],
            "[[Transaction Tracker/Monthly Budget/2026-09-01 2026-09 · September|2026-09 · September]]",
        )


if __name__ == "__main__":
    unittest.main()
