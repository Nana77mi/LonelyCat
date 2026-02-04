"""默认 catalog 含 WebProvider；web.search 由 web 提供；order 中 web 在 builtin/stub 前。"""

from worker.tools.catalog import _default_catalog_factory


def test_default_catalog_factory_includes_web_provider_and_web_search_tool():
    """_default_catalog_factory() 后 catalog.get('web.search') 非 None；provider_id=web；order 中 web 在 builtin 与 stub 前。"""
    catalog = _default_catalog_factory()
    meta = catalog.get("web.search")
    assert meta is not None
    assert meta.name == "web.search"
    assert meta.provider_id == "web"
    order = catalog._preferred_provider_order
    assert "web" in order
    assert "builtin" in order
    assert "stub" in order
    assert order.index("web") < order.index("builtin"), "web 必须在 builtin 前，路径统一走 WebProvider"
    assert order.index("web") < order.index("stub")
