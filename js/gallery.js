const TASK_LABELS = {
  t2v: "Text → Video",
  i2v: "Image → Video",
  multi_imgs_to_v: "Multi-image → Video",
  key_frames_to_v: "Keyframes → Video",
  v2v: "Video → Video",
  tiv2v: "Text+Image+Video → Video",
};

function fmt(n) {
  return new Intl.NumberFormat("en-US").format(n);
}

function truncate(text, max = 420) {
  const t = (text || "").trim();
  if (t.length <= max) return t;
  return `${t.slice(0, max).trim()}…`;
}

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "className") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key.startsWith("on") && typeof value === "function") {
      node.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (value !== undefined && value !== null) {
      node.setAttribute(key, value);
    }
  }
  for (const child of children) {
    if (child == null) continue;
    node.append(child.nodeType ? child : document.createTextNode(child));
  }
  return node;
}

function openLightbox(media) {
  const dialog = document.getElementById("lightbox");
  const body = document.getElementById("lightbox-body");
  body.replaceChildren();
  if (media.media_type === "video" || media.path.endsWith(".mp4")) {
    const video = el("video", {
      src: media.path,
      controls: "",
      autoplay: "",
      playsinline: "",
    });
    body.append(video);
  } else {
    body.append(el("img", { src: media.path, alt: media.role || "reference" }));
  }
  dialog.showModal();
}

function shortName(name, max = 18) {
  const text = (name || "").trim();
  if (!text) return "";
  if (text.length <= max) return text;
  return `${text.slice(0, max - 1)}…`;
}

function tileLabel(objectName, kind, multiObject) {
  const obj = shortName(objectName);
  if (multiObject && obj) return `${obj} · ${kind}`;
  return kind;
}

function makeTile({
  label,
  path,
  media,
  primary = false,
  selected = false,
  objectName = "",
}) {
  const payload = media || {
    path,
    media_type: "image",
    role: label,
  };
  const classes = ["ref-tile"];
  if (primary) classes.push("is-primary");
  if (selected) classes.push("is-selected");
  return el(
    "button",
    {
      type: "button",
      className: classes.join(" "),
      title: objectName ? `${objectName} · ${label}` : label,
      onClick: () => openLightbox(payload),
    },
    [
      el("img", { src: path, alt: label }),
      el("span", { className: "ref-caption", text: label }),
    ]
  );
}

function collectReferenceTiles(sample) {
  const refs = sample.references || [];
  const multiObject = refs.length > 1;
  const isEasy = sample.pipeline === "easy";
  const isHoi =
    sample.pipeline === "sam2_qwen_edit" ||
    sample.pipeline === "sam2_qwen_edit_hoi_object";

  const primary = [];
  const intermediates = [];
  const keyframes = [];

  for (const [index, ref] of refs.entries()) {
    const isFace = ref.role === "face";
    const objectName = ref.name || ref.role || `object ${index + 1}`;
    const viewPaths = Array.isArray(ref.views)
      ? ref.views
          .map((view) => (typeof view === "string" ? view : view?.path))
          .filter(Boolean)
      : [];
    const selectedCutout =
      ref.pre_edit ||
      ref.selected_cutout ||
      viewPaths[0] ||
      ref.cutout ||
      ref.raw ||
      null;
    const edited =
      ref.edited ||
      (ref.path &&
      ref.path !== ref.raw &&
      ref.path !== selectedCutout &&
      isHoi
        ? ref.path
        : null);

    if (isEasy) {
      // Easy: multi-view bbox crops; highest-scoring view marked selected.
      const viewObjs = Array.isArray(ref.views) ? ref.views : [];
      const crops = viewObjs.length
        ? viewObjs
            .map((view) =>
              typeof view === "string"
                ? { path: view, selected: false }
                : {
                    path: view?.path,
                    selected: Boolean(view?.selected),
                    score: view?.select_score?.total,
                  }
            )
            .filter((view) => view.path)
        : [selectedCutout || ref.path]
            .filter(Boolean)
            .map((path) => ({ path, selected: true }));
      if (crops.length && !crops.some((view) => view.selected)) {
        crops[0].selected = true;
      }
      crops.forEach((view, viewIndex) => {
        const kind = view.selected
          ? "selected"
          : `bbox view ${viewIndex + 1}`;
        const scoreHint =
          view.selected && view.score != null
            ? ` · score ${Number(view.score).toFixed(2)}`
            : "";
        primary.push(
          makeTile({
            label: tileLabel(
              objectName,
              kind,
              multiObject || crops.length > 1
            ),
            path: view.path,
            primary: true,
            selected: Boolean(view.selected),
            objectName: objectName + scoreHint,
          })
        );
      });
      if (ref.source_frame) {
        const frameLabel =
          ref.source_frame_index != null
            ? `bbox source f${ref.source_frame_index}`
            : "bbox source";
        intermediates.push(
          makeTile({
            label: tileLabel(objectName, frameLabel, multiObject),
            path: ref.source_frame,
            objectName,
          })
        );
        intermediates[intermediates.length - 1].classList.add("is-extract-frame");
      }
      continue;
    }

    // Front row: final training assets only (edited / object ref / face crop).
    if (isFace && (edited || ref.path || selectedCutout)) {
      primary.push(
        makeTile({
          label: tileLabel("face", "yolov8 crop", multiObject || true),
          path: edited || ref.path || selectedCutout,
          primary: true,
          objectName: "face",
        })
      );
    } else if (edited) {
      primary.push(
        makeTile({
          label: tileLabel(objectName, "edited output", multiObject),
          path: edited,
          primary: true,
          objectName,
        })
      );
    } else if (ref.path && !viewPaths.length && !isHoi) {
      primary.push(
        makeTile({
          label: tileLabel(
            objectName,
            ref.media_type === "video" ? "source" : "ref",
            multiObject
          ),
          path: ref.media_type === "video" ? ref.poster || ref.path : ref.path,
          media: ref,
          primary: true,
          objectName,
        })
      );
    } else if (!edited && selectedCutout && isHoi) {
      primary.push(
        makeTile({
          label: tileLabel(objectName, "object ref", multiObject),
          path: selectedCutout,
          primary: true,
          objectName,
        })
      );
    }

    // Debug row per object: extract frame (used for mask/ref) → pre-edit → mask → other cutouts.
    if (ref.source_frame) {
      const frameLabel =
        ref.source_frame_index != null
          ? `extract f${ref.source_frame_index}`
          : "extract frame";
      intermediates.push(
        makeTile({
          label: tileLabel(objectName, frameLabel, multiObject || isFace),
          path: ref.source_frame,
          objectName,
          primary: false,
        })
      );
      // Mark extract-frame tiles for CSS emphasis in the debug row.
      const last = intermediates[intermediates.length - 1];
      last.classList.add("is-extract-frame");
    }
    if (!isFace && selectedCutout) {
      intermediates.push(
        makeTile({
          label: tileLabel(objectName, "pre-edit cutout", multiObject),
          path: selectedCutout,
          objectName,
        })
      );
    }
    if (ref.mask) {
      intermediates.push(
        makeTile({
          label: tileLabel(objectName, "SAM mask", multiObject),
          path: ref.mask,
          objectName,
        })
      );
    }
    if (viewPaths.length > 1) {
      viewPaths.slice(1).forEach((path, viewIndex) => {
        intermediates.push(
          makeTile({
            label: tileLabel(
              objectName,
              `cutout ${viewIndex + 2}`,
              multiObject
            ),
            path,
            objectName,
          })
        );
      });
    }
  }

  // Shared video candidate / keyframes (prominent for easy page).
  const frames = Array.isArray(sample.candidate_frames)
    ? sample.candidate_frames
    : [];
  frames.forEach((frame, index) => {
    const path = typeof frame === "string" ? frame : frame?.path;
    if (!path) return;
    const idx =
      typeof frame === "object" && frame.frame_index != null
        ? frame.frame_index
        : index;
    const tile = makeTile({
      label: `keyframe f${idx}`,
      path,
      objectName: "video",
      primary: isEasy,
    });
    if (isEasy) keyframes.push(tile);
    else intermediates.push(tile);
  });

  return { primary, intermediates, keyframes };
}

function renderSample(sample) {
  const targetWidth = Number(sample.target?.width || 0);
  const targetHeight = Number(sample.target?.height || 0);
  const isPortrait = targetHeight > targetWidth && targetWidth > 0;
  const video = el("video", {
    src: sample.target.path,
    poster: sample.target.poster,
    muted: "",
    loop: "",
    playsinline: "",
    preload: "metadata",
  });
  video.addEventListener("mouseenter", () => {
    video.play().catch(() => {});
  });
  video.addEventListener("mouseleave", () => {
    video.pause();
    video.currentTime = 0;
  });

  const refs = sample.references || [];
  const { primary, intermediates, keyframes } = collectReferenceTiles(sample);
  const refBlocks = [];
  if (primary.length) {
    refBlocks.push(
      el(
        "div",
        {
          className: "ref-row ref-row-primary",
          "aria-label":
            sample.pipeline === "easy"
              ? "Multi-view object bbox crops"
              : "Final edited object references",
        },
        primary
      )
    );
  }
  if (keyframes && keyframes.length) {
    refBlocks.push(
      el(
        "div",
        {
          className: "ref-row ref-row-keyframes",
          "aria-label": "Selected keyframes",
        },
        [
          el("p", { className: "ref-row-label", text: "Selected keyframes" }),
          ...keyframes,
        ]
      )
    );
  }
  if (intermediates.length) {
    refBlocks.push(
      el(
        "div",
        {
          className: "ref-row ref-row-aux",
          "aria-label": "Debug intermediates",
        },
        intermediates
      )
    );
  }

  const status = sample.status || (refs.length ? "accepted" : "");
  const statusChip =
    status === "rejected"
      ? el("span", {
          className: "chip chip-rejected",
          text: `rejected · ${sample.reason || "unknown"}`,
        })
      : status === "accepted"
        ? el("span", { className: "chip chip-accepted", text: "accepted" })
        : null;

  return el(
    "article",
    {
      className: "sample",
      "data-task": sample.task,
      "data-dataset": sample.dataset || "",
      "data-status": status || "",
    },
    [
    el("div", { className: "media-stack" }, [
      el(
        "div",
        { className: `video-shell${isPortrait ? " is-portrait" : ""}` },
        [
          video,
          el("span", {
            className: "play-hint",
            text: "hover to play · 2.5s preview",
          }),
        ]
      ),
      ...refBlocks,
    ]),
    el("div", { className: "meta" }, [
      el("h2", { text: TASK_LABELS[sample.task] || sample.task }),
      el("div", { className: "chips" }, [
        statusChip,
        el("span", { className: "chip", text: sample.task }),
        el("span", { className: "chip", text: sample.dataset || "unknown" }),
        sample.pipeline
          ? el("span", { className: "chip", text: sample.pipeline })
          : null,
        Array.isArray(sample.hand_objects) && sample.hand_objects.length
          ? el("span", {
              className: "chip",
              text: sample.hand_objects.join(", "),
            })
          : null,
        sample.target?.duration_sec
          ? el("span", {
              className: "chip",
              text: `${sample.target.duration_sec}s · ${sample.target.width}×${sample.target.height}`,
            })
          : null,
        refs.length
          ? el("span", { className: "chip", text: `${refs.length} reference(s)` })
          : el("span", {
              className: "chip",
              text: status === "rejected" ? "no object crop" : "text only",
            }),
      ]),
      el("p", { className: "prompt", text: truncate(sample.prompt) }),
      sample.notes
        ? el("p", { className: "ids", text: sample.notes })
        : null,
      el("p", {
        className: "ids",
        text: `${sample.id}${sample.original_id ? ` · ${sample.original_id}` : ""}`,
      }),
    ]),
  ]
  );
}

function applyFilter(key) {
  for (const button of document.querySelectorAll(".filter")) {
    button.classList.toggle("is-active", button.dataset.task === key);
  }
  for (const card of document.querySelectorAll(".sample")) {
    let show = true;
    if (key === "all") show = true;
    else if (key === "status:accepted") show = card.dataset.status === "accepted";
    else if (key === "status:rejected") show = card.dataset.status === "rejected";
    else show = card.dataset.dataset === key;
    card.classList.toggle("hidden", !show);
  }
}

function buildDatasetFilters(samples) {
  const nav = document.querySelector(".filters");
  if (!nav) return;
  const isEasy = document.body.dataset.pipeline === "easy";
  const datasets = [
    ...new Set(
      samples
        .map((sample) => sample.dataset)
        .filter((name) => typeof name === "string" && name)
    ),
  ].sort();
  const acceptedN = samples.filter((s) => s.status === "accepted").length;
  const rejectedN = samples.filter((s) => s.status === "rejected").length;
  const buttons = [
    el("button", {
      type: "button",
      className: "filter is-active",
      "data-task": "all",
      text: "All",
    }),
  ];
  if (isEasy && (acceptedN || rejectedN)) {
    buttons.push(
      el("button", {
        type: "button",
        className: "filter",
        "data-task": "status:accepted",
        text: `Accepted (${acceptedN})`,
      }),
      el("button", {
        type: "button",
        className: "filter",
        "data-task": "status:rejected",
        text: `Rejected (${rejectedN})`,
      })
    );
  }
  buttons.push(
    ...datasets.map((name) =>
      el("button", {
        type: "button",
        className: "filter",
        "data-task": name,
        text: `${name.replace(/_/g, " ")} (${samples.filter((s) => s.dataset === name).length})`,
      })
    )
  );
  nav.replaceChildren(...buttons);
}

async function main() {
  const body = document.body;
  const catalogUrl = body.dataset.catalog || "./data/catalog.json";
  const pipelineFilter = body.dataset.pipeline || "sam2_qwen_edit_hoi_object";
  const res = await fetch(catalogUrl);
  if (!res.ok) throw new Error(`${catalogUrl} failed: ${res.status}`);
  const catalog = await res.json();
  const source = catalog.source || {};
  const samples = (catalog.samples || []).filter((sample) => {
    if (sample.task !== "multi_imgs_to_v") return false;
    if (pipelineFilter === "all") return true;
    return sample.pipeline === pipelineFilter;
  });

  const caseLabel =
    pipelineFilter === "easy" ? " easy bbox-crop cases" : " HOI object cases";
  const metaChildren = [
    el("span", {}, [
      el("strong", { text: fmt(samples.length) }),
      caseLabel,
    ]),
    el("span", {}, [
      el("strong", { text: fmt(new Set(samples.map((s) => s.dataset)).size) }),
      " sources",
    ]),
    el("span", {}, [
      el(
        "strong",
        {
          text:
            source.run ||
            source.real_multiref_run ||
            (pipelineFilter === "easy" ? "easy" : "hoi-object-pipeline"),
        }
      ),
      " run",
    ]),
  ];
  if (pipelineFilter === "easy" && source.by_status) {
    metaChildren.push(
      el("span", {}, [
        el(
          "strong",
          {
            text: `${source.by_status.accepted || 0}✓ / ${source.by_status.rejected || 0}✗`,
          }
        ),
        " in preview",
      ])
    );
  }
  document.getElementById("hero-meta").replaceChildren(...metaChildren);

  buildDatasetFilters(samples);
  const gallery = document.getElementById("gallery");
  gallery.replaceChildren(...samples.map(renderSample));

  document.querySelector(".filters").addEventListener("click", (event) => {
    const button = event.target.closest(".filter");
    if (!button) return;
    applyFilter(button.dataset.task);
  });
}

main().catch((err) => {
  document.getElementById("gallery").textContent = `Failed to load catalog: ${err}`;
});
