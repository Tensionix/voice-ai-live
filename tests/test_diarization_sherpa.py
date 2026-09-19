"""Speaker separation without a HuggingFace key (sherpa-onnx).

sherpa_onnx itself is faked. The tests pin the product rule: this engine runs
only with a speaker count from the user (no automatic mode, no thresholds),
and the registry prefers pyannote Community-1 when that stack is installed."""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace

import pytest

from system_core.core.models import Segment
from system_core.core.paths import get_project_paths
from system_core.providers import diarization_sherpa as ds
from system_core.providers import registry
from system_core.providers.base import DiarizationUnavailable
from system_core.providers.diarization_sherpa import SherpaDiarizationProvider


def _segments():
    return [
        Segment(index=0, start=0.0, end=10.0, text="first"),
        Segment(index=1, start=10.0, end=20.0, text="second"),
    ]


def _local_settings(**diarization):
    return {
        "compute_mode": "vulkan",
        "vulkan": {"engine": "gigaam"},
        "diarization": {"enabled": True, **diarization},
    }


class _FakeSherpa(types.ModuleType):
    def __init__(self):
        super().__init__("sherpa_onnx")
        self.clustering = None

        def passthrough(**kwargs):
            return SimpleNamespace(**kwargs)

        self.OfflineSpeakerSegmentationPyannoteModelConfig = passthrough
        self.OfflineSpeakerSegmentationModelConfig = passthrough
        self.SpeakerEmbeddingExtractorConfig = passthrough

        def clustering(**kwargs):
            self.clustering = kwargs
            return SimpleNamespace(**kwargs)

        self.FastClusteringConfig = clustering

        def config(**kwargs):
            return SimpleNamespace(validate=lambda: True, **kwargs)

        self.OfflineSpeakerDiarizationConfig = config

        turns = [
            SimpleNamespace(start=9.0, end=20.0, speaker=1),
            SimpleNamespace(start=0.0, end=9.0, speaker=0),
        ]

        class Engine:
            sample_rate = 16000

            def __init__(self, _config):
                pass

            def process(self, _samples):
                return SimpleNamespace(sort_by_start_time=lambda: sorted(turns, key=lambda t: t.start))

        self.OfflineSpeakerDiarization = Engine


@pytest.fixture
def fake_sherpa(monkeypatch):
    module = _FakeSherpa()
    monkeypatch.setitem(sys.modules, "sherpa_onnx", module)
    monkeypatch.setattr(ds, "sherpa_diarization_ready", lambda _paths: True)
    monkeypatch.setattr(ds, "_read_wav_mono", lambda _path: ([0.0] * 16000, 16000))
    return module


def test_runs_with_a_given_speaker_count_and_no_threshold(tmp_path, fake_sherpa):
    paths = get_project_paths(tmp_path)
    result = SherpaDiarizationProvider(paths, speakers=2).diarize(tmp_path / "audio.wav", _segments())
    assert [s.speaker for s in result] == ["Speaker 00", "Speaker 01"]
    assert fake_sherpa.clustering == {"num_clusters": 2}  # a count, never a threshold


@pytest.mark.parametrize("speakers", [0, 1, 21])
def test_refuses_to_guess_the_number_of_speakers(tmp_path, fake_sherpa, speakers):
    paths = get_project_paths(tmp_path)
    with pytest.raises(DiarizationUnavailable) as err:
        SherpaDiarizationProvider(paths, speakers=speakers).diarize(tmp_path / "audio.wav", _segments())
    assert "number of speakers" in str(err.value)


def test_missing_install_is_explained(tmp_path):
    paths = get_project_paths(tmp_path)
    with pytest.raises(DiarizationUnavailable) as err:
        SherpaDiarizationProvider(paths, speakers=3).diarize(tmp_path / "audio.wav", _segments())
    assert "Maintenance" in str(err.value)


def test_ready_needs_package_and_both_models(tmp_path, monkeypatch):
    paths = get_project_paths(tmp_path)
    monkeypatch.setattr(ds.importlib.util, "find_spec", lambda name: object())
    assert not ds.sherpa_diarization_ready(paths)
    root = ds.sherpa_model_dir(paths)
    root.mkdir(parents=True)
    (root / ds.SEGMENTATION_FILE).write_bytes(b"x")
    assert not ds.sherpa_diarization_ready(paths)
    (root / ds.EMBEDDING_FILE).write_bytes(b"x")
    assert ds.sherpa_diarization_ready(paths)


def test_registry_uses_sherpa_for_local_modes_and_passes_the_count(tmp_path):
    paths = get_project_paths(tmp_path)
    provider = registry.get_diarization_provider(paths, _local_settings(speakers=4))
    assert provider is not None and provider.name == "sherpa"
    assert provider.speakers == 4


def test_registry_skips_api_mode_and_disabled_separation(tmp_path):
    paths = get_project_paths(tmp_path)
    assert registry.get_diarization_provider(paths, {"compute_mode": "api", "diarization": {"enabled": True}}) is None
    assert registry.get_diarization_provider(paths, {"compute_mode": "vulkan", "diarization": {"enabled": False}}) is None


def test_registry_prefers_community_1_when_installed(tmp_path, monkeypatch):
    pyannote = pytest.importorskip("system_core.providers.diarization_pyannote")
    if not hasattr(pyannote, "pyannote_ready"):
        pytest.skip("Community-1 provider ships with Studio only")
    paths = get_project_paths(tmp_path)
    monkeypatch.setattr(pyannote, "pyannote_ready", lambda _paths: True)
    provider = registry.get_diarization_provider(paths, _local_settings(speakers=3))
    assert provider.name == "pyannote" and provider.speakers == 3
    # An explicit engine choice wins over what is installed.
    provider = registry.get_diarization_provider(paths, _local_settings(engine="sherpa", speakers=3))
    assert provider.name == "sherpa"
