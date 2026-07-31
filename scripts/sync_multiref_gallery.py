#!/usr/bin/env python3
"""Publish real SAM2 + Qwen-Edit multi-ref cases into the static gallery."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from PIL import Image

_HUMAN_RE = re.compile(
    r"\b(person|people|human|man|woman|boy|girl|child|face|hand|hands|subject)\b",
    re.I,
)


def re_human(name: str) -> bool:
    return bool(_HUMAN_RE.search(name or ""))

ROOT = Path(__file__).resolve().parents[1]
RUN = Path(
    "/mnt/data04/144632/zachxu@videorebirth.com/projects/DataPipe/s2v_datapipeline/runs/real-hoi-object-gallery"
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

    # Replace previous real multi-ref gallery entries; keep other Omni tasks.
    kept = [
        s
        for s in catalog.get("samples", [])
        if not (
            s.get("task") == "multi_imgs_to_v"
            and s.get("pipeline") in {"sam2_qwen_edit", "sam2_qwen_edit_hoi_object"}
        )
    ]

    new_samples = []
    for line in MANIFEST.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        status = row.get("status") if isinstance(row.get("status"), dict) else {}
        refs_raw = row.get("references") or []
        if status.get("state") == "rejected" or not refs_raw:
            print("skip", row.get("sample_id"), status.get("reason"))
            continue
        # Prefer object-role references only.
        object_refs = [
            ref
            for ref in refs_raw
            if str(ref.get("role") or "object") == "object"
            and not re_human(str(ref.get("name") or ""))
        ]
        if not object_refs:
            print("skip-no-object-ref", row.get("sample_id"))
            continue
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
        for idx, ref in enumerate(object_refs):
            cutouts = [
                Path(path)
                for path in (ref.get("multi_view_cutouts") or [])
                if path
            ]
            if not cutouts:
                primary = Path(
                    ref.get("cutout")
                    or ref.get("raw_context_crop")
                    or ref.get("context_crop")
                    or ""
                )
                if primary.is_file():
                    cutouts = [primary]
            edited = Path(ref.get("edited_reference") or "")
            mask = Path(ref.get("mask_crop") or "")
            entry = {
                "role": "object",
                "name": ref.get("name"),
                "media_type": "image",
                "views": [],
            }
            for vidx, cutout in enumerate(cutouts):
                if not cutout.is_file():
                    continue
                name = f"ref-{idx:02d}-view-{vidx:02d}.jpg"
                _copy_image(cutout, out / name)
                view_url = f"media/samples/{rel}/{name}"
                entry["views"].append(view_url)
                if vidx == 0:
                    entry["raw"] = view_url
                    entry["cutout"] = view_url
            if mask.is_file():
                name = f"ref-{idx:02d}-mask.jpg"
                _copy_image(mask, out / name)
                entry["mask"] = f"media/samples/{rel}/{name}"
            if edited.is_file():
                name = f"ref-{idx:02d}-edited.jpg"
                _copy_image(edited, out / name)
                entry["path"] = f"media/samples/{rel}/{name}"
                entry["edited"] = entry["path"]
            elif entry.get("raw"):
                # Qwen skipped (incomplete / no hand fringe): photographic cutout is the ref.
                entry["path"] = entry["raw"]
                entry["qwen_skipped"] = ref.get("qwen_skipped")
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
            "pipeline": "sam2_qwen_edit_hoi_object",
            "prompt": prompt,
            "original_id": source.get("record_id") or row.get("original_id"),
            "hand_objects": row.get("hand_objects")
            or [ref.get("name") for ref in object_refs if ref.get("name")],
            "target": {
                "path": f"media/samples/{rel}/target.mp4",
                "poster": f"media/samples/{rel}/poster.jpg",
                **meta,
            },
            "references": refs,
            "notes": "SAM2 cutouts → pick most complete view; Qwen only if complete+hand fringe",
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
