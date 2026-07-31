#!/usr/bin/env python3
"""Publish real SAM2 + Qwen-Edit multi-ref cases into the static gallery."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
RUN = Path(
    "/mnt/data04/144632/zachxu@videorebirth.com/projects/DataPipe/s2v_datapipeline/runs/real-multiref-gallery"
)
MANIFEST = RUN / "stages" / "report" / "part-00000.jsonl"


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


def main() -> None:
    if not MANIFEST.is_file():
        raise SystemExit(f"missing manifest: {MANIFEST}")

    media_root = ROOT / "media" / "samples" / "multi_imgs_to_v_real"
    if media_root.exists():
        shutil.rmtree(media_root)
    media_root.mkdir(parents=True)

    catalog_path = ROOT / "data" / "catalog.json"
    catalog = json.loads(catalog_path.read_text()) if catalog_path.exists() else {
        "title": "S2V / Omni prepared data gallery",
        "samples": [],
        "source": {},
    }

    # Drop previous real multi-ref gallery entries and weak single-ref HuMo demos
    # for the multi-ref filter clarity; keep other tasks.
    kept = [
        s
        for s in catalog.get("samples", [])
        if not (
            s.get("task") == "multi_imgs_to_v"
            and (
                s.get("pipeline") == "sam2_qwen_edit"
                or s.get("dataset") == "humoset"
            )
        )
    ]

    new_samples = []
    for line in MANIFEST.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("status", {}).get("state") not in {None, "accepted"} and not row.get(
            "quality", {}
        ).get("accepted", True):
            # still include accepted-ish records; smoke writes accepted
            pass
        sid = row["sample_id"]
        rel = f"multi_imgs_to_v_real/{sid}"
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

        refs = []
        for idx, ref in enumerate(row.get("references") or []):
            raw = Path(ref.get("raw_context_crop") or ref.get("context_crop") or "")
            edited = Path(ref.get("edited_reference") or "")
            mask = Path(ref.get("mask_crop") or "")
            entry = {
                "role": ref.get("role"),
                "name": ref.get("name"),
                "media_type": "image",
            }
            if raw.is_file():
                name = f"ref-{idx:02d}-raw.jpg"
                _copy_image(raw, out / name)
                entry["raw"] = f"media/samples/{rel}/{name}"
            if mask.is_file():
                name = f"ref-{idx:02d}-mask.jpg"
                _copy_image(mask, out / name)
                entry["mask"] = f"media/samples/{rel}/{name}"
            if edited.is_file():
                name = f"ref-{idx:02d}-edited.jpg"
                _copy_image(edited, out / name)
                entry["path"] = f"media/samples/{rel}/{name}"
                entry["edited"] = entry["path"]
            elif raw.is_file():
                entry["path"] = entry["raw"]
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
        sample = {
            "id": sid,
            "task": "multi_imgs_to_v",
            "dataset": source.get("name") or row.get("dataset") or "human_w_object",
            "pipeline": "sam2_qwen_edit",
            "prompt": prompt,
            "original_id": source.get("record_id") or row.get("original_id"),
            "target": {
                "path": f"media/samples/{rel}/target.mp4",
                "poster": f"media/samples/{rel}/poster.jpg",
                **meta,
            },
            "references": refs,
            "notes": "SAM2 multi-view crops + Qwen-Image-Edit completion",
        }
        new_samples.append(sample)
        print("ok", sid, "refs", len(refs))

    catalog["samples"] = new_samples + kept
    catalog["sample_count"] = len(catalog["samples"])
    source = catalog.setdefault("source", {})
    source["real_multiref_run"] = "real-multiref-gallery"
    source["real_multiref_count"] = len(new_samples)
    catalog_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"added": len(new_samples), "total": catalog["sample_count"]}, indent=2))


if __name__ == "__main__":
    main()
