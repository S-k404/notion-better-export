import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from notion_better_export import cli
from notion_better_export.base_exporter import build_view_order, map_view_type
from notion_better_export.client import NotionApiClient, NotionRateLimiter
from notion_better_export.hierarchy import HierarchyResolver
from notion_better_export.markdown_exporter import MarkdownExporter, redact_url


class RateLimiterTests(unittest.TestCase):
    def test_default_interval_matches_2_8_rps(self):
        self.assertAlmostEqual(NotionRateLimiter().interval, 1 / 2.8)

    def test_rate_is_clamped_to_notion_ceiling(self):
        self.assertAlmostEqual(NotionRateLimiter(50).interval, 1 / 3.0)

    def test_rate_can_be_lowered(self):
        self.assertAlmostEqual(NotionRateLimiter(1).interval, 1.0)

    def test_rejects_non_positive_rate(self):
        with self.assertRaises(ValueError):
            NotionRateLimiter(0)

    def test_retry_after_header_is_honored(self):
        err = mock.Mock(headers={"retry-after": "7"})
        self.assertEqual(NotionApiClient._retry_after_seconds(err, default=2.0), 7.0)

    def test_bad_retry_after_falls_back(self):
        err = mock.Mock(headers={"retry-after": "soon"})
        self.assertEqual(NotionApiClient._retry_after_seconds(err, default=2.0), 2.0)


class ViewMappingTests(unittest.TestCase):
    def test_unsupported_notion_views_map_to_bases_types(self):
        self.assertEqual(map_view_type("board"), "cards")
        self.assertEqual(map_view_type("gallery"), "cards")
        self.assertEqual(map_view_type("calendar"), "table")
        self.assertEqual(map_view_type("list"), "list")
        self.assertEqual(map_view_type(None), "table")

    def test_hidden_columns_are_left_out_of_order(self):
        order = build_view_order(["when", "venue"], ["notes"], ["when", "venue", "notes", "x"])
        self.assertEqual(order, ["file.name", "when", "venue"])

    def test_view_without_property_config_shows_everything(self):
        self.assertEqual(build_view_order([], [], ["a", "b"]), ["file.name", "a", "b"])


class AssetDownloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.exporter = MarkdownExporter(HierarchyResolver(self.dir), download_assets=True)

    def test_redact_url_strips_signature(self):
        url = "https://s3.example.com/a/b.png?X-Amz-Signature=secret&X-Amz-Credential=id"
        self.assertEqual(redact_url(url), "https://s3.example.com/a/b.png")

    def test_file_scheme_is_refused(self):
        secret = self.dir / "secret.txt"
        secret.write_text("private")
        with mock.patch("urllib.request.urlopen") as urlopen:
            result = self.exporter.maybe_download_asset(secret.as_uri(), self.dir, "leak")
        self.assertIsNone(result)
        urlopen.assert_not_called()
        self.assertFalse((self.dir / "_assets").exists())

    def test_oversized_asset_is_refused(self):
        resp = mock.MagicMock()
        resp.__enter__.return_value = resp
        resp.headers = {"Content-Length": str(10**12)}
        with mock.patch("urllib.request.urlopen", return_value=resp):
            result = self.exporter.maybe_download_asset("https://x.test/a.png", self.dir, "big")
        self.assertIsNone(result)

    def test_https_asset_is_saved(self):
        resp = mock.MagicMock()
        resp.__enter__.return_value = resp
        resp.headers = {}
        resp.read.return_value = b"png-bytes"
        with mock.patch("urllib.request.urlopen", return_value=resp):
            result = self.exporter.maybe_download_asset("https://x.test/a.png?sig=1", self.dir, "pic")
        self.assertEqual(result, "_assets/pic.png")
        self.assertEqual((self.dir / "_assets" / "pic.png").read_bytes(), b"png-bytes")


class TokenDiscoveryTests(unittest.TestCase):
    def test_env_var_wins(self):
        with mock.patch.dict(os.environ, {"NOTION_TOKEN": " ntn_abc "}):
            self.assertEqual(cli.find_default_token(), "ntn_abc")

    def test_reads_dotenv_with_export_and_quotes(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / ".env"
            f.write_text('# c\nexport NOTION_TOKEN="ntn_quoted"\n')
            self.assertEqual(cli.read_token_from_file(f), "ntn_quoted")

    def test_missing_file_returns_empty(self):
        self.assertEqual(cli.read_token_from_file(Path("/nonexistent/.env")), "")

    def test_no_sibling_project_lookup(self):
        source = Path(cli.__file__).read_text()
        self.assertNotIn("Notoma", source)
        self.assertNotIn("/Users/", source)


class OutDirTests(unittest.TestCase):
    def test_priority_and_vault_folder(self):
        with tempfile.TemporaryDirectory() as d:
            env = {"VAULT_PATH": d}
            with mock.patch.dict(os.environ, env, clear=True):
                self.assertEqual(cli.resolve_auto_out_dir(), Path(d).resolve() / "Notion Better Export")
            with mock.patch.dict(os.environ, {**env, "EXPORT_OUT_DIR": d + "/x"}, clear=True):
                self.assertEqual(cli.resolve_auto_out_dir(), Path(d + "/x").resolve())
            with mock.patch.dict(os.environ, {}, clear=True):
                self.assertEqual(cli.resolve_auto_out_dir(), Path("./output").resolve())


if __name__ == "__main__":
    unittest.main()
