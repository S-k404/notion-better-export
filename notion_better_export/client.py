import time
import logging
from typing import Any, Callable, Dict, List, Optional
from notion_client import Client
from notion_client.errors import APIResponseError

logger = logging.getLogger("notion_better_export")
# Suppress notion_client's internal noisy WARNING logs since we handle retries and pacing cleanly
logging.getLogger("notion_client").setLevel(logging.ERROR)


class NotionRateLimiter:
    """Enforces Notion's average rate limit (3 requests per second) proactively
    to prevent HTTP 429 errors and API throttling delays.
    """

    def __init__(self, requests_per_second: float = 2.8):
        self.interval = 1.0 / requests_per_second
        self.last_request_time = 0.0

    def wait(self) -> None:
        now = time.time()
        elapsed = now - self.last_request_time
        if elapsed < self.interval:
            time.sleep(self.interval - elapsed)
        self.last_request_time = time.time()


class NotionApiClient:
    """Robust Notion API Client with proactive rate limiting and exponential backoff."""

    def __init__(self, token: str, max_retries: int = 5, base_delay: float = 1.0):
        self.client = Client(auth=token)
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.rate_limiter = NotionRateLimiter(requests_per_second=2.8)

    def retry(self, func: Callable, *args, **kwargs) -> Any:
        """Executes API function with proactive pacing and exponential backoff on 429."""
        delay = self.base_delay
        for attempt in range(self.max_retries):
            try:
                self.rate_limiter.wait()
                return func(*args, **kwargs)
            except APIResponseError as err:
                if err.status == 429 or "rate_limited" in str(err).lower():
                    # Check for Retry-After header or fallback
                    retry_after = getattr(err, "headers", {}).get("retry-after")
                    wait_sec = float(retry_after) if retry_after else max(delay, 2.0)
                    logger.warning(
                        "Rate limited by Notion API (attempt %d/%d). Sleeping %.2fs...",
                        attempt + 1,
                        self.max_retries,
                        wait_sec,
                    )
                    time.sleep(wait_sec)
                    delay *= 2
                    continue
                if err.status >= 500:
                    logger.warning(
                        "Notion API 5xx error (%s). Retrying in %.2fs...",
                        err.message,
                        delay,
                    )
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise
            except Exception as e:
                msg = str(e).lower()
                if "connection" in msg or "timeout" in msg:
                    logger.warning(
                        "Network error (%s). Retrying in %.2fs...", e, delay
                    )
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise
        return func(*args, **kwargs)

    def search_all(self, filter_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Search for all accessible objects in the workspace."""
        results: List[Dict[str, Any]] = []
        cursor = None
        while True:
            kwargs: Dict[str, Any] = {"page_size": 100}
            if cursor:
                kwargs["start_cursor"] = cursor
            if filter_type:
                kwargs["filter"] = {"property": "object", "value": filter_type}

            resp = self.retry(self.client.search, **kwargs)
            results.extend(resp.get("results", []))
            if not resp.get("has_more"):
                break
            cursor = resp.get("next_cursor")
        return results

    def list_block_children(self, block_id: str) -> List[Dict[str, Any]]:
        """Fetch all children blocks for a page or container block."""
        results: List[Dict[str, Any]] = []
        cursor = None
        while True:
            kwargs: Dict[str, Any] = {"block_id": block_id, "page_size": 100}
            if cursor:
                kwargs["start_cursor"] = cursor
            resp = self.retry(self.client.blocks.children.list, **kwargs)
            results.extend(resp.get("results", []))
            if not resp.get("has_more"):
                break
            cursor = resp.get("next_cursor")
        return results

    def query_database_rows(
        self,
        db_or_data_source_id: str,
        is_data_source: bool = False,
        max_rows: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Query rows of a database or data source.
        Supports Notion's 2025-09-03 API (data_sources) with fallback to databases.query.
        """
        results: List[Dict[str, Any]] = []
        cursor = None

        query_fn = None
        id_param = "database_id"
        if is_data_source and hasattr(self.client, "data_sources"):
            query_fn = self.client.data_sources.query
            id_param = "data_source_id"
        elif hasattr(self.client.databases, "query"):
            query_fn = self.client.databases.query
            id_param = "database_id"
        elif hasattr(self.client, "data_sources"):
            query_fn = self.client.data_sources.query
            id_param = "data_source_id"

        if not query_fn:
            raise RuntimeError("No suitable query endpoint found on Notion client.")

        while True:
            kwargs: Dict[str, Any] = {id_param: db_or_data_source_id, "page_size": 100}
            if cursor:
                kwargs["start_cursor"] = cursor

            resp = self.retry(query_fn, **kwargs)
            results.extend(resp.get("results", []))

            if max_rows and len(results) >= max_rows:
                results = results[:max_rows]
                break

            if not resp.get("has_more"):
                break
            cursor = resp.get("next_cursor")
        return results

    def retrieve_page(self, page_id: str) -> Dict[str, Any]:
        return self.retry(self.client.pages.retrieve, page_id=page_id)

    def retrieve_database(self, database_id: str) -> Dict[str, Any]:
        try:
            return self.retry(self.client.databases.retrieve, database_id=database_id)
        except APIResponseError as err:
            if err.status == 404 or "object_not_found" in str(err).lower():
                if hasattr(self.client, "data_sources"):
                    try:
                        return self.retry(
                            self.client.data_sources.retrieve, data_source_id=database_id
                        )
                    except Exception:
                        pass
            raise

    def retrieve_data_source(self, data_source_id: str) -> Dict[str, Any]:
        if hasattr(self.client, "data_sources"):
            try:
                return self.retry(
                    self.client.data_sources.retrieve, data_source_id=data_source_id
                )
            except APIResponseError as err:
                if err.status == 404 or "object_not_found" in str(err).lower():
                    try:
                        return self.retry(
                            self.client.databases.retrieve, database_id=data_source_id
                        )
                    except Exception:
                        pass
                raise
        return self.retrieve_database(data_source_id)

    def retrieve_block(self, block_id: str) -> Dict[str, Any]:
        return self.retry(self.client.blocks.retrieve, block_id=block_id)
