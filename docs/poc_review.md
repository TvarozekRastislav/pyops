# Deep Review: PyOps POC vs Assignment

> Generated: 2026-03-16 | Reviewer: claude-opus-4-6

---

## 1. MISSING IMPLEMENTATION

### ~~1.1 Multi-Agent System (Approach 3) — NOT IMPLEMENTED~~ DONE
~~The assignment requires three approaches. `poc/multi_agent/__init__.py` is a 25-line stub that always returns failure.~~

**Fix:** Fully implemented multi-agent approach with orchestrator + 3 specialist sub-agents (Agent A: Docker image creation, Agent B: testing/validation, Agent C: registry push). Files: `orchestrator.py`, `sub_agent.py`, `prompts.py`.

### 1.2 No Automated Tests for the Harness Itself — DEFERRED
There are zero `pytest` tests for the infrastructure code (runner, scoring, storage, cost_tracker, validators, tools). For a PhD thesis, the evaluation framework itself should be validated.

**Status:** Deferred to a separate plan.

---

## 2. BUGS

### ~~2.1 Cost Tracker Uses Wrong Model Pricing (Critical)~~ FIXED
`runner.py:76` creates `TrackedOpenAIClient()` with no model argument, so it defaults to `"gpt-4o"`. The CLI `--model` parameter is passed to the approach but **never to the cost tracker**.

**Fix:** `runner.py:76` now passes `TrackedOpenAIClient(model=model)`.

### ~~2.2 GPT-5 Not in Pricing Table~~ FIXED (prior)
Replaced hardcoded pricing table with `litellm.cost_per_token()` which maintains up-to-date pricing for all models.

### ~~2.3 `t_build` Always Equals `t_total` (Critical)~~ FIXED
`runner.py:168` had `t_build = t_total` with no approach ever refining it.

**Fix:**
- Added `t_build: float = 0.0` to `BuildState` in `state.py`
- `tools.py:write_and_build_dockerfile()` now times the `docker_utils.build_image()` call with `time.monotonic()` and accumulates into `state.t_build`
- Added `t_build: float = 0.0` to `ApproachResult` in `interface.py`
- `BuildState.to_approach_result()` passes `t_build=self.t_build`
- `runner.py` uses `result.t_build if result.t_build > 0 else t_total`
- All three approaches get build time tracking automatically via shared `write_and_build_dockerfile`

### ~~2.4 s2 Semantics Are Wrong~~ FIXED
`validators/base.py:82`: `s2_container_starts = exit_code == 0` conflated "container started" with "ran correctly".

**Fix:** For script apps, s2 now checks `container_id != ""` (container was created). Server-mode s2 was already correct (checks `ready` = container running).

### ~~2.5 `read_source_code` Reads Binary Files~~ FIXED
`tools.py` walked all files including `__pycache__/*.pyc`, images, etc.

**Fix:** Added `_SKIP_DIRS` and `_SKIP_EXTENSIONS` sets. `os.walk` `dirs[:]` filtered in-place; files with matching extensions skipped.

### ~~2.6 A5 Validator Cannot Detect Missing `config.json`~~ FIXED
`config.json` had `"app_name": "DataProcessor"` which is identical to `DEFAULT_CONFIG` in `main.py:9`.

**Fix:** Changed `config.json` `app_name` to `"DataProcessor-Configured"`. Updated validator s4 to check for `"DataProcessor-Configured"`. Now: config copied = PASS, config missing (falls back to default "DataProcessor") = FAIL.

### ~~2.7 LaTeX Report Missing F_norm Column~~ FIXED
`report.py` header had 9 data columns but omitted `$F_n$`.

**Fix:** Added `r` to `\begin{tabular}` column spec, `$F_n$` to header, `{s['F_norm']:.3f}` to data rows.

### ~~2.8 Controlled Process Fix Loop Is Stateless~~ FIXED
`pipeline.py` created fresh messages for each fix request. LLM couldn't see previous fix attempts.

**Fix:** After initial generation, a `conversation` list is built containing the full system + generate + response history. `_request_fix` now appends fix prompts and assistant responses to this conversation, giving the LLM full context of prior attempts.

---

## 3. DESIGN ISSUES

### ~~3.1 Port Conflict Risk in A4 Validator~~ FIXED
`a4_validator.py` hardcoded `localhost:8000`.

**Fix:** Added `_find_free_port()` helper using `socket.bind(('', 0))`. `_validate_server()` allocates a free port stored as `self._allocated_port`. `A4Validator._get_ports()` maps the free host port to container port 8000. `check_s3`/`check_s4` use `self._allocated_port` for HTTP requests.

### 3.2 A6 Requires Network Access — NOT ADDRESSED
The A6 app fetches from `https://jsonplaceholder.typicode.com`. Containers without internet access will always fail. No fallback or mocking. This is an infrastructure-level concern, not a code bug.

### 3.3 Duplicate Docker Client Connections — SKIPPED
Each approach creates its own `docker_client` via `get_client()`, runner creates another. `docker.from_env()` is cheap and these are separate concerns (approach execution vs validation). Fixing requires changing the approach factory interface which is a larger refactor.

### ~~3.4 Status Command Hardcodes 5 Reps~~ FIXED
`cli.py:63` had `total_expected = ... * 5` ignoring actual `--reps` setting.

**Fix:** Added `--reps` arg to status subparser (default=5). Uses `args.reps` in total calculation and per-app display.

### 3.5 Normalization Weakness With < 3 Approaches — NOT ADDRESSED
Min-max normalization with only 2 approaches always gives 0.0 and 1.0. This is a mathematical property of the scoring formula, not a bug. Multi-agent is now implemented, so real experiments will have 3 approaches.

---

## 4. MINOR ISSUES

| Issue | Status | Notes |
|-------|--------|-------|
| ~~`_cleanup` function duplicated in all 3 `__init__.py` files~~ | **FIXED** | Moved to `BuildState.cleanup(docker_client)` in `state.py` |
| ~~Dry-run profiles for multi_agent generate data for stub~~ | **Resolved** | Multi-agent is now fully implemented |
| ~~No `poc/__init__.py`~~ | **FIXED** | Empty file exists |
| `prompt_tokens`/`completion_tokens` tracked but not persisted to metrics | Not addressed | Only `n_tokens` total is persisted; minor |

---

## 5. SUMMARY PRIORITY LIST

| Priority | Item | Status |
|----------|------|--------|
| **P0** | Implement multi_agent approach | **DONE** |
| **P0** | Fix `t_build` measurement (separate from `t_total`) | **FIXED** |
| **P0** | Fix cost tracker model mismatch | **FIXED** |
| **P1** | Fix s2 semantics (container starts != exit code 0) | **FIXED** |
| **P1** | Fix A5 validator to detect config.json absence | **FIXED** |
| **P1** | Filter binary files in `read_source_code` | **FIXED** |
| **P2** | Make fix loop stateful (controlled_process) | **FIXED** |
| **P2** | Fix LaTeX report F_norm column | **FIXED** |
| **P2** | Add harness unit tests | **DEFERRED** |
| **P3** | Dynamic port allocation for A4 | **FIXED** |
| **P3** | De-duplicate `_cleanup` function | **FIXED** |

---

## 6. WHAT IS SOLID

The harness architecture, scoring formulas, validators, storage, and reporting are well-built. All three approaches (controlled_process, mono_agent, multi_agent) are fully implemented with proper error handling, cleanup, and verbose logging. The dual-storage (JSON + SQLite), dry-run mode, and Rich terminal output are production-quality. The test applications (A1-A6) cover a good range of complexity and edge cases.

---
> Updated: 2026-03-17 | Model: claude-opus-4-6 | Initiated by: rt
