"""
Builds review/review.html : one page with every sunglasses product (SKU starting with DKS).
For each product you can (1) fix the frame shape, (2) pick the best FRONT-VIEW image for virtual try-on.
Open the HTML in your browser (Chrome/Edge). Progress is saved automatically in the browser; press
"Download results" when done -> review/review_results.json , then run  python apply_review.py

    python review_tool.py            # reads dataset/*.db (read-only)
"""
import argparse, base64, glob, html, json, os, re, sqlite3, sys
import cv2, numpy as np
from detect_frames import load_image, detect

HERE = os.path.dirname(os.path.abspath(__file__))
SHAPES = ["aviator", "wayfarer", "round", "rectangle", "square", "cat-eye", "oval", "geometric", "other / unsure"]


def thumb(blob, side):
    im = cv2.imdecode(np.frombuffer(blob, np.uint8), cv2.IMREAD_COLOR)
    if im is None:
        return None
    s = side / max(im.shape[:2])
    im = cv2.resize(im, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", im, [cv2.IMWRITE_JPEG_QUALITY, 72])
    return "data:image/jpeg;base64," + base64.b64encode(buf).decode()


def front_score(blob):
    """0..1 : how much this image looks like a clean, straight-on view (two matching lenses). 0 = no lens pair."""
    try:
        im = load_image(blob)
        r, _ = detect(im)
        f = r.get("features")
        if not f:
            return 0.0
        return round(float(f["sym"] * f["area_ratio"] * (1 - min(f["asym"], 0.5))), 3)
    except Exception:
        return 0.0


def field(text, name):
    m = re.search(name + r"\s*:\s*(.+)", text or "", re.I)
    return m.group(1).strip()[:60] if m else ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=None)
    a = ap.parse_args()
    db = a.db or (sorted(glob.glob(os.path.join(HERE, "dataset", "*.db"))) or [None])[0]
    if not db:
        sys.exit("No .db in dataset/")
    con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
    cols = [r[1] for r in con.execute("PRAGMA table_info(products)")]
    shape_col = "frame_shape" if "frame_shape" in cols else "NULL"
    prods = con.execute("SELECT product_id, sku, product_name, description_clean, %s FROM products "
                        "WHERE upper(sku) LIKE 'DKS%%' ORDER BY CAST(product_id AS INTEGER)" % shape_col).fetchall()
    print(len(prods), "sunglasses products")
    data = []
    for n, (pid, sku, name, desc, pred) in enumerate(prods, 1):
        imgs = []
        for iid, typ, pos, blob in con.execute(
                "SELECT image_id, image_type, position, image_data FROM images WHERE product_id=? "
                "AND download_status='downloaded' ORDER BY (image_type='main') DESC, position", (pid,)):
            t = thumb(blob, 320 if typ == "main" else 210)
            if t:
                imgs.append({"id": iid, "type": typ, "pos": pos, "src": t,
                             "front": front_score(blob) if typ == "gallery" else 0})
        gal = [i for i in imgs if i["type"] == "gallery"]
        best = max(gal, key=lambda i: i["front"], default=None)
        data.append({"id": str(pid), "sku": sku, "name": name, "material": field(desc, "Frame Material"),
                     "size": field(desc, "Size"), "pred": pred if pred in SHAPES else ("" if not pred or pred == "unknown" else pred),
                     "imgs": imgs, "suggest": best["id"] if best and best["front"] >= 0.75 else None})
        if n % 50 == 0:
            print(" ", n, "/", len(prods), flush=True)
    page = PAGE.replace("__DATA__", json.dumps(data)).replace("__SHAPES__", json.dumps(SHAPES))
    os.makedirs(os.path.join(HERE, "review"), exist_ok=True)
    out = os.path.join(HERE, "review", "review.html")
    open(out, "w", encoding="utf-8").write(page)
    print("Open this file in your browser:", out, "(%.1f MB)" % (os.path.getsize(out) / 1e6))


PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><title>Sunglasses review</title>
<style>
body{font-family:system-ui,Arial;margin:0;background:#f4f4f6;color:#222}
#bar{position:sticky;top:0;z-index:5;background:#fff;border-bottom:1px solid #ccc;padding:8px 14px;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
#grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(360px,1fr));gap:12px;padding:12px}
.card{background:#fff;border:2px solid #ddd;border-radius:8px;padding:8px}
.card.done{border-color:#2e9e4f}
.main{width:100%;max-height:300px;object-fit:contain;background:#eee;cursor:zoom-in}
.g{display:flex;gap:4px;flex-wrap:wrap;margin-top:6px}
.g img{height:64px;border:3px solid transparent;cursor:pointer;background:#eee}
.g img.sel{border-color:#2e9e4f}.g img.sug{border-color:#e0a800}
.meta{font-size:12px;color:#555;margin:4px 0}.row{display:flex;gap:6px;align-items:center;margin-top:6px;flex-wrap:wrap}
select,button{font-size:14px;padding:4px 6px}.pred{font-size:12px;color:#777}
#lb{display:none;position:fixed;inset:0;background:#000d;z-index:9;align-items:center;justify-content:center}#lb img{max-width:92vw;max-height:92vh}
</style></head><body>
<div id="bar"><b>Sunglasses review</b><span id="count"></span>
<select id="fs"><option value="all">All</option><option value="todo">Not reviewed</option><option value="done">Reviewed</option><option value="notry">No try-on image chosen</option></select>
<button onclick="dl()">Download results</button>
<span style="font-size:12px;color:#666">Click a small image to mark it as the FRONT-VIEW try-on image (yellow = auto-suggested, green = chosen). Saved automatically in this browser.</span></div>
<div id="grid"></div><div id="lb" onclick="this.style.display='none'"><img id="lbi"></div>
<script>
const D=__DATA__, SH=__SHAPES__, KEY="dukpion_review_v1";
let S={};try{S=JSON.parse(localStorage.getItem(KEY)||"{}")}catch(e){}
function save(){try{localStorage.setItem(KEY,JSON.stringify(S))}catch(e){}}
function st(id){return S[id]||(S[id]={shape:null,tryon:undefined,done:false})}
function zoom(s){document.getElementById('lbi').src=s;document.getElementById('lb').style.display='flex'}
function render(){
 const f=document.getElementById('fs').value,g=document.getElementById('grid');g.innerHTML='';let done=0;
 for(const p of D){const s=S[p.id]||{};if(s.done)done++;}
 for(const p of D){
  const s=st(p.id);const tryon=s.tryon!==undefined?s.tryon:p.suggest;
  if(f==='todo'&&s.done)continue;if(f==='done'&&!s.done)continue;if(f==='notry'&&tryon)continue;
  const c=document.createElement('div');c.className='card'+(s.done?' done':'');
  const main=p.imgs.find(i=>i.type==='main');
  c.innerHTML=(main?`<img class="main" src="${main.src}" onclick="zoom(this.src)">`:'<div class="meta">no main image</div>')+
   `<div class="meta"><b>${p.sku}</b> &middot; ${p.name}<br>Material: ${p.material||'?'} &middot; ${p.size||''}</div>`;
  const gal=p.imgs.filter(i=>i.type==='gallery');
  const gd=document.createElement('div');gd.className='g';
  for(const i of gal){const im=document.createElement('img');im.src=i.src;
   im.className=(tryon===i.id?'sel':(p.suggest===i.id&&tryon===undefined?'sug':''));im.title='front score '+i.front;
   im.onclick=()=>{s.tryon=(tryon===i.id)?null:i.id;s.done=true;save();render()};im.ondblclick=()=>zoom(i.src);gd.appendChild(im)}
  c.appendChild(gd);
  const r=document.createElement('div');r.className='row';
  const sel=document.createElement('select');
  sel.innerHTML='<option value="">-- shape --</option>'+SH.map(x=>`<option ${((s.shape||p.pred)===x)?'selected':''}>${x}</option>`).join('');
  sel.onchange=()=>{s.shape=sel.value||null;s.done=true;save();render()};
  const ok=document.createElement('button');ok.textContent=p.pred?`\u2713 "${p.pred}" is correct`:'\u2713 reviewed';
  ok.onclick=()=>{s.shape=s.shape||p.pred||null;s.done=true;save();render()};
  const um=document.createElement('button');um.textContent=(main&&tryon===main.id)?'\u2713 main = try-on':'use main as try-on';
  um.onclick=()=>{if(main){s.tryon=(tryon===main.id)?null:main.id;s.done=true;save();render()}};
  const none=document.createElement('button');none.textContent='no front image';none.onclick=()=>{s.tryon=null;s.done=true;save();render()};
  r.append(sel,ok,um,none);c.appendChild(r);
  const pr=document.createElement('div');pr.className='pred';pr.textContent='detector said: '+(p.pred||'unknown');c.appendChild(pr);
  g.appendChild(c);
 }
 document.getElementById('count').textContent=done+' / '+D.length+' reviewed';
}
function dl(){
 const out=D.map(p=>{const s=S[p.id]||{};const t=s.tryon!==undefined?s.tryon:p.suggest;
  return{product_id:p.id,sku:p.sku,verified_shape:(s.shape||p.pred||null),tryon_image_id:t||null,reviewed:!!s.done}});
 const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(out,null,1)],{type:'application/json'}));
 a.download='review_results.json';a.click();
}
document.getElementById('fs').onchange=render;render();
</script></body></html>"""

if __name__ == "__main__":
    main()
