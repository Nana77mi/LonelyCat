from __future__ import annotations

import os
import sys
from pathlib import Path

# 添加 core-api 路径以便导入数据库模型
core_api_path = Path(__file__).parent.parent.parent / "core-api"
if str(core_api_path) not in sys.path:
    sys.path.insert(0, str(core_api_path))

from app.db import RunModel, RunStatus, SessionLocal

__all__ = ["RunModel", "RunStatus", "SessionLocal", "get_db_session"]


def get_db_session():
    """获取数据库会话"""
    return SessionLocal()
