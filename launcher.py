from __future__ import annotations
import multiprocessing as mp
import os, time, json, requests, pathlib, sys
from typing import Any, Dict, List
import uvicorn
sys.path.append(str(pathlib.Path(__file__).parent))

from tools.server import create_app as create_tools_app
from green_agent.server import create_app as create_green_app
from purple_agent.server import create_app as create_purple_app
from common.schemas import FinanceResearchTask

HOST = "127.0.0.1"; PORT_TOOLS = 7001; PORT_GREEN = 7002; PORT_PURPLE = 7003

def run_uvicorn(app_factory, host: str, port: int):
    app = app_factory()
    config = uvicorn.Config(app=app, host=host, port=port, log_level="info", workers=1)
    server = uvicorn.Server(config); server.run()

def wait_ready(url: str, path: str, timeout_s: int = 20):
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        try:
            r = requests.get(f"{url}{path}", timeout=2)
            if r.status_code == 200: return True
        except Exception: pass
        time.sleep(0.2)
    raise RuntimeError(f"Service not ready: {url}{path}")

def main():
    print("Starting tool server, green agent, and purple agent...")
    p_tools = mp.Process(target=run_uvicorn, args=(create_tools_app, HOST, PORT_TOOLS), daemon=True)
    p_green = mp.Process(target=run_uvicorn, args=(create_green_app, HOST, PORT_GREEN), daemon=True)
    p_purple = mp.Process(target=run_uvicorn, args=(create_purple_app, HOST, PORT_PURPLE), daemon=True)

    p_tools.start(); os.environ.setdefault("TOOLS_BASE_URL", f"http://{HOST}:{PORT_TOOLS}"); time.sleep(0.5)
    p_green.start(); time.sleep(0.2)
    p_purple.start()

    tools_url = f"http://{HOST}:{PORT_TOOLS}"
    green_url = f"http://{HOST}:{PORT_GREEN}"
    purple_url = f"http://{HOST}:{PORT_PURPLE}"
    try:
        wait_ready(tools_url, "/tools"); wait_ready(green_url, "/agent_card"); wait_ready(purple_url, "/agent_card")
        print("All services are live. Resetting agents...")
        requests.post(f"{green_url}/reset", timeout=5); requests.post(f"{purple_url}/reset", timeout=5)

        tasks_path = pathlib.Path(__file__).parent / "data" / "tasks" / "sample_tasks.json"
        tasks_json = json.loads(tasks_path.read_text(encoding="utf-8"))
        tasks = [FinanceResearchTask.model_validate(t) for t in tasks_json]
        print(f"Loaded {len(tasks)} tasks. Launching assessment...")

        assess_req = {"purple_agent_url": purple_url, "tasks": [t.model_dump() for t in tasks], "tools_base_url": tools_url}
        r = requests.post(f"{green_url}/assess", json=assess_req, timeout=600); r.raise_for_status()
        result = r.json()

        print("\n=== Assessment Result ===")
        print(json.dumps(result["summary"], indent=2, ensure_ascii=False))
        print("\nPer-task:")
        for pt in result["per_task"]:
            print(f"- {pt['task_id']} | success={pt['success']} | score={pt['score']}")
            print(f"  answer: {pt['answer']['final_answer']}")
            if pt['answer']['sources']:
                print(f"  sources: {[s.get('url') for s in pt['answer']['sources']]}")
            print()
    finally:
        print("Terminating services...")
        for p in (p_purple, p_green, p_tools):
            if p.is_alive(): p.terminate(); p.join(timeout=3)

if __name__ == "__main__":
    mp.set_start_method("spawn", force=True); main()
