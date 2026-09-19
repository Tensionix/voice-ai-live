"""Optional HuggingFace key: credentials, maintenance row, installer environment."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from system_core.core.credentials import read_api_key, write_api_key
from system_core.core.paths import get_project_paths


def test_key_file_round_trip_and_env_fallback(tmp_path, monkeypatch):
    paths = get_project_paths(tmp_path)
    monkeypatch.delenv("HF_TOKEN", raising=False)
    assert read_api_key(paths, "huggingface") is None
    monkeypatch.setenv("HF_TOKEN", "hf_from_env")
    assert read_api_key(paths, "huggingface") == "hf_from_env"
    write_api_key(paths, "huggingface", "  hf_from_file  ")
    assert (paths.config / "api_key_huggingface.txt").read_text(encoding="utf-8").strip() == "hf_from_file"
    assert read_api_key(paths, "huggingface") == "hf_from_file"


_DEVLIBS = Path(__file__).resolve().parents[1] / ".devlibs"
if _DEVLIBS.exists():
    import sys

    sys.path.insert(0, str(_DEVLIBS))

if pytest.importorskip("PySide6", reason="GUI deps not installed"):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtWidgets import QApplication  # noqa: E402

    from system_core.core.modules import list_modules  # noqa: E402
    from system_core.ui import workers  # noqa: E402
    from system_core.ui.i18n import Translator  # noqa: E402
    from system_core.ui.modules_dialog import ModulesPanel  # noqa: E402

    @pytest.fixture(scope="module")
    def app():
        instance = QApplication.instance() or QApplication([])
        yield instance

    def _dispose(panel) -> None:
        """Stop the hardware-probe thread before the panel goes away; a QThread
        destroyed while running crashes a later test."""
        worker = panel._profile_worker
        if worker is not None:
            worker.cancel()
            worker.wait(10000)
        panel.deleteLater()

    def test_anonymous_download_warning_is_removed_from_the_log():
        line = (
            "Fetching 3 files:   0%|          | 0/3 [00:00<?, ?it/s]Warning: You are sending "
            "unauthenticated requests to the HF Hub. Please set a HF_TOKEN to enable higher rate "
            "limits and faster downloads."
        )
        cleaned = workers._HF_ANON_WARNING.sub("", line).rstrip()
        assert "HF_TOKEN" not in cleaned
        assert cleaned.startswith("Fetching 3 files")
        assert workers._HF_ANON_WARNING.sub("", "GigaAM payloads OK") == "GigaAM payloads OK"

    @pytest.mark.parametrize("language", ["ru", "en"])
    def test_maintenance_page_has_an_optional_key_row_with_howto(app, language):
        paths = get_project_paths()
        tr = Translator.load(paths, language)
        panel = ModulesPanel(paths, tr)
        assert panel._huggingface_key_name.text() == tr.tr("hf_key_name")
        assert panel._huggingface_key_btn.text() == tr.tr("api_key_enter")
        tip = panel._huggingface_key_btn.toolTip()
        assert "Access Tokens" in tip and "huggingface.co" in tip
        assert panel._huggingface_key_status.text()
        _dispose(panel)

    def test_gpu_diarization_is_not_downloaded_without_a_key(app, tmp_path, monkeypatch):
        paths = get_project_paths()
        gpu = next((m for m in list_modules(paths) if m.key == "gpu"), None)
        if gpu is None:
            pytest.skip("GPU diarization module exists only in Studio")
        from system_core.ui import modules_dialog

        monkeypatch.setattr(modules_dialog, "read_api_key", lambda _paths, provider: None)
        tr = Translator.load(paths, "en")
        panel = ModulesPanel(paths, tr)
        lines: list[str] = []
        panel.log_line.connect(lines.append)
        panel._install(gpu)
        assert not panel.is_busy()
        assert tr.tr("hf_key_required_for_gpu") in lines
        _dispose(panel)
