// Page controller: wires the fitting room together (photo -> analysis -> results -> try-on).
import { api } from "./api.js";
import { Camera, cameraSupported } from "./camera.js";
import { Collection } from "./collection.js";
import { markGuide, renderGuide, renderShapePicker } from "./guide.js";
import { startHero } from "./hero.js";
import { LiveTryOn } from "./live3d.js";
import { loadModel, preloadModel } from "./models.js";
import { prepareFile } from "./photo.js";
import { markSelected, renderFilters, renderRecs, renderShowcase, renderVerdict } from "./results.js";
import { TryOnStage } from "./stage.js";
import { $, $$, clear, h, sleep, toast } from "./ui.js";

const S = {
  meta: null, items: [], mode: "intake",              // intake | photo | shape
  photo: null, face: null, placement: null, pose3d: null, issues: [],
  view: "2d", live: false,                              // try-on style: "2d" | "3d"; live = the live 3D camera is on
  shape: null, overridden: false, audience: "all", style: null,
  recs: null, selectedSku: null, visible: 8,
};
const studio = $("#studio");
const camera = new Camera($("#cam-video"));
const stage = new TryOnStage($("#stage-canvas"), { onAdjust: syncControls });
const live = new LiveTryOn($("#live-canvas"), { onStatus: onLiveStatus });
const FACE_CM = 14.4;                                 // typical face width: turns the Height slider (in face widths) into centimetres
let collection = null;
let pending = null;                                   // AbortController of the latest recommendation request

// ── panels & notes ─────────────────────────────────────────────────────────
function setPanel(name) {
  studio.dataset.state = name;
  $$("[data-panel]").forEach((p) => (p.hidden = p.dataset.panel !== name));
}
function showNotes(notes, tone = "") {
  const box = $("#status");
  clear(box);
  notes.forEach((n) => box.append(h("p", { class: `note ${tone}` }, typeof n === "string" ? n : n.message)));
  box.hidden = !notes.length;
}
const scrollToStudio = (target = studio) => target.scrollIntoView({ behavior: "smooth", block: "start" });

// ── photo in ───────────────────────────────────────────────────────────────
async function handleFile(file) {
  if (!file) return;
  try {
    scrollToStudio();
    await analyze(await prepareFile(file));
  } catch (err) {
    toast(err.message);
    setPanel("intake");
  }
}

const SCAN_TEXTS = ["Mapping 478 points on your face…", "Measuring length, cheekbones and jaw…", "Matching frames to your face…"];

function drawScan(canvas) {
  const c = $("#scan-canvas");
  c.width = 400; c.height = 500;
  const ctx = c.getContext("2d");
  const s = Math.max(400 / canvas.width, 500 / canvas.height);
  ctx.drawImage(canvas, (400 - canvas.width * s) / 2, (500 - canvas.height * s) / 2, canvas.width * s, canvas.height * s);
  requestAnimationFrame(() => $(".scan-card").style.setProperty("--scan-h", `${$(".scan-card").clientHeight - 90}px`));
}

async function analyze({ canvas, blob }) {
  stopLive();
  camera.stop();
  S.photo = canvas;
  showNotes([]);
  setPanel("analyzing");
  drawScan(canvas);
  scrollToStudio($(".panel-analyzing"));
  let t = 0;
  const ticker = setInterval(() => { $("#scan-text").textContent = SCAN_TEXTS[++t % SCAN_TEXTS.length]; }, 1000);
  const started = performance.now();
  let res;
  try {
    res = await api.analyze(blob, S.audience);
    await sleep(Math.max(0, 1500 - (performance.now() - started)));      // let the scan finish; it reads as "working"
  } catch (err) {
    clearInterval(ticker);
    toast(err.message);
    setPanel("intake");
    return;
  }
  clearInterval(ticker);
  if (res.status === "reject") {
    setPanel("intake");
    showNotes(res.issues, "bad");
    return;
  }
  Object.assign(S, { mode: "photo", face: res.face, placement: res.placement, pose3d: res.pose3d || null, issues: res.issues, shape: res.face.shape, overridden: false,
    recs: res.recommendations, style: null, visible: 8, selectedSku: res.recommendations.items[0]?.sku ?? null });
  showResults(true);
}

// ── results ────────────────────────────────────────────────────────────────
function showResults(fresh) {
  setPanel("results");
  $(".fit").classList.toggle("no-photo", S.mode === "shape");
  $("#showcase").hidden = S.mode !== "shape";
  if (S.mode === "photo" && fresh) {
    stopLive();
    S.view = "2d";
    stage.siteName = S.meta.site_name;
    live.siteName = S.meta.site_name;
    stage.setPhoto(S.photo, S.placement, S.face.face_box, S.face.guide_points, S.pose3d);
    $("#stage-hint").classList.remove("gone");
    $("#btn-measure").setAttribute("aria-pressed", "false");
    stage.toggleMeasurements(false);
    syncControls();
  }
  syncMode();
  renderAll();
  applySelection();
  if (!S.style && collection) collection.setMatches(S.recs.items);
  markGuide(S.shape);
  scrollToStudio($(".fit"));
}

function renderAll() {
  renderVerdict($("#verdict"), S, { onShape: chooseShape, onResetShape: () => chooseShape(S.face.shape) });
  renderFilters($("#filters"), S, { onAudience: (a) => { S.audience = a; refetch(); }, onStyle: (st) => { S.style = st; refetch(); } });
  renderRecs($("#recs"), $("#btn-more"), S, {
    onSelect: (sku) => { S.selectedSku = sku; applySelection(); if (innerWidth <= 960 && S.mode === "photo") $("#stage").scrollIntoView({ behavior: "smooth", block: "center" }); },
    onMore: () => { S.visible += 8; renderRecs($("#recs"), $("#btn-more"), S, handlersFor()); },
  });
}
const handlersFor = () => ({
  onSelect: (sku) => { S.selectedSku = sku; applySelection(); },
  onMore: () => { S.visible += 8; renderRecs($("#recs"), $("#btn-more"), S, handlersFor()); },
});

function applySelection() {
  const item = S.recs.items.find((i) => i.sku === S.selectedSku);
  markSelected($("#recs"), S);
  if (!item) return;
  if (S.mode === "photo") {
    stage.resetAdjustments(false);
    syncControls();
    busy(stage.setProduct(item));
    if (S.live) startLiveModel(item);
    if (S.view === "3d" || S.live) {                                // fetch the next frames' models while the person looks at this one
      const i = S.recs.items.indexOf(item);
      S.recs.items.slice(i + 1, i + 3).forEach((n) => preloadModel(n.model));
    }
  } else renderShowcase($("#showcase-img"), item);
}

async function refetch() {
  if (pending) pending.abort();
  pending = new AbortController();
  const f = S.face;
  const body = {
    shape: S.shape, overridden: S.overridden || !f, audience: S.audience, frame_shapes: S.style ? [S.style] : [],
    probabilities: f ? Object.fromEntries(f.probabilities.map((p) => [p.shape, p.p])) : null,
    measurements: f ? f.measurements : null,
  };
  try {
    S.recs = await api.recommend(body, pending.signal);
  } catch (err) {
    if (err.name !== "AbortError") toast(err.message);
    return;
  }
  S.visible = 8;
  if (!S.recs.items.some((i) => i.sku === S.selectedSku)) S.selectedSku = S.recs.items[0]?.sku ?? null;
  renderAll();
  applySelection();
  if (!S.style && collection) collection.setMatches(S.recs.items);
}

function chooseShape(key) {
  S.shape = key;
  S.overridden = S.face ? key !== S.face.shape : true;
  markGuide(key);
  return refetch();
}

// ── try-on controls ────────────────────────────────────────────────────────
function syncControls() {
  $("#ctl-size").value = Math.round(stage.fit * 100);
  $("#ctl-lift").value = Math.round(stage.lift * 100);
  $("#stage-hint").classList.add("gone");
  live.setAdjust(liveAdjust());
}
const liveAdjust = () => ({ size: stage.fit, lift: -stage.lift * FACE_CM, shift: 0 });
$("#ctl-size").addEventListener("input", (e) => { stage.set({ fit: e.target.value / 100 }); live.setAdjust(liveAdjust()); });
$("#ctl-lift").addEventListener("input", (e) => { stage.set({ lift: e.target.value / 100 }); live.setAdjust(liveAdjust()); });
$("#btn-reset").addEventListener("click", () => { stage.resetAdjustments(); syncControls(); });

// A small spinner on the stage while a frame or 3D model is loading.
function busy(promise) {
  const el = $("#stage");
  el.classList.add("is-busy");
  return Promise.resolve(promise).catch((err) => toast(err.message)).finally(() => el.classList.remove("is-busy"));
}

// ── Quick 2D / Real 3D ─────────────────────────────────────────────────────
const modeSeg = $("#mode-seg");
const liveBtn = $("#btn-live");
const liveAvailable = () => S.mode === "photo" && !!S.meta?.live_camera && cameraSupported();

function syncMode() {
  const has3d = S.mode === "photo" && stage.has3d;
  for (const b of modeSeg.querySelectorAll("button")) {
    if (b.dataset.mode === "3d") b.disabled = !has3d;
    b.setAttribute("aria-pressed", String(b.dataset.mode === S.view));
  }
  $("#mode-note").textContent = !has3d ? "Real 3D needs a clearer, straight-on photo."
    : S.view === "3d" ? "A real 3D model drawn on your photo, no graphics card needed." : "";
  liveBtn.hidden = !liveAvailable();
  liveBtn.querySelector("span").textContent = S.live ? "Back to photo" : "Live 3D camera";
}

async function setView(view) {
  if (S.live) stopLive();
  if (view === S.view) return;
  if (view === "3d" && !stage.has3d) return;
  S.view = view;
  syncMode();
  const ok = await busy(stage.setMode(view));
  if (ok === false) { S.view = "2d"; syncMode(); }
  else if (S.view === "3d" && S.recs) S.recs.items.slice(0, 3).forEach((n) => preloadModel(n.model));
  if (S.view !== view) syncMode();
}
modeSeg.addEventListener("click", (e) => {
  const b = e.target.closest("button[data-mode]");
  if (b && !b.disabled) setView(b.dataset.mode);
});

// ── live 3D camera ─────────────────────────────────────────────────────────
function onLiveStatus(state) {
  const hint = $("#live-hint");
  const texts = { starting: "Starting the camera…", no_face: "Look at the camera", unusable: "Turn your face towards the camera" };
  hint.hidden = !(state in texts);
  hint.textContent = texts[state] || "";
  if (state === "error") { toast("The live camera stopped. You can start it again."); stopLive(); }
}

async function startLiveModel(item) {
  try {
    const model = await loadModel(item.model);
    if (S.live && item.sku === S.selectedSku) live.setModel(model);
  } catch (err) { toast(err.message); }
}

async function startLive() {
  const item = S.recs?.items.find((i) => i.sku === S.selectedSku);
  if (!item) return;
  S.live = true;
  const stageEl = $("#stage");
  stageEl.dataset.live = "on";
  $("#live-canvas").hidden = false;
  syncMode();
  live.setAdjust(liveAdjust());
  try {
    live.setModel(await loadModel(item.model));
    await live.start();
  } catch (err) {
    toast(err.message);
    stopLive();
    return;
  }
  scrollToStudio($(".fit"));
}

function stopLive() {
  if (!S.live && $("#stage").dataset.live !== "on") return;
  live.stop();
  S.live = false;
  $("#stage").dataset.live = "off";
  $("#live-canvas").hidden = true;
  $("#live-hint").hidden = true;
  syncMode();
}
liveBtn.addEventListener("click", () => (S.live ? stopLive() : startLive()));
document.addEventListener("visibilitychange", () => { if (document.hidden && S.live) stopLive(); });
const compare = $("#btn-compare");
for (const [down, up] of [["pointerdown", ["pointerup", "pointerleave", "pointercancel"]]]) {
  compare.addEventListener(down, () => stage.set({ showOriginal: true }));
  up.forEach((ev) => compare.addEventListener(ev, () => stage.set({ showOriginal: false })));
}
compare.addEventListener("keydown", (e) => { if (e.key === " " || e.key === "Enter") { stage.set({ showOriginal: true }); e.preventDefault(); } });
compare.addEventListener("keyup", () => stage.set({ showOriginal: false }));
$("#btn-measure").addEventListener("click", (e) => {
  const on = e.currentTarget.getAttribute("aria-pressed") !== "true";
  e.currentTarget.setAttribute("aria-pressed", String(on));
  e.currentTarget.textContent = on ? "Hide measurements" : "Show measurements";
  stage.toggleMeasurements(on);
});
$("#btn-download").addEventListener("click", async () => {
  const blob = await (S.live ? live.snapshot() : stage.toBlob());
  const a = h("a", { href: URL.createObjectURL(blob), download: `${S.meta.site_name.toLowerCase()}-${S.selectedSku || "look"}.jpg` });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 4000);
});

// ── camera ─────────────────────────────────────────────────────────────────
async function openCamera() {
  stopLive();
  scrollToStudio();
  showNotes([]);
  if (!cameraSupported()) { $("#file-capture").click(); return; }    // phone over plain http: use the camera app instead
  setPanel("camera");
  scrollToStudio($(".panel-camera"));
  try {
    $("#cam-flip").hidden = !(await camera.start("user"));
  } catch (err) {
    toast(err.message);
    setPanel("intake");
  }
}
$("#shutter").addEventListener("click", async (e) => {
  const btn = e.currentTarget, count = $("#cam-count");
  btn.disabled = true;
  for (const n of [3, 2, 1]) { count.textContent = n; count.hidden = false; await sleep(850); }
  count.hidden = true;
  $("#cam-flash").classList.remove("on"); void $("#cam-flash").offsetWidth; $("#cam-flash").classList.add("on");
  try { await analyze(await camera.capture()); } catch (err) { toast(err.message); setPanel("intake"); }
  btn.disabled = false;
});

// ── actions & inputs ───────────────────────────────────────────────────────
function restart() {
  stopLive();
  camera.stop();
  if (pending) pending.abort();
  Object.assign(S, { mode: "intake", photo: null, face: null, placement: null, pose3d: null, view: "2d", issues: [], recs: null, selectedSku: null, style: null, overridden: false, shape: null, audience: "all" });
  if (collection) collection.setMatches(null);
  markGuide(null);
  showNotes([]);
  setPanel("intake");
  scrollToStudio();
}

async function chooseShapeNoPhoto(key) {
  stopLive();
  Object.assign(S, { mode: "shape", face: null, placement: null, pose3d: null, view: "2d", issues: [], shape: key, overridden: true, style: null, visible: 8 });
  await refetch();
  if (!S.recs) return;
  S.selectedSku = S.recs.items[0]?.sku ?? null;
  showResults(false);
}

const actions = {
  upload: () => { scrollToStudio(); $("#file").click(); },
  camera: openCamera,
  "camera-cancel": () => { camera.stop(); setPanel("intake"); },
  "camera-flip": () => camera.flip().catch((e) => toast(e.message)),
  restart,
  "pick-shape": () => { renderShapePicker(S.meta, chooseShapeNoPhoto); setPanel("shape"); },
};
document.addEventListener("click", (e) => {
  const el = e.target.closest("[data-action]");
  if (!el || !actions[el.dataset.action]) return;
  e.preventDefault();
  actions[el.dataset.action]();
});

$("#file").addEventListener("change", (e) => { handleFile(e.target.files[0]); e.target.value = ""; });
$("#file-capture").addEventListener("change", (e) => { handleFile(e.target.files[0]); e.target.value = ""; });
const drop = $("#drop");
drop.addEventListener("click", () => $("#file").click());
drop.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); $("#file").click(); } });
for (const ev of ["dragenter", "dragover"]) studio.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); });
for (const ev of ["dragleave", "drop"]) studio.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); });
studio.addEventListener("drop", (e) => handleFile(e.dataTransfer.files[0]));
document.addEventListener("paste", (e) => {
  const f = [...(e.clipboardData?.files || [])].find((x) => x.type.startsWith("image/"));
  if (f) handleFile(f);
});
addEventListener("scroll", () => $("#nav").classList.toggle("scrolled", scrollY > 8), { passive: true });

// ── boot ───────────────────────────────────────────────────────────────────
async function tryFromCollection(product) {
  if (!S.recs) { scrollToStudio(); drop.classList.add("over"); setTimeout(() => drop.classList.remove("over"), 1600); return; }
  S.style = null;
  S.audience = product.audience === "kids" ? "kids" : S.audience === "kids" ? "all" : S.audience;
  await refetch();
  if (S.recs.items.some((i) => i.sku === product.sku)) { S.selectedSku = product.sku; applySelection(); }
  scrollToStudio();
}

async function init() {
  try {
    const [meta, cat] = await Promise.all([api.meta(), api.catalog()]);
    S.meta = meta; S.items = cat.items;
  } catch (err) {
    showNotes([err.message], "bad");
    return;
  }
  $("#stat-count").textContent = S.meta.product_count;
  startHero(S.items, S.meta);
  collection = new Collection(S.meta, S.items, { onTry: tryFromCollection });
  renderGuide(S.meta, (key) => {
    if (S.mode === "photo") { chooseShape(key); scrollToStudio(); } else chooseShapeNoPhoto(key);
  });
  setPanel("intake");
  $("#nav").classList.toggle("scrolled", scrollY > 8);
}
init();
