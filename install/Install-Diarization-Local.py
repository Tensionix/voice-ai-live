"""Install speaker separation without a HuggingFace key (sherpa-onnx, CPU, ~65 MB).

Run by Install-Diarization-Local.cmd with the portable Python. Output lines use
the formats the GUI progress parser understands:
``[audion-step] 1/4 label`` and ``Label: 12.3 MB / 37.8 MB (32.5%) @ 4.1 MB/s``.
"""

from __future__ import annotations

import hashlib
import importlib.util
import subprocess
import sys
import tarfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "models" / "sherpa-diarization"
DOWNLOAD = ROOT / "install" / "download" / "sherpa-diarization"
MARKER = ROOT / "Tools" / "diarization" / "audion-sherpa-diarization-pack.txt"
SHERPA_VERSION = "1.13.8"
RELEASES = "https://github.com/k2-fsa/sherpa-onnx/releases/download"

SEGMENTATION_ARCHIVE = (
    f"{RELEASES}/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2",
    "24615ee884c897d9d2ba09bb4d30da6bb1b15e685065962db5b02e76e4996488",
)
SEGMENTATION_MEMBER = "sherpa-onnx-pyannote-segmentation-3-0/model.onnx"
SEGMENTATION_SHA256 = "220ad67ca923bef2fa91f2390c786097bf305bceb5e261d4af67b38e938e1079"
EMBEDDING = (
    f"{RELEASES}/speaker-recongition-models/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx",
    "1a331345f04805badbb495c775a6ddffcdd1a732567d5ec8b3d5749e3c7a5e4b",
)
STEPS = 4


def step(number: int, label: str) -> None:
    print(f"[audion-step] {number}/{STEPS} {label}", flush=True)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download(url: str, dest: Path, label: str, expected: str) -> None:
    if dest.is_file() and sha256(dest) == expected:
        print(f"{label} already downloaded: {dest}", flush=True)
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "Audion-Voice-AI"})
    with urllib.request.urlopen(request, timeout=60) as response, part.open("wb") as out:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        last_done, last_tick = 0, time.monotonic()
        while True:
            block = response.read(256 * 1024)
            if not block:
                break
            out.write(block)
            done += len(block)
            now = time.monotonic()
            if now - last_tick >= 1.0 and total:
                speed = (done - last_done) / max(now - last_tick, 0.1)
                print(
                    f"{label}: {done / 2**20:.1f} MB / {total / 2**20:.1f} MB "
                    f"({done / total * 100:.1f}%) @ {speed / 2**20:.1f} MB/s",
                    flush=True,
                )
                last_done, last_tick = done, now
    actual = sha256(part)
    if actual != expected:
        part.unlink(missing_ok=True)
        raise SystemExit(f"[ERROR] {label}: checksum mismatch ({actual})")
    part.replace(dest)
    print(f"{label} download complete: {dest}", flush=True)


def pip_install(*packages: str) -> None:
    command = [
        sys.executable, "-m", "pip", "install",
        "--progress-bar", "raw", "--no-warn-script-location",
    ]
    for cache in ("diarization", "common", "directml", "cpu"):
        folder = ROOT / "wheelhouse" / cache
        if folder.is_dir():
            command += ["--find-links", str(folder)]
    result = subprocess.run(command + list(packages), check=False)
    if result.returncode != 0:
        raise SystemExit(f"[ERROR] pip install failed: {' '.join(packages)}")


def main() -> int:
    print("[Audion Voice AI] Installing speaker separation (no key)...", flush=True)
    print(f"Root: {ROOT}", flush=True)

    step(1, "Install sherpa-onnx")
    packages = [f"sherpa-onnx=={SHERPA_VERSION}"]
    if importlib.util.find_spec("numpy") is None:
        packages.append("numpy>=2.0")
    pip_install(*packages)

    step(2, "Download the segmentation model")
    archive = DOWNLOAD / "sherpa-onnx-pyannote-segmentation-3-0.tar.bz2"
    download(SEGMENTATION_ARCHIVE[0], archive, "Segmentation model", SEGMENTATION_ARCHIVE[1])
    MODELS.mkdir(parents=True, exist_ok=True)
    segmentation = MODELS / "segmentation.onnx"
    with tarfile.open(archive, "r:bz2") as bundle:
        member = bundle.extractfile(SEGMENTATION_MEMBER)
        if member is None:
            raise SystemExit("[ERROR] segmentation model is missing from the archive")
        segmentation.write_bytes(member.read())
        licence = bundle.extractfile("sherpa-onnx-pyannote-segmentation-3-0/LICENSE")
        if licence is not None:
            (MODELS / "LICENSE-pyannote-segmentation-3.0.txt").write_bytes(licence.read())
    if sha256(segmentation) != SEGMENTATION_SHA256:
        raise SystemExit("[ERROR] segmentation model: checksum mismatch after unpacking")

    step(3, "Download the speaker embedding model")
    download(EMBEDDING[0], MODELS / "embedding.onnx", "Speaker embedding model", EMBEDDING[1])

    step(4, "Verify")
    import sherpa_onnx  # noqa: PLC0415 - installed a moment ago

    config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(model=str(segmentation)),
        ),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(MODELS / "embedding.onnx")),
        clustering=sherpa_onnx.FastClusteringConfig(num_clusters=2),
    )
    if not config.validate():
        raise SystemExit("[ERROR] sherpa-onnx rejected the models")
    engine = sherpa_onnx.OfflineSpeakerDiarization(config)
    print(f"sherpa-onnx {sherpa_onnx.__version__}: OK, {engine.sample_rate} Hz", flush=True)

    MARKER.parent.mkdir(parents=True, exist_ok=True)
    MARKER.write_text(
        "kind=sherpa-onnx\n"
        f"version={sherpa_onnx.__version__}\n"
        f"models={MODELS}\n"
        f"installed_at={time.strftime('%Y-%m-%dT%H:%M:%S')}\n",
        encoding="utf-8",
    )
    print("Speaker separation (no key) is ready. It needs the number of speakers to run.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
