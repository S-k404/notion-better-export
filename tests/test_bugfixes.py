import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock
from notion_client.errors import APIResponseError

from notion_better_export.client import NotionApiClient
from notion_better_export.database import format_date_value, parse_property_value
from notion_better_export.hierarchy import HierarchyResolver
from notion_better_export.markdown_exporter import MarkdownExporter
from notion_better_export.models import NotionObject
from notion_better_export.post_processor import ExportPostProcessor


class TestDatabaseEdgeCases(unittest.TestCase):
    def test_format_date_value_all_nones(self):
        # Guard against {"start": None, "end": None} returning None
        res = format_date_value({"start": None, "end": None})
        self.assertEqual(res, "")
        self.assertIsInstance(res, str)

        res2 = format_date_value(None)
        self.assertEqual(res2, "")

        res3 = format_date_value({"start": "2026-09-01", "end": None})
        self.assertEqual(res3, "2026-09-01")

        res4 = format_date_value({"start": "2026-09-01", "end": "2026-09-30"})
        self.assertEqual(res4, "2026-09-01 -> 2026-09-30")

    def test_external_files_without_file_object(self):
        # When Notion sets "file": None on external files, ensure no AttributeError
        prop = {
            "type": "files",
            "files": [
                {
                    "name": "Syllabus.pdf",
                    "file": None,
                    "external": {"url": "https://university.edu/syllabus.pdf"},
                }
            ],
        }
        val, rel_ids = parse_property_value(prop)
        self.assertEqual(val, "[Syllabus.pdf](https://university.edu/syllabus.pdf)")
        self.assertIsNone(rel_ids)

    def test_formula_edge_cases(self):
        # Boolean false must be "false", not empty or True
        prop_false = {
            "type": "formula",
            "formula": {"type": "boolean", "boolean": False},
        }
        val, _ = parse_property_value(prop_false)
        self.assertEqual(val, "false")

        # Boolean None should be empty
        prop_none = {
            "type": "formula",
            "formula": {"type": "boolean", "boolean": None},
        }
        val, _ = parse_property_value(prop_none)
        self.assertEqual(val, "")

        # Formula 2.0 array output
        prop_array = {
            "type": "formula",
            "formula": {
                "type": "array",
                "array": [
                    {"type": "string", "string": "Alpha"},
                    {"type": "string", "string": "Beta"},
                ],
            },
        }
        val, _ = parse_property_value(prop_array)
        self.assertEqual(val, "Alpha, Beta")

    def test_rollup_inferred_type_and_arrays(self):
        # Rollup item without explicit 'type' key
        prop_rollup = {
            "type": "rollup",
            "rollup": {
                "type": "array",
                "array": [
                    {"rich_text": [{"plain_text": "Task A"}]},
                    {"rich_text": [{"plain_text": "Task B"}]},
                ],
            },
        }
        val, _ = parse_property_value(prop_rollup)
        self.assertEqual(val, "Task A, Task B")

    def test_verification_property(self):
        prop_ver = {
            "type": "verification",
            "verification": {"state": "verified"},
        }
        val, _ = parse_property_value(prop_ver)
        self.assertEqual(val, "verified")


class TestToggleAndMentions(unittest.TestCase):
    def setUp(self):
        self.out_root = Path("/tmp/test_toggle_mentions")
        self.resolver = HierarchyResolver(self.out_root)
        self.md_exporter = MarkdownExporter(self.resolver)

        db_canonical = NotionObject(
            id="db-schedule-123",
            object_type="database",
            title="📅 Class Schedule",
            parent_type="page_id",
            rel_path="University/📅 Class Schedule",
        )
        self.resolver.register_object(db_canonical)

    def test_toggle_without_children_closes_tag(self):
        # Toggle block with has_children=False should never leave an unclosed <details>
        blocks = [
            {
                "type": "toggle",
                "id": "toggle-empty",
                "has_children": False,
                "toggle": {"rich_text": [{"plain_text": "Click to expand"}]},
            }
        ]
        md = self.md_exporter.blocks_to_markdown(blocks, target_dir=self.out_root)
        self.assertIn("<details><summary>Click to expand</summary></details>", md)
        self.assertNotIn("<details><summary>Click to expand</summary>\n", md)

    def test_toggle_with_children_closes_tag(self):
        blocks = [
            {
                "type": "toggle",
                "id": "toggle-parent",
                "has_children": True,
                "toggle": {"rich_text": [{"plain_text": "Parent Toggle"}]},
            }
        ]

        def mock_children(bid):
            if bid == "toggle-parent":
                return [
                    {
                        "type": "paragraph",
                        "id": "p-1",
                        "paragraph": {"rich_text": [{"plain_text": "Inside child content"}]},
                    }
                ]
            return []

        md = self.md_exporter.blocks_to_markdown(
            blocks, target_dir=self.out_root, fetch_children_fn=mock_children
        )
        self.assertIn("<details><summary>Parent Toggle</summary>", md)
        self.assertIn("Inside child content", md)
        self.assertIn("</details>", md)

    def test_rich_text_database_and_user_mentions(self):
        rich_texts = [
            {
                "type": "mention",
                "plain_text": "📅 Class Schedule",
                "mention": {
                    "type": "database",
                    "database": {"id": "db-schedule-123"},
                },
            },
            {"type": "text", "plain_text": " with "},
            {
                "type": "mention",
                "plain_text": "Dr. Smith",
                "mention": {
                    "type": "user",
                    "user": {"name": "Dr. Smith"},
                },
            },
            {"type": "text", "plain_text": " on "},
            {
                "type": "mention",
                "plain_text": "2026-09-22",
                "mention": {
                    "type": "date",
                    "date": {"start": "2026-09-22"},
                },
            },
        ]
        md = self.md_exporter.rich_text_to_markdown(rich_texts)
        self.assertEqual(
            md,
            "[[University/📅 Class Schedule|📅 Class Schedule]] with @Dr. Smith on @2026-09-22",
        )


class TestPostProcessorBaseFiles(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path("/tmp/test_post_processor_base")
        self.test_dir.mkdir(parents=True, exist_ok=True)

        self.manifest_file = self.test_dir / "notion_export_manifest.json"
        manifest_data = {
            "3ce453c2-1690-817e-a5ed-c7889f188117": "Transaction Tracker/Monthly Budget/2026-09-01 2026-09 · September"
        }
        self.manifest_file.write_text(json.dumps(manifest_data), encoding="utf-8")

    def test_process_base_file_uuid_replacement(self):
        base_file = self.test_dir / "Transactions.base"
        content = """filters:
  or:
    - 'file.hasTag("3ce453c2-1690-817e-a5ed-c7889f188117")'
"""
        base_file.write_text(content, encoding="utf-8")

        processor = ExportPostProcessor(self.test_dir, self.manifest_file)
        processor.load_or_build_manifest()
        replaces = processor.process_base_file(base_file)

        self.assertEqual(replaces, 1)
        updated_text = base_file.read_text(encoding="utf-8")
        self.assertIn("2026-09 · September", updated_text)
        self.assertNotIn("3ce453c2-1690-817e-a5ed-c7889f188117", updated_text)


class TestClientFallback(unittest.TestCase):
    def test_retrieve_database_fallback_on_404(self):
        client = NotionApiClient(token="test-token")
        client.client = MagicMock()

        import httpx
        err = APIResponseError(
            code="object_not_found",
            status=404,
            message="Object not found",
            headers=httpx.Headers(),
            raw_body_text="{}",
        )
        client.client.databases.retrieve.side_effect = err
        client.client.data_sources.retrieve.return_value = {
            "id": "ds-123",
            "object": "data_source",
            "name": "Recovered Data Source",
        }

        res = client.retrieve_database("ds-123")
        self.assertEqual(res["name"], "Recovered Data Source")
        client.client.data_sources.retrieve.assert_called_once()


if __name__ == "__main__":
    unittest.main()
