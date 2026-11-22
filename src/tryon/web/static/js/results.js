// Rendering of the result panel: face verdict, filters and the recommendation cards.
import { cap, clear, h, tintLight } from "./ui.js";
import { faceIcon } from "./shapes.js";

// ── verdict ────────────────────────────────────────────────────────────────
export function renderVerdict(el, s, { onShape, onResetShape }) {
  const spec = s.meta.face_shapes.find((f) => f.key === s.shape);
  const face = s.face;
  const detected = face && s.meta.face_shapes.find((f) => f.key === face.shape);
  clear(el);

  let chip;
  if (!face) chip = h("span", { class: "conf" }, "Your choice");
  else if (s.overridden) chip = h("span", { class: "conf" }, "Your choice");
  else {
    const top = face.probabilities.find((x) => x.shape === face.shape);
    const pct = Math.round((top ? top.p : face.confidence) * 100);
    chip = face.needs_confirmation ? h("span", { class: "conf low" }, `Best guess · ${pct}%`) : h("span", { class: "conf high" }, `Strong read · ${pct}%`);
  }

  const pills = h("div", { class: "pills", role: "radiogroup", "aria-label": "Face shape" },
    s.meta.face_shapes.map((f) => {
      const p = face && face.probabilities.find((x) => x.shape === f.key);
      return h("button", { class: "pill", role: "radio", "aria-checked": String(f.key === s.shape), onclick: () => onShape(f.key) },
        f.label, p && p.p >= 0.05 ? h("small", {}, `${Math.round(p.p * 100)}%`) : null);
    }));

  let note;
  if (face && s.overridden) {
    note = h("p", { class: "pills-note" }, `You chose ${spec.label}; we measured ${detected.label}. `,
      h("button", { class: "link", onclick: onResetShape }, `Use ${detected.label} again`));
  } else if (face && face.needs_confirmation) {
    note = h("p", { class: "pills-note" }, "We're not fully sure. Tap the shape that looks most like yours and your matches update.");
  } else {
    note = h("p", { class: "pills-note" }, face ? "Not quite you? Tap another shape and your matches update." : "Tap another shape to compare.");
  }

  el.append(
    h("p", { class: "eyebrow on-dark" }, face ? "Your face shape" : "Your chosen face shape"),
    h("div", { class: "verdict-top" }, h("h3", { class: "shape-name" }, spec.label, " ", h("em", {}, "face")), chip),
    h("p", { class: "verdict-sum" }, spec.summary),
    h("p", { class: "verdict-principle" }, h("b", {}, "The idea: "), spec.principle),
    ...(s.issues || []).map((i) => h("p", { class: `note ${i.level === "reject" ? "bad" : ""}` }, i.message)),
    pills, note,
  );

  if (face && face.traits) {
    el.append(h("details", { class: "traits", open: true },
      h("summary", {}, "Your proportions"),
      h("div", { class: "gauges" }, face.traits.map((t) => {
        const marker = h("i", { style: { "--pos": "50%" } });
        requestAnimationFrame(() => requestAnimationFrame(() => marker.style.setProperty("--pos", `${t.position * 100}%`)));
        return h("div", { class: "gauge" },
          h("div", { class: "gauge-top" }, h("span", {}, t.label), h("b", {}, t.value)),
          h("div", { class: "gauge-bar" }, marker), h("p", {}, t.note));
      }))));
  }
}

// ── filters ────────────────────────────────────────────────────────────────
const AUDIENCE_LABELS = [["all", "All"], ["women", "Women"], ["men", "Men"], ["kids", "Kids"]];

export function renderFilters(el, s, { onAudience, onStyle }) {
  clear(el);
  const r = s.recs;
  const showKids = (s.meta.audiences.kids || 0) > 0;
  el.append(
    h("div", { class: "filters-row" },
      h("h4", {}, "Your matches"),
      h("div", { class: "seg", role: "group", "aria-label": "Show frames for" },
        AUDIENCE_LABELS.filter(([k]) => k !== "kids" || showKids).map(([k, label]) =>
          h("button", { "aria-pressed": String(s.audience === k), onclick: () => onAudience(k) }, label)))),
    h("div", { class: "chips", role: "group", "aria-label": "Frame style" },
      h("button", { class: "chip", "aria-pressed": String(!s.style), onclick: () => onStyle(null) }, "All styles"),
      r.styles.map((st) => h("button", { class: "chip", "aria-pressed": String(s.style === st.shape), onclick: () => onStyle(st.shape) },
        st.label, h("i", {}, `${st.best_percent}%`)))),
  );
}

// ── recommendation cards ───────────────────────────────────────────────────
function ring(pct) {
  const tone = pct >= 85 ? "" : pct >= 70 ? " mid" : " low";
  const el = h("div", { class: `ring${tone}`, style: { "--p": 0 }, "aria-label": `${pct} percent match` },
    h("svg:svg", { viewBox: "0 0 40 40", "aria-hidden": "true" },
      h("svg:circle", { class: "track", cx: 20, cy: 20, r: 16 }), h("svg:circle", { class: "bar", cx: 20, cy: 20, r: 16, pathLength: 100.5 })),
    h("b", {}, String(pct), h("small", {}, "%")));
  requestAnimationFrame(() => requestAnimationFrame(() => el.style.setProperty("--p", pct)));
  return el;
}

/** "134 mm wide · Acetate · G-15 green lenses" */
export function specs(item) {
  const parts = [];
  if (item.size && item.size.frame_width_mm) parts.push(`${Math.round(item.size.frame_width_mm)} mm wide`);
  if (item.material) parts.push(cap(item.material));
  if (item.lens) parts.push(`${item.lens.name} lenses`);
  return parts.join(" · ");
}

function detail(item) {
  const b = item.breakdown;
  const bar = (label, value) => h("div", {},
    h("div", { class: "bar-top" }, h("span", {}, label), h("b", {}, `${value}%`)),
    h("div", { class: "bar-track" }, h("i", { style: { "--w": `${value}%` } })));
  return h("div", { class: "rec-detail" },
    h("h5", {}, "Why it works for you"),
    h("ul", { class: "reasons" }, item.reasons.map((r) => h("li", {}, r))),
    h("div", { class: "bars" }, bar("Shape harmony", b.shape), b.proportion != null ? bar("Proportions", b.proportion) : null),
    h("div", { class: "rec-links" },
      h("span", { class: "sku" }, item.sku),
      h("span", { class: "rec-specs" }, specs(item))));
}

export function renderRecs(list, moreBtn, s, { onSelect, onMore }) {
  clear(list);
  const items = s.recs.items;
  if (!items.length) {
    list.append(h("li", { class: "empty" }, "No frames match those filters. Try another style or audience."));
    moreBtn.hidden = true;
    return;
  }
  items.slice(0, s.visible).forEach((item, i) => {
    const li = h("li", { class: "rec", "data-sku": item.sku, style: { "animation-delay": `${Math.min(i, 8) * 40}ms` } },
      h("button", { class: "rec-main", onclick: () => onSelect(item.sku), "aria-label": `${item.name}, ${item.match.percent} percent match` },
        h("span", { class: "rec-thumb", style: { "--tint": tintLight(item.color.hex) } }, h("img", { src: item.thumb, alt: "", loading: "lazy", width: 240, height: 90 })),
        h("span", { class: "rec-info" },
          item.match.top_pick ? h("span", { class: "rec-top" }, "Top pick") : null,
          h("span", { class: "rec-name" }, item.name),
          h("span", { class: "rec-meta" }, item.frame_label, h("span", { class: "swatch", style: { "--c": item.color.hex } }), item.color.name)),
        h("span", { class: "rec-score" }, ring(item.match.percent), h("span", { class: "rec-label" }, item.match.label.replace(" match", "")))));
    list.append(li);
  });
  moreBtn.hidden = s.visible >= items.length;
  moreBtn.onclick = onMore;
  markSelected(list, s);
}

/** Highlight the selected card and show its explanation (only the selected one carries the detail). */
export function markSelected(list, s) {
  const items = new Map(s.recs.items.map((i) => [i.sku, i]));
  for (const li of list.querySelectorAll(".rec")) {
    const on = li.dataset.sku === s.selectedSku;
    li.setAttribute("aria-current", String(on));
    const existing = li.querySelector(".rec-detail");
    if (on && !existing) li.append(detail(items.get(li.dataset.sku)));
    if (!on && existing) existing.remove();
  }
}

export function renderShowcase(el, item) {
  clear(el);
  if (!item) return;
  el.append(h("img", { src: item.cutout, alt: item.name }));
  el.style.setProperty("--tint", tintLight(item.color.hex));
}

export { cap, faceIcon };
