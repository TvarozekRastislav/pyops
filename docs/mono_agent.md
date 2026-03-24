# Mono Agent Architecture

The mono agent is the **high-agenticity** approach: a single autonomous LLM agent that reads source code, creates a Dockerfile, builds an image, runs the container, and verifies the result — all via a ReAct (Reasoning + Acting) loop using OpenAI function calling.

---

## File Structure

```
poc/mono_agent/
├── __init__.py     # MonoAgentApproach class + create_approach() factory
├── agent.py        # ReAct loop: message management, tool dispatch, iteration control
└── prompts.py      # System prompt + user message templates

poc/
├── state.py        # BuildState dataclass (shared across all approaches)
└── tools.py        # 5 tool schemas + implementations (shared across all approaches)
```

---

## Design Principles

- **Native OpenAI tool_use** — no LangGraph or other agent frameworks. The ReAct loop is implemented directly with `client.chat.completions.create(tools=...)`.
- **Shared tooling** — `poc/tools.py` and `poc/state.py` are reused by all three approaches. The mono agent differs only in how it drives the tools (autonomous LLM decisions vs. programmatic control).
- **Never raises** — `MonoAgentApproach.run()` catches all exceptions and returns a valid `ApproachResult`. The harness always gets a result.
- **Full cost tracking** — all LLM calls flow through `TrackedOpenAIClient`, automatically recording tokens and cost per run.

---

## How It Works

### ReAct Loop (`agent.py`)

```
                    ┌─────────────────────────────────┐
                    │         System Prompt            │
                    │    "You are a DevOps engineer"   │
                    │  + workflow rules + tool list    │
                    └───────────────┬─────────────────┘
                                    │
                    ┌───────────────▼─────────────────┐
                    │         User Message             │
                    │  "Containerize app at /path..."  │
                    └───────────────┬─────────────────┘
                                    │
              ┌─────────────────────▼──────────────────────┐
              │              LLM Call                       │
              │  chat.completions.create(tools, messages)   │
              └─────────────────────┬──────────────────────┘
                                    │
                        ┌───────────▼───────────┐
                        │   tool_calls present?  │
                        └───┬───────────────┬───┘
                          Yes               No
                            │                │
              ┌─────────────▼──────┐   ┌─────▼─────────┐
              │  Execute each tool  │   │  Agent done    │
              │  Append results to  │   │  state.completed│
              │  message history    │   │  = True         │
              └─────────────┬──────┘   └────────────────┘
                            │
                            └──── loop back to LLM Call
```

The loop runs until:
1. The LLM responds with **no tool calls** (signals completion), or
2. **MAX_ITERATIONS** (15) is reached, or
3. An unrecoverable LLM API error occurs

### Typical Execution (Happy Path: 4-6 iterations)

```
Iter 1:  LLM → read_source_code("/path/to/app")
         Tool returns JSON of all source files

Iter 2:  LLM → write_and_build_dockerfile("FROM python:3.11-slim\n...")
         Tool copies source to temp dir, writes Dockerfile, builds image
         Returns: "Build SUCCESS (attempt 1/5)"

Iter 3:  LLM → run_container(detach=false)
         Tool runs container, waits for exit
         Returns: "Container exited with code: 0\nLogs: ..."

Iter 4:  LLM → text summary (no tool calls)
         Agent signals completion
```

### Error Recovery (A6 Problematic: 6-10 iterations)

```
Iter 1:  read_source_code → sees `import requests`, requirements.txt has "python-requests"
Iter 2:  write_and_build_dockerfile with pip install -r requirements.txt → BUILD FAILS
Iter 3:  LLM reads error log, writes new Dockerfile: RUN pip install requests → BUILD SUCCESS
Iter 4:  run_container → exit code 0
Iter 5:  text summary → done
```

---

## Components

### `MonoAgentApproach` (`__init__.py`)

Entry point for the harness. Implements the `Approach` protocol.

```python
class MonoAgentApproach:
    def __init__(self, client: TrackedOpenAIClient, model: str = "gpt-4o")
    def run(self, app_source_path: Path, run_id: str) -> ApproachResult
```

- Creates `BuildState` with image tag `pyops-{app_name}:{run_id}`
- Delegates to `run_agent_loop()`
- Cleanup in `finally` block via `state.cleanup(docker_client)`: removes all temp dirs and containers tracked in state
- Factory: `create_approach(client, **kwargs)` reads `model` from kwargs

### `run_agent_loop()` (`agent.py`)

Core ReAct engine.

| Parameter | Description |
|-----------|-------------|
| `client` | `TrackedOpenAIClient` — LLM calls are auto-tracked |
| `docker_client` | Docker SDK client for tool implementations |
| `app_source_path` | Absolute path to the application source directory |
| `run_id` | Unique identifier for this run |
| `state` | `BuildState` — mutable, accumulates artifacts |
| `model` | LLM model name (default `gpt-4o`) |

**Safety mechanisms:**
- `MAX_ITERATIONS = 15` — prevents infinite loops
- `MAX_BUILD_ATTEMPTS = 5` — enforced in the build tool
- LLM API retry: 1 retry after 2s wait, then fail gracefully
- Per-tool exception guard: tool crashes become error text fed back to the LLM

### System Prompt (`prompts.py`)

Defines the agent's identity and behavior:

- **Role**: expert DevOps engineer
- **Workflow**: read → build → run → verify → done (respond with no tool calls)
- **Dockerfile best practices**: python:3.11-slim base, COPY + WORKDIR, pip install, correct CMD
- **Error recovery rules**: read error logs, fix the Dockerfile, don't repeat the same mistake
- **Completion signal**: respond with text and no tool calls when done

### Shared Tools (`poc/tools.py`)

| Tool | Key Behavior |
|------|-------------|
| `read_source_code` | Walks directory (skipping `__pycache__`, `.git`, binary files, etc.), returns `{relative_path: content}` JSON. Truncated at 30k chars. |
| `write_and_build_dockerfile` | Copies source to temp dir (never writes into `poc/apps/`), writes Dockerfile, builds via `docker_utils.build_image`. Enforces MAX_BUILD_ATTEMPTS. |
| `run_container` | Always uses `state.image_tag` (no image_tag param — prevents LLM hallucinating tags). Auto-cleans previous container before starting a new one. |
| `check_container` | Gets status + logs for detached/server containers. Falls back to `state.container_id`. |
| `stop_container` | Stops and removes via `docker_utils.stop_and_remove`. Clears `state.container_id`. |

All tool responses are truncated (MAX_LOG_CHARS = 4000) to manage context window usage.

### Shared State (`poc/state.py`)

`BuildState` dataclass tracks everything:

| Group | Fields |
|-------|--------|
| **Dockerfile** | `dockerfile_content` |
| **Build** | `image_tag`, `build_succeeded`, `build_log`, `build_attempts` |
| **Container** | `container_id`, `container_logs`, `container_exit_code` |
| **Cleanup** | `temp_dirs: list[str]`, `container_ids: list[str]` |
| **Timing** | `t_build` — accumulated Docker build time (seconds) |
| **Control** | `iteration`, `completed`, `error` |

`to_approach_result()` converts to `ApproachResult` by splitting `image_tag` into `image_name` + `image_tag` (e.g., `pyops-a1:run_1` → `image_name="pyops-a1"`, `image_tag="run_1"`).

---

## Harness Integration

```
runner._execute_single_run()
  │
  ├─ with openai_client.track(run_id):
  │     result = approach.run(app_path, run_id)
  │       │
  │       ├─ LLM calls → TrackedOpenAIClient → auto-tracked
  │       ├─ Tools use docker_utils for build/run/cleanup
  │       └─ Returns ApproachResult
  │
  ├─ validator.validate(result, docker_client)   # s2/s3/s4
  ├─ usage = openai_client.get_usage(run_id)     # cost/token data
  └─ cleanup + save metrics
```

---

## Configuration

| Setting | Value | Location |
|---------|-------|----------|
| LLM model | `--model` CLI flag (default: `gpt-5-nano`) | `cli.py` → `runner` → `create_approach()` |
| Max iterations | 15 | `agent.py:MAX_ITERATIONS` |
| Max build attempts | 5 | `tools.py:MAX_BUILD_ATTEMPTS` |
| Source truncation | 30,000 chars | `tools.py:MAX_SOURCE_CHARS` |
| Log truncation | 4,000 chars | `tools.py:MAX_LOG_CHARS` |
| LLM retry | 1 retry, 2s delay | `agent.py:_call_llm()` |
| Image tag format | `pyops-{app_name}:{run_id}` | `__init__.py:run()` |

---
> Updated: 2026-03-17 | Model: claude-opus-4-6 | Initiated by: rt
