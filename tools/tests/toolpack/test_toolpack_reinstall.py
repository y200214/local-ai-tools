"""再追加の確認・保存版の再登録・明示的な新版採番。外部登録は全てフェイク。"""

import hashlib
import json
import zipfile

import pytest

import toolpack_install as installer
import toolpack_gui as gui
from toolpack import toolpack_selection as selection
from test_toolpack_install import build_localtool, tool_json, store, deploy_stub


def contents(directory):
    return {p.relative_to(directory).as_posix(): p.read_bytes()
            for p in directory.rglob("*") if p.is_file()}


def saved_tool(tmp_path, store, deploy_stub):
    package = build_localtool(tmp_path)
    result = installer.install(package, apply=True, store=store)
    assert result.ok, result.reason
    store.unregister("duty_summary")
    deploy_stub.present.clear()
    deploy_stub.hub_ids.clear()
    return package


def test_saved_copy_requires_confirmation_before_tests(tmp_path, store, deploy_stub, monkeypatch):
    package = saved_tool(tmp_path, store, deploy_stub)
    before = contents(store.installed)
    monkeypatch.setattr(installer, "_stage_tests", lambda *args: pytest.fail("確認前に実行しない"))
    result = installer.install(package, apply=True, store=store)
    assert result.failed_stage == installer.STAGE_SAVED
    assert "保存済み" in result.reason
    assert store.load_registry()["tools"] == {}
    assert contents(store.installed) == before


def test_restore_saved_version_rechecks_without_overwriting(tmp_path, store, deploy_stub):
    package = saved_tool(tmp_path, store, deploy_stub)
    before = contents(store.installed)
    plan = selection.inspect_package(package, store)
    assert plan.needs_confirmation and not plan.registered
    assert [v.version for v in plan.versions] == ["1.0.0"]
    assert selection.apply_selection(plan, "saved", store, version="1.0.0")
    assert store.load_registry()["tools"]["duty_summary"]["status"] == "unapproved"
    assert contents(store.installed) == before
    assert not list(store.staging.iterdir())
    assert not list(store.incoming.iterdir())


def test_restore_deploy_failure_preserves_saved_files(tmp_path, store, deploy_stub):
    package = saved_tool(tmp_path, store, deploy_stub)
    pipe = store.generated_dir("duty_summary", "1.0.0") / "open_webui_duty_summary_pipe.py"
    pipe.write_text("# previous generated source\n", encoding="utf-8")
    before = contents(store.installed)
    deploy_stub.should_fail = True
    result = installer.install(package, apply=True, restore_saved=True, store=store)
    assert not result.ok and result.failed_stage == installer.STAGE_DEPLOY
    assert store.load_registry()["tools"] == {}
    assert contents(store.installed) == before
    assert "duty_summary" in deploy_stub.removed


@pytest.mark.parametrize("changed", ["main.py", "extra.txt"])
def test_changed_saved_contents_are_not_reused(tmp_path, store, deploy_stub, changed):
    package = saved_tool(tmp_path, store, deploy_stub)
    (store.package_dir("duty_summary", "1.0.0") / changed).write_text("changed", encoding="utf-8")
    before = contents(store.installed)
    result = installer.install(package, apply=True, restore_saved=True, store=store)
    assert not result.ok and result.failed_stage == installer.STAGE_SAVED
    assert contents(store.installed) == before
    assert store.load_registry()["tools"] == {}


@pytest.mark.parametrize("registered", [False, True])
def test_new_version_from_same_zip_preserves_original_and_old_version(tmp_path, store, deploy_stub, registered):
    package = saved_tool(tmp_path, store, deploy_stub)
    if registered:
        restored = installer.install(package, apply=True, restore_saved=True, store=store)
        assert restored.ok
    original = package.read_bytes()
    previous = contents(store.version_dir("duty_summary", "1.0.0"))
    plan = selection.inspect_package(package, store)
    assert plan.registered is registered
    assert plan.suggested_version == "1.0.1"
    assert selection.apply_selection(plan, "new", store, version="1.0.1")
    entry = store.load_registry()["tools"]["duty_summary"]
    assert entry["active_version"] == "1.0.1" and entry["status"] == "unapproved"
    assert not entry["versions"]["1.0.1"]["approved"]
    assert package.read_bytes() == original
    assert contents(store.version_dir("duty_summary", "1.0.0")) == previous
    source = store.source_path("duty_summary", "1.0.1")
    assert (source.parent / "imported.zip").read_bytes() == original
    with zipfile.ZipFile(source) as packed, zipfile.ZipFile(package) as imported:
        meta = json.loads(packed.read("tool.json"))
        assert meta["version"] == "1.0.1"
        for name in imported.namelist():
            if name not in ("tool.json", "manifest.sha256"):
                assert packed.read(name) == imported.read(name)
    record = json.loads(store.install_json_path("duty_summary", "1.0.1").read_text(encoding="utf-8"))
    assert record["original_package_hash"] == hashlib.sha256(original).hexdigest()
    assert record["original_version"] == "1.0.0"
    assert installer.toolpack_verify.check_manifest(store.package_dir("duty_summary", "1.0.1")) == []


def test_changed_incoming_same_version_can_become_explicit_new_version(tmp_path, store, deploy_stub):
    saved_tool(tmp_path, store, deploy_stub)
    changed = build_localtool(tmp_path, name="changed.zip", meta=tool_json(summary="変更した内容"))
    plan = selection.inspect_package(changed, store)
    assert selection.apply_selection(plan, "new", store, version="2.0.0")
    meta = json.loads((store.package_dir("duty_summary", "2.0.0") / "tool.json").read_text(encoding="utf-8"))
    assert meta["summary"] == "変更した内容"


@pytest.mark.parametrize("version", ["1.0.0", "0.9.9", "../elsewhere", "1.0", "v2"])
def test_invalid_or_existing_version_is_refused(tmp_path, store, deploy_stub, version):
    package = saved_tool(tmp_path, store, deploy_stub)
    before = contents(store.installed)
    result = installer.install(package, apply=True, new_version=version, store=store)
    assert not result.ok and result.failed_stage == installer.STAGE_TARGET
    assert contents(store.installed) == before


def test_new_version_failure_leaves_old_version_intact(tmp_path, store, deploy_stub):
    package = saved_tool(tmp_path, store, deploy_stub)
    before = contents(store.installed)
    deploy_stub.should_fail = True
    result = installer.install(package, apply=True, new_version="1.0.1", store=store)
    assert not result.ok and result.failed_stage == installer.STAGE_DEPLOY
    assert contents(store.installed) == before
    assert store.load_registry()["tools"] == {}


def test_confirmation_has_no_registration_side_effect(tmp_path, store, deploy_stub):
    package = saved_tool(tmp_path, store, deploy_stub)
    before = contents(store.root)
    selection.inspect_package(package, store)
    assert contents(store.root) == before


def test_registry_changed_while_dialog_open_requires_new_confirmation(tmp_path, store, deploy_stub):
    package = saved_tool(tmp_path, store, deploy_stub)
    plan = selection.inspect_package(package, store)
    store.register("duty_summary", "1.0.0", package_hash="changed")
    with pytest.raises(installer.InstallError, match="登録状態が変わり"):
        selection.apply_selection(plan, "new", store, version="1.0.1")


def test_zip_changed_while_dialog_open_is_refused(tmp_path, store, deploy_stub):
    package = saved_tool(tmp_path, store, deploy_stub)
    plan = selection.inspect_package(package, store)
    package.write_bytes(b"changed")
    assert not selection.apply_selection(plan, "new", store, version="1.0.1")
    assert store.load_registry()["tools"] == {}


def test_approved_model_cannot_be_replaced_via_confirmation(tmp_path, store, deploy_stub):
    package = saved_tool(tmp_path, store, deploy_stub)
    assert installer.install(package, apply=True, restore_saved=True, store=store).ok
    registry = store.load_registry()
    registry["tools"]["duty_summary"]["versions"]["1.0.0"]["approved"] = True
    store._write_registry(registry)
    plan = selection.inspect_package(package, store)
    assert not selection.apply_selection(plan, "new", store, version="1.0.1")
    assert store.load_registry()["tools"]["duty_summary"]["active_version"] == "1.0.0"


def test_gui_cancel_does_not_call_registration(monkeypatch):
    from types import SimpleNamespace

    messages = []
    app = SimpleNamespace(master=None, write=messages.append, reload=lambda: None,
                          start=lambda *args: pytest.fail("キャンセル時に登録しない"))
    monkeypatch.setattr(gui, "choose_existing", lambda *args: None)
    gui.App._confirm_selection(app, SimpleNamespace(needs_confirmation=True))
    assert "変更していません" in messages[0]


@pytest.mark.parametrize("choice, version", [("saved", "1.0.0"), ("new", "1.0.1")])
def test_gui_passes_explicit_choice_to_core(monkeypatch, choice, version):
    from types import SimpleNamespace

    plan = SimpleNamespace(needs_confirmation=True)
    marker = object()
    calls = []
    app = SimpleNamespace(master=None, store=marker, start=lambda label, fn: fn())
    monkeypatch.setattr(gui, "choose_existing", lambda *args: (choice, version))
    monkeypatch.setattr(gui, "action_selection", lambda *args: calls.append(args))
    gui.App._confirm_selection(app, plan)
    assert calls == [(plan, choice, marker, version)]


@pytest.mark.parametrize("button, expected", [
    ("この保存済みの版を使う", ("saved", "1.0.0")),
    ("この版番号で新版として登録", ("new", "1.2.0")),
    ("キャンセル", None),
])
def test_confirmation_widgets_without_visible_window(monkeypatch, button, expected):
    import tkinter as tk
    from tkinter import messagebox
    from pathlib import Path

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tkの表示環境がありません")
    root.withdraw()
    original_top = tk.Toplevel
    callback_errors = []

    def visit(widget):
        for child in widget.winfo_children():
            yield child
            yield from visit(child)

    class HiddenDialog(original_top):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.withdraw()
            self.after(0, self.click)

        def grab_set(self):
            pass  # 非表示の試験窓で利用者の入力を奪わない

        def click(self):
            try:
                widgets = list(visit(self))
                assert any(w.winfo_class() == "TCombobox" for w in widgets)
                entry = next(w for w in widgets if w.winfo_class() == "TEntry")
                entry.delete(0, "end")
                entry.insert(0, "1.2.0")
                target = next(w for w in widgets if w.winfo_class() == "TButton" and w.cget("text") == button)
                target.invoke()
            except Exception as error:
                callback_errors.append(error)
                self.destroy()

    monkeypatch.setattr(tk, "Toplevel", HiddenDialog)
    monkeypatch.setattr(messagebox, "askokcancel", lambda *args, **kwargs: True)
    plan = selection.Selection(Path("trial.zip"), "trial_tool", "試験ツール", "1.0.0", "hash",
                               False, "stamp", (selection.SavedVersion("1.0.0", "hash", False),))
    try:
        assert gui.choose_existing(root, plan) == expected
        assert not callback_errors
    finally:
        root.destroy()


def test_failed_new_version_update_keeps_registered_previous_version(tmp_path, store, deploy_stub, monkeypatch):
    package = saved_tool(tmp_path, store, deploy_stub)
    assert installer.install(package, apply=True, restore_saved=True, store=store).ok
    previous = contents(store.installed)
    old = store.load_registry()

    def unreachable(_tool_id):
        raise installer.InstallError(installer.STAGE_REACH, "試験用の確認失敗")

    monkeypatch.setattr(installer, "_stage_reachable", unreachable)
    result = installer.install(package, apply=True, update=True, new_version="1.0.1", store=store)
    assert not result.ok
    assert store.load_registry() == old
    assert contents(store.installed) == previous


def test_saved_original_changed_after_confirmation_is_refused(tmp_path, store, deploy_stub):
    package = saved_tool(tmp_path, store, deploy_stub)
    plan = selection.inspect_package(package, store)
    store.source_path("duty_summary", "1.0.0").write_bytes(b"changed")
    with pytest.raises(installer.InstallError, match="保存原本が変わり"):
        selection.apply_selection(plan, "saved", store, version="1.0.0")
    assert store.load_registry()["tools"] == {}


def test_saved_choice_does_not_use_different_incoming_code(tmp_path, store, deploy_stub):
    saved_tool(tmp_path, store, deploy_stub)
    previous = contents(store.installed)
    changed = build_localtool(tmp_path, name="other.zip", meta=tool_json(summary="今回の変更"))
    plan = selection.inspect_package(changed, store)
    assert selection.apply_selection(plan, "saved", store, version="1.0.0")
    assert contents(store.installed) == previous


def test_inspection_failure_is_readable_without_traceback(tmp_path, store, capsys):
    assert gui.inspect_selection(tmp_path / "missing.zip", store) is False
    output = capsys.readouterr().out
    assert "Traceback" not in output


def test_already_newer_zip_can_keep_its_version(tmp_path, store, deploy_stub):
    saved_tool(tmp_path, store, deploy_stub)
    newer = build_localtool(tmp_path, name="newer.zip", meta=tool_json(version="2.0.0"))
    plan = selection.inspect_package(newer, store)
    assert plan.suggested_version == "2.0.0"
    assert selection.apply_selection(plan, "new", store, version="2.0.0")
    assert store.load_registry()["tools"]["duty_summary"]["active_version"] == "2.0.0"


def test_tests_dir_is_resolved_before_passing_to_isolation(tmp_path, monkeypatch):
    from types import SimpleNamespace

    package = tmp_path / "package"
    package.mkdir()
    seen = {}

    def run(*args, **kwargs):
        seen.update(kwargs)
        return SimpleNamespace(ok=True, result=SimpleNamespace(status="ok"))

    monkeypatch.setattr(installer, "_run_stage_tool", run)
    installer._stage_tests(package / ".." / "package", {}, tmp_path / "work")
    assert seen["config"]["tests_dir"] == str((package / "tests").resolve())
