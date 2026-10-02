"""In-memory stand-in for the Notion SDK client so the export pipeline can be tested offline.

It models the 2025-09-03 API shape (databases own data sources, properties live on the
data source, search returns pages + data sources) and counts every call so tests can
assert how many requests an export costs.
"""

import time
from collections import Counter
from types import SimpleNamespace
from typing import Any, Dict, List, Optional


def uid(n: int) -> str:
    return f"{n:08x}-0000-4000-8000-{n:012x}"


def rich(text: str) -> List[Dict[str, Any]]:
    return [{"type": "text", "plain_text": text, "annotations": {}, "href": None}]


class FakeWorkspace:
    """A tiny Notion workspace: pages, block trees, databases, data sources and views."""

    def __init__(self) -> None:
        self._n = 0
        self.pages: Dict[str, Dict[str, Any]] = {}
        self.children: Dict[str, List[Dict[str, Any]]] = {}
        self.databases: Dict[str, Dict[str, Any]] = {}
        self.data_sources: Dict[str, Dict[str, Any]] = {}
        self.rows: Dict[str, List[str]] = {}
        self.views: Dict[str, List[Dict[str, Any]]] = {}

    def next_id(self) -> str:
        self._n += 1
        return uid(self._n)

    # ---- block builders (each returns a block; children are registered by id) ----
    def _block(self, btype: str, payload: Dict[str, Any], kids: Optional[List[Dict[str, Any]]] = None):
        bid = self.next_id()
        block = {"object": "block", "id": bid, "type": btype, "has_children": bool(kids), btype: payload}
        if kids:
            self.children[bid] = kids
        return block

    def para(self, text: str):
        return self._block("paragraph", {"rich_text": rich(text)})

    def heading(self, text: str):
        return self._block("heading_1", {"rich_text": rich(text)})

    def toggle(self, text: str, kids: Optional[List[Dict[str, Any]]] = None):
        return self._block("toggle", {"rich_text": rich(text)}, kids)

    def table(self, rows: List[List[str]]):
        kids = [
            self._block("table_row", {"cells": [rich(c) for c in row]})
            for row in rows
        ]
        return self._block("table", {"table_width": len(rows[0]), "has_column_header": True}, kids)

    def column_list(self, *columns: List[Dict[str, Any]]):
        cols = [self._block("column", {}, list(col)) for col in columns]
        return self._block("column_list", {}, cols)

    def child_page_block(self, page_id: str):
        title = self.pages[page_id]["properties"]["title"]["title"][0]["plain_text"]
        block = self._block("child_page", {"title": title})
        block["id"] = page_id  # a child_page block shares its page's id
        return block

    def child_db_block(self, db_id: str, title: str):
        block = self._block("child_database", {"title": title})
        block["id"] = db_id
        return block

    # ---- object builders ----
    def add_page(
        self,
        title: str,
        parent: Dict[str, Any],
        blocks: Optional[List[Dict[str, Any]]] = None,
        extra_props: Optional[Dict[str, Any]] = None,
    ) -> str:
        pid = self.next_id()
        props = {"title": {"id": "title", "type": "title", "title": rich(title)}}
        props.update(extra_props or {})
        self.pages[pid] = {
            "object": "page",
            "id": pid,
            "url": f"https://notion.so/{pid.replace('-', '')}",
            "created_time": "2026-01-02T03:04:05.000Z",
            "last_edited_time": "2026-01-03T03:04:05.000Z",
            "parent": parent,
            "properties": props,
        }
        self.children[pid] = list(blocks or [])
        return pid

    def add_database(self, title: str, parent: Dict[str, Any], row_titles: List[str], row_blocks=None):
        """Create a database with one data source and rows; returns (db_id, ds_id, row_ids)."""
        db_id, ds_id = self.next_id(), self.next_id()
        schema = {
            "Name": {"id": "title", "type": "title", "name": "Name", "title": {}},
            "Status": {"id": "st", "type": "select", "name": "Status", "select": {}},
        }
        self.databases[db_id] = {
            "object": "database",
            "id": db_id,
            "title": rich(title),
            "url": f"https://notion.so/{db_id.replace('-', '')}",
            "parent": parent,
            "data_sources": [{"id": ds_id, "name": title}],
        }
        self.data_sources[ds_id] = {
            "object": "data_source",
            "id": ds_id,
            "title": rich(title),
            "parent": {"type": "database_id", "database_id": db_id},
            "database_parent": parent,
            "properties": schema,
        }
        row_ids = []
        for i, rt in enumerate(row_titles):
            blocks = row_blocks(i) if row_blocks else []
            rid = self.add_page(
                rt,
                {"type": "data_source_id", "data_source_id": ds_id, "database_id": db_id},
                blocks,
                {"Status": {"id": "st", "type": "select", "select": {"name": "Open" if i % 2 else "Done"}}},
            )
            row_ids.append(rid)
        self.rows[ds_id] = row_ids
        self.views[db_id] = [self.next_id()]
        return db_id, ds_id, row_ids

    def add_linked_view(self, target_ds_id: str, target_name: str):
        """An embedded view: a database object with no title pointing at an existing data source."""
        vid = self.next_id()
        self.databases[vid] = {
            "object": "database",
            "id": vid,
            "title": [],
            "parent": {"type": "page_id", "page_id": "x"},
            "data_sources": [{"id": target_ds_id, "name": target_name}],
        }
        self.views[vid] = [self.next_id()]
        return vid


class VirtualClock:
    """Replaces time.sleep/time.monotonic so latency and pacing cost no real time."""

    def __init__(self) -> None:
        self.now = 1000.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += max(seconds, 0.0)


class FakeNotionClient:
    """Drop-in for notion_client.Client. Counts calls; optional per-call latency."""

    def __init__(self, workspace: FakeWorkspace, latency: float = 0.0, page_size_cap: int = 100):
        self.ws = workspace
        self.latency = latency
        self.calls: Counter = Counter()
        self.children_calls: Counter = Counter()
        self.page_size_cap = page_size_cap
        self.blocks = SimpleNamespace(
            children=SimpleNamespace(list=self._children_list), retrieve=self._block_retrieve
        )
        self.pages = SimpleNamespace(retrieve=self._page_retrieve)
        self.databases = SimpleNamespace(retrieve=self._db_retrieve)
        self.data_sources = SimpleNamespace(retrieve=self._ds_retrieve, query=self._ds_query)
        self.views = SimpleNamespace(list=self._views_list, retrieve=self._views_retrieve)

    def __call__(self, *args: Any, **kwargs: Any) -> "FakeNotionClient":  # Client(auth=...)
        return self

    @property
    def total(self) -> int:
        return sum(self.calls.values())

    def _tick(self, endpoint: str) -> None:
        self.calls[endpoint] += 1
        if self.latency:
            time.sleep(self.latency)

    def _paginate(self, items: List[Any], page_size: int, cursor: Optional[str]):
        size = min(page_size, self.page_size_cap)
        start = int(cursor or 0)
        chunk = items[start : start + size]
        more = start + size < len(items)
        return {"results": chunk, "has_more": more, "next_cursor": str(start + size) if more else None}

    def search(self, page_size: int = 100, start_cursor: Optional[str] = None, **_: Any):
        self._tick("search")
        everything = list(self.ws.pages.values()) + list(self.ws.data_sources.values())
        return self._paginate(everything, page_size, start_cursor)

    def _children_list(self, block_id: str, page_size: int = 100, start_cursor: Optional[str] = None):
        self._tick("blocks.children.list")
        if not start_cursor:  # count logical fetches, not follow-up pages of one fetch
            self.children_calls[block_id] += 1
        return self._paginate(self.ws.children.get(block_id, []), page_size, start_cursor)

    def _block_retrieve(self, block_id: str):
        self._tick("blocks.retrieve")
        return {"id": block_id}

    def _page_retrieve(self, page_id: str):
        self._tick("pages.retrieve")
        return self.ws.pages[page_id]

    def _db_retrieve(self, database_id: str):
        self._tick("databases.retrieve")
        if database_id not in self.ws.databases:
            from notion_client.errors import APIResponseError
            import httpx

            raise APIResponseError(
                httpx.Response(404, json={"code": "object_not_found", "message": "not found"},
                               request=httpx.Request("GET", "https://api.notion.com")),
                "not found",
                "object_not_found",
            )
        return self.ws.databases[database_id]

    def _ds_retrieve(self, data_source_id: str):
        self._tick("data_sources.retrieve")
        return self.ws.data_sources[data_source_id]

    def _ds_query(self, data_source_id: str, page_size: int = 100, start_cursor: Optional[str] = None):
        self._tick("data_sources.query")
        rows = [self.ws.pages[r] for r in self.ws.rows[data_source_id]]
        return self._paginate(rows, page_size, start_cursor)

    def _views_list(self, database_id: Optional[str] = None, data_source_id: Optional[str] = None):
        self._tick("views.list")
        return {"results": [{"id": v} for v in self.ws.views.get(database_id, [])]}

    def _views_retrieve(self, view_id: str):
        self._tick("views.retrieve")
        return {
            "id": view_id,
            "name": "All tasks",
            "type": "table",
            "configuration": {
                "properties": [
                    {"property_id": "st", "property_name": "Status", "visible": True},
                ]
            },
            "sorts": [],
        }


def build_sample_workspace() -> FakeWorkspace:
    """Home page with nested pages, toggles, columns, a table, a database and a linked view."""
    ws = FakeWorkspace()
    root = {"type": "workspace", "workspace": True}

    def under(pid: str) -> Dict[str, Any]:
        return {"type": "page_id", "page_id": pid}

    home = ws.add_page("Home", root)

    a1 = ws.add_page("Alpha One", under(home), [ws.para("alpha one body")])
    a2 = ws.add_page("Alpha Two", under(home), [ws.para("alpha two body")])
    alpha = ws.add_page(
        "Alpha", under(home),
        [ws.para("alpha body"), ws.child_page_block(a1), ws.child_page_block(a2)],
    )
    notes = ws.add_page("Notes", under(home), [ws.para(f"note {i}") for i in range(130)])  # paginates

    deep = ws.add_page("Deep", under(home), [ws.para("deep body")])
    col = ws.add_page("Column Page", under(home), [ws.para("column body")])

    row_page = {}

    def row_blocks(i: int):
        blocks = [ws.para(f"row {i} body")]
        if i % 3 == 0:
            blocks.append(ws.toggle(f"row {i} toggle", [ws.para(f"row {i} hidden")]))
        if i == 3:
            sub = ws.add_page("Row Sub Page", {"type": "page_id", "page_id": "row"}, [ws.para("nested in row")])
            row_page["sub"] = sub
            blocks.append(ws.child_page_block(sub))
        return blocks

    db_id, ds_id, row_ids = ws.add_database(
        "Tasks", under(home), [f"Task {i}" for i in range(12)], row_blocks
    )
    ws.pages[row_page["sub"]]["parent"] = under(row_ids[3])  # nested inside its row
    linked = ws.add_linked_view(ds_id, "Tasks")

    ws.children[home] = [
        ws.heading("Welcome"),
        ws.toggle("More", [ws.para("hidden"), ws.toggle("Nested", [ws.para("deep text"), ws.child_page_block(deep)])]),
        ws.column_list([ws.para("left")], [ws.para("right"), ws.child_page_block(col)]),
        ws.table([["a", "b"], ["1", "2"], ["3", "4"]]),
        ws.child_page_block(alpha),
        ws.child_page_block(notes),
        ws.child_db_block(db_id, "Tasks"),
        ws.child_db_block(linked, ""),
    ]
    return ws
