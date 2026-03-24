"""Main orchestration loop: approach x app x repetition."""

from __future__ import annotations

import importlib
import random
import time
from pathlib import Path

import docker

from .cost_tracker import TrackedOpenAIClient
from .docker_utils import (
    get_client,
    push_image as docker_push,
    remove_image,
    stop_and_remove,
    tag_image,
)
from .interface import Approach, ApproachResult
from .metrics import RawRunMetrics
from .report import generate_report
from .storage import load_run, save_run
from .validators import get_validator

APPS_DIR = Path(__file__).resolve().parent.parent / "apps"

APPROACH_REGISTRY = {
    "controlled_process": "poc.controlled_process",
    "mono_agent": "poc.mono_agent",
    "multi_agent": "poc.multi_agent",
}

ALL_APPS = [
    "a1_simple_script",
    "a2_dependencies",
    "a3_modular",
    "a4_server",
    "a5_configurable",
    "a6_problematic",
]


def load_approach(
    name: str, client: TrackedOpenAIClient, **kwargs
) -> Approach:
    """Import and instantiate an approach by name."""
    module_path = APPROACH_REGISTRY.get(name)
    if module_path is None:
        raise ValueError(
            f"Unknown approach: {name}. Available: {list(APPROACH_REGISTRY)}"
        )
    module = importlib.import_module(module_path)
    return module.create_approach(client, **kwargs)


def run_experiment(
    approaches: list[str] | None = None,
    apps: list[str] | None = None,
    reps: int = 5,
    registry: str | None = None,
    no_cleanup: bool = False,
    model: str = "gpt-4o",
    dry_run: bool = False,
) -> list[RawRunMetrics]:
    """Execute the full experiment loop."""
    approaches = approaches or list(APPROACH_REGISTRY.keys())
    apps = apps or ALL_APPS

    all_metrics: list[RawRunMetrics] = []
    total = len(approaches) * len(apps) * reps
    completed = 0

    if not dry_run:
        docker_client = get_client()
        openai_client = TrackedOpenAIClient(model=model)

    for approach_name in approaches:
        if not dry_run:
            approach = load_approach(approach_name, openai_client, model=model)

        print(f"\n{'=' * 60}")
        print(f"Approach: {approach_name}" if dry_run else f"Approach: {approach.name}")
        print(f"{'=' * 60}")

        for app_name in apps:
            if not dry_run:
                validator = get_validator(app_name)
                app_path = APPS_DIR / app_name

                if not app_path.exists():
                    print(f"  WARNING: app path {app_path} not found, skipping")
                    continue

            for rep in range(1, reps + 1):
                completed += 1
                run_id = f"{approach_name}_{app_name}_{rep}"

                # Check cache — skip already-completed runs
                cached = load_run(run_id, dry_run=dry_run)
                if cached is not None:
                    print(f"\n  [{completed}/{total}] {run_id}  (cached)")
                    metrics = RawRunMetrics(**cached)
                    all_metrics.append(metrics)
                    continue

                print(f"\n  [{completed}/{total}] {run_id}")

                if dry_run:
                    metrics = _generate_dry_run_metrics(
                        approach_name, app_name, rep, model,
                    )
                else:
                    metrics = _execute_single_run(
                        run_id=run_id,
                        approach=approach,
                        approach_name=approach_name,
                        app_name=app_name,
                        app_path=app_path,
                        rep=rep,
                        model=model,
                        validator=validator,
                        docker_client=docker_client,
                        openai_client=openai_client,
                        registry=registry,
                        no_cleanup=no_cleanup,
                    )

                save_run(metrics, dry_run=dry_run)
                all_metrics.append(metrics)

                status = "PASS" if metrics.s3_tests_pass else "FAIL"
                print(
                    f"    s1={metrics.s1_build} s2={metrics.s2_container_starts} "
                    f"s3={metrics.s3_tests_pass} s4={metrics.s4_deep_validation} "
                    f"[{status}]"
                )

                print()
                generate_report(dry_run=dry_run)

    return all_metrics


def _execute_single_run(
    *,
    run_id: str,
    approach: Approach,
    approach_name: str,
    app_name: str,
    app_path: Path,
    rep: int,
    model: str,
    validator,
    docker_client: docker.DockerClient,
    openai_client: TrackedOpenAIClient,
    registry: str | None,
    no_cleanup: bool,
) -> RawRunMetrics:
    """Execute a single approach+app+rep run and return metrics."""
    t_start = time.time()

    with openai_client.track(run_id):
        try:
            result = approach.run(app_path, run_id)
        except Exception as e:
            result = ApproachResult(
                build_succeeded=False,
                error=str(e),
            )

    t_total = time.time() - t_start

    # s1: build succeeded?
    s1 = result.build_succeeded
    f_build = not s1
    t_build = result.t_build if result.t_build > 0 else t_total

    # s2, s3, s4: validate
    f_run = False
    vr = None
    try:
        vr = validator.validate(result, docker_client)
    except Exception as e:
        f_run = True
        print(f"    Validation error: {e}")

    s2 = vr.s2_container_starts if vr else False
    s3 = vr.s3_tests_pass if vr else False
    s4 = vr.s4_deep_validation if vr else False
    container_logs = vr.container_logs if vr else ""
    test_details = vr.details_str if vr else ""

    # Push image to registry
    f_push = False if not registry else True
    if registry and result.build_succeeded and result.image_name:
        local_tag = (
            f"{result.image_name}:{result.image_tag}"
            if result.image_tag
            else result.image_name
        )
        remote_tag = f"{registry}/pyops-{app_name}:{approach_name}-{rep}"
        if tag_image(docker_client, local_tag, remote_tag):
            push_ok, push_log = docker_push(docker_client, remote_tag)
            f_push = not push_ok
            if not push_ok:
                print(f"    Push failed: {push_log[:200]}")
        else:
            print(f"    Tag failed for {local_tag} -> {remote_tag}")

    # Get cost tracking data
    usage = openai_client.get_usage(run_id)

    # Cleanup
    if not no_cleanup and vr and vr.container_id:
        stop_and_remove(docker_client, vr.container_id)
    if not no_cleanup and result.image_name:
        local_tag = (
            f"{result.image_name}:{result.image_tag}"
            if result.image_tag
            else result.image_name
        )
        remove_image(docker_client, local_tag)

    return RawRunMetrics(
        run_id=run_id,
        approach=approach_name,
        app=app_name,
        repetition=rep,
        model=model,
        s1_build=s1,
        s2_container_starts=s2,
        s3_tests_pass=s3,
        s4_deep_validation=s4,
        cost_usd=usage.cost_usd,
        n_calls=usage.n_calls,
        n_tokens=usage.total_tokens,
        t_total=t_total,
        t_build=t_build,
        f_build=f_build,
        f_run=f_run,
        f_push=f_push,
        dockerfile_content=result.dockerfile_content,
        build_log=result.build_log,
        container_logs=container_logs,
        test_details=test_details,
    )


# -- Approach behavior profiles for dry-run -----------------------------------
_DRY_RUN_PROFILES = {
    "controlled_process": {"s1": 0.95, "s2": 0.90, "s3": 0.85, "s4": 0.80,
                           "time": (8, 15), "calls": (3, 6),
                           "prompt_tokens": (500, 1200), "completion_tokens": (200, 600)},
    "mono_agent":         {"s1": 0.98, "s2": 0.95, "s3": 0.92, "s4": 0.90,
                           "time": (20, 40), "calls": (8, 15),
                           "prompt_tokens": (2000, 5000), "completion_tokens": (800, 2500)},
    "multi_agent":        {"s1": 0.95, "s2": 0.85, "s3": 0.60, "s4": 0.40,
                           "time": (15, 30), "calls": (6, 10),
                           "prompt_tokens": (1500, 3500), "completion_tokens": (600, 1800)},
}

_APP_ADJUSTMENTS = {
    "a4_server":      {"time_mult": 1.5},
    "a5_configurable": {"time_mult": 1.3},
    "a6_problematic": {"s3_override": 0.0, "s4_override": 0.0},
}


def _generate_dry_run_metrics(
    approach_name: str, app_name: str, rep: int, model: str,
) -> RawRunMetrics:
    """Generate synthetic metrics for a dry run (no LLM/Docker calls)."""
    run_id = f"{approach_name}_{app_name}_{rep}"
    rng = random.Random(hash(run_id))

    profile = _DRY_RUN_PROFILES.get(approach_name, _DRY_RUN_PROFILES["controlled_process"])
    adj = _APP_ADJUSTMENTS.get(app_name, {})

    s1 = rng.random() < profile["s1"]
    s2 = s1 and rng.random() < profile["s2"]
    s3_prob = adj.get("s3_override", profile["s3"])
    s3 = s2 and rng.random() < s3_prob
    s4_prob = adj.get("s4_override", profile["s4"])
    s4 = s3 and rng.random() < s4_prob

    time_mult = adj.get("time_mult", 1.0)
    t_total = rng.uniform(*profile["time"]) * time_mult
    t_build = t_total * rng.uniform(0.3, 0.6)
    n_calls = rng.randint(*profile["calls"])
    prompt_tokens = rng.randint(*profile["prompt_tokens"])
    completion_tokens = rng.randint(*profile["completion_tokens"])
    n_tokens = prompt_tokens + completion_tokens

    # Compute cost using litellm's pricing database
    try:
        from litellm import cost_per_token
        p_cost, c_cost = cost_per_token(
            model=model, prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
        cost = p_cost + c_cost
    except Exception:
        cost = 0.0

    return RawRunMetrics(
        run_id=run_id,
        approach=approach_name,
        app=app_name,
        repetition=rep,
        model=model,
        s1_build=s1,
        s2_container_starts=s2,
        s3_tests_pass=s3,
        s4_deep_validation=s4,
        cost_usd=round(cost, 6),
        n_calls=n_calls,
        n_tokens=n_tokens,
        t_total=round(t_total, 2),
        t_build=round(t_build, 2),
        f_build=not s1,
        f_run=not s2 if s1 else False,
        f_push=True,
        dockerfile_content="# dry-run synthetic Dockerfile\nFROM python:3.12-slim\nCOPY . /app\nCMD [\"python\", \"main.py\"]",
        build_log="[dry-run] synthetic build log",
        container_logs="[dry-run] synthetic container output",
        test_details="[dry-run] synthetic test results",
    )
