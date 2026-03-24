"""Load phase - persist processed records."""

import json
import os


OUTPUT_DIR = "output"


def save_results(records: list[dict], filename: str = "processed.json") -> str:
    """Save records as JSON file."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)
    return path
