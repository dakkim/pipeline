# Pipeline

Static gallery of **sampled** prepared OmniWeaving / S2V training rows.

This is a review surface, not the training corpus. Full Arrow manifests and
archive indexes stay on the data machines; only short web previews and a
catalog JSON are published here.

## What you are looking at

| Task | Where samples come from |
|---|---|
| `t2v` | HOIGen + internal `human_w_object` |
| `multi_imgs_to_v` | HuMoSet (+ one derived multi-ref row) |
| `v2v` / `tiv2v` | GOKU edit tasks |
| `i2v` / `key_frames_to_v` | `omni_aux_v1` derived manifests |

Each card shows the target clip preview, optional condition references, and
the prompt the loader would see.

## Local preview

```bash
cd pipeline
python -m http.server 8080
# open http://127.0.0.1:8080
```

## Rebuild media (on the data machine)

```bash
PYTHONPATH=../DataPipe/s2v_datapipeline/src \
  python scripts/build_gallery.py
```

Requires access to `omni_v3`, `omni_aux_v1`, `archive_index_v2.sqlite`, and the
underlying archives / loose files.

## Real multi-reference cases

`media/samples/multi_imgs_to_v_real/` comes from run `real-multiref-gallery`:

1. candidate frames from video
2. **SAM2** masks → multi-view crops
3. **Qwen-Image-Edit** completes occluded/incomplete crops

Each card shows raw crop, SAM mask crop, and Qwen-edited reference side by side.

Refresh after a new run:

```bash
python scripts/sync_multiref_gallery.py
```
