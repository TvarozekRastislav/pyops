# PyOps - Automated Python Application Deployment Using GenAI

## Goal

Build a platform/application that **automatically deploys Python applications to production** based solely on provided source code. The system uses **Generative AI (LLM)** to replace the operational engineer in the deployment process.

**Input**: Path to Python application source code
**Output**: Reference to a built and tested Docker image (pushed to remote repository)

The user provides only the source code path. Everything else (Dockerfile creation, image building, testing, pushing) is handled autonomously by the system.

## Problem Statement

Deploying applications to production is repetitive, time-consuming, and error-prone. Operational engineers must:
1. Analyze the source code
2. Create a Dockerfile
3. Build a Docker image
4. Test the container
5. Push to a remote registry
6. Create Kubernetes manifests

This work focuses on the **Docker part** (steps 1-5). Kubernetes deployment is noted as a future extension.

## Three Approaches to Compare

The thesis proposes and compares **three architecturally different approaches** to solve this problem using LLM:

### 1. Controlled Process (Riadeny Proces) - `poc/controlled_process/`

- **Low agenticity** - deterministic pipeline with LLM used only for specific transformation steps
- Steps are fixed and sequential: Read Code → Generate Dockerfile (LLM) → Build Image → Fix Dockerfile if error (LLM) → Test → Push
- LLM acts as an expert system encoded in a single prompt, no autonomous decision-making
- Has feedback loops: if Docker build fails, error is sent back to LLM to fix the Dockerfile
- Predictable, easy to validate, lower risk of unwanted autonomy

### 2. Monolithic Agent (Monoliticky Agent) - `poc/mono_agent/`

- **High agenticity** - single LLM agent with access to tools, makes all decisions autonomously
- Agent receives source code as input and autonomously decides what to do
- Tools available: read source code, create Docker image, run Docker image, test container, upload to repository
- Uses observation-action-feedback loop: after each tool action, result is observed and next step decided
- Agent decides when the process is complete
- Single prompt, single context, single decision-making unit

### 3. Multi-Agent System (Multi-agenticky System) - `poc/multi_agent/`

- **Modular agenticity** - central orchestrator agent delegates to specialized sub-agents
- Architecture uses **nested agents** pattern (vnoreni agenti)
- **Central Agent**: orchestrator, does not execute steps directly, delegates to sub-agents
- **Agent A (Docker Image Agent)**: analyzes source code, creates Dockerfile, builds Docker image
- **Agent B (Testing Agent)**: runs and tests the built container
- **Agent C (Finalization Agent)**: pushes verified image to remote repository
- Each agent has its own prompt, context, and limited tool set
- Agents communicate only through the central agent (no direct inter-agent communication)

## Experimental Methodology

### Test Applications (`poc/apps/`)

Six Python applications of varying complexity are used to validate all three approaches. Each app is processed by each methodology **5 times** (due to non-deterministic LLM outputs), yielding **90 total experimental runs** (6 apps × 3 methods × 5 repetitions).

### Evaluation Metrics

Four metrics are tracked per run:

#### 1. Accuracy (Presnost) - weight 70%
Weighted binary score based on 4 sub-tasks:
- **Docker image builds successfully** (w₁ = 15 points)
- **Docker container starts successfully** (w₂ = 20 points)
- **Automated tests pass** (w₃ = 30 points)
- **Manual functionality verification passes** (w₄ = 35 points)

Formula: `Accuracy% = (Σ sᵢ·wᵢ / Σ wᵢ) × 100`

#### 2. Cost (Nakladovost) - weight 20%
- Total estimated cost of all LLM API calls per run
- Number of LLM calls (N_calls)
- Total tokens used (N_tokens)

#### 3. Time Complexity (Casova Narocnost) - weight 5%
- Total run time T_total [s]
- Docker build time T_build [s]
- Formula: `TimeComplexity = 0.9 · (1/T_total) + 0.1 · (1/T_build)`

#### 4. Stability (Stabilita) - weight 5%
Failure count per phase across all runs:
- F_build: failures during Docker image creation
- F_run: failures during container startup
- F_push: failures during image push to registry

#### Aggregated Score
`S = 0.70·A_norm + 0.20·C_norm + 0.05·T_norm + 0.05·F_norm`

All metrics normalized to [0, 1] before aggregation.

### Experimental Environment
- Docker Desktop 4.50.0
- Python 3.13
- LLM: GPT-5 (OpenAI) — single model for initial experiments, multi-model comparison planned for dissertation
- OS: Windows 10 (Intel i5-11300H, 16GB RAM)

## Technology Stack

- **Containerization**: Docker
- **Orchestration**: Kubernetes (future scope)
- **Python environment**: pip (chosen for simplicity with LLM)
- **API framework**: FastAPI (for server-type apps)
- **Web framework**: Flask (for web apps)
- **LLM integration**: OpenAI API

---

## Test Cases (poc/apps/)

### A1 - Simple Script (`a1_simple_script/`)

| Attribute | Value |
|-----------|-------|
| **Type** | Simple script application (Jednoducha skriptova aplikacia) |
| **Tested Aspect** | Basic functionality (Zakladna funkcnost) |
| **Structure** | Single file, no packages |
| **Dependencies** | None (stdlib only) |
| **Description** | Generates multiplication table and computes statistics on a list of numbers. Uses only `math`, `statistics`, `sys` from stdlib. |
| **What it validates** | Can the system containerize the most trivial Python script? Correct base image selection, entry point identification, basic Dockerfile generation. |
| **Expected Dockerfile challenge** | Minimal — should be straightforward. Base image + COPY + CMD. |

### A2 - Application with Dependencies (`a2_dependencies/`)

| Attribute | Value |
|-----------|-------|
| **Type** | Application with dependencies (Aplikacia so zavislostami) |
| **Tested Aspect** | Dependency handling and Docker image build stability (Spracovanie zavislosti a stabilita vytvarania Docker Image) |
| **Structure** | Single file + requirements.txt |
| **Dependencies** | pandas, numpy, matplotlib |
| **Description** | Generates simulated sensor data, cleans anomalies, aggregates per-sensor stats, and produces a matplotlib chart saved as PNG. |
| **What it validates** | Can the system correctly detect and install dependencies from requirements.txt? Handles heavier packages (numpy/pandas build times, matplotlib backend config). |
| **Expected Dockerfile challenge** | Must install requirements.txt, may need system-level deps for matplotlib. Agg backend usage is embedded in code. |

### A3 - Modular Application (`a3_modular/`)

| Attribute | Value |
|-----------|-------|
| **Type** | Modular application (Modularna aplikacia) |
| **Tested Aspect** | Project structure analysis and entry-point identification (Analyza projektovej struktury a identifikacia vstupneho bodu) |
| **Structure** | main.py + pipeline/ package (4 modules: extract, transform, load, report) |
| **Dependencies** | None (stdlib only) |
| **Description** | ETL-style data pipeline: extracts simulated sensor data, cleans/enriches it, saves as JSON, generates text report. |
| **What it validates** | Can the system correctly analyze a multi-file project? Identifies main.py as entry point, understands package imports, copies entire project structure into container. |
| **Expected Dockerfile challenge** | Must COPY entire directory (not just main.py). Must preserve package structure so `from pipeline.extract import ...` works. |

### A4 - Server Application (`a4_server/`)

| Attribute | Value |
|-----------|-------|
| **Type** | Server application (Serverova aplikacia) |
| **Tested Aspect** | Container startup and network accessibility testing (Testovanie spustenia kontajnera a sietovej dostupnosti) |
| **Structure** | Single file + requirements.txt |
| **Dependencies** | fastapi, uvicorn |
| **Description** | FastAPI REST API for inventory management. CRUD endpoints for items + /health and /stats. In-memory storage. |
| **What it validates** | Can the system recognize this is a server app (not a script)? Must use `uvicorn main:app` as CMD, expose correct port, and the container must stay running (not exit immediately). |
| **Expected Dockerfile challenge** | Must detect FastAPI pattern, set correct CMD (`uvicorn main:app --host 0.0.0.0 --port 8000`), EXPOSE port. Testing requires HTTP requests to verify endpoints respond. |

### A5 - Configurable Application (`a5_configurable/`)

| Attribute | Value |
|-----------|-------|
| **Type** | Configurable application (Konfigurovatelna aplikacia) |
| **Tested Aspect** | Inference and correct setting of configuration parameters (Inferencia a spravne nastavenie konfiguracnych parametrov) |
| **Structure** | main.py + config.json |
| **Dependencies** | None (stdlib only) |
| **Description** | Data processor that reads config from environment variables and/or config.json file. Processes data in configurable batches. |
| **What it validates** | Can the system detect that config.json must be included in the image? Can it identify env var usage (APP_CONFIG_PATH, APP_NAME, LOG_LEVEL, etc.) and optionally set defaults? |
| **Expected Dockerfile challenge** | Must COPY config.json alongside main.py. May need to set ENV variables or document them. The app should run with defaults even without explicit env var configuration. |

### A6 - Problematic Application (`a6_problematic/`)

| Attribute | Value |
|-----------|-------|
| **Type** | Problematic application (Problemova aplikacia) |
| **Tested Aspect** | System robustness and ability to handle error states (Robustnost systemu a schopnost riesit chybove stavy) |
| **Structure** | main.py + requirements.txt (broken) |
| **Dependencies** | requests (used in code but listed as `python-requests` in requirements.txt), `data-helpers-toolkit` (non-existent package) |
| **Description** | Fetches data from a REST API, processes it, saves output. Code is functional but requirements.txt has wrong package names. |
| **What it validates** | How does the system handle a broken requirements.txt? Can it detect the mismatch between `import requests` in code and `python-requests` in requirements? Can it recover from `pip install` failures? Tests the feedback loop / error correction capabilities. |
| **Expected Dockerfile challenge** | `pip install` will fail. The system must either: (a) fix requirements.txt automatically, (b) use the error feedback loop to correct the Dockerfile, or (c) detect the issue during code analysis. This is the hardest test case. |

---
> Updated: 2026-03-16 | Model: claude-opus-4-6 | Initiated by: rt
