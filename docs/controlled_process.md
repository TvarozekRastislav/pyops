# Controlled Process Architecture

The controlled process is the **low-agenticity** approach: a deterministic Python pipeline where the LLM is used only for text generation (Dockerfile creation and error fixing). All control flow decisions are made by Python code, not the LLM.

---

## File Structure

```
poc/controlled_process/
├── __init__.py     # ControlledProcessApproach class + create_approach() factory
├── pipeline.py     # Deterministic pipeline: read → generate → build → fix → run
└── prompts.py      # System prompt + generate/fix prompt templates

poc/
├── state.py        # BuildState dataclass (shared across all approaches)
└── tools.py        # 5 tool schemas + implementations (shared across all approaches)
```

---

## Design Principles

- **Deterministic control flow** — Python code decides what to do at every step. The LLM never chooses which tool to call or when to stop.
- **LLM as text generator** — called only to produce Dockerfile content (initial generation + fix attempts). No tool_calls, no agent loop.
- **Shared tooling** — `poc/tools.py` and `poc/state.py` are reused by all three approaches. The controlled process differs in that Python code drives the tools directly.
- **Never raises** — `ControlledProcessApproach.run()` catches all exceptions and returns a valid `ApproachResult`. The harness always gets a result.
- **Full cost tracking** — all LLM calls flow through `TrackedOpenAIClient`, automatically recording tokens and cost per run.

---

## How It Works

### Pipeline Overview

```
Step 1: Read source code          [Python → tool]
Step 2: Generate Dockerfile       [Python → LLM]
Step 3: Build Docker image        [Python → tool]
  └─ Step 3b: Fix on failure      [Python → LLM → rebuild]
Step 4: Run container             [Python → tool]
  └─ Step 4b: Fix on failure      [Python → LLM → rebuild → rerun]
Step 5: Cleanup                   [Python]
```

### Step-by-Step

**Step 1: Read source code**
- Calls `read_source_code()` tool (from `poc/tools.py`)
- Returns all Python source files as a JSON string
- No LLM involved — purely deterministic

**Step 2: Generate Dockerfile via LLM**
- Sends system prompt + source JSON to LLM
- LLM returns JSON: `{dockerfile, is_server, port}`
- Response parsed with 3-level fallback: raw JSON → markdown fences → Dockerfile block
- **First LLM call**

**Step 3: Build image**
- Calls `write_and_build_dockerfile()` tool
- Copies source to temp dir, writes Dockerfile, runs `docker build`

**Step 3b: Fix loop (on build failure)**
- If build fails and `fix_count < MAX_FIX_ATTEMPTS` (4):
  - Appends fix prompt to the running conversation history (LLM sees: initial prompt + initial response + all prior fix attempts)
  - LLM returns fixed JSON; response is appended to conversation
  - Loop back to Step 3 with new Dockerfile
- **Additional LLM calls** (one per fix attempt, each with full conversation context)

**Step 4: Run container**
- Script mode (`is_server=False`): runs to completion, checks exit code
- Server mode (`is_server=True`): runs detached with port mapping, waits for ready state (30s timeout)

**Step 4b: Fix loop (on runtime failure)**
- Same fix mechanism as Step 3b (appends to shared conversation history)
- Error log from container runtime passed to LLM
- Triggers full rebuild + rerun

**Step 5: Cleanup**
- Stops server containers if still running
- All temp dirs and containers cleaned via `state.cleanup(docker_client)` in `finally` block

---

## Components

### `ControlledProcessApproach` (`__init__.py`)

Entry point for the harness. Implements the `Approach` protocol.

```python
class ControlledProcessApproach:
    def __init__(self, client: TrackedOpenAIClient, model: str = "gpt-4o")
    def run(self, app_source_path: Path, run_id: str) -> ApproachResult
```

- Creates `BuildState` with image tag `pyops-{app_name}:{run_id}`
- Delegates to `run_pipeline()`
- Cleanup in `finally` block via `state.cleanup(docker_client)`: removes all temp dirs and containers tracked in state
- Factory: `create_approach(client, **kwargs)` reads `model` from kwargs

### `run_pipeline()` (`pipeline.py`)

Core deterministic pipeline.

```python
def run_pipeline(
    client: TrackedOpenAIClient,
    docker_client: docker.DockerClient,
    app_source_path: str,
    run_id: str,
    state: BuildState,
    model: str = "gpt-4o",
) -> BuildState
```

| Constant | Value | Purpose |
|----------|-------|---------|
| `MAX_FIX_ATTEMPTS` | 4 | Max retries for failed builds/runtime |
| `MAX_LOG_CHARS` | 4,000 | Log truncation before sending to LLM |

### Prompt Templates (`prompts.py`)

| Function | Purpose |
|----------|---------|
| `get_system_prompt()` | Expert DevOps engineer identity + JSON response format + Dockerfile best practices |
| `get_generate_prompt(source_json, image_tag)` | Initial Dockerfile generation from source code |
| `get_fix_prompt(source_json, previous_dockerfile, error_log, error_type, is_server, port)` | Error recovery with context of what failed |

The LLM is instructed to return JSON:
```json
{
  "dockerfile": "FROM python:3.11-slim\n...",
  "is_server": false,
  "port": null
}
```

### Response Parsing

`_parse_response()` extracts Dockerfile + metadata with a 3-level fallback chain:

1. Direct JSON parse
2. JSON inside markdown code fences
3. Bare Dockerfile block (fallback: `is_server=False`, `port=None`)

---

## Comparison with Mono Agent

| Aspect | Controlled Process | Mono Agent |
|--------|-------------------|-----------|
| **Decision maker** | Python code | LLM |
| **LLM role** | Text generation only | Full ReAct agent with tools |
| **LLM calls** | 1 (generate) + up to 4 (fixes) = 5 max | Up to 15 (MAX_ITERATIONS) |
| **Tool selection** | Python decides which tools to call | LLM decides via `tool_calls` |
| **Message history** | Conversation maintained across fix attempts | Full conversation maintained |
| **Iteration limit** | MAX_FIX_ATTEMPTS (4) | MAX_ITERATIONS (15) |
| **Server detection** | LLM classifies once, Python follows | LLM observes and adapts |

---

## Harness Integration

```
runner._execute_single_run()
  │
  ├─ with openai_client.track(run_id):
  │     result = approach.run(app_path, run_id)
  │       │
  │       ├─ run_pipeline()
  │       │    ├─ read_source_code()        → deterministic
  │       │    ├─ LLM generate              → TrackedOpenAIClient
  │       │    ├─ build loop                → deterministic + LLM fix
  │       │    └─ run + verify              → deterministic
  │       └─ Returns ApproachResult
  │
  ├─ validator.validate(result, docker_client)   # s2/s3/s4
  ├─ usage = openai_client.get_usage(run_id)     # cost/token data
  └─ cleanup + save metrics
```

---

## Verbose Output

When `-v` / `--verbose` is passed, the pipeline prints colored terminal output:

- Step headers with separators
- Tool calls and results (truncated)
- LLM response previews
- Token usage per LLM call
- Final summary footer (state, elapsed time, LLM calls, fix count)

---

## Configuration

| Setting | Value | Location |
|---------|-------|----------|
| LLM model | `--model` CLI flag (default: `gpt-5-nano`) | `cli.py` → `runner` → `create_approach()` |
| Max fix attempts | 4 | `pipeline.py:MAX_FIX_ATTEMPTS` |
| Max build attempts | 5 | `tools.py:MAX_BUILD_ATTEMPTS` |
| Source truncation | 30,000 chars | `tools.py:MAX_SOURCE_CHARS` |
| Log truncation | 4,000 chars | `pipeline.py:MAX_LOG_CHARS` |
| Image tag format | `pyops-{app_name}:{run_id}` | `__init__.py:run()` |

---
> Updated: 2026-03-17 | Model: claude-opus-4-6 | Initiated by: rt
