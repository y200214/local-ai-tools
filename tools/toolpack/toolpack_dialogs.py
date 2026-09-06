"""管理画面の版選択・保存一覧。操作の実行は管理コアへ返す。"""

from __future__ import annotations


def choose_version(master, *, title, prompt, versions, selected="", accept="この版へ戻す"):
    import tkinter as tk
    from tkinter import ttk, messagebox

    choices = tuple(dict.fromkeys(versions))
    if not choices:
        messagebox.showinfo(title, "選択できる保存済みの版がありません。", parent=master)
        return None
    dialog = tk.Toplevel(master)
    dialog.title(title)
    dialog.transient(master)
    dialog.resizable(False, False)
    body = ttk.Frame(dialog, padding=18)
    body.pack(fill="both", expand=True)
    ttk.Label(body, text=prompt, wraplength=520).pack(anchor="w")
    ttk.Label(body, text="版を選んでください").pack(anchor="w", pady=(14, 4))
    chosen = tk.StringVar(value=selected if selected in choices else choices[0])
    combo = ttk.Combobox(body, textvariable=chosen, values=choices, state="readonly", width=28)
    combo.pack(fill="x", pady=(0, 12))
    result = None

    def finish():
        nonlocal result
        if chosen.get() in choices:
            result = chosen.get()
            dialog.destroy()

    bar = ttk.Frame(body)
    bar.pack(fill="x")
    ttk.Button(bar, text=accept, command=finish).pack(side="left")
    ttk.Button(bar, text="キャンセル", command=dialog.destroy).pack(side="right")
    dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
    dialog.bind("<Escape>", lambda _event: dialog.destroy())
    combo.focus_set()
    dialog.grab_set()
    master.wait_window(dialog)
    return result


def choose_saved_library(master, library):
    """初期チェックはゼロ。選択行は再登録、チェック行は完全削除の対象。"""
    import tkinter as tk
    from tkinter import ttk, messagebox

    dialog = tk.Toplevel(master)
    dialog.title("保存済みのツール（未登録）")
    dialog.transient(master)
    dialog.geometry("880x460")
    dialog.minsize(700, 360)
    body = ttk.Frame(dialog, padding=12)
    body.pack(fill="both", expand=True)
    ttk.Label(body, text="登録を外した後もPCに残っているツールです。登録中・無効化中のツールは含みません。\n"
              "再登録：行を選択して版を選びます。完全削除：消すツールにチェックを付けます。",
              wraplength=830).pack(anchor="w", pady=(0, 10))
    frame = ttk.Frame(body)
    frame.pack(fill="both", expand=True)
    tree = ttk.Treeview(frame, columns=("name", "id", "versions"), show="tree headings",
                        selectmode="browse")
    tree.heading("#0", text="削除")
    tree.column("#0", width=48, minwidth=48, stretch=False, anchor="center")
    for key, label, width in (("name", "ツール", 230), ("id", "ID", 210), ("versions", "保存済みの版", 245)):
        tree.heading(key, text=label)
        tree.column(key, width=width, minwidth=100)
    scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scroll.set)
    scroll.pack(side="right", fill="y")
    tree.pack(side="left", fill="both", expand=True)
    items = {item.tool_id: item for item in library.tools}
    checked = set()
    for item in library.tools:
        tree.insert("", "end", iid=item.tool_id, text="☐",
                    values=(item.display_name, item.tool_id, "、".join(item.versions) or "版を確認できません"))
    status = ttk.Label(body)
    status.pack(anchor="w", pady=8)
    if library.problems:
        ttk.Label(body, text="\n".join(library.problems), wraplength=830).pack(anchor="w")
    result = None
    bar = ttk.Frame(body)
    bar.pack(fill="x", pady=(4, 0))

    def update():
        current = tree.selection()
        can_restore = bool(current and items[current[0]].restorable_versions)
        restore.configure(state="normal" if can_restore else "disabled")
        purge.configure(state="normal" if checked else "disabled")
        text = f"保存ツール {len(items)} 件 / 削除チェック {len(checked)} 件"
        if not items:
            text += "（未登録の保存ツールはありません）"
        elif current and not can_restore:
            text += "（選択したツールには再登録用の保存原本がありません）"
        status.configure(text=text)

    def toggle(item_id):
        if item_id not in items:
            return
        if item_id in checked:
            checked.remove(item_id)
        else:
            checked.add(item_id)
        tree.item(item_id, text="☑" if item_id in checked else "☐")
        tree.selection_set(item_id)
        tree.focus(item_id)
        update()

    def click(event):
        if tree.identify_column(event.x) == "#0" and tree.identify_region(event.x, event.y) in ("tree", "cell"):
            toggle(tree.identify_row(event.y))
            return "break"

    def space(_event):
        current = tree.selection()
        if current:
            toggle(current[0])
        return "break"

    def clear_checks():
        for item_id in checked:
            tree.item(item_id, text="☐")
        checked.clear()
        update()

    def finish(action, selected, version=""):
        nonlocal result
        result = (action, selected, version)
        dialog.destroy()

    def reregister():
        current = tree.selection()
        if not current:
            return
        item = items[current[0]]
        version = choose_version(
            dialog, title="保存済みのツールを再登録", versions=item.restorable_versions,
            prompt=f"{item.display_name} ({item.tool_id})\n保存原本から再検査し、未承認として登録します。",
            accept="この版を再登録する",
        )
        if version:
            finish("restore", item, version)
        elif dialog.winfo_exists():
            dialog.grab_set()

    def delete_checked():
        selected = tuple(item for item in library.tools if item.tool_id in checked)
        if not selected:
            return
        details = "\n".join(f"・{item.display_name} ({item.tool_id}) / {'、'.join(item.versions) or '全保存ファイル'}"
                            for item in selected)
        if messagebox.askyesno(
            "保存ファイルの完全削除を確認",
            f"次の {len(selected)} ツールの保存済みの全ての版を完全削除します。\n\n{details}\n\n"
            "保存原本ZIP・処理コード・生成Pipeを削除します。この操作は元に戻せません。\n"
            "再登録するには、USB側の元ZIPか外部バックアップが必要になります。\n"
            "業務の入力・出力ファイル、USB側の原本は削除しません。\n\n完全削除しますか？",
            parent=dialog, default="no", icon="warning",
        ):
            finish("purge", selected)

    restore = ttk.Button(bar, text="選んだツールを再登録...", command=reregister, state="disabled")
    restore.pack(side="left")
    purge = ttk.Button(bar, text="チェックしたツールを完全削除...", command=delete_checked, state="disabled")
    purge.pack(side="left", padx=8)
    ttk.Button(bar, text="チェックを外す", command=clear_checks).pack(side="left")
    ttk.Button(bar, text="閉じる", command=dialog.destroy).pack(side="right")
    tree.bind("<Button-1>", click)
    tree.bind("<space>", space)
    tree.bind("<<TreeviewSelect>>", lambda _event: update())
    dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
    dialog.bind("<Escape>", lambda _event: dialog.destroy())
    update()
    dialog.grab_set()
    master.wait_window(dialog)
    return result
