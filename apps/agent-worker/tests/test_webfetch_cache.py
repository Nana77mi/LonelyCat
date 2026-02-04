"""Tests for webfetch cache: get/put by URL, cache_hit flag (TDD PR#3)."""

import json
import tempfile
from pathlib import Path

import pytest

from worker.tools.webfetch.cache import WebFetchCache
from worker.tools.webfetch.url_utils import normalize_fetch_url


def test_cache_get_miss_returns_none():
    """未命中时 get 返回 None。"""
    with tempfile.TemporaryDirectory() as tmp:
        cache = WebFetchCache(cache_dir=tmp)
        out = cache.get("https://example.com/page")
        assert out is None


def test_cache_put_then_get_returns_result_with_cache_hit_true():
    """put 后 get 返回与 backend 合同一致的 dict，且 cache_hit 为 True。"""
    with tempfile.TemporaryDirectory() as tmp:
        cache = WebFetchCache(cache_dir=tmp)
        url = "https://example.com/article"
        fetch_dict = {
            "url": url,
            "final_url": url,
            "status_code": 200,
            "content_type": "text/html; charset=utf-8",
            "text": "Hello world",
            "extracted_text": "Hello world",
            "truncated": False,
            "title": "Example",
            "extraction_method": "readability",
            "paragraphs_count": 1,
        }
        raw_bytes = b"<html><head><title>Example</title></head><body>Hello world</body></html>"
        cache.put(url, fetch_dict, raw_bytes)
        out = cache.get(url)
        assert out is not None
        assert out.get("cache_hit") is True
        assert out.get("url") == url
        assert out.get("final_url") == url
        assert out.get("status_code") == 200
        assert out.get("text") == "Hello world"
        assert out.get("title") == "Example"
        assert out.get("extraction_method") == "readability"
        assert "artifact_paths" in out
        ap = out["artifact_paths"]
        assert "raw" in ap and "extracted" in ap and "meta" in ap
        assert Path(ap["raw"]).exists()
        assert Path(ap["extracted"]).exists()
        assert Path(ap["meta"]).exists()


def test_cache_get_uses_normalized_url():
    """get 使用规范化 URL 作为 key，与 put 时一致。"""
    with tempfile.TemporaryDirectory() as tmp:
        cache = WebFetchCache(cache_dir=tmp)
        url_canonical = normalize_fetch_url("https://example.com/p?utm_source=1")
        fetch_dict = {
            "url": url_canonical,
            "final_url": url_canonical,
            "status_code": 200,
            "content_type": "text/html",
            "text": "Body",
            "truncated": False,
        }
        cache.put("https://example.com/p?utm_source=1", fetch_dict, b"<html>Body</html>")
        # get with same normalized form hits
        out1 = cache.get("https://example.com/p?utm_source=1")
        assert out1 is not None and out1.get("cache_hit") is True
        out2 = cache.get(url_canonical)
        assert out2 is not None and out2.get("cache_hit") is True


def test_cache_put_writes_raw_html_extracted_txt_meta_json():
    """put 在 cache_dir 下写入 raw.html、extracted.txt、meta.json。"""
    with tempfile.TemporaryDirectory() as tmp:
        cache = WebFetchCache(cache_dir=tmp)
        url = "https://example.com/x"
        fetch_dict = {
            "url": url,
            "final_url": url,
            "status_code": 200,
            "content_type": "text/html",
            "text": "Extracted",
            "truncated": False,
            "title": "T",
        }
        raw_bytes = b"<html><body>Raw</body></html>"
        cache.put(url, fetch_dict, raw_bytes)
        base = Path(tmp)
        # 应存在一个子目录（按 url 的 safe key）
        subdirs = [d for d in base.iterdir() if d.is_dir()]
        assert len(subdirs) == 1
        d = subdirs[0]
        raw_path = d / "raw.html"
        extracted_path = d / "extracted.txt"
        meta_path = d / "meta.json"
        assert raw_path.exists()
        assert extracted_path.exists()
        assert meta_path.exists()
        assert raw_path.read_bytes() == raw_bytes
        assert extracted_path.read_text(encoding="utf-8") == "Extracted"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        assert meta.get("url") == url
        assert meta.get("normalized_url") == url
        assert meta.get("status_code") == 200
        assert meta.get("title") == "T"
        assert "sha256" in meta
        assert len(meta["sha256"]) == 64
        assert "stored_at" in meta
        assert meta.get("bytes_read") == len(raw_bytes)
        assert meta.get("truncated") is False
        assert meta.get("cache_hit") is False
        assert meta.get("extraction_method") is None  # 未传则无
        assert "content_type" in meta
        assert "final_url" in meta
