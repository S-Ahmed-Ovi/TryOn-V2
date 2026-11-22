// Face shape guide cards.
import { $, clear, h } from "./ui.js";
import { faceIcon } from "./shapes.js";

export function renderGuide(meta, onChoose) {
  const root = $("#shape-cards");
  clear(root);
  for (const f of meta.face_shapes) {
    root.append(h("article", { class: "shape-card", "data-shape": f.key },
      faceIcon(f.key),
      h("h3", {}, f.label),
      h("p", { class: "sum" }, f.summary),
      h("dl", {},
        h("div", {}, h("dt", {}, "Best frames"), h("dd", {}, f.best.map((b) => b.label).join(", ") || "Most styles")),
        f.avoid.length ? h("div", {}, h("dt", {}, "Go easy on"), h("dd", {}, f.avoid.map((b) => b.label).join(", "))) : null),
      h("button", { class: "btn btn-ghost btn-sm", onclick: () => onChoose(f.key) }, `See ${f.label.toLowerCase()} matches`)));
  }
}

export function markGuide(shape) {
  document.querySelectorAll(".shape-card").forEach((c) => c.classList.toggle("current", c.dataset.shape === shape));
}

export function renderShapePicker(meta, onChoose) {
  const root = $("#shape-pick-grid");
  clear(root);
  for (const f of meta.face_shapes) {
    root.append(h("button", { class: "shape-opt", onclick: () => onChoose(f.key) },
      faceIcon(f.key), h("span", {}, f.label), h("small", {}, f.summary.split(",")[0].replace(/\.$/, ""))));
  }
}
