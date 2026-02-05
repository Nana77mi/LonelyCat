import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def clear_web_search_cache():
    """每个测试前清空 web.search 缓存，避免跨测试返回其他 backend 的缓存结果。"""
    try:
        from worker.tools import web_provider
        if hasattr(web_provider, "_SEARCH_CACHE"):
            web_provider._SEARCH_CACHE.clear()
    except Exception:
        pass
    yield
