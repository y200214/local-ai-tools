from repo_paths import ROOT as PROJECT_ROOT, TOOLS as TOOLS_ROOT
from pathlib import Path


ROOT = PROJECT_ROOT


def test_excel_upload_guard_only_targets_excel_uploads() -> None:
    source = (ROOT / "webui_tour/assets/open_webui_excel_upload_guard.js").read_text(encoding="utf-8")
    assert r"\.(?:xlsx|xlsm)$" in source
    assert 'url.searchParams.set("process", "false")' in source
    assert "/api\\/v1\\/files" in source
    assert "pdf" not in source.lower()


def test_webui_tweaks_installs_guard_idempotently() -> None:
    source = (ROOT / "scripts/legacy/Apply-WebUiTweaks.ps1").read_text(encoding="utf-8")
    assert "open_webui_excel_upload_guard.js" in source
    assert "excel-upload-guard.js" in source
    assert "removeOldGuard" in source
