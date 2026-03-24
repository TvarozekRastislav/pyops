"""Report generation from processed records."""

from collections import Counter


def generate_report(records: list[dict]) -> str:
    """Generate a text summary report."""
    if not records:
        return "No records to report."

    temps = [r["temperature"] for r in records]
    categories = Counter(r["temp_category"] for r in records)
    sensors = Counter(r["sensor"] for r in records)

    lines = [
        "=== Pipeline Report ===",
        f"Total records: {len(records)}",
        f"Temperature range: {min(temps):.1f} - {max(temps):.1f} C",
        f"Average temperature: {sum(temps) / len(temps):.1f} C",
        "",
        "Category distribution:",
    ]
    for cat, count in categories.most_common():
        lines.append(f"  {cat}: {count}")

    lines.append("")
    lines.append("Sensor distribution:")
    for sensor, count in sensors.most_common():
        lines.append(f"  {sensor}: {count}")

    return "\n".join(lines)
