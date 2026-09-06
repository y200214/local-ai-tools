"""保存一覧・再登録・明示削除。実データ・実登録は一切変更しない。"""

import json
import os
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

import toolpack_gui as gui
import toolpack_manage as manage
import toolpack_store as storage
from toolpack import toolpack_dialogs as dialogs, toolpack_saved as saved
from test_toolpack_install import store, deploy_stub
from test_toolpack_reinstall import saved_tool, contents


def make_saved(store, tool_id="saved_trial", versions=("1.0.0",)):
    for version in versions:
        package = store.package_dir(tool_id, version)
        package.mkdir(parents=True)
        (package / "tool.json").write_text(json.dumps({"display_name": "保存試験ツール"}), encoding="utf-8")
        (package / "main.py").write_text("raise RuntimeError('一覧では実行しない')\n", encoding="utf-8")
        source = store.source_path(tool_id, version)
        source.parent.mkdir()
        source.write_bytes(b"test-only-zip-placeholder")
    return saved.saved_tool(store, tool_id)


def test_inventory_is_read_only_and_excludes_registered_even_disabled(store):
    make_saved(store, versions=("1.2.0", "1.10.0"))
    make_saved(store, "registered_trial")
    store.register("registered_trial", "1.0.0", package_hash="hash")
    store.set_enabled("registered_trial", False)
    before = contents(store.root)
    library = saved.collect_saved(store)
    assert [item.tool_id for item in library.tools] == ["saved_trial"]
    assert library.tools[0].versions == ("1.10.0", "1.2.0")
    assert library.tools[0].display_name == "保存試験ツール"
    assert contents(store.root) == before


def test_missing_source_can_be_deleted_but_not_restored(store):
    item = make_saved(store)
    store.source_path(item.tool_id, "1.0.0").unlink()
    item = saved.collect_saved(store).tools[0]
    assert item.restorable_versions == ()
    with pytest.raises(storage.StoreError, match="保存原本"):
        saved.restore_saved(store, item, "1.0.0")


def test_empty_inventory_does_not_create_files(tmp_path):
    root = tmp_path / "not-created"
    assert saved.collect_saved(storage.ToolpackStore(root)).tools == ()
    assert not root.exists()


def test_restore_from_library_rechecks_and_starts_unapproved(tmp_path, store, deploy_stub):
    saved_tool(tmp_path, store, deploy_stub)
    before = contents(store.installed)
    item = saved.collect_saved(store).tools[0]
    assert gui.action_saved("restore", store, item, "1.0.0") is True
    entry = store.load_registry()["tools"][item.tool_id]
    assert entry["active_version"] == "1.0.0" and not storage.is_approved(entry)
    assert contents(store.installed) == before
    assert saved.collect_saved(store).tools == ()


def test_restore_failure_keeps_saved_files(tmp_path, store, deploy_stub):
    saved_tool(tmp_path, store, deploy_stub)
    item = saved.collect_saved(store).tools[0]
    before = contents(store.installed)
    deploy_stub.should_fail = True
    assert gui.action_saved("restore", store, item, "1.0.0") is False
    assert contents(store.installed) == before
    assert store.load_registry()["tools"] == {}


@pytest.mark.parametrize("operation", ["restore", "purge"])
def test_reregistered_after_display_is_protected(store, deploy_stub, operation):
    item = make_saved(store)
    store.register(item.tool_id, "1.0.0", package_hash="hash")
    before = contents(store.root)
    assert gui.action_saved(operation, store, item if operation == "restore" else (item,), "1.0.0") is False
    assert contents(store.root) == before


@pytest.mark.parametrize("operation", ["restore", "purge"])
def test_changed_files_after_display_require_reselection(store, deploy_stub, operation):
    item = make_saved(store)
    (store.package_dir(item.tool_id, "1.0.0") / "extra.txt").write_text("new", encoding="utf-8")
    before = contents(store.root)
    assert gui.action_saved(operation, store, item if operation == "restore" else (item,), "1.0.0") is False
    assert contents(store.root) == before


def test_only_checked_tools_are_purged_and_usb_and_outputs_remain(store, deploy_stub, tmp_path):
    item = make_saved(store, "delete_trial", ("1.0.0", "1.1.0"))
    keep = make_saved(store, "keep_trial")
    usb = tmp_path / "usb-original.zip"
    usb.write_bytes(b"original")
    (store.root / "output.txt").write_text("result", encoding="utf-8")
    assert manage.command_purge_saved(store, (item,), yes=True) == 0
    assert not (store.installed / item.tool_id).exists()
    assert (store.installed / keep.tool_id).is_dir()
    assert usb.read_bytes() == b"original"
    assert (store.root / "output.txt").read_text() == "result"


def test_all_checked_items_are_preflighted_before_any_deletion(store, deploy_stub):
    one = make_saved(store, "aaa_trial")
    two = make_saved(store, "bbb_trial")
    store.register(two.tool_id, "1.0.0", package_hash="hash")
    before = contents(store.root)
    assert gui.action_saved("purge", store, (one, two)) is False
    assert contents(store.root) == before


@pytest.mark.parametrize("state", ["openwebui", "hub", "unknown_openwebui", "unknown_hub"])
def test_external_presence_or_unknown_blocks_deletion(store, deploy_stub, state):
    item = make_saved(store)
    if state == "openwebui":
        deploy_stub.present.add(item.tool_id)
    elif state == "hub":
        deploy_stub.hub_ids.add(item.tool_id)
    elif state == "unknown_openwebui":
        deploy_stub.openwebui_unreachable = True
    else:
        deploy_stub.hub_unreachable = True
    assert gui.action_saved("purge", store, (item,)) is False
    assert (store.installed / item.tool_id).is_dir()


def test_no_selection_or_confirmation_does_nothing(store, deploy_stub):
    item = make_saved(store)
    assert manage.command_purge_saved(store, (item,)) == 1
    assert manage.command_purge_saved(store, (), yes=True) == 1
    assert (store.installed / item.tool_id).is_dir()


@pytest.mark.parametrize("tool_id, version", [("..", None), ("saved_trial\n", None),
                                              ("saved_trial", "../1.0.0"), ("C:\\", None)])
def test_unsafe_targets_are_rejected(store, tool_id, version):
    with pytest.raises(storage.StoreError):
        store.purge_files(tool_id, version)


def test_hardlink_in_saved_tree_is_not_followed_or_deleted(store, tmp_path):
    item = make_saved(store)
    external = tmp_path / "fake-secret.txt"
    external.write_text("FAKE SECRET", encoding="utf-8")
    os.link(external, store.package_dir(item.tool_id, "1.0.0") / "linked.txt")
    library = saved.collect_saved(store)
    assert library.tools == () and library.problems
    with pytest.raises(storage.StoreError, match="リンク"):
        store.purge_files(item.tool_id)
    assert external.read_text() == "FAKE SECRET"


@pytest.mark.skipif(os.name != "nt", reason="Windows junction")
@pytest.mark.parametrize("level", ["installed", "tool", "inside"])
def test_junction_at_any_level_is_not_followed(store, tmp_path, level):
    import _winapi

    external = tmp_path / "outside"
    external.mkdir()
    marker = external / "fake-secret.txt"
    marker.write_text("FAKE", encoding="utf-8")
    if level == "installed":
        store.installed.rmdir()  # テスト専用の空フォルダのみ
        link = store.installed
    elif level == "tool":
        link = store.installed / "saved_trial"
    else:
        make_saved(store)
        link = store.package_dir("saved_trial", "1.0.0") / "external"
    _winapi.CreateJunction(str(external), str(link))
    try:
        with pytest.raises(storage.StoreError):
            store.purge_files("saved_trial")
        assert marker.read_text() == "FAKE"
    finally:
        link.rmdir()  # ジャンクション自体のみ。リンク先は消さない。


def test_running_job_blocks_purge_without_interrupting_it(store, deploy_stub, monkeypatch):
    from local_tool_bridge import job_lock

    item = make_saved(store)
    real = job_lock.JobLock

    def new_lock(name=job_lock.MUTEX_NAME):
        if name != job_lock.MUTEX_NAME:
            return real(name)
        return SimpleNamespace(cross_process=True, acquire=lambda **kwargs: False,
                               close=lambda: None, release=lambda: pytest.fail("未取得を解放しない"))

    monkeypatch.setattr(job_lock, "JobLock", new_lock)
    assert gui.action_saved("purge", store, (item,)) is False
    assert (store.installed / item.tool_id).is_dir()


def test_partial_delete_failure_is_reported_without_false_rollback(store, deploy_stub, monkeypatch, capsys):
    import shutil

    one = make_saved(store, "aaa_trial")
    two = make_saved(store, "bbb_trial")
    three = make_saved(store, "ccc_trial")
    original = shutil.rmtree

    def fail(path, *args, **kwargs):
        if Path(path).name == two.tool_id:
            raise PermissionError("simulated")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(shutil, "rmtree", fail)
    assert gui.action_saved("purge", store, (one, two, three)) is False
    output = capsys.readouterr().out
    assert "aaa_trial" in output and "以降の削除は中止" in output and "戻せません" in output
    assert not (store.installed / one.tool_id).exists()
    assert (store.installed / two.tool_id).exists() and (store.installed / three.tool_id).exists()


def test_rollback_dropdown_receives_versions_and_preselected_row(monkeypatch):
    row = gui.ModelRow("trial_tool", "試験モデル", gui.KIND_ADDED,
                       version="1.2.0", versions=["1.0.0", "1.2.0", "1.1.0"])
    calls = []

    def choose(master, **kwargs):
        assert kwargs["versions"] == ["1.1.0", "1.0.0"]
        assert kwargs["selected"] == "1.0.0"
        return "1.0.0"

    monkeypatch.setattr(dialogs, "choose_version", choose)
    monkeypatch.setattr(gui, "action_manage", lambda *args: calls.append(args))
    app = SimpleNamespace(master=None, store=None, selection=lambda: (row, "1.0.0", "version"),
                          start=lambda _label, action: action())
    gui.App.on_rollback(app)
    assert calls == [("rollback", None, "trial_tool", "1.0.0")]


def test_rollback_cancel_does_not_execute(monkeypatch):
    row = gui.ModelRow("trial_tool", "試験モデル", gui.KIND_ADDED,
                       version="1.1.0", versions=["1.0.0", "1.1.0"])
    monkeypatch.setattr(dialogs, "choose_version", lambda *args, **kwargs: None)
    app = SimpleNamespace(master=None, selection=lambda: (row, "", "model"),
                          start=lambda *args: pytest.fail("キャンセルでは実行しない"))
    gui.App.on_rollback(app)


@pytest.fixture(scope="module")
def hidden_root():
    import tkinter as tk

    try:
        root = tk.Tk()
    except tk.TclError as error:
        if os.name == "nt":
            raise
        pytest.skip(f"Tk環境なし: {error}")
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def hidden_dialog(monkeypatch, hidden_root):
    import tkinter as tk

    root = hidden_root
    top = tk.Toplevel
    state = SimpleNamespace(root=root, callback=None, errors=[])

    def visit(widget):
        for child in widget.winfo_children():
            yield child
            yield from visit(child)

    class Hidden(top):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.withdraw()
            self.after(0, self.check)

        def grab_set(self):
            pass  # 利用者の入力を奪わない

        def check(self):
            try:
                state.callback(self, list(visit(self)))
            except BaseException as error:
                state.errors.append(error)
                self.destroy()

    monkeypatch.setattr(tk, "Toplevel", Hidden)
    yield state
    assert not state.errors, state.errors


@pytest.mark.parametrize("cancel", [False, True])
def test_actual_readonly_version_dropdown(hidden_dialog, cancel):
    def callback(dialog, widgets):
        combo = next(w for w in widgets if w.winfo_class() == "TCombobox")
        assert str(combo.cget("state")) == "readonly"
        assert combo.get() == "1.0.0"
        combo.set("1.1.0")
        label = "キャンセル" if cancel else "この版へ戻す"
        next(w for w in widgets if w.winfo_class() == "TButton" and w.cget("text") == label).invoke()

    hidden_dialog.callback = callback
    assert dialogs.choose_version(hidden_dialog.root, title="試験", prompt="版を選択",
                                  versions=("1.1.0", "1.0.0"), selected="1.0.0") == (None if cancel else "1.1.0")


@pytest.mark.parametrize("action", ["restore", "purge", "cancel_delete", "close"])
def test_actual_saved_library_checkbox_and_actions(hidden_dialog, store, monkeypatch, action):
    from tkinter import messagebox

    item = make_saved(store)
    library = saved.collect_saved(store)
    confirmations = []

    def confirm(*args, **kwargs):
        confirmations.append((args, kwargs))
        return action != "cancel_delete"

    monkeypatch.setattr(messagebox, "askyesno", confirm)
    monkeypatch.setattr(dialogs, "choose_version", lambda *args, **kwargs: "1.0.0")

    def callback(dialog, widgets):
        tree = next(w for w in widgets if w.winfo_class() == "Treeview")
        buttons = {w.cget("text"): w for w in widgets if w.winfo_class() == "TButton"}
        assert tree.item(item.tool_id, "text") == "☐"
        assert buttons["チェックしたツールを完全削除..."].instate(["disabled"])
        tree.selection_set(item.tool_id)
        tree.event_generate("<<TreeviewSelect>>")
        if action in ("purge", "cancel_delete"):
            # TkのSpaceハンドラを呼ぶ。非表示窓へのキーボードフォーカスは不要。
            binding = re.search(r"\[([^\s]+)", tree.bind("<space>")).group(1)
            tree.tk.call(binding, *(["0"] * 19))
            assert tree.item(item.tool_id, "text") == "☑"
            buttons["チェックしたツールを完全削除..."].invoke()
            if action == "cancel_delete":
                assert dialog.winfo_exists()
                buttons["閉じる"].invoke()
        elif action == "restore":
            buttons["選んだツールを再登録..."].invoke()
        else:
            buttons["閉じる"].invoke()

    hidden_dialog.callback = callback
    result = dialogs.choose_saved_library(hidden_dialog.root, library)
    if action == "restore":
        assert result == ("restore", library.tools[0], "1.0.0")
    elif action == "purge":
        assert result == ("purge", library.tools, "")
        assert confirmations[0][1]["default"] == "no"
        assert item.tool_id in confirmations[0][0][1]
    else:
        assert result is None


@pytest.mark.parametrize("cancel", [False, True])
def test_actual_nested_restore_version_dialog(hidden_dialog, store, cancel):
    make_saved(store, versions=("1.0.0", "1.1.0"))
    library = saved.collect_saved(store)

    def callback(dialog, widgets):
        buttons = {w.cget("text"): w for w in widgets if w.winfo_class() == "TButton"}
        if dialog.title() == "保存済みのツールを再登録":
            combo = next(w for w in widgets if w.winfo_class() == "TCombobox")
            assert tuple(combo.cget("values")) == ("1.1.0", "1.0.0")
            combo.set("1.0.0")
            buttons["キャンセル" if cancel else "この版を再登録する"].invoke()
        else:
            tree = next(w for w in widgets if w.winfo_class() == "Treeview")
            tree.selection_set(library.tools[0].tool_id)
            tree.event_generate("<<TreeviewSelect>>")
            buttons["選んだツールを再登録..."].invoke()
            if cancel:
                assert dialog.winfo_exists()
                buttons["閉じる"].invoke()

    hidden_dialog.callback = callback
    result = dialogs.choose_saved_library(hidden_dialog.root, library)
    assert result == (None if cancel else ("restore", library.tools[0], "1.0.0"))


def test_main_window_has_saved_library_button(hidden_root, store, monkeypatch):
    from tkinter import font, ttk

    monkeypatch.setattr(gui.App, "reload", lambda self: None)
    app = gui.App(hidden_root, store)
    try:
        bar = hidden_root.winfo_children()[0]
        buttons = [w for w in bar.winfo_children() if w.winfo_class() == "TButton"]
        assert [w.cget("text") for w in buttons] == [
            "ツールを追加", "ツールを入れ替え", "保存済みのツール", "自己診断", "再読込",
        ]
        button_font = font.Font(root=hidden_root, font=ttk.Style(hidden_root).lookup("TButton", "font") or "TkDefaultFont")
        for button in buttons:
            assert int(button.cget("width")) == 0
            assert button.winfo_reqwidth() >= button_font.measure(button.cget("text")) + 20
        assert hidden_root.minsize()[0] >= bar.winfo_reqwidth() + 16
    finally:
        app.stop()
        for widget in hidden_root.winfo_children():
            widget.destroy()
