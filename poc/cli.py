"""PyOps CLI entrypoint."""

import argparse
import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()


def cmd_run(args):
    from .harness.runner import run_experiment

    if args.verbose:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(name)s %(message)s",
            datefmt="%H:%M:%S",
            stream=sys.stderr,
        )

    approaches = args.approach if args.approach else None
    apps = [args.app] if args.app else None
    registry = os.environ.get("PYOPS_REGISTRY")

    if not registry:
        print("WARNING: PYOPS_REGISTRY not set. Push will be skipped (f_push=fail).")

    results = run_experiment(
        approaches=approaches,
        apps=apps,
        reps=args.reps,
        registry=registry,
        no_cleanup=args.no_cleanup,
        model=args.model,
        dry_run=args.dry_run,
    )

    print(f"\nCompleted {len(results)} runs.")
    passed = sum(1 for r in results if r.s3_tests_pass)
    print(f"  s3 pass rate: {passed}/{len(results)}")


def cmd_report(args):
    from .harness.report import generate_report

    text = generate_report(
        fmt=args.format, output_path=args.output, dry_run=args.dry_run,
    )
    if text:
        print(text)


def cmd_status(args):
    from .harness.runner import ALL_APPS, APPROACH_REGISTRY
    from .harness.storage import count_runs, load_all_runs

    dry_run = args.dry_run
    reps = args.reps
    runs = load_all_runs(dry_run=dry_run)
    counts = count_runs(dry_run=dry_run)
    total_expected = len(APPROACH_REGISTRY) * len(ALL_APPS) * reps
    label = " (dry-run)" if dry_run else ""

    print(f"PyOps Status{label}: {len(runs)}/{total_expected} runs completed")
    print()

    if counts:
        for (approach, app), count in sorted(counts.items()):
            print(f"  {approach}/{app}: {count}/{reps} reps")
    else:
        print("  No runs recorded yet.")


def cmd_clear(args):
    from .harness.storage import clear_all_runs

    dry_run = args.dry_run
    count = clear_all_runs(dry_run=dry_run)
    label = "dry-run " if dry_run else ""
    print(f"Cleared {count} {label}runs.")


def main():
    parser = argparse.ArgumentParser(
        prog="harness", description="PyOps test harness"
    )
    sub = parser.add_subparsers(dest="command")

    # run
    p_run = sub.add_parser("run", help="Run experiments")
    p_run.add_argument(
        "--approach",
        nargs="+",
        choices=["controlled_process", "mono_agent", "multi_agent"],
        help="One or more approaches to run (default: all)",
    )
    p_run.add_argument("--app", help="App name (e.g. a1_simple_script)")
    p_run.add_argument(
        "--reps", type=int, default=5, help="Number of repetitions (default: 5)"
    )
    p_run.add_argument(
        "--model",
        default="gpt-5-nano",
        help="LLM model for agent approaches (default: gpt-5-nano)",
    )
    p_run.add_argument(
        "--no-cleanup",
        action="store_true",
        help="Keep containers/images after run",
    )
    p_run.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate synthetic results without LLM/Docker calls",
    )
    p_run.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Show real-time agent logs",
    )

    # report
    p_report = sub.add_parser("report", help="Generate comparison report")
    p_report.add_argument(
        "--format",
        choices=["table", "csv", "json", "latex"],
        default="table",
    )
    p_report.add_argument("--output", help="Output file path")
    p_report.add_argument(
        "--dry-run", action="store_true",
        help="Include dry-run data (merged with real runs if any)",
    )

    # status
    p_status = sub.add_parser("status", help="Show experiment progress")
    p_status.add_argument(
        "--reps", type=int, default=5,
        help="Expected repetitions per app (default: 5)",
    )
    p_status.add_argument(
        "--dry-run", action="store_true",
        help="Show dry-run status",
    )

    # clear
    p_clear = sub.add_parser("clear", help="Delete all stored results")
    p_clear.add_argument(
        "--dry-run", action="store_true",
        help="Clear only dry-run results",
    )

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        sys.exit(1)

    {"run": cmd_run, "report": cmd_report, "status": cmd_status, "clear": cmd_clear}[
        args.command
    ](args)


if __name__ == "__main__":
    main()
