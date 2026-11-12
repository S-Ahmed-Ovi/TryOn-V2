"""
Local web page: upload a face photo -> face shape -> recommended sunglasses on your face.

    python app.py                 # then open http://localhost:8000  (opens automatically)
    python app.py --db dataset/dukpion_tryon.db --port 8000

The photo is processed in memory and never saved.
"""
import argparse, base64, json, threading, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import cv2
import numpy as np
from tryon import TryOnEngine

MAX_BYTES = 20 * 1024 * 1024
ENGINE = None


def jpeg_b64(img):
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 88])
    return "data:image/jpeg;base64," + base64.b64encode(buf).decode()


def analyse(body, shape, offset, top=6):
    img = cv2.imdecode(np.frombuffer(body, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return {"error": "This file is not a readable image."}
    r = ENGINE.run(img, shape or None, top, offset)
    f = r["face"]
    return {
        "status": f["status"], "issues": f["issues"],
        "detected": {"shape": f["face_shape"], "confidence": f["confidence"], "alternatives": f["alternatives"],
                     "needs_confirmation": f["needs_confirmation"]},
        "used_shape": r["used_shape"], "why": r["why"], "total": r["total"], "offset": offset,
        "recs": [{"sku": x["sku"], "name": x["name"], "frame_shape": x["frame_shape"], "match": x["match"],
                  "url": x["url"], "image": jpeg_b64(x["image"])} for x in r["recs"]],
    }


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype):
        self.send_response(code); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self):
        if self.path != "/analyze":
            return self._send(404, b"not found", "text/plain")
        n = int(self.headers.get("Content-Length", 0))
        if n <= 0 or n > MAX_BYTES:
            return self._send(413, json.dumps({"error": "Photo is too large (max 20 MB)."}).encode(), "application/json")
        try:
            res = analyse(self.rfile.read(n), self.headers.get("X-Shape", ""), int(self.headers.get("X-Offset", 0) or 0))
        except Exception as e:                                   # never crash the server on one bad photo
            res = {"error": "Could not process this photo: %s" % e}
        self._send(200, json.dumps(res).encode(), "application/json")

    def log_message(self, *a):                                   # keep the console quiet
        pass


PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Find your sunglasses</title><style>
body{font-family:system-ui,Arial,sans-serif;margin:0;background:#f5f5f7;color:#222}
main{max-width:1000px;margin:0 auto;padding:18px}h1{font-size:24px;margin:6px 0}
.box{background:#fff;border:1px solid #ddd;border-radius:10px;padding:16px;margin:12px 0}
#drop{border:2px dashed #aaa;border-radius:10px;padding:26px;text-align:center;cursor:pointer;color:#555}
.chips button{margin:3px;padding:7px 13px;border-radius:18px;border:1px solid #888;background:#fff;cursor:pointer;font-size:14px}
.chips button.on{background:#222;color:#fff;border-color:#222}
.warn{color:#a15c00;font-size:14px;margin:3px 0}.bad{color:#b00020;font-size:14px;margin:3px 0}
#grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:14px}
.card{background:#fff;border:1px solid #ddd;border-radius:10px;overflow:hidden}.card img{width:100%;display:block}
.card div{padding:9px 12px;font-size:14px}.tag{display:inline-block;background:#e8f5e9;color:#1b5e20;border-radius:10px;padding:1px 8px;font-size:12px;margin-left:6px}
a{color:#0b57d0}button.more{padding:9px 18px;font-size:15px;cursor:pointer;margin-top:12px}
.small{font-size:12px;color:#666}
</style></head><body><main>
<h1>Find your sunglasses</h1>
<div class="small">Your photo is processed on this computer and is not saved. Best result: a straight-on, well-lit photo of one face, hair off the forehead.</div>
<div class="box"><div id="drop" onclick="f.click()">Click to choose a photo (or drag it here)</div>
<input type="file" id="f" accept="image/*" style="display:none"></div>
<div id="msg" class="box" style="display:none"></div>
<div id="shape" class="box" style="display:none"></div>
<div id="grid"></div><div id="moreWrap"></div>
</main><script>
const SH=["oval","round","square","heart","oblong"];let file=null,chosen="",offset=0;
const $=id=>document.getElementById(id);
$('f').onchange=e=>{file=e.target.files[0];chosen="";offset=0;go(false)};
const d=$('drop');d.ondragover=e=>{e.preventDefault()};d.ondrop=e=>{e.preventDefault();file=e.dataTransfer.files[0];chosen="";offset=0;go(false)};
async function go(append){
  if(!file)return;$('msg').style.display='block';$('msg').textContent='Analysing...';
  const r=await fetch('/analyze',{method:'POST',body:file,headers:{'X-Shape':chosen,'X-Offset':offset}});
  const j=await r.json();render(j,append)}
function render(j,append){
  const m=$('msg');m.innerHTML='';
  if(j.error){m.textContent=j.error;return}
  for(const i of j.issues){const p=document.createElement('div');p.className=j.status==='reject'?'bad':'warn';p.textContent=i;m.appendChild(p)}
  if(!m.innerHTML)m.style.display='none';
  const s=$('shape');
  if(j.status==='reject'){s.style.display='none';$('grid').innerHTML='';$('moreWrap').innerHTML='';
     m.insertAdjacentHTML('beforeend','<div>Please try another photo.</div>');m.style.display='block';return}
  s.style.display='block';
  const conf=j.detected.needs_confirmation?'We are not fully sure - please pick the face shape that looks right to you:':'Detected face shape (tap another if it is not right):';
  s.innerHTML='<b>'+j.used_shape+'</b> face &nbsp;<span class="small">'+conf+'</span><div class="chips" id="chips"></div><div class="small" style="margin-top:6px">'+j.why+'</div>';
  for(const x of SH){const b=document.createElement('button');b.textContent=x;if(x===j.used_shape)b.className='on';
     b.onclick=()=>{chosen=x;offset=0;go(false)};$('chips').appendChild(b)}
  if(!append)$('grid').innerHTML='';
  for(const r of j.recs){const c=document.createElement('div');c.className='card';
    c.innerHTML='<img src="'+r.image+'"><div><b>'+(r.name||r.sku)+'</b><span class="tag">'+r.match+'</span><br><span class="small">'+r.sku+' &middot; '+r.frame_shape+' frame</span>'+(r.url?'<br><a href="'+r.url+'" target="_blank">View product</a>':'')+'</div>';
    $('grid').appendChild(c)}
  const more=j.offset+j.recs.length<j.total;
  $('moreWrap').innerHTML=more?'<button class="more" onclick="offset+=6;go(true)">Show more</button>':'';
}
</script></body></html>"""

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--db"); ap.add_argument("--port", type=int, default=8000)
    a = ap.parse_args()
    ENGINE = TryOnEngine(a.db)
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    url = "http://localhost:%d" % a.port
    print("Open", url, " (Ctrl+C to stop)")
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
