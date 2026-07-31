#!/usr/bin/env python3
"""Publish Easy corpus artifacts (accepted + rejected) into the Pages gallery."""

from __future__ import annotations

import argparse
import json
import random
import re
import subprocess
from pathlib import Path

from PIL import Image

_HUMAN_RE = re.compile(
    r"\b(person|people|human|man|woman|boy|girl|child|face|hand|hands|subject)\b",
    re.I,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CORPUS = Path(
    "/mnt/data04/144632/zachxu@videorebirth.com/projects/DataPipe/"
    "human_w_object/easy_hoi_reusable_v1"
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


def _pick(rows: list[dict], limit: int, seed: int) -> list[dict]:
    if limit <= 0 or len(rows) <= limit:
        return list(rows)
    rng = random.Random(seed)
    return rng.sample(rows, limit)


def _sync_record(record: dict, media_root: Path) -> dict | None:
    sid = str(record.get("sample_id") or "")
    if not sid:
        return None
    status = record.get("status") if isinstance(record.get("status"), dict) else {}
    state = str(status.get("state") or record.get("state") or "")
    reason = str(status.get("reason") or record.get("reason") or "")

    media = record.get("media") if isinstance(record.get("media"), dict) else {}
    video = Path(
        record.get("video_path")
        or media.get("video")
        or ((record.get("source") or {}).get("video") or {}).get("path")
        or ""
    )
    if not video.is_file():
        # corpus index uses top-level video
        video = Path(str(record.get("video") or ""))
    if not video.is_file():
        print("skip-missing-video", sid, video)
        return None

    rel = f"easy/{sid}"
    out = media_root / sid
    out.mkdir(parents=True, exist_ok=True)
    meta = _ffmpeg_preview(video, out / "target.mp4", out / "poster.jpg")

    frame_urls = []
    for findex, frame in enumerate(record.get("candidate_frames") or []):
        frame_path = Path(str(frame.get("path") or ""))
        if not frame_path.is_file():
            continue
        name = f"frame-{findex:02d}.jpg"
        _copy_image(frame_path, out / name, max_side=640)
        frame_urls.append(
            {
                "path": f"media/samples/{rel}/{name}",
                "frame_index": frame.get("frame_index", findex),
                "timestamp": frame.get("timestamp"),
            }
        )

    refs = []
    object_refs = [
        ref
        for ref in (record.get("references") or [])
        if str(ref.get("role") or "object") == "object"
        and not re_human(str(ref.get("name") or ""))
    ]
    for idx, ref in enumerate(object_refs):
        view_rows = list(ref.get("views") or [])
        entry = {
            "role": "object",
            "name": ref.get("name"),
            "media_type": "image",
            "reference_kind": "bbox_crop",
            "views": [],
            "select_score": ref.get("select_score"),
            "source_frame_index": ref.get("source_frame_index"),
        }
        source_frame = Path(str(ref.get("source_frame") or ""))
        if source_frame.is_file():
            name = f"ref-{idx:02d}-source-frame.jpg"
            _copy_image(source_frame, out / name, max_side=640)
            entry["source_frame"] = f"media/samples/{rel}/{name}"
        if not view_rows and ref.get("multi_view_cutouts"):
            view_rows = [
                {"path": path, "selected": i == 0}
                for i, path in enumerate(ref.get("multi_view_cutouts") or [])
            ]
        for vidx, view in enumerate(view_rows):
            if isinstance(view, str):
                view = {"path": view, "selected": vidx == 0}
            cutout = Path(str(view.get("path") or ""))
            if not cutout.is_file():
                continue
            name = f"ref-{idx:02d}-view-{vidx:02d}.jpg"
            _copy_image(cutout, out / name)
            view_url = f"media/samples/{rel}/{name}"
            entry["views"].append(
                {
                    "path": view_url,
                    "selected": bool(view.get("selected")),
                    "select_score": view.get("select_score"),
                    "source_frame_index": view.get("source_frame_index"),
                }
            )
            if view.get("selected") or not entry.get("path"):
                entry["path"] = view_url
                entry["raw"] = view_url
                entry["cutout"] = view_url
                entry["selected_cutout"] = view_url
        if entry.get("views"):
            refs.append(entry)

    text = record.get("text") or {}
    prompt = (
        text.get("user_prompt")
        or text.get("dense_caption")
        or text.get("long")
        or text.get("short")
        or record.get("caption")
        or ""
    )
    source = record.get("source") if isinstance(record.get("source"), dict) else {}
    dataset = (
        source.get("name")
        or record.get("dataset")
        or "human_w_object"
    )
    sample = {
        "id": sid,
        "task": "multi_imgs_to_v",
        "dataset": dataset,
        "pipeline": "easy",
        "status": state or ("accepted" if refs else "rejected"),
        "reason": reason,
        "prompt": prompt,
        "original_id": source.get("record_id") or record.get("original_id"),
        "hand_objects": record.get("hand_objects")
        or [ref.get("name") for ref in refs if ref.get("name")],
        "target": {
            "path": f"media/samples/{rel}/target.mp4",
            "poster": f"media/samples/{rel}/poster.jpg",
            **meta,
        },
        "candidate_frames": frame_urls,
        "references": refs,
        "notes": (
            f"Easy corpus · {state or '?'} · {reason}"
            if state == "rejected"
            else "Easy corpus · accepted bbox crops (selected marked)."
        ),
    }
    print(
        "ok",
        sid,
        sample["status"],
        sample.get("reason") or "",
        "refs",
        len(refs),
        "frames",
        len(frame_urls),
    )
    return sample


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--accepted", type=int, default=24)
    parser.add_argument("--rejected", type=int, default=12)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    corpus = args.corpus.resolve()
    index_path = corpus / "reusable" / "index.jsonl"
    if not index_path.is_file():
        raise SystemExit(f"missing index: {index_path}")

    accepted_rows: list[dict] = []
    rejected_rows: list[dict] = []
    for line in index_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        record_path = Path(str(row.get("record_json") or ""))
        if not record_path.is_file():
            continue
        record = json.loads(record_path.read_text(encoding="utf-8"))
        # Prefer fields from full record; keep index video fallback.
        if not record.get("video") and row.get("video"):
            record["video"] = row["video"]
        if not record.get("dataset") and row.get("dataset"):
            record["dataset"] = row["dataset"]
        state = str((record.get("status") or {}).get("state") or row.get("state") or "")
        if state == "accepted":
            accepted_rows.append(record)
        elif state == "rejected":
            rejected_rows.append(record)

    chosen = _pick(accepted_rows, args.accepted, args.seed) + _pick(
        rejected_rows, args.rejected, args.seed + 1
    )
    media_root = ROOT / "media" / "samples" / "easy"
    media_root.mkdir(parents=True, exist_ok=True)

    # Clear previous easy gallery media for a clean corpus snapshot.
    for old in media_root.glob("s2v_*"):
        if old.is_dir():
            for child in old.rglob("*"):
                if child.is_file():
                    child.unlink()
            # keep dirs rebuilt below

    samples = []
    for record in chosen:
        sample = _sync_record(record, media_root)
        if sample is not None:
            samples.append(sample)

    by_dataset: dict[str, int] = {}
    by_status: dict[str, int] = {}
    for sample in samples:
        by_dataset[str(sample.get("dataset") or "?")] = (
            by_dataset.get(str(sample.get("dataset") or "?"), 0) + 1
        )
        by_status[str(sample.get("status") or "?")] = (
            by_status.get(str(sample.get("status") or "?"), 0) + 1
        )

    catalog = {
        "title": "Easy HOI corpus preview (accepted + rejected)",
        "samples": samples,
        "sample_count": len(samples),
        "source": {
            "pipeline": "easy",
            "run": corpus.name,
            "note": (
                "Preview from easy_hoi_reusable_v1. Accepted = Gemma found "
                "hand-object + bbox crops. Rejected = no_hand_object."
            ),
            "by_dataset": by_dataset,
            "by_status": by_status,
            "corpus_index": str(index_path),
        },
    }
    out = ROOT / "data" / "catalog_easy.json"
    out.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                "written": str(out),
                "samples": len(samples),
                "by_status": by_status,
                "by_dataset": by_dataset,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
