"""从 repo 根 skills/ 目录加载 manifest，供 GET /skills 与 POST /skills/{id}/invoke。"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# skill id 必须匹配 [a-z0-9]+(\.[a-z0-9]+)+，与 manifest.schema.json 一致
# 目录名必须等于 id（含点），如 skills/shell.run/manifest.json
SKILL_ID_PATTERN = re.compile(r"^[a-z0-9]+(\.[a-z0-9]+)+$")


def _find_repo_root() -> Path | None:
    """从当前文件向上查找含 .git 或 pyproject.toml 的目录作为 repo 根。"""
    start = Path(__file__).resolve().parent
    for parent in [start, *start.parents]:
        if (parent / ".git").exists() or (parent / "pyproject.toml").is_file():
            return parent
    return None


def get_skills_root() -> Path:
    """
    Skills 目录解析顺序：
    1) 环境变量 REPO_ROOT → <REPO_ROOT>/skills
    2) 环境变量 SKILLS_ROOT → 直接作为 skills 目录（可指向 skills 目录本身）
    3) 从当前文件向上找 .git 或 pyproject.toml 作为 repo 根 → <repo_root>/skills
    4) 最后 fallback 到 cwd/skills
    """
    if os.environ.get("SKILLS_ROOT"):
        return Path(os.environ["SKILLS_ROOT"]).resolve()
    if os.environ.get("REPO_ROOT"):
        return Path(os.environ["REPO_ROOT"]).resolve() / "skills"
    repo = _find_repo_root()
    if repo is not None:
        return repo / "skills"
    return Path(os.getcwd()).resolve() / "skills"


def _get_schema_path() -> Path:
    return get_skills_root() / "_schema" / "manifest.schema.json"


def _load_schema() -> dict[str, Any] | None:
    path = _get_schema_path()
    if not path.is_file():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _validate_manifest_schema(manifest: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    """用 jsonschema 校验 manifest，返回错误列表（空表示通过）。"""
    import jsonschema
    try:
        jsonschema.validate(instance=manifest, schema=schema)
        return []
    except jsonschema.ValidationError as e:
        return [getattr(e, "message", str(e))]
    except jsonschema.SchemaError:
        return ["schema invalid"]


def list_skills() -> list[dict[str, Any]]:
    """
    列出 skills 目录下所有有效技能。
    要求：存在 manifest.json、id 匹配规范、目录名等于 id（含点）、通过 schema 校验。
    schema 校验失败则跳过该 skill 并打日志，不 500。
    """
    root = get_skills_root()
    if not root.is_dir():
        return []
    schema = _load_schema()
    result = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        manifest_path = child / "manifest.json"
        if not manifest_path.is_file():
            continue
        try:
            manifest = _load_manifest_file(manifest_path)
        except (json.JSONDecodeError, OSError):
            logger.warning("skill manifest load failed: %s", manifest_path, exc_info=True)
            continue
        sid = manifest.get("id")
        if not sid or not SKILL_ID_PATTERN.match(sid):
            continue
        if child.name != sid:
            continue
        if schema:
            errs = _validate_manifest_schema(manifest, schema)
            if errs:
                logger.warning("skill manifest schema invalid (skipped) id=%s path=%s errors=%s", sid, manifest_path, errs)
                continue
        result.append({
            "id": sid,
            "name": manifest.get("name", ""),
            "description": manifest.get("description", ""),
            "runtime": manifest.get("runtime", {}),
            "interface": manifest.get("interface", {}),
            "permissions": manifest.get("permissions", {}),
            "limits": manifest.get("limits", {}),
        })
    return result


def load_manifest(skill_id: str) -> dict[str, Any] | None:
    """
    加载指定 skill_id 的 manifest。
    id 必须匹配 [a-z0-9]+(.[a-z0-9]+)+，路径限定在 skills/<id>/manifest.json。
    若 schema 校验失败则抛出 ValueError（调用方返回 500）。
    """
    if not skill_id or not SKILL_ID_PATTERN.match(skill_id):
        return None
    root = get_skills_root()
    manifest_path = root / skill_id / "manifest.json"
    if not manifest_path.is_file():
        return None
    try:
        manifest = _load_manifest_file(manifest_path)
    except (json.JSONDecodeError, OSError) as e:
        raise ValueError(f"manifest read failed: {manifest_path}") from e
    schema = _load_schema()
    if schema:
        errs = _validate_manifest_schema(manifest, schema)
        if errs:
            raise ValueError(f"manifest schema invalid: {errs}")
    return manifest


def _load_manifest_file(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)
