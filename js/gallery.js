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

function makeTile({ label, path, media, primary = false, objectName = "" }) {
  const payload = media || {
    path,
    media_type: "image",
    role: label,
  };
  return el(
    "button",
    {
      type: "button",
      className: primary ? "ref-tile is-primary" : "ref-tile",
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
  const isHoi =
    sample.pipeline === "sam2_qwen_edit" ||
    sample.pipeline === "sam2_qwen_edit_hoi_object";

  const primary = [];
  const intermediates = [];

  for (const [index, ref] of refs.entries()) {
    const objectName = ref.name || ref.role || `object ${index + 1}`;
    const viewPaths = Array.isArray(ref.views) ? ref.views.filter(Boolean) : [];
    const selectedCutout = viewPaths[0] || ref.cutout || ref.raw || null;
    const edited =
      ref.edited ||
      (ref.path &&
      ref.path !== ref.raw &&
      ref.path !== selectedCutout &&
      isHoi
        ? ref.path
        : null);

    // Front row: selected cutout → edited output → SAM mask (per object).
    if (selectedCutout) {
      primary.push(
        makeTile({
          label: tileLabel(objectName, "selected cutout", multiObject),
          path: selectedCutout,
          primary: true,
          objectName,
        })
      );
    }
    if (edited) {
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
    }
    if (ref.mask) {
      primary.push(
        makeTile({
          label: tileLabel(objectName, "SAM mask", multiObject),
          path: ref.mask,
          primary: true,
          objectName,
        })
      );
    }

    // Back row: remaining multi-view cutouts / raw crops.
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
    } else if (ref.raw && ref.raw !== selectedCutout && ref.raw !== edited) {
      intermediates.push(
        makeTile({
          label: tileLabel(objectName, "raw crop", multiObject),
          path: ref.raw,
          objectName,
        })
      );
    }
  }

  return { primary, intermediates };
}

function renderSample(sample) {
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
  const { primary, intermediates } = collectReferenceTiles(sample);
  const refBlocks = [];
  if (primary.length) {
    refBlocks.push(
      el(
        "div",
        { className: "ref-row ref-row-primary", "aria-label": "Selected object references" },
        primary
      )
    );
  }
  if (intermediates.length) {
    refBlocks.push(
      el(
        "div",
        {
          className: "ref-row ref-row-aux",
          "aria-label": "Intermediate cutouts",
        },
        intermediates
      )
    );
  }

  return el("article", { className: "sample", "data-task": sample.task }, [
    el("div", { className: "media-stack" }, [
      el("div", { className: "video-shell" }, [
        video,
        el("span", { className: "play-hint", text: "hover to play · 2.5s preview" }),
      ]),
      ...refBlocks,
    ]),
    el("div", { className: "meta" }, [
      el("h2", { text: TASK_LABELS[sample.task] || sample.task }),
      el("div", { className: "chips" }, [
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
          : el("span", { className: "chip", text: "text only" }),
      ]),
      el("p", { className: "prompt", text: truncate(sample.prompt) }),
      el("p", {
        className: "ids",
        text: `${sample.id}${sample.original_id ? ` · ${sample.original_id}` : ""}`,
      }),
    ]),
  ]);
}

function applyFilter(task) {
  for (const button of document.querySelectorAll(".filter")) {
    button.classList.toggle("is-active", button.dataset.task === task);
  }
  for (const card of document.querySelectorAll(".sample")) {
    const show = task === "all" || card.dataset.task === task;
    card.classList.toggle("hidden", !show);
  }
}

async function main() {
  const res = await fetch("./data/catalog.json");
  if (!res.ok) throw new Error(`catalog.json failed: ${res.status}`);
  const catalog = await res.json();
  const source = catalog.source || {};

  document.getElementById("hero-meta").replaceChildren(
    el("span", {}, [
      el("strong", { text: fmt(catalog.sample_count) }),
      " shown here",
    ]),
    el("span", {}, [
      el("strong", { text: fmt(source.records_omni || 0) }),
      " omni_v3 rows",
    ]),
    el("span", {}, [
      el("strong", { text: fmt(source.records_aux || 0) }),
      " aux rows",
    ]),
    el("span", {}, [
      el("strong", { text: fmt(source.rejected_zero_byte || 0) }),
      " zero-byte rejects",
    ])
  );

  const gallery = document.getElementById("gallery");
  gallery.replaceChildren(...(catalog.samples || []).map(renderSample));

  document.querySelector(".filters").addEventListener("click", (event) => {
    const button = event.target.closest(".filter");
    if (!button) return;
    applyFilter(button.dataset.task);
  });
}

main().catch((err) => {
  document.getElementById("gallery").textContent = `Failed to load catalog: ${err}`;
});
