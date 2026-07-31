#!/usr/bin/env python3
"""Sample Omni prepared Arrow rows and emit a static gallery catalog + media."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.ipc as ipc
from PIL import Image

from s2v_datapipeline.storage import AssetResolver, NodeCache


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OMNI = Path("/mnt/data04/144632/zachxu@videorebirth.com/datasets/prepared/omni_v3")
DEFAULT_AUX = Path("/mnt/data04/144632/zachxu@videorebirth.com/datasets/prepared/omni_aux_v1")
DEFAULT_INDEX = Path(
    "/mnt/data04/144632/zachxu@videorebirth.com/datasets/prepared/archive_index_v2.sqlite"
)
DEFAULT_DATASETS = Path("/mnt/data04/144632/zachxu@videorebirth.com/datasets")

# Prefer diversity across datasets within each task.
PLAN: list[dict[str, Any]] = [
    {"task": "t2v", "dataset": "hoigen", "root": "omni", "count": 2},
    {"task": "t2v", "dataset": "human_w_object", "root": "omni", "count": 2},
    {"task": "multi_imgs_to_v", "dataset": "humoset", "root": "omni", "count": 3},
    {"task": "multi_imgs_to_v", "dataset": None, "root": "omni", "count": 1},  # derived smoke
    {"task": "v2v", "dataset": "goku", "root": "omni", "count": 3},
    {"task": "tiv2v", "dataset": "goku", "root": "omni", "count": 3},
    {"task": "i2v", "dataset": None, "root": "aux", "count": 3},
    {"task": "key_frames_to_v", "dataset": None, "root": "aux", "count": 3},
]


def _arrow_parts(root: Path, task: str) -> list[Path]:
    base = root / f"task={task}"
    if not base.exists():
        return []
    return sorted(base.rglob("*.arrow"))


def _iter_rows(parts: list[Path], *, dataset: str | None):
    for part in parts:
        if dataset and f"/dataset={dataset}/" not in f"/{part.as_posix()}/":
            # also match path segments without leading slash quirks
            if f"dataset={dataset}" not in part.as_posix():
                continue
        with pa.memory_map(str(part), "r") as source:
            table = ipc.open_file(source).read_all()
        for i in range(table.num_rows):
            yield {name: table.column(name)[i].as_py() for name in table.column_names}


def _stable_pick(rows: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    ranked = sorted(
        rows,
        key=lambda r: hashlib.sha1(str(r.get("sample_id", "")).encode()).hexdigest(),
    )
    if len(ranked) <= count:
        return ranked
    # even spacing across the ranked list for visual diversity
    step = max(1, len(ranked) // count)
    picks = []
    for i in range(count):
        picks.append(ranked[min(i * step, len(ranked) - 1)])
    # de-dupe while preserving order
    seen = set()
    out = []
    for row in picks:
        sid = row["sample_id"]
        if sid in seen:
            continue
        seen.add(sid)
        out.append(row)
    return out


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _extract_video_preview(src: Path, out_mp4: Path, poster: Path) -> dict[str, Any]:
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    # short, small, web-friendly clip
    _run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(src),
            "-t",
            "2.5",
            "-vf",
            "scale='min(640,iw)':-2",
            "-an",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "28",
            "-movflags",
            "+faststart",
            str(out_mp4),
        ]
    )
    _run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(src),
            "-vf",
            "scale='min(640,iw)':-2",
            "-frames:v",
            "1",
            str(poster),
        ]
    )
    probe = subprocess.check_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(src),
        ],
        text=True,
    )
    meta = json.loads(probe)
    stream = (meta.get("streams") or [{}])[0]
    duration = float((meta.get("format") or {}).get("duration") or 0)
    return {
        "width": stream.get("width"),
        "height": stream.get("height"),
        "duration_sec": round(duration, 3),
    }


def _copy_image(src: Path, dst: Path, max_side: int = 640) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as im:
        im = im.convert("RGB")
        im.thumbnail((max_side, max_side))
        im.save(dst, format="JPEG", quality=85, optimize=True)


def _materialize(resolver: AssetResolver, asset: dict[str, Any], tmp: Path) -> Path:
    storage = asset.get("storage")
    if storage == "file":
        path = Path(asset.get("path") or asset["uri"])
        if not path.exists():
            raise FileNotFoundError(path)
        return path
    if storage == "archive":
        # Prefer materialize_video for large members (uses node cache + CRC).
        path = resolver.materialize_video(
            {
                "storage": "archive",
                "archive": asset["archive"],
                "member": asset["member"],
            }
        )
        return Path(path)
    raise ValueError(f"unsupported storage {storage}")


def _role(assets: list[dict[str, Any]], role: str) -> dict[str, Any] | None:
    for item in assets:
        if item.get("role") == role:
            return item
    return None


def build(args: argparse.Namespace) -> None:
    media_root = ROOT / "media" / "samples"
    if media_root.exists():
        shutil.rmtree(media_root)
    media_root.mkdir(parents=True)

    roots = {"omni": Path(args.omni), "aux": Path(args.aux)}
    cache = NodeCache(args.cache_dir, max_bytes=int(args.cache_max_bytes))
    resolver = AssetResolver(
        args.archive_index,
        datasets_root=args.datasets_root,
        cache=cache,
    )

    samples: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="pipeline-gallery-") as tmp_name:
        tmp = Path(tmp_name)
        for plan in PLAN:
            task = plan["task"]
            parts = _arrow_parts(roots[plan["root"]], task)
            if not parts:
                errors.append({"plan": plan, "error": "no arrow parts"})
                continue
            # gather a modest candidate pool then pick stably
            pool: list[dict[str, Any]] = []
            for row in _iter_rows(parts, dataset=plan.get("dataset")):
                # skip pure derived smoke unless dataset filter is None and we want non-humoset
                if (
                    plan["task"] == "multi_imgs_to_v"
                    and plan.get("dataset") is None
                    and row.get("dataset") == "humoset"
                ):
                    continue
                if plan.get("dataset") and row.get("dataset") != plan["dataset"]:
                    continue
                pool.append(row)
                if len(pool) >= 400:
                    break
            picks = _stable_pick(pool, int(plan["count"]))
            for row in picks:
                sid = row["sample_id"]
                rel_dir = f"{task}/{sid}"
                out_dir = media_root / rel_dir
                out_dir.mkdir(parents=True, exist_ok=True)
                try:
                    target = _role(row["assets"], "target")
                    if not target:
                        raise RuntimeError("missing target asset")
                    target_path = _materialize(resolver, target, tmp)
                    video_meta = _extract_video_preview(
                        target_path,
                        out_dir / "target.mp4",
                        out_dir / "poster.jpg",
                    )

                    refs_out = []
                    for idx, ref in enumerate(row.get("references") or []):
                        ref_path = _materialize(resolver, ref, tmp)
                        media_type = ref.get("media_type")
                        if media_type == "image":
                            name = f"ref-{idx:02d}.jpg"
                            _copy_image(ref_path, out_dir / name)
                            refs_out.append(
                                {
                                    "role": ref.get("role"),
                                    "media_type": "image",
                                    "path": f"media/samples/{rel_dir}/{name}",
                                }
                            )
                        elif media_type == "video":
                            name = f"ref-{idx:02d}.mp4"
                            poster = f"ref-{idx:02d}-poster.jpg"
                            meta = _extract_video_preview(
                                ref_path, out_dir / name, out_dir / poster
                            )
                            refs_out.append(
                                {
                                    "role": ref.get("role"),
                                    "media_type": "video",
                                    "path": f"media/samples/{rel_dir}/{name}",
                                    "poster": f"media/samples/{rel_dir}/{poster}",
                                    **meta,
                                }
                            )
                    entry = {
                        "id": sid,
                        "task": task,
                        "dataset": row.get("dataset"),
                        "prompt": (row.get("prompt") or "").strip(),
                        "original_id": row.get("original_id"),
                        "archive_group": row.get("archive_group"),
                        "target": {
                            "path": f"media/samples/{rel_dir}/target.mp4",
                            "poster": f"media/samples/{rel_dir}/poster.jpg",
                            **video_meta,
                        },
                        "references": refs_out,
                    }
                    samples.append(entry)
                    print("ok", task, sid, row.get("dataset"))
                except Exception as exc:  # noqa: BLE001 - gallery build should continue
                    errors.append(
                        {
                            "sample_id": sid,
                            "task": task,
                            "dataset": row.get("dataset"),
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )
                    print("fail", task, sid, exc)
                    shutil.rmtree(out_dir, ignore_errors=True)

    stats_omni = json.loads((roots["omni"] / "statistics.json").read_text())
    stats_aux = json.loads((roots["aux"] / "statistics.json").read_text())
    catalog = {
        "title": "S2V / Omni prepared data gallery",
        "source": {
            "omni_v3": str(roots["omni"]),
            "omni_aux_v1": str(roots["aux"]),
            "records_omni": stats_omni.get("records"),
            "records_aux": stats_aux.get("records"),
            "tasks_omni": stats_omni.get("tasks"),
            "tasks_aux": stats_aux.get("tasks"),
            "rejected_zero_byte": stats_omni.get("rejected"),
        },
        "sample_count": len(samples),
        "samples": samples,
        "errors": errors,
    }
    data_dir = ROOT / "data"
    data_dir.mkdir(exist_ok=True)
    (data_dir / "catalog.json").write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n"
    )
    print(
        json.dumps(
            {"samples": len(samples), "errors": len(errors), "bytes": _dir_size(media_root)},
            indent=2,
        )
    )
    resolver.close()


def _dir_size(path: Path) -> int:
    total = 0
    for p in path.rglob("*"):
        if p.is_file():
            total += p.stat().st_size
    return total


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--omni", default=str(DEFAULT_OMNI))
    parser.add_argument("--aux", default=str(DEFAULT_AUX))
    parser.add_argument("--archive-index", default=str(DEFAULT_INDEX))
    parser.add_argument("--datasets-root", default=str(DEFAULT_DATASETS))
    parser.add_argument("--cache-dir", default="/tmp/s2v-pipeline-gallery-cache")
    parser.add_argument("--cache-max-bytes", default=8 * 1024**3, type=int)
    args = parser.parse_args()
    Path(args.cache_dir).mkdir(parents=True, exist_ok=True)
    build(args)


if __name__ == "__main__":
    main()
