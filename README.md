# PyOps

PhD proof-of-concept comparing three LLM-based approaches to **automatically deploy
Python applications to Docker** from source code alone — no human ops engineer in
the loop.

Given a path to a Python application, the system produces a built and tested
Docker image (optionally pushed to a remote registry). The interesting question
is *how much agenticity* is the right amount: from a fixed pipeline that uses an
LLM only as a code generator, all the way to a multi-agent system with nested
sub-agents.

## The three approaches

| Approach | Agenticity | What the LLM does |
|---|---|---|
| `controlled_process` | Low | Deterministic pipeline; LLM only generates Dockerfile content and patches it on build errors |
| `mono_agent` | High | A single ReAct agent with all 6 tools, decides every step on its own |
| `multi_agent` | Modular | An orchestrator LLM delegates to three specialist sub-agents (build / test / push), each with its own context and filtered tool set |

All three approaches share the same tool implementations (`poc/tools.py`), the
same mutable `BuildState` (`poc/state.py`), and run through the same harness so
the comparison is apples-to-apples.

## Repository layout

```
poc/
  apps/                 6 test apps of varying complexity (a1_simple_script ... a6_problematic)
  controlled_process/   Approach 1: deterministic pipeline
  mono_agent/           Approach 2: single ReAct agent
  multi_agent/          Approach 3: orchestrator + sub-agents
  harness/              Runner, metrics, scoring, storage, reporting
  tools.py              Shared tool schemas + implementations
  state.py              Shared BuildState dataclass
  cli.py                `harness` CLI entry point
docs/                   Assignment, approach notes, harness docs
```

## Setup

The project uses [`uv`](https://github.com/astral-sh/uv) and a local virtualenv
at `.venv/`. All commands should go through `.venv/bin/harness` (or
`.venv/bin/python`), not bare `python`.

```bash
uv sync
cp .env-example .env   # then fill in OPENAI_API_KEY
```

Required environment variables:

- `OPENAI_API_KEY` — needed for any non-dry run (mono / multi / controlled all
  call the LLM)
- `PYOPS_REGISTRY` — optional; if set, built images are pushed there. If unset,
  the push phase is skipped and recorded as `f_push=fail`.

Docker must be reachable from the current user.

## Running experiments

The CLI is `harness` (defined in `pyproject.toml` as `poc.cli:main`).

```bash
# Dry-run — no LLM, no Docker, synthetic metrics. Good for plumbing checks.
.venv/bin/harness run --approach multi_agent --dry-run --reps 1

# Single approach, single app, verbose logs to stderr
.venv/bin/harness run --approach multi_agent --app a1_simple_script --reps 1 -v

# Full grid: all 3 approaches × all 6 apps × 5 repetitions = 90 runs
.venv/bin/harness run --reps 5

# See progress so far
.venv/bin/harness status --reps 5

# Generate a comparison report (table | csv | json | latex)
.venv/bin/harness report --format table

# Wipe stored results
.venv/bin/harness clear
```

Useful flags on `run`:

- `--model` — LLM model for the agent approaches (default `gpt-5-nano`)
- `--no-cleanup` — keep containers and images after the run for inspection
- `-v` / `--verbose` — stream per-iteration tool calls and agent responses

## Evaluation

Each run is scored on four metrics, aggregated into a single score `S`:

```
S = 0.70·Accuracy + 0.20·Cost + 0.05·Time + 0.05·Stability
```

- **Accuracy (70%)** — weighted binary score over `build / start / tests pass /
  manual functionality` (weights 15 / 20 / 30 / 35)
- **Cost (20%)** — total LLM token spend per run, tracked by
  `harness/cost_tracker.py`
- **Time (5%)** — total wall time and Docker build time
- **Stability (5%)** — failure counts per phase across repetitions

See `docs/assigment.md` for the full methodology.

## Status

Proof-of-concept stage. The harness, all three approaches, the six test apps,
and the metric pipeline are in place; the dissertation experiments themselves
(multi-model comparison, larger app set) are future work.
