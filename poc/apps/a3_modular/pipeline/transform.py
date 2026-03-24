"""Transform phase - clean and enrich raw records."""

import datetime


TEMP_MIN = -40.0
TEMP_MAX = 60.0


def clean_records(records: list[dict]) -> list[dict]:
    """Remove records with out-of-range temperature values."""
    return [
        r for r in records
        if TEMP_MIN <= r["temperature"] <= TEMP_MAX
    ]


def enrich_records(records: list[dict]) -> list[dict]:
    """Add derived fields to each record."""
    enriched = []
    for r in records:
        ts = datetime.datetime.fromisoformat(r["timestamp"])
        enriched.append({
            **r,
            "hour": ts.hour,
            "day_of_week": ts.strftime("%A"),
            "temp_category": _categorize_temp(r["temperature"]),
        })
    return enriched


def _categorize_temp(temp: float) -> str:
    if temp < 10:
        return "cold"
    elif temp < 25:
        return "normal"
    else:
        return "hot"
