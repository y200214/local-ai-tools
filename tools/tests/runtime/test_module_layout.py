"""Layout guarantees: one implementation, stable CLI, unchanged isolation boundary."""

import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

from repo_paths import ROOT, TOOLS


# 整理前から存在した入口を固定する。入口を削除したら検知でき、
# 新設した内部部品にまで不要な互換入口を要求しない。
MODULES = {
    **dict.fromkeys((
        "toolpack_backup", "toolpack_child", "toolpack_ci", "toolpack_contract",
        "toolpack_gui", "toolpack_install", "toolpack_manage", "toolpack_name_guard",
        "toolpack_pack", "toolpack_pipe_template", "toolpack_pipegen", "toolpack_runner",
        "toolpack_state", "toolpack_store", "toolpack_test_entry", "toolpack_textio",
        "toolpack_verify", "toolpack_winjob", "toolpack_winsec",
    ), "toolpack"),
    **dict.fromkeys((
        "check_sheet_presence", "excel_comment_build", "excel_comment_context",
        "excel_comment_report", "excel_reader", "office_excel", "office_ppt",
        "office_template", "office_word",
    ), "office"),
}


@pytest.mark.parametrize("name,domain", sorted(MODULES.items()))
def test_旧importと本体は同じモジュール(name, domain):
    legacy = importlib.import_module(name)
    actual = importlib.import_module(f"{domain}.{name}")
    assert legacy is actual
    assert Path(actual.__file__).parent == TOOLS / domain
    entry = (TOOLS / f"{name}.py").read_text(encoding="utf-8")
    assert len(entry.splitlines()) <= 8  # no business logic in compatibility entries


@pytest.mark.parametrize("name", [
    "toolpack_pack", "toolpack_verify", "toolpack_runner", "toolpack_install",
    "toolpack_manage", "toolpack_backup", "office_excel", "excel_reader",
])
def test_従来のCLIは別ディレクトリからも起動できる(name, tmp_path):
    result = subprocess.run(
        [sys.executable, str(TOOLS / f"{name}.py"), "--help"],
        cwd=tmp_path, capture_output=True, timeout=30,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    assert result.stdout


def test_隔離用のコピー元は互換入口ではなく本体():
    from toolpack import toolpack_runner as runner, toolpack_install as installer
    from toolpack import toolpack_pipegen as pipegen

    for path in (runner.CHILD_SCRIPT, runner.TEXTIO_MODULE, installer.TEST_ENTRY, pipegen.TEMPLATE_PATH):
        assert path.parent == TOOLS / "toolpack"
        assert "from _compat import" not in path.read_text(encoding="utf-8")


def test_旧入口経由でもリポジトリは読取許可に含めない(monkeypatch):
    from toolpack import toolpack_child as child

    monkeypatch.setattr(sys, "path", [str(ROOT), str(TOOLS), str(TOOLS / "toolpack"), sys.base_prefix])
    allowed = child._env_python_roots()
    for path in (ROOT, TOOLS, TOOLS / "toolpack"):
        assert os.path.normcase(str(path)) not in allowed
    assert os.path.normcase(sys.base_prefix) in allowed
