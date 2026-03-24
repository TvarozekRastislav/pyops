"""Data pipeline - extract, transform, load and report."""

from pipeline.extract import extract_records
from pipeline.transform import clean_records, enrich_records
from pipeline.load import save_results
from pipeline.report import generate_report


def main() -> None:
    print("=== Data Pipeline ===")

    print("[1/4] Extracting records...")
    raw = extract_records()
    print(f"      Extracted {len(raw)} records")

    print("[2/4] Cleaning records...")
    cleaned = clean_records(raw)
    print(f"      {len(cleaned)} records after cleaning")

    print("[3/4] Enriching records...")
    enriched = enrich_records(cleaned)
    print(f"      {len(enriched)} enriched records")

    print("[4/4] Saving results...")
    output_path = save_results(enriched)
    print(f"      Results saved to {output_path}")

    report = generate_report(enriched)
    print("\n" + report)


if __name__ == "__main__":
    main()
