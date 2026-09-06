"""追加前の確認内容と、利用者が選んだ再登録・新版登録の実行。GUIに判断を置かない。"""

from __future__ import annotations

import hashlib
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import toolpack_install as installer
from . import toolpack_store as storage
from . import toolpack_verify as verifier


@dataclass(frozen=True)
class SavedVersion:
    version: str
    source_hash: str | None
    registered: bool


@dataclass(frozen=True)
class Selection:
    package: Path
    tool_id: str
    display_name: str
    incoming_version: str
    incoming_hash: str
    registered: bool
    registry_stamp: str
    versions: tuple[SavedVersion, ...]

    @property
    def needs_confirmation(self) -> bool:
        return self.registered or bool(self.versions)

    @property
    def suggested_version(self) -> str:
        incoming = installer.version_key(self.incoming_version)
        saved = [installer.version_key(s.version) for s in self.versions]
        if not saved or incoming > max(saved):
            return self.incoming_version
        major, minor, patch = max(saved)
        return f"{major}.{minor}.{patch + 1}"


def _stamp(entry) -> str:
    return hashlib.sha256(json.dumps(entry, sort_keys=True).encode()).hexdigest()


def inspect_package(package: Path, store: storage.ToolpackStore) -> Selection:
    """形式だけを一時領域で検査。実行・登録・モデル削除はしない。"""
    package = Path(package).resolve()
    before = installer._package_hash(package)
    with tempfile.TemporaryDirectory(prefix="toolpack-selection-") as temporary:
        result = verifier.verify_package(package, Path(temporary) / "package")
        if not result.ok:
            raise installer.InstallError(
                installer.STAGE_VERIFY, "パッケージが検査に通りませんでした",
                "\n".join(str(error) for error in result.errors[:10]),
            )
    if before != installer._package_hash(package):
        raise installer.InstallError(installer.STAGE_VERIFY, "検査中にZIPが変わりました。選び直してください")
    meta = result.tool_json
    tool_id = meta["id"]
    with storage.admin_lock():
        entry = store.load_registry()["tools"].get(tool_id)
        versions = []
        for version in installer.saved_versions(store, tool_id):
            source = store.source_path(tool_id, version)
            try:
                digest = installer._package_hash(source) if source.is_file() else None
            except OSError:
                digest = None
            versions.append(SavedVersion(version, digest, version in (entry or {}).get("versions", {})))
    return Selection(package, tool_id, meta["display_name"], meta["version"], before,
                     entry is not None, _stamp(entry), tuple(versions))


def apply_selection(selection: Selection, choice: str, store: storage.ToolpackStore,
                    *, version: str = "") -> bool:
    """明示した選択だけを実行。確認中に登録やZIPが変わったら選び直してもらう。"""
    with storage.admin_lock():
        entry = store.load_registry()["tools"].get(selection.tool_id)
        if _stamp(entry) != selection.registry_stamp:
            raise installer.InstallError(installer.STAGE_TARGET, "確認中に登録状態が変わりました。選び直してください")
        if choice == "new":
            report = installer.install(selection.package, apply=True, update=selection.registered,
                                       new_version=version, expected_hash=selection.incoming_hash, store=store)
        elif choice == "add" and not selection.needs_confirmation:
            report = installer.install(selection.package, apply=True,
                                       expected_hash=selection.incoming_hash, store=store)
        elif choice == "saved":
            saved = next((s for s in selection.versions if s.version == version), None)
            if saved is None or saved.source_hash is None:
                raise installer.InstallError(installer.STAGE_SAVED, "選択した版の保存原本がありません")
            source = store.source_path(selection.tool_id, version)
            if installer._package_hash(source) != saved.source_hash:
                raise installer.InstallError(installer.STAGE_SAVED, "確認中に保存原本が変わりました。選び直してください")
            if saved.registered:
                # 既存の版への切替は既存コアに委譲し、承認・無効化の保護を迂回しない。
                from . import toolpack_manage as manage

                if storage.is_approved(entry):
                    raise installer.InstallError(installer.STAGE_TARGET, "承認済みのツールはこの操作で変更できません")
                if entry.get("active_version") == version:
                    if entry.get("enabled", True):
                        problems = manage._verify(selection.tool_id, in_openwebui=True, in_hub=True)
                        if problems:
                            raise installer.InstallError(installer.STAGE_REACH, "使用中の版の登録を確認できません", "\n".join(problems))
                        print(f"既に保存済みの版 {version} を使用しています。変更はありません。")
                        return True
                    return manage.command_enable(store, selection.tool_id) == 0
                if entry.get("enabled", True) is False:
                    raise installer.InstallError(installer.STAGE_TARGET, "無効なツールです。先に有効に戻してから版を切り替えてください")
                return manage.command_rollback(store, selection.tool_id, version) == 0
            report = installer.install(source, apply=True, update=selection.registered,
                                       restore_saved=True, expected_hash=saved.source_hash, store=store)
        else:
            raise installer.InstallError(installer.STAGE_TARGET, "登録方法を明示的に選択してください")
    print(installer.format_report(report))
    return report.ok
