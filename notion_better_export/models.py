from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from pathlib import Path


@dataclass
class NotionObject:
    """Represents a Notion Page, Database, or Data Source."""
    id: str
    object_type: str  # "page", "database", "data_source"
    title: str
    parent_type: str  # "workspace", "page_id", "database_id", "block_id"
    parent_id: Optional[str] = None
    created_time: str = ""
    last_edited_time: str = ""
    url: str = ""
    icon: str = ""
    properties: Dict[str, Any] = field(default_factory=dict)
    
    # Hierarchy and resolution fields
    rel_path: str = ""               # Vault-relative path without extension
    file_path: Optional[Path] = None  # Full output file path
    is_linked_view: bool = False
    canonical_id: Optional[str] = None
    view_title: Optional[str] = None


@dataclass
class DatabaseRow:
    """Represents a single row/entry in a Notion database."""
    id: str
    title: str
    date_prefix: str
    database_id: str
    properties: Dict[str, Any] = field(default_factory=dict)
    plain_properties: Dict[str, Any] = field(default_factory=dict)
    # prop_name -> list of target page/row UUIDs
    relations: Dict[str, List[str]] = field(default_factory=dict)
    rel_path: str = ""
    file_name: str = ""
    created_time: str = ""
    last_edited_time: str = ""
    url: str = ""


@dataclass
class DatabaseMetadata:
    """Metadata and schema for a Notion database."""
    id: str
    title: str
    properties_schema: Dict[str, Any] = field(default_factory=dict)
    parent_id: Optional[str] = None
    parent_type: str = "workspace"
    is_linked_view: bool = False
    canonical_id: Optional[str] = None
    rows: List[DatabaseRow] = field(default_factory=list)
    rel_folder: str = ""
