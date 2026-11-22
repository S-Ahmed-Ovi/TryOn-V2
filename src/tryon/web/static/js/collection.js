// The full collection grid with filters, and the quick-view dialog.
import { $, clear, h, tintLight } from "./ui.js";
import { specs } from "./results.js";

const PAGE = 16;

export class Collection {
  constructor(meta, items, { onTry }) {
    this.meta = meta;
    this.items = items;
    this.onTry = onTry;
    this.f = { audience: "all", style: null, color: null };
    this.visible = PAGE;
    this.matches = null;          // sku -> match item, once a face is known
    $("#quick-x").onclick = () => $("#quick").close();
    $("#quick").addEventListener("click", (e) => { if (e.target.id === "quick") e.target.close(); });
    this.renderFilters();
    this.renderGrid();
  }

  setMatches(items) {
    this.matches = items ? new Map(items.map((i) => [i.sku, i])) : null;
    this.renderGrid();
  }

  filtered() {
    const { audience, style, color } = this.f;
    let list = this.items.filter((p) =>
      (audience === "all" ? p.audience !== "kids" : audience === "kids" ? p.audience === "kids" : p.audience === audience || p.audience === "unisex")
      && (!style || p.frame_shape === style) && (!color || p.color.name === color));
    if (this.matches) list = [...list].sort((a, b) => (this.matches.get(b.sku)?.match.percent ?? 0) - (this.matches.get(a.sku)?.match.percent ?? 0));
    return list;
  }

  renderFilters() {
    const root = $("#coll-filters");
    clear(root);
    const set = (key, value) => { this.f[key] = this.f[key] === value && key !== "audience" ? null : value; this.visible = PAGE; this.renderFilters(); this.renderGrid(); };
    const kids = (this.meta.audiences.kids || 0) > 0;
    root.append(
      h("div", { class: "group" }, h("div", { class: "seg", role: "group", "aria-label": "For" },
        [["all", "All"], ["women", "Women"], ["men", "Men"], ["kids", "Kids"]].filter(([k]) => k !== "kids" || kids).map(([k, l]) =>
          h("button", { "aria-pressed": String(this.f.audience === k), onclick: () => set("audience", k) }, l)))),
      h("div", { class: "group" }, h("span", { class: "label" }, "Style"),
        this.meta.frame_shapes.filter((s) => s.count).map((s) => h("button", { class: "chip", "aria-pressed": String(this.f.style === s.key), onclick: () => set("style", s.key) }, s.label, h("i", {}, s.count)))),
      h("div", { class: "group" }, h("span", { class: "label" }, "Colour"),
        this.meta.colors.slice(0, 8).map((c) => h("button", { class: "chip", "aria-pressed": String(this.f.color === c.name), onclick: () => set("color", c.name) }, h("span", { class: "swatch", style: { "--c": c.hex } }), c.name))));
  }

  renderGrid() {
    const grid = $("#grid");
    const list = this.filtered();
    $("#collection-count").textContent = `${list.length} ${list.length === 1 ? "frame" : "frames"}${this.matches ? " · sorted by your match" : ""}`;
    clear(grid);
    this.renderMore(list.length);
    if (!list.length) { grid.append(h("p", { class: "empty", style: { "grid-column": "1/-1", color: "var(--mute)" } }, "No frames match these filters.")); return; }
    for (const p of list.slice(0, this.visible)) {
      const m = this.matches && this.matches.get(p.sku);
      grid.append(h("button", { class: "tile", onclick: () => this.open(p), "aria-label": `${p.name}, ${p.frame_label}${m ? `, ${m.match.percent} percent match` : ""}` },
        h("span", { class: "tile-img", style: { "--tint": tintLight(p.color.hex) } },
          h("img", { src: p.thumb, alt: "", loading: "lazy", decoding: "async", width: 480, height: 180 }),
          m ? h("span", { class: "tile-pct" }, `${m.match.percent}% match`) : null),
        h("span", { class: "tile-body" }, h("span", { class: "tile-name" }, p.name),
          h("span", { class: "tile-meta" }, p.frame_label, h("span", { class: "swatch", style: { "--c": p.color.hex } }), p.color.name))));
    }
  }

  renderMore(total) {
    const old = $("#coll-more");
    if (old) old.remove();
    if (this.visible >= total) return;
    $("#grid").after(h("button", { class: "btn btn-ghost coll-more", id: "coll-more", onclick: () => { this.visible += PAGE; this.renderGrid(); } },
      `Show more frames (${total - this.visible} left)`));
  }

  open(p) {
    const m = this.matches && this.matches.get(p.sku);
    $("#quick-img").replaceChildren(h("img", { src: p.cutout, alt: p.name }));
    $("#quick-img").style.setProperty("--tint", tintLight(p.color.hex));
    $("#quick-body").replaceChildren(
      h("p", { class: "eyebrow" }, p.frame_label, " frame"),
      h("h3", { id: "quick-title" }, p.name),
      h("p", { class: "meta" }, h("span", {}, h("span", { class: "swatch", style: { "--c": p.color.hex } }), " ", p.color.name), h("span", {}, p.sku)),
      h("p", { class: "meta" }, h("span", {}, specs(p))),
      m ? h("p", { class: "why" }, h("b", {}, `${m.match.percent}% match for you. `), m.reasons[0] || "") : h("p", { class: "why" }, "Add a photo and we'll show how well this frame suits your face, and put it on you."),
      h("div", { class: "quick-actions" },
        h("button", { class: "btn btn-primary", onclick: () => { $("#quick").close(); this.onTry(p); } }, m ? "Try it on" : "Find my match"),
        h("button", { class: "btn btn-ghost", onclick: () => $("#quick").close() }, "Close")));
    $("#quick").showModal();
  }
}
