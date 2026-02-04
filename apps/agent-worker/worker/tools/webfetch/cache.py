"""webfetch 缓存：按规范化 URL 存储 raw/extracted/meta，SQLite 索引（PR#3）。"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, Optional

from worker.tools.webfetch.url_utils import normalize_fetch_url

TABLE_NAME = "web_documents"
TABLE_SQL = """
CREATE TABLE IF NOT EXISTS web_documents (
    normalized_url TEXT PRIMARY KEY,
    final_url TEXT NOT NULL,
    status_code INTEGER NOT NULL,
    content_type TEXT,
    raw_path TEXT NOT NULL,
    extracted_path TEXT NOT NULL,
    meta_path TEXT NOT NULL,
    stored_at TEXT NOT NULL
)
"""


def _safe_key(url: str) -> str:
    """URL 的磁盘安全子目录名（SHA256 前 16 位）。"""
    h = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return h[:16]


class WebFetchCache:
    """按规范化 URL 缓存 fetch 结果：SQLite + 持久化 raw.html / extracted.txt / meta.json。"""

    def __init__(self, cache_dir: str, db_path: Optional[str] = None) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = Path(db_path) if db_path else (self.cache_dir / "web_documents.db")
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute(TABLE_SQL)

    def get(self, url: str) -> Optional[Dict[str, Any]]:
        """按规范化 URL 查缓存；命中返回与 backend 合同一致的 dict 且 cache_hit=True，未命中返回 None。"""
        norm = normalize_fetch_url(url)
        if not norm:
            return None
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT final_url, status_code, content_type, raw_path, extracted_path, meta_path FROM web_documents WHERE normalized_url = ?",
                (norm,),
            ).fetchone()
        if not row:
            return None
        meta_path = Path(row["meta_path"])
        extracted_path = Path(row["extracted_path"])
        if not meta_path.exists() or not extracted_path.exists():
            return None
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        text = extracted_path.read_text(encoding="utf-8")
        raw_path_str = row["raw_path"]
        extracted_path_str = row["extracted_path"]
        meta_path_str = row["meta_path"]
        out = {
            "url": norm,
            "final_url": row["final_url"],
            "status_code": row["status_code"],
            "content_type": row["content_type"] or "",
            "text": text,
            "extracted_text": text,
            "truncated": meta.get("truncated", False),
            "cache_hit": True,
            "artifact_paths": {
                "raw": raw_path_str,
                "extracted": extracted_path_str,
                "meta": meta_path_str,
            },
        }
        if meta.get("title") is not None:
            out["title"] = meta["title"]
        if meta.get("extraction_method") is not None:
            out["extraction_method"] = meta["extraction_method"]
        if meta.get("paragraphs_count") is not None:
            out["paragraphs_count"] = meta["paragraphs_count"]
        return out

    def put(self, url: str, fetch_dict: Dict[str, Any], raw_bytes: bytes) -> None:
        """将一次 fetch 结果写入缓存：raw.html、extracted.txt、meta.json + SQLite。"""
        norm = normalize_fetch_url(url)
        if not norm:
            return
        key = _safe_key(norm)
        subdir = self.cache_dir / key
        subdir.mkdir(parents=True, exist_ok=True)
        raw_path = subdir / "raw.html"
        extracted_path = subdir / "extracted.txt"
        meta_path = subdir / "meta.json"

        raw_path.write_bytes(raw_bytes)
        text = fetch_dict.get("text") or fetch_dict.get("extracted_text") or ""
        extracted_path.write_text(text, encoding="utf-8")

        stored_at = str(int(time.time()))
        sha256_hex = hashlib.sha256(raw_bytes).hexdigest()
        bytes_read = len(raw_bytes)
        meta = {
            "url": norm,
            "normalized_url": norm,
            "final_url": fetch_dict.get("final_url") or norm,
            "status_code": fetch_dict.get("status_code", 0),
            "content_type": fetch_dict.get("content_type") or "",
            "stored_at": stored_at,
            "sha256": sha256_hex,
            "truncated": bool(fetch_dict.get("truncated", False)),
            "bytes_read": bytes_read,
            "cache_hit": False,
        }
        if fetch_dict.get("title") is not None:
            meta["title"] = fetch_dict["title"]
        if fetch_dict.get("extraction_method") is not None:
            meta["extraction_method"] = fetch_dict["extraction_method"]
        if fetch_dict.get("paragraphs_count") is not None:
            meta["paragraphs_count"] = fetch_dict["paragraphs_count"]
        meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")

        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO web_documents
                (normalized_url, final_url, status_code, content_type, raw_path, extracted_path, meta_path, stored_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    norm,
                    meta["final_url"],
                    meta["status_code"],
                    meta["content_type"],
                    str(raw_path),
                    str(extracted_path),
                    str(meta_path),
                    stored_at,
                ),
            )
