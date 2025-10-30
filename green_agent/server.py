from __future__ import annotations
import os, time, json, requests, statistics, pathlib
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, Body
from pydantic import BaseModel
from common.schemas import FinanceResearchTask, AnswerSchema, PerTaskResult, AssessmentResult

app = FastAPI(title="Finance Green Agent (Evaluator)")
STATE: Dict[str, Any] = {"runs": 0}
AB_OUTPUT_DIR = pathlib.Path(os.getenv("AB_OUTPUT_DIR", "/outputs"))

class AssessRequest(BaseModel):
    purple_agent_url: Optional[str] = None
    white_agent_url: Optional[str] = None  # backwards compatibility
    tasks: List[FinanceResearchTask]
    tools_base_url: Optional[str] = None
    progress_url: Optional[str] = None

    @property
    def participant_url(self):
        return self.purple_agent_url or self.white_agent_url

@app.get("/agent_card")
def agent_card():
    return {
        "name": "FinanceGreenAgent",
        "protocol": "a2a-lite-0.2",
        "endpoints": {"reset": "/reset", "assess": "/assess"},
        "capabilities": {"progress_updates": True, "artifacts": True}
    }

@app.post("/reset")
def reset():
    STATE.clear(); STATE["runs"] = 0
    return {"ok": True}

def fetch_tools_spec(base_url: str) -> Dict[str, Any]:
    r = requests.get(f"{base_url}/tools", timeout=15); r.raise_for_status(); return r.json()

def call_participant(participant_url: str, task: Dict[str, Any], tools_spec: Dict[str, Any]) -> AnswerSchema:
    payload = {"task": task, "tools_spec": tools_spec}
    r = requests.post(f"{participant_url}/task", json=payload, timeout=600)
    r.raise_for_status()
    return AnswerSchema.model_validate(r.json())

def _post_progress(url: Optional[str], payload: Dict[str, Any]):
    if not url: return
    try: requests.post(url, json=payload, timeout=5)
    except Exception: pass

def grade(task: FinanceResearchTask, answer: AnswerSchema) -> PerTaskResult:
    success = False; score = 0.0; details: Dict[str, Any] = {}
    exp = task.expected or {}

    # numeric
    if exp.get("type") == "numeric":
        import re
        tol = float(exp.get("tolerance", 0.5))
        m = re.search(r"([\d]+(\.\d+)?)\s*(?:USD\s*)?billions?", answer.final_answer, flags=re.I)
        val = float(m.group(1)) if m else None
        details["parsed_value_bil"] = val; details["expected_value_bil"] = exp.get("value")
        if val is not None and abs(val - float(exp.get("value"))) <= tol:
            success, score = True, 1.0

    # beat/miss with EPS direction
    elif exp.get("type") == "beat_miss":
        want = (exp.get("result") or "").lower()  # "beat" or "miss"
        text = answer.final_answer.lower()
        classified = "beat" if "beat" in text else ("miss" if "miss" in text else "unknown")
        details["classified"] = classified
        ok_cls = (classified == want)

        import re
        eps = None
        m = re.search(r"eps[^$]*\$(\d+(\.\d+)?)", answer.final_answer, flags=re.I)
        if m: eps = float(m.group(1))
        consensus = exp.get("consensus")
        direction_ok = None
        if eps is not None and isinstance(consensus, (int, float)):
            direction_ok = ((eps - float(consensus)) > 0) == (want == "beat")
        details.update({"eps": eps, "consensus": consensus, "direction_ok": direction_ok})

        success = bool(ok_cls and (direction_ok is not False))
        score = 1.0 if success else 0.0

    # evidence & domain policy
    must_cite = bool(getattr(task.evidence_policy, "must_cite", True))
    allowed = set((getattr(task.evidence_policy, "allowed_domains", None) or []))
    urls = [s.url for s in (answer.sources or []) if getattr(s, "url", None)]

    if must_cite and not urls:
        score *= 0.5
        details["penalty_missing_sources"] = True

    if allowed and urls:
        def _in_allowed(u: str) -> bool: return any(dom in u for dom in allowed)
        bad = [u for u in urls if not _in_allowed(u)]
        if bad:
            score *= 0.5
            details["penalty_disallowed_domains"] = bad

    return PerTaskResult(task_id=task.task_id, category=task.category, success=bool(success), score=float(score), details=details, answer=answer)

@app.post("/assess")
def assess(req: AssessRequest = Body(...)) -> AssessmentResult:
    STATE["runs"] += 1
    tools_base_url = req.tools_base_url or os.environ.get("TOOLS_BASE_URL")
    if not tools_base_url: raise RuntimeError("tools_base_url not provided and TOOLS_BASE_URL env is empty")
    participant = req.participant_url
    if not participant: raise RuntimeError("participant (purple) agent URL is required")

    tools_spec = fetch_tools_spec(tools_base_url)
    per_task: List[PerTaskResult] = []; t0 = time.time()

    _post_progress(req.progress_url, {"event": "assessment_started", "num_tasks": len(req.tasks)})
    for t in req.tasks:
        _post_progress(req.progress_url, {"event": "task_started", "task_id": t.task_id})
        ans = call_participant(participant, t.model_dump(), tools_spec)
        res = grade(t, ans); per_task.append(res)
        _post_progress(req.progress_url, {"event": "task_finished", "task_id": t.task_id, "success": res.success, "score": res.score})
    elapsed = time.time() - t0

    acc = sum(1 for r in per_task if r.success) / max(1, len(per_task))
    class_means: Dict[str, List[float]] = {}
    for r in per_task: class_means.setdefault(r.category, []).append(1.0 if r.success else 0.0)
    class_mean_acc = statistics.mean([sum(v)/len(v) for v in class_means.values()]) if class_means else acc

    summary = {"num_tasks": len(per_task), "accuracy": round(acc,3), "class_mean_accuracy": round(class_mean_acc,3), "time_used_sec": round(elapsed,3), "tool_server": tools_base_url}

    # artifacts
    try:
        AB_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        (AB_OUTPUT_DIR / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        with (AB_OUTPUT_DIR / "per_task.jsonl").open("w", encoding="utf-8") as f:
            for pt in per_task: f.write(pt.model_dump_json() + "\n")
    except Exception as e:
        summary["artifact_write_error"] = str(e)

    _post_progress(req.progress_url, {"event": "assessment_finished", "summary": summary})

    return AssessmentResult(purple_agent_url=participant, per_task=per_task, summary=summary)

def create_app(): return app

if __name__ == "__main__":
    import uvicorn, argparse
    p = argparse.ArgumentParser()
    p.add_argument("--host", default=os.getenv("GREEN_HOST", "127.0.0.1"))
    p.add_argument("--port", type=int, default=int(os.getenv("GREEN_PORT", "7002")))
    args = p.parse_args()
    uvicorn.run(app, host=args.host, port=args.port)
