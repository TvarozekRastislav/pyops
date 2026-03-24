"""Data fetcher application."""

import json
import os


def fetch_data(url: str) -> dict:
    """Fetch data from a remote API."""
    import requests
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    return response.json()


def process_data(data: dict) -> dict:
    """Process the fetched data."""
    if not isinstance(data, dict):
        raise TypeError(f"Expected dict, got {type(data).__name__}")

    result = {
        "keys": list(data.keys()),
        "total_values": len(data),
        "has_nested": any(isinstance(v, (dict, list)) for v in data.values()),
    }
    return result


def save_output(data: dict, path: str = None) -> str:
    """Save processed data to a file."""
    if path is None:
        path = os.path.join("results", "output.json")

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    return path


def main() -> None:
    url = os.environ.get("DATA_URL", "https://jsonplaceholder.typicode.com/todos/1")
    print(f"Fetching data from: {url}")

    data = fetch_data(url)
    print(f"Received: {json.dumps(data, indent=2)}")

    result = process_data(data)
    print(f"Processed: {result}")

    output_path = save_output(result)
    print(f"Saved to: {output_path}")


def run():
    main()


if __name__ == "__main__":
    main()
