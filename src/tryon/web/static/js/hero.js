// The rotating frames in the hero.
import { $ } from "./ui.js";
import { loadImage } from "./stage.js";

export function startHero(items, meta) {
  const order = ["wayfarer", "cat-eye", "round", "geometric", "oval"];
  // showcase frames: bold, well-proportioned and colourful rather than thin or grey
  const dull = new Set(["Grey", "Silver", "White", "Charcoal"]);
  const good = (i) => i.audience !== "kids" && i.aspect >= 2.2 && i.aspect <= 3.2 && !dull.has(i.color.name);
  const picks = order.map((shape) => items.find((i) => i.frame_shape === shape && good(i)) || items.find((i) => i.frame_shape === shape && i.audience !== "kids")).filter(Boolean);
  if (!picks.length) return;
  const imgs = [$("#hero-a"), $("#hero-b")];
  const chip = $("#hero-chip");
  const dots = $("#hero-dots");
  dots.replaceChildren(...picks.map(() => document.createElement("span")));

  let i = 0, front = 0;
  const show = async (n, first = false) => {
    const item = picks[n];
    const back = first ? imgs[front] : imgs[1 - front];
    await loadImage(item.cutout);
    back.src = item.cutout;
    if (!first) { imgs[front].classList.remove("is-front"); front = 1 - front; }
    back.classList.add("is-front");
    const spec = meta.frame_shapes.find((f) => f.key === item.frame_shape);
    const best = spec && spec.best_for && spec.best_for[0];
    chip.querySelector(".hero-chip-pct").textContent = best ? `${Math.round(best.score * 98)}%` : "";
    chip.querySelector(".hero-chip-text").replaceChildren(
      Object.assign(document.createElement("b"), { textContent: item.frame_label }),
      document.createTextNode(best ? `for ${best.label} faces` : ""));
    chip.style.visibility = best ? "visible" : "hidden";
    [...dots.children].forEach((d, k) => d.classList.toggle("on", k === n));
  };
  show(0, true);
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  setInterval(() => { if (!document.hidden) { i = (i + 1) % picks.length; show(i); } }, 4600);
}
