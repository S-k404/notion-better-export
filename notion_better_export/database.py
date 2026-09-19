import logging
from typing import Any, Dict, List, Optional, Tuple
from notion_better_export.hierarchy import extract_plain_text
from notion_better_export.models import DatabaseRow

logger = logging.getLogger("notion_better_export")


def format_date_value(d: Optional[Dict[str, Any]]) -> str:
    """Formats a Notion date dict {'start': ..., 'end': ...} into a clean string."""
    if not d or not isinstance(d, dict):
        return ""
    start = d.get("start", "")
    end = d.get("end")
    return f"{start} -> {end}" if end else start


def parse_property_value(
    prop: Dict[str, Any]
) -> Tuple[str, Optional[List[str]]]:
    """Parse a Notion property value.
    Returns:
        (plain_text_representation, list_of_relation_ids_or_None)
    """
    if not prop or not isinstance(prop, dict):
        return "", None

    ptype = prop.get("type")

    if ptype == "title":
        return extract_plain_text(prop.get("title", [])), None

    if ptype == "rich_text":
        return extract_plain_text(prop.get("rich_text", [])), None

    if ptype == "select":
        sel = prop.get("select")
        return sel.get("name", "") if sel else "", None

    if ptype == "multi_select":
        items = prop.get("multi_select", [])
        return ", ".join(i.get("name", "") for i in items if isinstance(i, dict)), None

    if ptype == "status":
        st = prop.get("status")
        return st.get("name", "") if st else "", None

    if ptype == "date":
        return format_date_value(prop.get("date")), None

    if ptype == "checkbox":
        return "true" if prop.get("checkbox") else "false", None

    if ptype == "number":
        n = prop.get("number")
        return "" if n is None else str(n), None

    if ptype == "people":
        peeps = prop.get("people", [])
        return ", ".join(p.get("name", "") for p in peeps if isinstance(p, dict)), None

    if ptype in ("url", "email", "phone_number"):
        return str(prop.get(ptype) or ""), None

    if ptype == "created_time":
        return str(prop.get("created_time") or ""), None

    if ptype == "last_edited_time":
        return str(prop.get("last_edited_time") or ""), None

    if ptype == "created_by":
        u = prop.get("created_by") or {}
        return u.get("name") or "", None

    if ptype == "last_edited_by":
        u = prop.get("last_edited_by") or {}
        return u.get("name") or "", None

    if ptype == "unique_id":
        u = prop.get("unique_id") or {}
        prefix = u.get("prefix")
        num = u.get("number")
        if num is None:
            return "", None
        return f"{prefix}-{num}" if prefix else str(num), None

    if ptype == "relation":
        rel_list = prop.get("relation", [])
        ids = [r["id"] for r in rel_list if isinstance(r, dict) and "id" in r]
        # Return the IDs as the raw value, but also return them in the second tuple item
        return ", ".join(ids), ids

    if ptype == "formula":
        f = prop.get("formula") or {}
        ftype = f.get("type")
        if ftype == "date":
            return format_date_value(f.get("date")), None
        if ftype == "number":
            n = f.get("number")
            return "" if n is None else str(n), None
        if ftype == "boolean":
            return "true" if f.get("boolean") else "false", None
        if ftype == "string":
            return str(f.get("string") or ""), None
        return "", None

    if ptype == "rollup":
        r = prop.get("rollup") or {}
        rtype = r.get("type")
        if rtype == "number":
            n = r.get("number")
            return "" if n is None else str(n), None
        if rtype == "date":
            return format_date_value(r.get("date")), None
        if rtype == "array":
            parts = []
            rel_ids: List[str] = []
            for item in r.get("array", []):
                val, ids = parse_property_value(item)
                if val:
                    parts.append(val)
                if ids:
                    rel_ids.extend(ids)
            return ", ".join(parts), rel_ids if rel_ids else None
        return "", None

    if ptype == "files":
        parts = []
        for item in prop.get("files", []):
            name = item.get("name", "")
            url = (
                item.get("file", {}).get("url")
                or item.get("external", {}).get("url", "")
            )
            parts.append(f"[{name}]({url})" if url else name)
        return ", ".join(parts), None

    return "", None


def extract_row_date_prefix(row_dict: Dict[str, Any]) -> str:
    """Extract YYYY-MM-DD prefix for a row to sort chronologically and disambiguate."""
    properties = row_dict.get("properties", {})
    if isinstance(properties, dict):
        for prop in properties.values():
            if isinstance(prop, dict) and prop.get("type") == "date":
                d = prop.get("date")
                if d and d.get("start"):
                    return str(d["start"])[:10]
    created = row_dict.get("created_time", "")
    return str(created)[:10] if created else ""


def build_database_row(
    row_dict: Dict[str, Any], database_id: str
) -> DatabaseRow:
    """Construct a DatabaseRow object from Notion's page dictionary."""
    row_id = row_dict["id"]
    properties = row_dict.get("properties", {})

    # Extract title
    title = "Untitled"
    for prop in properties.values():
        if isinstance(prop, dict) and prop.get("type") == "title":
            t = extract_plain_text(prop.get("title", []))
            if t.strip():
                title = t.strip()
            break

    date_prefix = extract_row_date_prefix(row_dict)

    plain_props: Dict[str, str] = {}
    relations_map: Dict[str, List[str]] = {}

    for pname, pval in properties.items():
        if isinstance(pval, dict) and pval.get("type") == "title":
            continue
        plain_str, rel_ids = parse_property_value(pval)
        plain_props[pname] = plain_str
        if rel_ids:
            relations_map[pname] = rel_ids

    return DatabaseRow(
        id=row_id,
        title=title,
        date_prefix=date_prefix,
        database_id=database_id,
        properties=properties,
        plain_properties=plain_props,
        relations=relations_map,
        created_time=row_dict.get("created_time", ""),
        last_edited_time=row_dict.get("last_edited_time", ""),
        url=row_dict.get("url", ""),
    )
