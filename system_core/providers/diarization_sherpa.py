"""Speaker separation without a HuggingFace key: sherpa-onnx, CPU, ~65 MB.

The pipeline is the stock sherpa-onnx offline diarization (pyannote
segmentation 3.0 + a speaker-embedding model, both ONNX). It is used ONLY with
a speaker count given by the user.

Why no automatic count: sherpa-onnx has no calibrated clustering threshold. On
the authors' own four-speaker sample the default threshold finds 7 speakers,
0.8 finds 5, 0.9 finds 4, and another embedding model finds 1-2. Picking a
threshold would tune the app to one recording and break the next. With a known
count the clustering needs no threshold and the result is stable.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from ..core.models import Segment
from ..core.paths import ProjectPaths
from .base import DiarizationProvider, DiarizationUnavailable

MODEL_DIR_NAME = "sherpa-diarization"
SEGMENTATION_FILE = "segmentation.onnx"
EMBEDDING_FILE = "embedding.onnx"
MIN_SPEAKERS = 2
MAX_SPEAKERS = 20


def sherpa_model_dir(paths: ProjectPaths) -> Path:
    return paths.models / MODEL_DIR_NAME


def sherpa_diarization_ready(paths: ProjectPaths) -> bool:
    """Package importable and both model files in place."""
    try:
        if importlib.util.find_spec("sherpa_onnx") is None:
            return False
    except (ImportError, ValueError):
        return False
    root = sherpa_model_dir(paths)
    return (root / SEGMENTATION_FILE).is_file() and (root / EMBEDDING_FILE).is_file()


def _read_wav_mono(path: Path):
    import wave

    import numpy as np

    with wave.open(str(path), "rb") as handle:
        if handle.getsampwidth() != 2:
            raise ValueError(f"unsupported WAV sample width: {handle.getsampwidth()}")
        rate = handle.getframerate()
        channels = handle.getnchannels()
        data = np.frombuffer(handle.readframes(handle.getnframes()), dtype=np.int16)
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    return data.astype(np.float32) / 32768.0, rate


class SherpaDiarizationProvider(DiarizationProvider):
    name = "sherpa"

    def __init__(self, paths: ProjectPaths, *, speakers: int = 0) -> None:
        self.paths = paths
        self.speakers = int(speakers or 0)

    def _build(self):
        if not sherpa_diarization_ready(self.paths):
            raise DiarizationUnavailable(
                "Speaker separation is not installed. Install 'Speaker separation (no key)' "
                "on the Maintenance page."
            )
        if not MIN_SPEAKERS <= self.speakers <= MAX_SPEAKERS:
            raise DiarizationUnavailable(
                "Speaker separation without a HuggingFace key needs the number of speakers: "
                f"set 'Speakers' to {MIN_SPEAKERS}-{MAX_SPEAKERS} in the file settings."
            )
        import sherpa_onnx  # type: ignore

        root = sherpa_model_dir(self.paths)
        config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
            segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
                pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                    model=str(root / SEGMENTATION_FILE)
                ),
            ),
            embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(root / EMBEDDING_FILE)),
            # A fixed count: no threshold is involved, by design (see module docstring).
            clustering=sherpa_onnx.FastClusteringConfig(num_clusters=self.speakers),
            min_duration_on=0.3,
            min_duration_off=0.5,
        )
        if not config.validate():
            raise DiarizationUnavailable("sherpa-onnx rejected the speaker separation models.")
        return sherpa_onnx.OfflineSpeakerDiarization(config)

    def diarize(self, audio_path: Path, segments: list[Segment]) -> list[Segment]:
        engine = self._build()
        samples, rate = _read_wav_mono(audio_path)
        if rate != engine.sample_rate:
            raise DiarizationUnavailable(
                f"Speaker separation expects {engine.sample_rate} Hz audio, got {rate} Hz."
            )
        turns = [
            (turn.start, turn.end, f"Speaker {turn.speaker:02d}")
            for turn in engine.process(samples).sort_by_start_time()
        ]
        for seg in segments:
            seg.speaker = _best_speaker(seg, turns) or seg.speaker
        return segments


def _best_speaker(seg: Segment, turns: list[tuple[float, float, str]]) -> str | None:
    best_label: str | None = None
    best_overlap = 0.0
    for start, end, label in turns:
        overlap = max(0.0, min(seg.end, end) - max(seg.start, start))
        if overlap > best_overlap:
            best_overlap = overlap
            best_label = label
    return best_label
