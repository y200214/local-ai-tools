"""未登録の保存ツールの一覧と確認内容。パッケージのコードは実行しない。"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from . import toolpack_store as storage


@dataclass(frozen=True)
class SavedTool:
    tool_id: str
    display_name: str
    versions: tuple[str, ...]
    restorable_versions: tuple[str, ...]
    stamp: str


@dataclass(frozen=True)
class SavedLibrary:
    tools: tuple[SavedTool, ...]
    problems: tuple[str, ...] = ()


def _plain_stat(path: Path):
    info = path.lstat()
    if (stat.S_ISLNK(info.st_mode)
            or getattr(info, "st_file_attributes", 0) & 0x400
            or not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode))
            or (stat.S_ISREG(info.st_mode) and info.st_nlink > 1)):
        raise storage.StoreError("リンクや特殊ファイルがあるため、この保存先は操作できません")
    return info


def safe_tree(store, tool_id: str, version: str | None = None):
    """削除前に絶対パス・全階層のリンクを検査し、一覧時の状態を記録する。"""
    if not isinstance(tool_id, str) or not storage.ID_PATTERN.fullmatch(tool_id):
        raise storage.StoreError("ツールIDが規約に合いません")
    if version is not None and (not isinstance(version, str)
                               or not storage.VERSION_PATTERN.fullmatch(version)):
        raise storage.StoreError("版の書式が不正です")
    installed = store.installed.absolute()
    target = installed / tool_id
    if version is not None:
        target /= version
    # root 自体や途中の親がジャンクションでも、外部へ辿ってはいけない。
    for ancestor in reversed((target, *target.parents)):
        _plain_stat(ancestor)
    resolved = target.resolve(strict=True)
    if not resolved.is_relative_to(installed.resolve(strict=True)) or not resolved.is_dir():
        raise storage.StoreError("保存領域内の通常のフォルダではありません")
    records = []
    files = []

    def record(path):
        info = _plain_stat(path)
        records.append((path.relative_to(target).as_posix(), info.st_mode,
                        info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_ino))
        if len(records) > 20000:
            raise storage.StoreError("保存ファイルが多すぎます。管理担当者へ確認してください")
        if stat.S_ISREG(info.st_mode):
            files.append(path)

    def fail(error):
        raise error

    record(target)
    for current, directories, names in os.walk(target, followlinks=False, onerror=fail):
        for name in sorted(directories + names):
            record(Path(current) / name)
    stamp = hashlib.sha256(json.dumps(sorted(records)).encode("utf-8")).hexdigest()
    return resolved, files, stamp


def saved_tool(store, tool_id: str) -> SavedTool:
    _target, files, stamp = safe_tree(store, tool_id)
    base = store.installed.absolute() / tool_id
    versions = tuple(sorted(
        (path.name for path in base.iterdir()
         if path.is_dir() and storage.VERSION_PATTERN.fullmatch(path.name)),
        key=lambda value: tuple(map(int, value.split("."))), reverse=True,
    ))
    name = tool_id
    for version in versions:
        meta_path = store.package_dir(tool_id, version).absolute() / "tool.json"
        if meta_path not in files or meta_path.stat().st_size > 128 * 1024:
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if isinstance(meta, dict) and isinstance(meta.get("display_name"), str):
                name = " ".join(meta["display_name"].split())[:160] or tool_id
                break
        except (OSError, ValueError):
            continue
    restorable = tuple(v for v in versions if store.source_path(tool_id, v).absolute() in files)
    return SavedTool(tool_id, name, versions, restorable, stamp)


def collect_saved(store) -> SavedLibrary:
    """登録があるツールは、有効/無効・承認に関係なく対象外。"""
    with storage.admin_lock():
        registry = store.load_registry()["tools"]
        if not store.installed.exists():
            return SavedLibrary(())
        for ancestor in reversed((store.installed.absolute(), *store.installed.absolute().parents)):
            _plain_stat(ancestor)
        items, problems = [], []
        for path in sorted(store.installed.iterdir()):
            if path.name in registry:
                continue
            try:
                items.append(saved_tool(store, path.name))
            except (storage.StoreError, OSError):
                problems.append(f"{path.name}: 保存先を安全に確認できないため操作対象外です")
        return SavedLibrary(tuple(items), tuple(problems))


def require_unchanged(store, item: SavedTool) -> None:
    if item.tool_id in store.load_registry()["tools"]:
        raise storage.StoreError(f"登録が残っています: {item.tool_id}。一覧を読み直してください")
    if saved_tool(store, item.tool_id).stamp != item.stamp:
        raise storage.StoreError(f"保存内容が変わりました: {item.tool_id}。一覧を読み直してください")


def restore_saved(store, item: SavedTool, version: str) -> bool:
    """保存原本から通常の再検査・再登録へ。既存IDの更新へは切り替えない。"""
    from . import toolpack_selection as selection

    with storage.admin_lock():
        require_unchanged(store, item)
        if version not in item.restorable_versions:
            raise storage.StoreError("選択した版の保存原本がありません")
        plan = selection.inspect_package(store.source_path(item.tool_id, version), store)
        if plan.tool_id != item.tool_id or plan.incoming_version != version or plan.registered:
            raise storage.StoreError("保存原本と選択したツール・版が一致しません")
        return selection.apply_selection(plan, "saved", store, version=version)
