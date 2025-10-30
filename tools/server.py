from __future__ import annotations
import os, re
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, Body, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import requests
from bs4 import BeautifulSoup
try:
    from duckduckgo_search import DDGS
except Exception:
    DDGS = None

app = FastAPI(title="Agentify Tools Hub")
KV: Dict[str, Dict[str, Any]] = {}

class ToolCallRequest(BaseModel):
    tool: str
    args: Dict[str, Any] = Field(default_factory=dict)
    context_id: Optional[str] = None

def _google_search(query: str, top_n: int = 5) -> List[Dict[str, Any]]:
    serpapi_key = os.getenv("SERPAPI_KEY")
    if serpapi_key:
        url = "https://serpapi.com/search.json"
        params = {"q": query, "engine": "google", "api_key": serpapi_key}
        r = requests.get(url, params=params, timeout=30); r.raise_for_status()
        data = r.json()
        return [{"title": it.get("title"), "link": it.get("link"), "snippet": it.get("snippet")} 
                for it in (data.get("organic_results") or [])[:top_n]]
    if DDGS is None:
        raise HTTPException(503, "No search backend available")
    with DDGS() as ddgs:
        out = []
        for res in ddgs.text(query, max_results=top_n or 5):
            out.append({"title": res.get("title"), "link": res.get("href") or res.get("url"), "snippet": res.get("body")})
        return out

def _http_fetch(url: str, timeout: int = 30) -> Dict[str, Any]:
    r = requests.get(url, headers={"User-Agent": "agentify/0.1"}, timeout=timeout)
    r.raise_for_status()
    ct = r.headers.get("content-type","").lower()
    if "html" in ct or "text" in ct:
        return {"status": r.status_code, "content_type": ct, "text": r.text}
    return {"status": r.status_code, "content_type": ct, "bytes_len": len(r.content)}

def _html_parse(html: str) -> Dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")
    for s in soup(["script","style"]): s.extract()
    text = soup.get_text(separator="\n", strip=True)
    links = [{"text": a.get_text(strip=True), "href": a.get("href")} for a in soup.find_all("a", href=True)]
    return {"text": text, "links": links, "tables": []}

def _kv_put(context_id: str, key: str, value: Any) -> Dict[str, Any]:
    if not context_id: raise HTTPException(400, "context_id required")
    KV.setdefault(context_id, {})[key] = value
    return {"ok": True, "keys": list(KV[context_id].keys())}

def _kv_get(context_id: str, key: str) -> Dict[str, Any]:
    if not context_id: raise HTTPException(400, "context_id required")
    return {"ok": key in KV.get(context_id, {}), "value": KV.get(context_id, {}).get(key)}

def _parse_billions(text: str) -> Optional[float]:
    s = text.replace(",", "")
    m = re.search(r"\$?([\d]+(\.\d+)?)\s*(million|billion)", s, flags=re.I)
    if not m: return None
    val = float(m.group(1))
    unit = m.group(3).lower()
    if unit.startswith("million"): return val/1000.0
    return val

@app.get("/tools")
def get_tools():
    base_url = os.getenv("TOOLS_BASE_URL", "http://127.0.0.1:7001")
    return {"base_url": base_url, "tools":[
        {"name":"google_search","desc":"Web search (SerpAPI or DDG)"},
        {"name":"http_fetch","desc":"HTTP GET content"},
        {"name":"html_parse","desc":"Parse HTML to text/links/tables"},
        {"name":"kv_put","desc":"KV set (per context_id)"},
        {"name":"kv_get","desc":"KV get (per context_id)"},
        {"name":"finance_calc_extract_first_billions","desc":"Extract first $X billion/million from text"}
    ]}

@app.post("/call")
def call_tool(req: ToolCallRequest = Body(...)):
    t = req.tool; a = req.args or {}
    if t == "google_search": return {"ok": True, "result": _google_search(a.get("query",""), int(a.get("top_n",5)))}
    if t == "http_fetch":    return {"ok": True, "result": _http_fetch(a.get("url"), int(a.get("timeout",30)))}
    if t == "html_parse":    return {"ok": True, "result": _html_parse(a.get("html",""))}
    if t == "kv_put":        return {"ok": True, "result": _kv_put(req.context_id, a.get("key"), a.get("value"))}
    if t == "kv_get":        return {"ok": True, "result": _kv_get(req.context_id, a.get("key"))}
    if t == "finance_calc_extract_first_billions":
        val = None; ev = None
        text = a.get("text","")
        for line in text.splitlines():
            v = _parse_billions(line)
            if v is not None:
                val = v; ev = line.strip(); break
        return {"ok": True, "result": {"value_billions": val, "evidence": ev}}
    raise HTTPException(404, f"Unknown tool {t}")

app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="static")

def create_app(): return app

if __name__ == "__main__":
    import uvicorn, argparse
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=7001)
    args = p.parse_args()
    os.environ.setdefault("TOOLS_BASE_URL", f"http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port)
