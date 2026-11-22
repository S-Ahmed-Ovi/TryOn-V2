// Small DOM helpers shared by every module.

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

/** h("div", {class: "x", onclick: fn, style: {"--a": 1}}, "text", child) -> element. Text is never parsed as HTML. */
export function h(tag, props = {}, ...children) {
  const svg = tag.startsWith("svg:");
  const el = svg ? document.createElementNS("http://www.w3.org/2000/svg", tag.slice(4)) : document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.setAttribute("class", v);
    else if (k === "style" && typeof v === "object") for (const [p, val] of Object.entries(v)) el.style.setProperty(p, val);
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) if (c != null && c !== false) el.append(c.nodeType ? c : document.createTextNode(String(c)));
  return el;
}

export const clear = (el) => { el.replaceChildren(); return el; };

let toastTimer;
export function toast(message, ms = 4200) {
  const t = $("#toast");
  t.textContent = message;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), ms);
}

/** Soft background colour for a product tile, derived from the frame colour. */
export const tintDark = (hex) => `color-mix(in oklab, ${hex} 26%, #26302b)`;
export const tintLight = (hex) => `color-mix(in oklab, ${hex} 16%, #dfe5db)`;

export const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);
export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
