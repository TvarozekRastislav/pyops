# PyOps Evaluation Harness

The evaluation harness is the central testing and benchmarking infrastructure of the PyOps project. It orchestrates the execution of three LLM-based deployment approaches against six test applications, collects metrics, and produces comparative reports.

All harness code lives in `poc/harness/`.

---

## Architecture Overview

```
poc/
├── cli.py                       # CLI entrypoint (run, report, status, clear)
├── state.py                     # BuildState dataclass (shared across approaches)
├── tools.py                     # 5 shared tool schemas + implementations
└── harness/
    ├── __init__.py              # Package init
    ├── interface.py             # Approach protocol & ApproachResult dataclass
    ├── runner.py                # Main orchestration loop (approach x app x repetition)
    ├── metrics.py               # RawRunMetrics dataclass (22 fields per run)
    ├── scoring.py               # Weighted scoring formulas
    ├── storage.py               # Dual persistence: JSON files + SQLite
    ├── cost_tracker.py          # TrackedOpenAIClient for token/cost tracking
    ├── docker_utils.py          # Docker SDK wrappers (build, run, push, cleanup)
    ├── report.py                # Report generation (table, CSV, LaTeX, JSON)
    └── validators/
        ├── __init__.py          # Validator registry (app_name -> validator class)
        ├── base.py              # BaseValidator abstract class
        ├── a1_validator.py      # A1 Simple Script validator
        ├── a2_validator.py      # A2 Dependencies validator
        ├── a3_validator.py      # A3 Modular App validator
        ├── a4_validator.py      # A4 Server (FastAPI) validator
        ├── a5_validator.py      # A5 Configurable App validator
        └── a6_validator.py      # A6 Problematic App validator
```

---

## File Descriptions

### `interface.py` — Approach Protocol & Result Types

Defines the contract every approach must implement:

- **`Approach`** (Protocol): requires a `name` property and a `run(app_source_path, run_id)` method.
- **`ApproachResult`** (dataclass): returned by each approach run, containing `image_name`, `image_tag`, `build_succeeded`, `build_log`, `dockerfile_content`, `error`, and `t_build`.

### `poc/state.py` — Shared Build State

`BuildState` dataclass used by all approaches to track artifacts during a run:

- Dockerfile content, image tag, build status, build attempts
- Container ID, logs, exit code
- Cleanup tracking: `temp_dirs`, `container_ids`
- Timing: `t_build` — accumulated Docker build time (seconds), measured in `write_and_build_dockerfile()`
- Loop control: `iteration`, `completed`, `error`
- `to_approach_result()` — converts to `ApproachResult` for the harness
- `cleanup(docker_client)` — removes temp directories and orphaned containers (used by all three approaches)

### `poc/tools.py` — Shared Tool Set

Six tools available to all approaches (schemas in OpenAI function-calling format):

| Tool | Purpose |
|------|---------|
| `read_source_code` | Recursively reads source files as JSON (filters binary files and common non-source directories) |
| `write_and_build_dockerfile` | Copies source to temp dir, writes Dockerfile, builds image (times the build for `t_build` metric) |
| `run_container` | Runs the last built image (blocking or detached) |
| `check_container` | Gets container status + logs |
| `stop_container` | Stops and removes a container |
| `push_image` | Pushes the last built image to a Docker registry |

`read_source_code` skips common non-source directories (`__pycache__`, `.git`, `node_modules`, `.venv`, etc.) and binary file extensions (`.pyc`, `.png`, `.zip`, etc.) to avoid wasting LLM tokens.

Also provides `execute_tool()` dispatcher with per-tool exception handling and log truncation.

### `runner.py` — Orchestration Engine

The main experiment loop. Key components:

- **`APPROACH_REGISTRY`**: maps approach names (`controlled_process`, `mono_agent`, `multi_agent`) to their module paths.
- **`ALL_APPS`**: list of six test applications (`a1_simple_script` through `a6_problematic`).
- **`run_experiment()`**: iterates over approaches x apps x repetitions (default 5). Accepts `model` parameter.
- **`load_approach()`**: dynamically imports approach module and calls `create_approach(client, **kwargs)`.
- **`_execute_single_run()`**: handles a single run lifecycle:
  1. Calls `approach.run()` with cost tracking enabled
  2. Runs the appropriate validator (`s2`, `s3`, `s4` checks)
  3. Optionally pushes the image to a remote registry
  4. Cleans up containers and images
  5. Persists metrics to JSON + SQLite

### `metrics.py` — Run Metrics

`RawRunMetrics` dataclass capturing 22 fields per run:

| Category | Fields |
|----------|--------|
| **Identity** | `run_id`, `approach`, `app`, `repetition`, `model`, `timestamp` |
| **Accuracy** | `s1_build` (image builds), `s2_container_starts`, `s3_tests_pass`, `s4_deep_validation` |
| **Cost** | `cost_usd`, `n_calls`, `n_tokens` |
| **Time** | `t_total` (seconds), `t_build` (seconds) |
| **Stability** | `f_build`, `f_run`, `f_push` (failure flags) |
| **Artifacts** | `dockerfile_content`, `build_log`, `container_logs`, `test_details` |

### `scoring.py` — Weighted Scoring Formulas

Computes the final composite score per approach:

**Accuracy sub-score:**
```
accuracy = s1*15 + s2*20 + s3*30 + s4*35
```

**Final score (S):**
```
S = 0.70 * A_norm + 0.20 * C_norm + 0.05 * T_norm + 0.05 * F_norm
```

Where:
- `A_norm` — min-max normalized accuracy (higher is better)
- `C_norm` — min-max normalized cost (inverted; lower cost is better)
- `T_norm` — time complexity: `0.9*(1/T_total) + 0.1*(1/T_build)`, normalized
- `F_norm` — failure count (inverted; fewer failures is better)

### `storage.py` — Results Persistence

Dual storage backend with **separate storage for real and dry-run data**:

| Mode | JSON directory | SQLite database |
|------|---------------|-----------------|
| **Real runs** | `poc/results/runs/` | `poc/results/pyops_results.db` |
| **Dry runs** | `poc/results/dry_runs/` | `poc/results/pyops_dry_results.db` |

All storage functions accept a `dry_run: bool` parameter to select the correct backend.

Functions:
- `save_run(metrics, dry_run)` — writes to both JSON and SQLite
- `load_all_runs(dry_run, include_dry)` — loads runs from SQLite. When `include_dry=True`, merges real + dry-run data.
- `load_run(run_id, dry_run)` — loads a single run
- `count_runs(dry_run)` — returns run counts grouped by approach x app
- `clear_all_runs(dry_run)` — deletes run directories and clears the SQLite table for the selected mode

### `cost_tracker.py` — OpenAI Cost Tracking

`TrackedOpenAIClient` wraps `openai.OpenAI()` to track per-run LLM usage:

- Tracks `prompt_tokens`, `completion_tokens`, `n_calls`, and `cost_usd`
- Uses a context manager pattern: `with client.track(run_id): ...`
- Cost estimation via **litellm** (`cost_per_token()`) — automatically uses up-to-date pricing for any model litellm supports (GPT-4o, GPT-5-nano, etc.). Falls back to `cost=0.0` with a warning if the model is unknown.

### `docker_utils.py` — Docker Operations

Wrappers around the Docker SDK (`docker` Python package):

| Function | Purpose |
|----------|---------|
| `get_client()` | Returns a `docker.DockerClient` instance |
| `build_image()` | Builds a Docker image; returns `(success, build_log)` |
| `run_container()` | Runs a container (blocking or detached mode) |
| `wait_for_ready()` | Polls until the container is in `running` state |
| `get_container_logs()` | Retrieves stdout/stderr from a container |
| `copy_from_container()` | Extracts a file from inside a container |
| `stop_and_remove()` | Stops and removes a container |
| `remove_image()` | Removes a Docker image |
| `tag_image()` | Tags an image for a remote registry |
| `push_image()` | Pushes an image to a remote registry |

### `report.py` — Report Generation

`generate_report()` produces comparison reports in multiple formats:

- **Table** — colored terminal output using **rich** library: Summary table (best/worst color-ranked), Normalized Scores (threshold-colored), Per-App Pass Rates (compact `s1/s2/s3/s4` format with green/yellow/red coloring)
- **CSV** — machine-readable export
- **LaTeX** — formatted table for the thesis document
- **JSON** — structured data export

For `table` format, output is printed directly to the terminal with ANSI colors. A plain-text version is returned for file output (`--output` flag).

---

## Validators

All validators inherit from `BaseValidator` (defined in `validators/base.py`), which provides:

- `is_server` flag — `True` for long-running apps (e.g., FastAPI)
- `container_timeout` — maximum seconds to wait
- `validate()` — main method orchestrating `s2`, `s3`, `s4` checks
- `_validate_script()` — runs a container; s2 passes if the container was created (`container_id != ""`), regardless of exit code (for non-server apps)
- `_validate_server()` — allocates a free port via `_find_free_port()`, runs a container in detached mode, waits for readiness, then tests via HTTP (for server apps)
- `check_s3()` / `check_s4()` — abstract methods implemented by each validator

`ValidationResult` dataclass returned by each validator:
- `s2_container_starts`: bool
- `s3_tests_pass`: bool
- `s4_deep_validation`: bool
- `container_logs`: str
- `test_details`: list[str]
- `container_id`: str

### Per-App Validators

| Validator | App | Checks |
|-----------|-----|--------|
| `a1_validator.py` | `a1_simple_script` | Parses multiplication table output; verifies 5x5 grid, checks statistics (mean=13, sum=325) |
| `a2_validator.py` | `a2_dependencies` | Validates data pipeline output format and statistical results |
| `a3_validator.py` | `a3_modular` | Checks ETL output: JSON file existence and report generation |
| `a4_validator.py` | `a4_server` | HTTP testing on dynamically allocated port: `GET /health`, `GET /items`, `POST`, `PUT`, `DELETE` CRUD cycle, `GET /stats` |
| `a5_validator.py` | `a5_configurable` | Verifies `config.json` was copied (checks `app_name == "DataProcessor-Configured"` vs default `"DataProcessor"`) |
| `a6_validator.py` | `a6_problematic` | Tests error recovery: dependency mismatch detection and correction |

The validator registry in `validators/__init__.py` maps each app name to its validator class via `VALIDATOR_REGISTRY` and exposes a `get_validator(app_name)` helper.

---

## CLI Entrypoint

`poc/cli.py` provides four commands via the `harness` script:

| Command | Description |
|---------|-------------|
| `run` | Execute the experiment (approaches x apps x repetitions) |
| `report` | Generate a comparison report from stored results |
| `status` | Show current run counts and experiment progress |
| `clear` | Delete all stored results (run directories + SQLite rows) |

### `run` Options

| Flag | Default | Description |
|------|---------|-------------|
| `--approach` | all | `controlled_process`, `mono_agent`, or `multi_agent` |
| `--app` | all | App name (e.g. `a1_simple_script`) |
| `--reps` | 5 | Number of repetitions |
| `--model` | `gpt-5-nano` | LLM model for agent approaches (e.g. `gpt-4o`, `gpt-4o-mini`) |
| `--no-cleanup` | off | Keep containers/images after run |
| `--dry-run` | off | Generate synthetic results without LLM/Docker calls |
| `-v, --verbose` | off | Show real-time agent logs (iterations, tool calls) |

### `report` / `status` / `clear` Options

| Flag | Applicable | Description |
|------|-----------|-------------|
| `--dry-run` | all | Operate on dry-run data. For `report`: merges real + dry-run data. For `status`/`clear`: targets dry-run storage only. |
| `--reps N` | `status` | Expected repetitions per app (default: 5). Used to compute total expected runs and per-app progress display. |

### Dry-Run Mode

`--dry-run` exercises the entire pipeline (CLI parsing, run loop, storage, scoring, normalization, report generation) without making any LLM calls or Docker operations. Synthetic `RawRunMetrics` are generated using:

- **Per-approach behavior profiles** — differentiated accuracy, token counts, and timing (controlled_process: cheap/fast, mono_agent: highest accuracy/expensive, multi_agent: medium)
- **Per-app adjustments** — a6_problematic always fails s3/s4, server apps (a4, a5) have longer times
- **Litellm pricing** — synthetic token counts are priced via `litellm.cost_per_token()` for realistic costs
- **Seeded RNG** — `random.Random(hash(run_id))` for reproducible results

Dry-run data is stored separately (see storage.py) and never pollutes real experiment results.

### Environment Variables

The CLI auto-loads a `.env` file from the project root (via `python-dotenv`).

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | Yes (for agent approaches) | OpenAI API key |
| `PYOPS_REGISTRY` | No | Docker registry for pushing images (e.g. `ghcr.io/user`) |

See `.env-example` for a template.

### Quick Start

```bash
# Copy and fill in your API key
cp .env-example .env

# Single test run with verbose output
uv run harness run --approach mono_agent --app a1_simple_script --reps 1 -v

# Different model
uv run harness run --approach mono_agent --app a1_simple_script --reps 1 --model gpt-4o -v

# Full experiment (all approaches, all apps, 5 reps each)
uv run harness run

# Dry run (no LLM/Docker calls, synthetic data)
uv run harness run --dry-run --reps 3
uv run harness report --dry-run
uv run harness status --dry-run
uv run harness clear --dry-run

# View report in different formats
uv run harness report
uv run harness report --format csv
uv run harness report --format json
uv run harness report --format latex

# Clear all results
uv run harness clear
```

**Note:** A comparison report is automatically printed after every individual run completes, so you can monitor progress in real time.

---

## Experiment Workflow

```
harness run
  └─> runner.run_experiment()
        ├─ for each approach in [controlled_process, mono_agent, multi_agent]:
        │    ├─ for each app in [a1..a6]:
        │    │    ├─ for repetition in [1..5]:
        │    │    │    ├─ cost_tracker.track(run_id)
        │    │    │    ├─ approach.run(app_source, run_id)  → ApproachResult
        │    │    │    ├─ validator.validate(image)          → ValidationResult
        │    │    │    ├─ docker_utils.push_image()          (optional)
        │    │    │    ├─ docker_utils.stop_and_remove()     (cleanup)
        │    │    │    ├─ storage.save_run(metrics)          → <run_id>/metrics.json + SQLite
        │    │    │    └─ report.generate_report()           → print live report
```

**Total runs per full experiment:** 3 approaches x 6 apps x 5 repetitions = **90 runs**

---
> Updated: 2026-03-17 | Model: claude-opus-4-6 | Initiated by: rt
