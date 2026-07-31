#!/usr/bin/env python3
"""Publish HOI multi_imgs_to_v object-reference cases into the static gallery."""

from __future__ import annotations

import argparse
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

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUN = Path(
    "/mnt/data04/144632/zachxu@videorebirth.com/projects/DataPipe/"
    "s2v_datapipeline/runs/real-hoi-multisource-gallery"
)
PRIORITY = ("HOIGen-1M", "HuMoSet", "GOKU-2M")


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
                or ref.get("raw_context_crop")
                or ref.get("context_crop")
                or ""
            )
            if primary.is_file():
                cutouts = [primary]
        edited = Path(ref.get("edited_reference") or "")
        mask = Path(ref.get("mask_crop") or "")
        source_frame = Path(ref.get("source_frame") or "")
        entry = {
            "role": "object",
            "name": ref.get("name"),
            "media_type": "image",
            "views": [],
            "source_frame_index": ref.get("source_frame_index"),
        }
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
                entry["raw"] = view_url
                entry["cutout"] = view_url
                entry["pre_edit"] = view_url
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
            entry["path"] = entry["raw"]
            entry["qwen_skipped"] = ref.get("qwen_skipped")
            entry["nano_banana_skipped"] = ref.get("nano_banana_skipped")
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
        or "human_w_object"
    )
    sample = {
        "id": sid,
        "task": "multi_imgs_to_v",
        "dataset": dataset,
        "pipeline": "sam2_qwen_edit_hoi_object",
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
        "notes": "Primary: edited output. Debug: source frame, pre-edit cutout, SAM mask, other views/frames.",
        "gemma_scores": [
            {
                "name": ref.get("name"),
                "overall": (ref.get("gemma_score") or {}).get("overall"),
                "sharpness": (ref.get("gemma_score") or {}).get("sharpness"),
                "completeness": (ref.get("gemma_score") or {}).get("completeness"),
                "cleanliness": (ref.get("gemma_score") or {}).get("cleanliness"),
                "reject": (ref.get("gemma_score") or {}).get("reject"),
                "reason": (ref.get("gemma_score") or {}).get("reason"),
            }
            for ref in object_refs
            if ref.get("gemma_score")
        ],
        "completion_backend": [
            ref.get("completion_backend")
            for ref in object_refs
            if ref.get("completion_backend")
        ],
    }
    print("ok", sid, dataset, "refs", len(refs), "frames", len(frame_urls))
    return sample


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--run",
        type=Path,
        action="append",
        dest="runs",
        help="pipeline run directory (repeatable; later runs override same sample_id)",
    )
    args = parser.parse_args()
    runs = [p.resolve() for p in (args.runs or [DEFAULT_RUN])]

    media_root = ROOT / "media" / "samples" / "multi_imgs_to_v_real"
    media_root.mkdir(parents=True, exist_ok=True)

    catalog_path = ROOT / "data" / "catalog.json"
    # Preserve existing gallery samples (prepared omni + prior HOI). Only upsert
    # samples produced by the requested runs; never wipe unrelated media/catalog.
    by_id: dict[str, dict] = {}
    if catalog_path.is_file():
        existing = json.loads(catalog_path.read_text())
        for sample in existing.get("samples") or []:
            sid = sample.get("id")
            if isinstance(sid, str) and sid:
                by_id[sid] = sample

    run_names: list[str] = []
    upserted = 0
    for run in runs:
        manifest = run / "stages" / "report" / "part-00000.jsonl"
        if not manifest.is_file():
            raise SystemExit(f"missing manifest: {manifest}")
        run_names.append(run.name)
        for line in manifest.read_text().splitlines():
            if not line.strip():
                continue
            sample = _sync_row(json.loads(line), media_root)
            if sample is None:
                continue
            # Replace only this sample's media dir contents via _sync_row writes.
            by_id[sample["id"]] = sample
            upserted += 1

    new_samples = sorted(
        by_id.values(),
        key=lambda s: (
            0 if s.get("task") == "multi_imgs_to_v" else 1,
            PRIORITY.index(s["dataset"]) if s.get("dataset") in PRIORITY else 99,
            str(s.get("task") or ""),
            str(s.get("dataset") or ""),
            str(s.get("id") or ""),
        ),
    )

    by_dataset: dict[str, int] = {}
    by_task: dict[str, int] = {}
    for sample in new_samples:
        key = str(sample.get("dataset") or "?")
        by_dataset[key] = by_dataset.get(key, 0) + 1
        task = str(sample.get("task") or "?")
        by_task[task] = by_task.get(task, 0) + 1

    prev_source = {}
    if catalog_path.is_file():
        prev_source = (json.loads(catalog_path.read_text()).get("source") or {})
    catalog = {
        "title": "Omni / S2V sample gallery",
        "samples": new_samples,
        "sample_count": len(new_samples),
        "source": {
            **prev_source,
            "real_multiref_run": "+".join(run_names) if run_names else prev_source.get("real_multiref_run"),
            "real_multiref_count": sum(
                1
                for s in new_samples
                if s.get("task") == "multi_imgs_to_v"
                and str(s.get("pipeline") or "").startswith("sam2")
            ),
            "task": "mixed",
            "pipeline": "omni+hoi_object",
            "by_dataset": by_dataset,
            "by_task": by_task,
        },
    }
    catalog_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                "upserted": upserted,
                "total": len(new_samples),
                "by_dataset": by_dataset,
                "by_task": by_task,
                "runs": run_names,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
