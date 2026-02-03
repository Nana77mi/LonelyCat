"""Database models adapter layer.

This module provides a single point of import for core-api models.
Future decoupling (e.g., worker as separate service) only needs to change this file.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Add core-api path for imports
core_api_path = Path(__file__).parent.parent.parent / "core-api"
if str(core_api_path) not in sys.path:
    sys.path.insert(0, str(core_api_path))

from app.db import MessageModel, MessageRole

__all__ = ["MessageModel", "MessageRole"]
