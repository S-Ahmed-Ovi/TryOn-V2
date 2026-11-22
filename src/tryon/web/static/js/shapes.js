// Simple outline icons for the five face shapes.
import { h } from "./ui.js";

const PATHS = {
  oval:   "M38 4C58 4 68 26 68 48C68 74 54 92 38 92C22 92 8 74 8 48C8 26 18 4 38 4Z",
  round:  "M38 10C60 10 70 27 70 48C70 69 56 86 38 86C20 86 6 69 6 48C6 27 16 10 38 10Z",
  square: "M14 8H62Q70 8 70 16V58Q70 70 61 78L47 89Q38 94 29 89L15 78Q6 70 6 58V16Q6 8 14 8Z",
  heart:  "M8 20C8 9 20 6 38 6C56 6 68 9 68 20C68 40 58 62 46 80Q38 93 30 80C18 62 8 40 8 20Z",
  oblong: "M18 4H58Q68 4 68 14V64Q68 82 54 90Q38 96 22 90Q8 82 8 64V14Q8 4 18 4Z",
};

export function faceIcon(key) {
  return h("svg:svg", { viewBox: "0 0 76 96", "aria-hidden": "true", fill: "none", stroke: "currentColor", "stroke-width": "2.2", "stroke-linejoin": "round", "stroke-linecap": "round" },
    h("svg:path", { d: PATHS[key] || PATHS.oval }),
    h("svg:path", { d: "M21 42h11M44 42h11", opacity: ".55" }));
}
