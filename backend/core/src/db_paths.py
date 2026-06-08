# -*- coding: utf-8 -*-
"""Shared SQLite path resolution for backend subsystems."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Iterable, Optional


logger = logging.getLogger(__name__)

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_REPO_ROOT = _BACKEND_ROOT.parent
_BACKEND_DATA_DIR = _BACKEND_ROOT / "data"

WEB_DB_FILENAME = "stock_analysis_app.db"
CORE_DB_FILENAME = "stock_analysis_core.db"

_LEGACY_WEB_DB_PATH = _BACKEND_ROOT / "stock_analysis.db"
_LEGACY_CORE_DB_PATHS = (
    _BACKEND_DATA_DIR / "stock_analysis.db",
    _REPO_ROOT / "data" / "stock_analysis.db",
)
_DEFAULT_CORE_DB_ALIASES = {
    "",
    "./data/stock_analysis.db",
    "data/stock_analysis.db",
    "./backend/data/stock_analysis.db",
    "backend/data/stock_analysis.db",
    f"./data/{CORE_DB_FILENAME}",
    f"data/{CORE_DB_FILENAME}",
}


def backend_root() -> Path:
    return _BACKEND_ROOT


def backend_data_dir() -> Path:
    return _BACKEND_DATA_DIR


def default_web_database_path() -> Path:
    return backend_data_dir() / WEB_DB_FILENAME


def default_core_database_path() -> Path:
    return backend_data_dir() / CORE_DB_FILENAME


def _sqlite_sidecar_paths(base_path: Path) -> list[Path]:
    return [
        base_path,
        Path(f"{base_path}-wal"),
        Path(f"{base_path}-shm"),
    ]


def _latest_sqlite_mtime(base_path: Path) -> float:
    mtimes = []
    for path in _sqlite_sidecar_paths(base_path):
        if path.exists():
            try:
                mtimes.append(path.stat().st_mtime)
            except OSError:
                continue
    return max(mtimes) if mtimes else -1.0


def _migrate_sqlite_files(target: Path, candidates: Iterable[Path]) -> None:
    if any(path.exists() for path in _sqlite_sidecar_paths(target)):
        return

    ranked_candidates = []
    for candidate in candidates:
        latest_mtime = _latest_sqlite_mtime(candidate)
        if latest_mtime >= 0:
            ranked_candidates.append((latest_mtime, candidate))

    for _, candidate in sorted(ranked_candidates, key=lambda item: item[0], reverse=True):
        source_paths = [path for path in _sqlite_sidecar_paths(candidate) if path.exists()]
        if not source_paths:
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            for source_path in source_paths:
                suffix = source_path.name[len(candidate.name) :]
                destination = Path(f"{target}{suffix}")
                if destination.exists():
                    continue
                try:
                    source_path.replace(destination)
                except OSError:
                    shutil.copy2(source_path, destination)
                    source_path.unlink()
            logger.info("SQLite 数据文件已迁移到统一目录: %s", target)
        except Exception as exc:
            logger.warning(
                "SQLite 数据文件迁移失败，继续使用目标路径 %s: %s",
                target,
                exc,
            )
        return


def _normalize_input_path(path_value: Optional[str]) -> str:
    return (path_value or "").strip()


def resolve_web_database_path() -> Path:
    target = default_web_database_path()
    _migrate_sqlite_files(target, [_LEGACY_WEB_DB_PATH])
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def resolve_core_database_path(path_value: Optional[str] = None) -> Path:
    raw = _normalize_input_path(path_value)

    if raw in _DEFAULT_CORE_DB_ALIASES:
        target = default_core_database_path()
    else:
        raw_path = Path(raw).expanduser()
        target = raw_path if raw_path.is_absolute() else (backend_root() / raw_path).resolve()

    if target == default_core_database_path():
        _migrate_sqlite_files(target, _LEGACY_CORE_DB_PATHS)

    target.parent.mkdir(parents=True, exist_ok=True)
    return target
