#!/usr/bin/env python3
"""Publish easy HOI bbox-crop multi-view cases into a separate gallery catalog."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

from PIL import Image

_HUMAN_RE = re.compile(
    r"\b(person|people|human|man|woman|boy|girl|child|face|hand|hands|subject)\b",
    re.I,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUN = Path(
    "/mnt/data04/144632/zachxu@videorebirth.com/projects/DataPipe/"
    "s2v_datapipeline/runs/real-hoi-easy-gallery"
)


def re_human(name: str) -> bool:
    return bool(_HUMAN_RE.search(name or ""))


def _ffmpeg_preview(src: Path, mp4: Path, poster: Path) -> dict:
    mp4.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(src), "-t", "2.5",
            "-vf", "scale='min(640,iw)':-2", "-an",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "28",
            "-movflags", "+faststart", str(mp4),
        ],
        check=True,
    )
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(src), "-vf", "scale='min(640,iw)':-2",
            "-frames:v", "1", str(poster),
        ],
        check=True,
    )
    meta = json.loads(
        subprocess.check_output(
            [
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=width,height",
                "-show_entries", "format=duration", "-of", "json", str(src),
            ],
            text=True,
        )
    )
    stream = (meta.get("streams") or [{}])[0]
    return {
        "width": stream.get("width"),
        "height": stream.get("height"),
        "duration_sec": round(float((meta.get("format") or {}).get("duration") or 0), 3),
    }


def _copy_image(src: Path, dst: Path, max_side: int = 720) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as im:
        im = im.convert("RGB")
        im.thumbnail((max_side, max_side))
        im.save(dst, format="JPEG", quality=88, optimize=True)


def _sync_row(row: dict, media_root: Path) -> dict | None:
    status = row.get("status") if isinstance(row.get("status"), dict) else {}
    refs_raw = row.get("references") or []
    if status.get("state") == "rejected" or not refs_raw:
        print("skip", row.get("sample_id"), status.get("reason"))
        return None
    object_refs = [
        ref
        for ref in refs_raw
        if str(ref.get("role") or "object") == "object"
        and not re_human(str(ref.get("name") or ""))
    ]
    if not object_refs:
        print("skip-no-object-ref", row.get("sample_id"))
        return None

    sid = row["sample_id"]
    rel = f"easy/{sid}"
    out = media_root / sid
    out.mkdir(parents=True, exist_ok=True)

    media = row.get("media") if isinstance(row.get("media"), dict) else {}
    video = Path(
        row.get("video_path")
        or media.get("video")
        or ((row.get("source") or {}).get("video") or {}).get("path")
        or ""
    )
    if not video.is_file():
        raise FileNotFoundError(f"missing video for {sid}: {video}")
    meta = _ffmpeg_preview(video, out / "target.mp4", out / "poster.jpg")

    frame_urls = []
    for findex, frame in enumerate(row.get("candidate_frames") or []):
        frame_path = Path(str(frame.get("path") or ""))
        if not frame_path.is_file():
            continue
        name = f"frame-{findex:02d}.jpg"
        _copy_image(frame_path, out / name, max_side=640)
        frame_urls.append(
            {
                "path": f"media/samples/{rel}/{name}",
                "frame_index": frame.get("frame_index"),
                "timestamp": frame.get("timestamp"),
            }
        )

    refs = []
    for idx, ref in enumerate(object_refs):
        cutouts = [
            Path(path)
            for path in (ref.get("multi_view_cutouts") or [])
            if path
        ]
        if not cutouts:
            primary = Path(
                ref.get("selected_cutout")
                or ref.get("cutout")
                or ref.get("path")
                or ""
            )
            if primary.is_file():
                cutouts = [primary]
        entry = {
            "role": "object",
            "name": ref.get("name"),
            "media_type": "image",
            "reference_kind": "bbox_crop",
            "views": [],
            "source_frame_index": ref.get("source_frame_index"),
        }
        source_frame = Path(ref.get("source_frame") or "")
        if source_frame.is_file():
            name = f"ref-{idx:02d}-source-frame.jpg"
            _copy_image(source_frame, out / name, max_side=640)
            entry["source_frame"] = f"media/samples/{rel}/{name}"
        for vidx, cutout in enumerate(cutouts):
            if not cutout.is_file():
                continue
            name = f"ref-{idx:02d}-view-{vidx:02d}.jpg"
            _copy_image(cutout, out / name)
            view_url = f"media/samples/{rel}/{name}"
            entry["views"].append(view_url)
            if vidx == 0:
                entry["path"] = view_url
                entry["raw"] = view_url
                entry["cutout"] = view_url
        if entry.get("views"):
            refs.append(entry)

    text = row.get("text") or {}
    prompt = (
        text.get("user_prompt")
        or text.get("dense_caption")
        or text.get("long")
        or text.get("short")
        or row.get("caption")
        or ""
    )
    source = row.get("source") if isinstance(row.get("source"), dict) else {}
    dataset = (
        (source.get("name") if isinstance(source, dict) else None)
        or row.get("dataset")
        or "HOIGen-1M"
    )
    sample = {
        "id": sid,
        "task": "multi_imgs_to_v",
        "dataset": dataset,
        "pipeline": "easy",
        "prompt": prompt,
        "original_id": (
            (source.get("record_id") if isinstance(source, dict) else None)
            or row.get("original_id")
        ),
        "hand_objects": row.get("hand_objects")
        or [ref.get("name") for ref in object_refs if ref.get("name")],
        "target": {
            "path": f"media/samples/{rel}/target.mp4",
            "poster": f"media/samples/{rel}/poster.jpg",
            **meta,
        },
        "candidate_frames": frame_urls,
        "references": refs,
        "notes": "Easy: Gemma HOI bbox crops across keyframes (no SAM / edit / face).",
        "timing": row.get("timing"),
    }
    print(
        "ok",
        sid,
        dataset,
        "refs",
        len(refs),
        "views",
        sum(len(r.get("views") or []) for r in refs),
        "frames",
        len(frame_urls),
    )
    return sample


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--run",
        type=Path,
        default=DEFAULT_RUN,
        help="easy pipeline run directory",
    )
    args = parser.parse_args()
    run = args.run.resolve()
    manifest = run / "stages" / "report" / "part-00000.jsonl"
    if not manifest.is_file():
        raise SystemExit(f"missing manifest: {manifest}")

    media_root = ROOT / "media" / "samples" / "easy"
    media_root.mkdir(parents=True, exist_ok=True)

    samples = []
    for line in manifest.read_text().splitlines():
        if not line.strip():
            continue
        sample = _sync_row(json.loads(line), media_root)
        if sample is not None:
            samples.append(sample)

    catalog = {
        "title": "Easy HOI → multi-view bbox crops",
        "samples": samples,
        "sample_count": len(samples),
        "source": {
            "pipeline": "easy",
            "run": run.name,
            "note": (
                "Gemma detects hand-interacted objects; bbox crops kept across "
                "keyframes. No SAM, no completion edit, no face."
            ),
            "by_dataset": {},
        },
    }
    by_dataset: dict[str, int] = {}
    for sample in samples:
        key = str(sample.get("dataset") or "?")
        by_dataset[key] = by_dataset.get(key, 0) + 1
    catalog["source"]["by_dataset"] = by_dataset

    out = ROOT / "data" / "catalog_easy.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"written": str(out), "samples": len(samples), "by_dataset": by_dataset}, indent=2))


if __name__ == "__main__":
    main()
