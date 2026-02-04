"""Default catalog 按 WEB_FETCH_BACKEND 选择 fetch backend（stub / httpx / 未知回退）。"""

import os
from unittest.mock import MagicMock, patch

from worker.tools.catalog import _default_catalog_factory, _web_fetch_backend_from_env


def test_default_catalog_fetch_backend_stub_when_unset():
    """WEB_FETCH_BACKEND 未设置或 stub → backend_id == stub。"""
    with patch.dict(os.environ, {"WEB_FETCH_BACKEND": ""}, clear=False):
        backend = _web_fetch_backend_from_env()
    assert getattr(backend, "backend_id", None) == "stub"


def test_default_catalog_fetch_backend_httpx_when_set():
    """WEB_FETCH_BACKEND=httpx → backend_id == httpx。"""
    with patch.dict(os.environ, {"WEB_FETCH_BACKEND": "httpx"}, clear=False):
        backend = _web_fetch_backend_from_env()
    assert getattr(backend, "backend_id", None) == "httpx"


def test_default_catalog_fetch_backend_unknown_falls_back_to_stub_and_warns():
    """WEB_FETCH_BACKEND=weird → 回退 stub 且 logger.warning 被调用。"""
    with patch.dict(os.environ, {"WEB_FETCH_BACKEND": "weird"}, clear=False):
        with patch("worker.tools.catalog.logger") as mock_logger:
            backend = _web_fetch_backend_from_env()
    assert getattr(backend, "backend_id", None) == "stub"
    mock_logger.warning.assert_called()
    call_args = str(mock_logger.warning.call_args)
    assert "weird" in call_args or "unknown" in call_args.lower()
