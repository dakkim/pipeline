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
  const refTiles = [];
  for (const [index, ref] of refs.entries()) {
    const variants = [];
    if (ref.raw) variants.push({ label: "raw crop", path: ref.raw });
    if (ref.mask) variants.push({ label: "SAM mask", path: ref.mask });
    if (ref.edited || (ref.path && sample.pipeline === "sam2_qwen_edit")) {
      variants.push({ label: "Qwen edit", path: ref.edited || ref.path });
    } else if (ref.path) {
      variants.push({
        label: ref.media_type === "video" ? "source" : "ref",
        path: ref.media_type === "video" ? ref.poster || ref.path : ref.path,
        media: ref,
      });
    }
    for (const variant of variants) {
      const media = variant.media || {
        path: variant.path,
        media_type: "image",
        role: `${ref.role || "ref"}/${variant.label}`,
      };
      refTiles.push(
        el(
          "button",
          {
            type: "button",
            title: `${ref.name || ref.role || "ref"} · ${variant.label}`,
            onClick: () => openLightbox(media),
          },
          [
            el("img", {
              src: variant.path,
              alt: `${ref.role || "reference"} ${index + 1} ${variant.label}`,
            }),
            el("span", { className: "ref-caption", text: variant.label }),
          ]
        )
      );
    }
  }
  const refRow =
    refTiles.length === 0
      ? null
      : el("div", { className: "ref-row", "aria-label": "Condition references" }, refTiles);

  return el("article", { className: "sample", "data-task": sample.task }, [
    el("div", { className: "media-stack" }, [
      el("div", { className: "video-shell" }, [
        video,
        el("span", { className: "play-hint", text: "hover to play · 2.5s preview" }),
      ]),
      refRow,
    ]),
    el("div", { className: "meta" }, [
      el("h2", { text: TASK_LABELS[sample.task] || sample.task }),
      el("div", { className: "chips" }, [
        el("span", { className: "chip", text: sample.task }),
        el("span", { className: "chip", text: sample.dataset || "unknown" }),
        sample.pipeline
          ? el("span", { className: "chip", text: sample.pipeline })
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
