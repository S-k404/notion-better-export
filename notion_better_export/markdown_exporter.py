import os
import re
import urllib.request
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
try:
    import yaml
except ImportError:
    yaml = None

from notion_better_export.hierarchy import (
    HierarchyResolver,
    sanitize_filename,
    slugify_property_name,
)
from notion_better_export.models import DatabaseRow

logger = logging.getLogger("notion_better_export")


class MarkdownExporter:
    """Converts Notion blocks and pages to Obsidian-flavored Markdown with resolved links."""

    def __init__(
        self,
        resolver: HierarchyResolver,
        download_assets: bool = False,
    ):
        self.resolver = resolver
        self.download_assets = download_assets

    def format_frontmatter(self, fields: Dict[str, Any]) -> str:
        """Format metadata as YAML frontmatter."""
        if yaml:
            body = yaml.safe_dump(fields, sort_keys=False, allow_unicode=True).strip()
            return f"---\n{body}\n---\n"

        # Fallback writer if pyyaml is missing
        lines = ["---"]
        for k, v in fields.items():
            if isinstance(v, list):
                lines.append(f"{k}:")
                for item in v:
                    lines.append(f"  - {item}")
            elif isinstance(v, (dict, tuple)):
                lines.append(f'{k}: "{str(v)}"')
            else:
                clean_v = str(v).replace('"', '\\"')
                lines.append(f'{k}: "{clean_v}"')
        lines.append("---\n")
        return "\n".join(lines)

    def rich_text_to_markdown(self, rich_text_list: Any) -> str:
        """Convert Notion rich text array to Markdown, resolving page mentions to wikilinks."""
        if not rich_text_list or not isinstance(rich_text_list, list):
            return ""

        out: List[str] = []
        for rt in rich_text_list:
            if not isinstance(rt, dict):
                continue
            text = rt.get("plain_text", "")
            ann = rt.get("annotations", {})
            href = rt.get("href")

            # Check if this is a mention
            mention = rt.get("mention")
            if mention and isinstance(mention, dict):
                m_type = mention.get("type")
                if m_type == "page":
                    target_id = mention.get("page", {}).get("id")
                    if target_id:
                        clean_id = target_id.replace("-", "").lower()
                        target_rel = self.resolver.id_to_relpath.get(target_id) or self.resolver.id_to_relpath.get(clean_id)
                        target_title = self.resolver.id_to_title.get(target_id) or self.resolver.id_to_title.get(clean_id, text)
                        if target_rel:
                            out.append(f"[[{target_rel}|{target_title}]]")
                            continue
                        out.append(f"[[__PENDING__:{target_id}|{target_title}]]")
                        continue
                elif m_type == "database":
                    target_id = mention.get("database", {}).get("id")
                    if target_id:
                        clean_id = target_id.replace("-", "").lower()
                        canonical = self.resolver.get_canonical_database(target_id)
                        target_rel = (canonical.rel_path if canonical else None) or self.resolver.id_to_relpath.get(target_id) or self.resolver.id_to_relpath.get(clean_id)
                        target_title = (canonical.title if (canonical and canonical.title not in ("Untitled", "Untitled Database")) else None) or self.resolver.id_to_title.get(target_id) or self.resolver.id_to_title.get(clean_id, text)
                        if target_rel:
                            out.append(f"[[{target_rel}|{target_title}]]")
                            continue
                        out.append(f"[[__PENDING__:{target_id}|{target_title}]]")
                        continue
                elif m_type == "date":
                    d = mention.get("date")
                    if d:
                        start = d.get("start") or ""
                        end = d.get("end") or ""
                        date_str = f"{start} -> {end}" if (start and end) else (start or end)
                        if date_str:
                            out.append(f"@{date_str}")
                            continue
                elif m_type == "user":
                    u = mention.get("user", {})
                    user_name = u.get("name") or text
                    out.append(f"@{user_name}")
                    continue

            # Format styles
            if ann.get("code"):
                text = f"`{text}`"
            if ann.get("bold"):
                text = f"**{text}**"
            if ann.get("italic"):
                text = f"*{text}*"
            if ann.get("strikethrough"):
                text = f"~~{text}~~"
            if href and not text.startswith("[["):
                text = f"[{text}]({href})"
            out.append(text)

        return "".join(out)

    def maybe_download_asset(
        self, url: str, target_dir: Path, name_hint: str
    ) -> Optional[str]:
        """Download asset to _assets folder and return relative markdown path."""
        if not self.download_assets or not url:
            return None
        try:
            assets_dir = target_dir / "_assets"
            assets_dir.mkdir(parents=True, exist_ok=True)
            clean_hint = sanitize_filename(name_hint, maxlen=50)
            ext = os.path.splitext(url.split("?")[0])[1] or ".png"
            dest_file = assets_dir / f"{clean_hint}{ext}"
            urllib.request.urlretrieve(url, dest_file)
            return f"_assets/{dest_file.name}"
        except Exception as e:
            logger.warning("Failed to download asset %s: %s", url, e)
            return None

    def blocks_to_markdown(
        self,
        blocks: List[Dict[str, Any]],
        target_dir: Path,
        indent: int = 0,
        fetch_children_fn: Optional[Any] = None,
    ) -> str:
        """Convert a list of Notion block objects to clean markdown."""
        lines: List[str] = []
        pad = "  " * indent

        for block in blocks:
            if not isinstance(block, dict):
                continue
            btype = block.get("type", "")
            data = block.get(btype, {})

            if btype == "child_page":
                title = data.get("title", "Untitled Page")
                rel = self.resolver.id_to_relpath.get(block["id"])
                if rel:
                    lines.append(f"{pad}- 📄 [[{rel}|{title}]]")
                else:
                    lines.append(f"{pad}- 📄 [[__PENDING__:{block['id']}|{title}]]")
                continue

            if btype == "child_database":
                # Embedded / child database view — render as embedded Obsidian Base
                block_title = data.get("title", "")
                canonical = self.resolver.get_canonical_database(block["id"])
                base_rel = self.resolver.id_to_base_path.get(block["id"]) or (
                    self.resolver.id_to_base_path.get(block["id"].replace("-", "").lower())
                )
                rel = base_rel or (canonical.rel_path if canonical else self.resolver.id_to_relpath.get(block["id"]))
                display_title = block_title or (canonical.title if canonical else self.resolver.id_to_title.get(block["id"], "Database"))
                if display_title in ("Untitled", "Untitled Database"):
                    display_title = canonical.title if (canonical and canonical.title not in ("Untitled", "Untitled Database")) else "Database"

                if rel:
                    lines.append(f"\n{pad}[↗ {display_title}]([[{rel}.base]])\n\n{pad}![[{rel}.base]]\n")
                else:
                    lines.append(f"\n{pad}[[__EMBED_BASE__:{block['id']}|{display_title}]]\n")
                continue

            if btype == "link_to_page":
                # Linked page or database reference
                target_type = data.get("type", "")
                target_id = data.get(target_type, "")
                if target_id:
                    canonical = self.resolver.get_canonical_database(target_id)
                    rel = canonical.rel_path if canonical else self.resolver.id_to_relpath.get(target_id)
                    title = canonical.title if canonical else self.resolver.id_to_title.get(target_id, "Linked Item")
                    icon = "📊" if target_type == "database_id" else "📄"
                    if rel:
                        lines.append(f"{pad}- {icon} [[{rel}|{title}]]")
                    else:
                        lines.append(f"{pad}- {icon} [[__PENDING__:{target_id}|{title}]]")
                continue

            if btype == "paragraph":
                text = self.rich_text_to_markdown(data.get("rich_text", []))
                lines.append(f"{pad}{text}" if text else "")
            elif btype in ("heading_1", "heading_2", "heading_3"):
                h_level = {"heading_1": "#", "heading_2": "##", "heading_3": "###"}[btype]
                text = self.rich_text_to_markdown(data.get("rich_text", []))
                lines.append(f"{pad}{h_level} {text}")
            elif btype == "bulleted_list_item":
                text = self.rich_text_to_markdown(data.get("rich_text", []))
                lines.append(f"{pad}- {text}")
            elif btype == "numbered_list_item":
                text = self.rich_text_to_markdown(data.get("rich_text", []))
                lines.append(f"{pad}1. {text}")
            elif btype == "to_do":
                text = self.rich_text_to_markdown(data.get("rich_text", []))
                box = "x" if data.get("checked") else " "
                lines.append(f"{pad}- [{box}] {text}")
            elif btype == "toggle":
                text = self.rich_text_to_markdown(data.get("rich_text", []))
                has_kids = bool(block.get("has_children") and fetch_children_fn)
                if has_kids:
                    lines.append(f"{pad}<details><summary>{text}</summary>")
                else:
                    lines.append(f"{pad}<details><summary>{text}</summary></details>")
            elif btype == "quote":
                text = self.rich_text_to_markdown(data.get("rich_text", []))
                lines.append(f"{pad}> {text}")
            elif btype == "callout":
                text = self.rich_text_to_markdown(data.get("rich_text", []))
                icon = data.get("icon", {}).get("emoji", "")
                icon_prefix = f"{icon} " if icon else ""
                lines.append(f"{pad}> [!note]\n{pad}> {icon_prefix}{text}")
            elif btype == "code":
                text = self.rich_text_to_markdown(data.get("rich_text", []))
                lang = data.get("language", "")
                lines.append(f"{pad}```{lang}\n{text}\n{pad}```")
            elif btype == "divider":
                lines.append(f"{pad}---")
            elif btype == "image":
                url = (
                    data.get("file", {}).get("url")
                    or data.get("external", {}).get("url", "")
                )
                caption = self.rich_text_to_markdown(data.get("caption", []))
                local_asset = self.maybe_download_asset(url, target_dir, caption or block["id"])
                img_src = local_asset if local_asset else url
                lines.append(f"{pad}![{caption}]({img_src})")
            elif btype in ("file", "pdf", "video", "audio"):
                url = (
                    data.get("file", {}).get("url")
                    or data.get("external", {}).get("url", "")
                )
                lines.append(f"{pad}[{btype.capitalize()}]({url})")
            elif btype in ("bookmark", "link_preview"):
                url = data.get("url", "")
                lines.append(f"{pad}<{url}>")
            elif btype == "equation":
                expr = data.get("expression", "")
                lines.append(f"{pad}$$\n{pad}{expr}\n{pad}$$")
            elif btype == "table":
                # Render Notion table
                if fetch_children_fn:
                    try:
                        rows = fetch_children_fn(block["id"])
                        md_table = self.table_rows_to_markdown(rows)
                        if md_table:
                            lines.append(md_table)
                    except Exception as e:
                        logger.debug("Failed fetching table rows for %s: %s", block.get("id"), e)
            elif btype in ("column_list", "column", "synced_block"):
                pass  # Flatten container blocks, recurse into children below

            # Recurse into children blocks if block has children
            if block.get("has_children") and fetch_children_fn and btype not in (
                "child_page", "child_database", "table"
            ):
                try:
                    child_blocks = fetch_children_fn(block["id"])
                except Exception as e:
                    logger.debug("Failed fetching children for block %s: %s", block.get("id"), e)
                    child_blocks = []
                nested_indent = indent if btype in ("column_list", "column", "synced_block") else indent + 1
                child_md = self.blocks_to_markdown(
                    child_blocks, target_dir, nested_indent, fetch_children_fn
                )
                if child_md:
                    lines.append(child_md)
                if btype == "toggle":
                    lines.append(f"{pad}</details>")

        return "\n".join(l for l in lines if l is not None)

    def table_rows_to_markdown(self, rows: List[Dict[str, Any]]) -> str:
        """Render table row blocks into a markdown table."""
        md_rows: List[str] = []
        for i, row in enumerate(rows):
            cells = row.get("table_row", {}).get("cells", [])
            cell_texts = [
                self.rich_text_to_markdown(c).replace("|", "/") for c in cells
            ]
            md_rows.append("| " + " | ".join(cell_texts) + " |")
            if i == 0:
                sep = "| " + " | ".join(["---"] * len(cells)) + " |"
                md_rows.append(sep)
        return "\n".join(md_rows)

    def build_page_markdown(
        self,
        title: str,
        page_id: str,
        url: str,
        created_time: str,
        last_edited_time: str,
        body_markdown: str,
        extra_frontmatter: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Construct a full markdown document with frontmatter and body."""
        fm: Dict[str, Any] = {
            "title": title,
            "notion_id": page_id,
            "notion_url": url,
            "created_time": created_time,
            "last_edited_time": last_edited_time,
        }
        if extra_frontmatter:
            fm.update(extra_frontmatter)

        header = self.format_frontmatter(fm)
        return f"{header}\n{body_markdown.strip()}\n"

    def build_row_frontmatter(
        self, row: DatabaseRow, prop_slugs: Dict[str, str]
    ) -> Dict[str, Any]:
        """Construct frontmatter for a database row with resolved relations as wikilinks."""
        fm: Dict[str, Any] = {}
        for pname, plain_val in row.plain_properties.items():
            slug = prop_slugs.get(pname, slugify_property_name(pname))
            rel_ids = row.relations.get(pname)

            if rel_ids:
                # Format relations as a list of wikilinks
                resolved_links = []
                for rid in rel_ids:
                    clean_rid = rid.replace("-", "").lower()
                    title = self.resolver.id_to_title.get(rid) or self.resolver.id_to_title.get(clean_rid)
                    rel_path = self.resolver.id_to_relpath.get(rid) or self.resolver.id_to_relpath.get(clean_rid)
                    if title and rel_path:
                        resolved_links.append(f"[[{rel_path}|{title}]]")
                    elif title:
                        resolved_links.append(f"[[{title}]]")
                    else:
                        resolved_links.append(rid)
                fm[slug] = resolved_links if len(resolved_links) > 1 else (resolved_links[0] if resolved_links else "")
            elif plain_val:
                fm[slug] = plain_val

        return fm

    def rewrite_forward_links(self, out_dir: Path) -> None:
        """Second-pass: Rewrite [[__PENDING__:id|title]] and [[__EMBED_BASE__:id|title]] placeholders."""
        pattern_embed = re.compile(r"\[\[__EMBED_BASE__:([^|]+)\|([^\]]*)\]\]")
        pattern_pending = re.compile(r"\[\[__PENDING__:([^|]+)\|([^\]]*)\]\]")

        for md_path in out_dir.rglob("*.md"):
            try:
                text = md_path.read_text(encoding="utf-8")
            except Exception:
                continue

            if "__EMBED_BASE__" not in text and "__PENDING__" not in text:
                continue

            def embed_replacer(m):
                target_id = m.group(1)
                clean_target_id = target_id.replace("-", "").lower()
                label = m.group(2)
                base_rel = self.resolver.id_to_base_path.get(target_id) or self.resolver.id_to_base_path.get(
                    clean_target_id
                )
                canonical = self.resolver.get_canonical_database(target_id)

                if canonical and canonical.title and canonical.title not in ("Untitled", "Untitled Database"):
                    display_title = canonical.title
                elif label and label not in ("Untitled", "Database"):
                    display_title = label
                else:
                    display_title = self.resolver.id_to_title.get(target_id) or self.resolver.id_to_title.get(
                        clean_target_id, "Database"
                    )

                target_rel = base_rel or (canonical.rel_path if canonical else (
                    self.resolver.id_to_relpath.get(target_id) or self.resolver.id_to_relpath.get(clean_target_id)
                ))
                if target_rel:
                    return f"[↗ {display_title}]([[{target_rel}.base]])\n\n![[{target_rel}.base]]"
                return f"[↗ {display_title}]"

            def pending_replacer(m):
                target_id = m.group(1)
                clean_target_id = target_id.replace("-", "").lower()
                label = m.group(2)
                canonical = self.resolver.get_canonical_database(target_id)
                if canonical and canonical.rel_path:
                    title = canonical.title if canonical.title not in ("Untitled", "Untitled Database") else label
                    return f"[[{canonical.rel_path}|{title}]]"

                rel = self.resolver.id_to_relpath.get(target_id) or self.resolver.id_to_relpath.get(clean_target_id)
                if rel:
                    clean_label = label if label not in ("Untitled", "") else (
                        self.resolver.id_to_title.get(target_id) or self.resolver.id_to_title.get(clean_target_id, "Note")
                    )
                    return f"[[{rel}|{clean_label}]]"

                clean_label = label if label not in ("Untitled", "") else (
                    self.resolver.id_to_title.get(target_id) or self.resolver.id_to_title.get(clean_target_id, "Note")
                )
                return f"[[{clean_label}]]"

            new_text = pattern_embed.sub(embed_replacer, text)
            new_text = pattern_pending.sub(pending_replacer, new_text)
            if new_text != text:
                md_path.write_text(new_text, encoding="utf-8")
