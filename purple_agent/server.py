from __future__ import annotations
import re, requests
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, Body
from pydantic import BaseModel
from common.schemas import FinanceResearchTask, AnswerSchema, SourceItem, ToolStats

app = FastAPI(title="Generic Purple Agent")
STATE: Dict[str, Any] = {"sessions": {}}

class TaskRequest(BaseModel):
    task: FinanceResearchTask
    tools_spec: Dict[str, Any]

@app.get("/agent_card")
def agent_card():
    return {"name":"GenericPurpleAgent","protocol":"a2a-lite-0.1","endpoints":{"reset":"/reset","task":"/task"}}

@app.post("/reset")
def reset():
    STATE.clear(); STATE["sessions"] = {}; return {"ok": True}

class ToolsClient:
    def __init__(self, spec: Dict[str, Any], context_id: str):
        self.base = spec["base_url"]; self.ctx = context_id; self.stats: Dict[str,int] = {}
    def call(self, name: str, **kwargs):
        payload = {"tool": name, "args": kwargs, "context_id": self.ctx}
        r = requests.post(f"{self.base}/call", json=payload, timeout=90); r.raise_for_status()
        self.stats[name] = self.stats.get(name, 0) + 1
        return r.json()["result"]

def solve_task(task: FinanceResearchTask, spec: Dict[str, Any]) -> AnswerSchema:
    tools = ToolsClient(spec, task.task_id)
    texts: List[str] = []; sources: List[SourceItem] = []; trace: List[Dict[str,Any]] = []
    for url in (task.context_urls or []):
        page = tools.call("http_fetch", url=url); trace.append({"tool":"http_fetch","url":url,"status":page.get("status")})
        if "text" in page:
            parsed = tools.call("html_parse", html=page["text"]); texts.append(parsed.get("text",""))
            sources.append(SourceItem(url=url)); trace.append({"tool":"html_parse","chars":len(parsed.get("text",""))})
    final_answer = "FINAL ANSWER: Unable to determine."
    blob = "\n".join(texts)

    if task.category.lower().startswith("numerical"):
        res = tools.call("finance_calc_extract_first_billions", text=blob)
        val = res.get("value_billions"); ev = res.get("evidence")
        if val is not None: final_answer = f"FINAL ANSWER: {val:.1f} USD billions. Evidence: {ev}"
    else:
        if re.search(r"\bbeat\b", blob, flags=re.I):
            m = re.search(r"EPS[^$]*\$(\d+(\.\d+)?)", blob, flags=re.I)
            final_answer = f"FINAL ANSWER: Beat. EPS ${m.group(1) if m else '?'}."
        elif re.search(r"\bmiss\b", blob, flags=re.I):
            m = re.search(r"EPS[^$]*\$(\d+(\.\d+)?)", blob, flags=re.I)
            final_answer = f"FINAL ANSWER: Miss. EPS ${m.group(1) if m else '?'}."
    return AnswerSchema(final_answer=final_answer, sources=sources, work_notes=None, tool_trace=trace, tool_stats=ToolStats(calls=tools.stats))

@app.post("/task")
def task(req: TaskRequest = Body(...)) -> AnswerSchema:
    return solve_task(req.task, req.tools_spec)

def create_app(): return app

if __name__ == "__main__":
    import uvicorn, argparse
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=7003)
    args = p.parse_args()
    uvicorn.run(app, host=args.host, port=args.port)
