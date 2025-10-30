# Agentify FinBench — **Purple/Green** Template

> Turn a finance agent benchmark into a **Green (evaluator)** agent that runs **end‑to‑end on AgentBeats**, and test any **Purple (competing)** agent against it.  
> This repo includes: a green evaluator, a sample purple agent, an MCP‑like tools hub, task schemas + demo tasks, and Docker/Scenario configs.

---

## Why this repo?

- **Plug‑and‑play evaluation**: The **Green agent** handles task orchestration, tool delivery, scoring, progress updates, and artifact output—so you can fairly compare different **Purple agents** without modifying them.
- **Reproducible**: Reset endpoints, fixed tasks, and deterministic grading make runs comparable.
- **AgentBeats‑ready**: Containerized with a minimal `scenario.toml` for hosted runs; same image also works locally.

---

## What’s inside

```
.
├── Dockerfile
├── entrypoint.sh
├── launcher.py
├── requirements.txt
├── common/
│   └── schemas.py               # Task, answer, result models (Pydantic)
├── tools/
│   ├── server.py                # MCP-like tools hub: /tools, /call, /static/*
│   └── static/
│       ├── aapl_10k_2023_excerpt.html
│       └── msft_fy2024_q4_press_release.html
├── green_agent/
│   └── server.py                # Evaluator: /agent_card, /reset, /assess
├── purple_agent/
│   └── server.py                # Competing agent example: /agent_card, /reset, /task
└── data/
    └── tasks/
        └── sample_tasks.json    # Offline demo tasks
```

- **Ports**: tools `7001`, green `7002`, purple `7003`  
- **Artifacts**: written to `$AB_OUTPUT_DIR` (default `/outputs`):  
  - `summary.json` (run‑level metrics)  
  - `per_task.jsonl` (one line per task with score and details)

---

## Quickstart — local (venv)

> Requires Python 3.10+

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# One command: launch tools + green + purple, run the demo assessment
python launcher.py
```

You should see logs for all three services and a final summary like:

```
=== Assessment Result ===
{
  "num_tasks": 2,
  "accuracy": 1.0,
  "class_mean_accuracy": 1.0,
  "time_used_sec": ...
}
Per-task:
- demo-aapl-2023-revenue | success=True | score=1.0
  answer: FINAL ANSWER: 383.3 USD billions. Evidence: $383,285 million
  sources: ['http://127.0.0.1:7001/static/aapl_10k_2023_excerpt.html']

- demo-msft-fy24q4-beat | success=True | score=1.0
  answer: FINAL ANSWER: Beat. EPS $2.95.
  sources: ['http://127.0.0.1:7001/static/msft_fy2024_q4_press_release.html']
```

---

## Quickstart — Docker (artifacts on host)

```bash
docker build -t agentify-finbench:latest .
docker run --rm -p 7001:7001 -p 7002:7002   -e TOOLS_HOST=0.0.0.0 -e TOOLS_PORT=7001   -e GREEN_HOST=0.0.0.0 -e GREEN_PORT=7002   -v "$PWD/tmp_outputs:/outputs"   agentify-finbench:latest
```

In another terminal:

```bash
# start the purple agent locally
python -m purple_agent.server --port 7003

# trigger an assessment
curl -s -X POST http://127.0.0.1:7002/assess   -H 'Content-Type: application/json'   -d '{
    "purple_agent_url": "http://127.0.0.1:7003",
    "tools_base_url": "http://127.0.0.1:7001",
    "tasks": '"$(cat data/tasks/sample_tasks.json)"'
  }' | jq .
```

Artifacts will appear in `tmp_outputs/summary.json` and `tmp_outputs/per_task.jsonl`.

---

## Run end‑to‑end on **AgentBeats**

1. Push the image to a registry the platform can access (or build in‑platform).  
2. Use `scenarios/finbench/scenario.toml` as your hosted scenario.  
3. Configure required env vars and open ports `7001`/`7002`.  
4. Supply the **Purple agent URL** in the assessment config (the platform passes it to the Green agent).  
5. Start the run; the platform will probe `/agent_card`, POST `/assess`, and capture `/outputs` as artifacts.

> You can also host the Green agent remotely (public URL). Ensure `/agent_card`, `/assess`, `/reset` are reachable.

---

## Interfaces & data contracts (A2A‑lite)

### Green (evaluator) agent

- `GET /agent_card` → identity/capabilities (progress, artifacts)  
- `POST /reset` → assessment‑level isolation  
- `POST /assess` (request):

```jsonc
{
  "purple_agent_url": "http://<participant>/...",   // or legacy: white_agent_url
  "tools_base_url": "http://<tools>/...",
  "tasks": [ /* FinanceResearchTask[] */ ],
  "progress_url": "http://<optional-webhook>"       // optional progress updates
}
```

**Response**: `AssessmentResult { summary, per_task[] }`  
Also writes `summary.json` and `per_task.jsonl` to `$AB_OUTPUT_DIR`.

> **Progress** (optional): will POST `assessment_started`, `task_started`, `task_finished`, `assessment_finished` to `progress_url`.

### Purple (competing) agent

- `GET /agent_card`, `POST /reset`  
- `POST /task`:

```jsonc
{
  "task": { /* FinanceResearchTask */ },
  "tools_spec": { "base_url": "http://<tools>", "tools": [/*...*/] }
}
```

**Response**: `AnswerSchema` with:  
`final_answer`, `sources[]`, optional `tool_trace`, `tool_stats`.

### Task schema (excerpt)

```jsonc
{
  "task_id": "demo-aapl-2023-revenue",
  "category": "NumericalReasoning",
  "question": "What was Apple's total revenue (net sales) in fiscal year 2023?",
  "constraints": { "allowed_tools": ["http_fetch","html_parse","finance_calc_extract_first_billions"] },
  "evidence_policy": { "must_cite": true, "allowed_domains": ["127.0.0.1"] },
  "answer_contract": { "final_prefix": "FINAL ANSWER:", "require_sources_dict": true },
  "expected": { "type": "numeric", "value": 383.285, "tolerance": 0.5 }
}
```

---

## Tools Hub (MCP‑like)

- `GET /tools` → returns tool list + `base_url`
- `POST /call` → `{ "tool": "<name>", "args": {...}, "context_id": "<task_id>" }`  
- `/static/*` → serves offline HTML docs (demo)

**Built‑in tools**:  
`google_search` (SerpAPI or DuckDuckGo fallback), `http_fetch`, `html_parse`,  
`kv_put`/`kv_get` (per‑context KV),  
`finance_calc_extract_first_billions` (extracts first “$X million/billion” and normalizes to USD billions)

> For production, replace this with a **standard MCP server** and let the Purple agent dynamically load tools.

---

## Scoring & metrics (how “evaluate” is done)

**Grader is inside the Green agent.** In this template it’s minimal but already useful:

- **Numeric tasks**: parse `"X USD billions"` from `final_answer` and compare with `expected.value` using a tolerance (e.g., ±0.5).  
- **Beat/Miss tasks**:  
  1) classify as Beat/Miss from the answer text;  
  2) extract EPS and, if `expected.consensus` is set, check the **direction** (`EPS - consensus > 0` ↔ Beat).  
- **Evidence policy**:  
  - If `must_cite=true` and `sources` is empty → **penalty** (score halved).  
  - If `allowed_domains` is set and any source URL falls outside → **penalty** (score halved) + list offending domains.  
- **Run‑level metrics**: `accuracy`, `class_mean_accuracy`, and `time_used_sec`.

**Artifacts**:
- `summary.json` — overall metrics and metadata.  
- `per_task.jsonl` — one JSON object per task including `success`, `score`, `details` (parsed values, penalties, EPS/consensus checks), and the Purple agent’s `answer`.

> To go beyond this demo: plug in **LLM‑as‑Judge + rubric**, **contradiction checks**, **cost/step/error breakdown**, and **rolling averages**. Hooks are already in place.

---

## Config & environment variables

| Variable            | Purpose                                       | Default            |
|--------------------|-----------------------------------------------|--------------------|
| `TOOLS_HOST/PORT`  | Tools Hub bind address/port                    | `0.0.0.0` / `7001` |
| `GREEN_HOST/PORT`  | Green agent bind address/port                  | `0.0.0.0` / `7002` |
| `TOOLS_BASE_URL`   | How the Green agent reaches the Tools Hub      | set in `entrypoint.sh` |
| `AB_OUTPUT_DIR`    | Artifact output directory                       | `/outputs`         |
| `SERPAPI_KEY`      | SerpAPI key for Google search (optional)       | empty → DDG fallback |

Dependencies are pinned in `requirements.txt` (`duckduckgo-search>=6.2.12,<9` to avoid unavailable pins).

---

## Integrate your own Purple agent

To evaluate your agent, implement three endpoints and point `purple_agent_url` at it:

- `GET /agent_card` (identity)  
- `POST /reset` (clear state)  
- `POST /task` (input: `FinanceResearchTask` + `tools_spec`; output: `AnswerSchema`)

No need to change the evaluator—just swap the URL and re‑run.

---

## Troubleshooting

- **Can’t build `lxml` on macOS**: `xcode-select --install`, or use a wheel‑available version.  
- **`duckduckgo-search` version not found**: we use `>=6.2.12,<9`. For offline demos you can omit it.  
- **Ports in use**: change ports in `launcher.py`, or free them (e.g., `lsof -i :7001`).  
- **No artifacts**: when running in Docker, ensure `/outputs` is mounted to a host directory.  
- **Progress webhook not firing**: make sure `progress_url` is reachable; failures don’t abort the run.  
- **Search 503**: happens if `SERPAPI_KEY` is empty *and* `duckduckgo-search` isn’t installed; offline tasks still work.

---

## Roadmap

1) Replace MCP‑like tools with a **standard MCP server** and dynamic tool loading in Purple.  
2) **Judge upgrade**: LLM‑as‑Judge + rubric + contradiction checks (temp=0, unified token limits).  
3) **Parallelism & stability**: internal concurrency, pass@k / rolling averages.  
4) **Analytics**: API cost, tool usage profiles, step counts, error taxonomy.  
5) **Data versioning**: task set versions and content hashes, snapshot caching.

---

## License

Add your preferred license (MIT/Apache‑2.0/etc.). This template is for demonstration/teaching to help teams agentify benchmarks for AgentBeats.
