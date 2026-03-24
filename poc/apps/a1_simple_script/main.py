"""Multiplication table generator with basic statistics."""

import math
import statistics
import sys


def multiplication_table(n: int) -> list[list[int]]:
    """Return an n x n multiplication table."""
    return [[i * j for j in range(1, n + 1)] for i in range(1, n + 1)]


def print_table(table: list[list[int]]) -> None:
    width = len(str(max(row[-1] for row in table)))
    for row in table:
        print("  ".join(str(cell).rjust(width) for cell in row))


def compute_stats(numbers: list[float]) -> dict:
    return {
        "count": len(numbers),
        "mean": statistics.mean(numbers),
        "median": statistics.median(numbers),
        "stdev": statistics.stdev(numbers) if len(numbers) > 1 else 0.0,
        "min": min(numbers),
        "max": max(numbers),
        "sum": math.fsum(numbers),
    }


def main() -> None:
    size = int(sys.argv[1]) if len(sys.argv) > 1 else 5

    print(f"Multiplication table ({size}x{size}):")
    print_table(multiplication_table(size))

    numbers = [float(x) for x in range(1, size * size + 1)]
    stats = compute_stats(numbers)
    print("\nStatistics for values 1..{}: ".format(size * size))
    for key, value in stats.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
