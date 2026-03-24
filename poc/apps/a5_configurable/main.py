"""Batch data processor with external configuration."""

import json
import os
import sys


DEFAULT_CONFIG = {
    "app_name": "DataProcessor",
    "log_level": "INFO",
    "batch_size": 10,
    "output_format": "json",
    "max_retries": 3,
    "database_url": "sqlite:///data.db",
    "api_key": "",
    "features": {
        "enable_cache": True,
        "enable_notifications": False,
    },
}


def load_config() -> dict:
    """Load configuration from environment variables and optional config file."""
    config = DEFAULT_CONFIG.copy()

    # Override from config file if present
    config_path = os.environ.get("APP_CONFIG_PATH", "config.json")
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            file_config = json.load(f)
        config.update(file_config)
        print(f"Loaded config from: {config_path}")

    # Override from environment variables
    env_mappings = {
        "APP_NAME": "app_name",
        "LOG_LEVEL": "log_level",
        "BATCH_SIZE": ("batch_size", int),
        "OUTPUT_FORMAT": "output_format",
        "MAX_RETRIES": ("max_retries", int),
        "DATABASE_URL": "database_url",
        "API_KEY": "api_key",
    }

    for env_key, mapping in env_mappings.items():
        value = os.environ.get(env_key)
        if value is not None:
            if isinstance(mapping, tuple):
                config_key, cast_fn = mapping
                config[config_key] = cast_fn(value)
            else:
                config[mapping] = value

    return config


def validate_config(config: dict) -> list[str]:
    """Validate configuration and return list of warnings."""
    warnings = []
    if not config.get("api_key"):
        warnings.append("API_KEY is not set - some features will be disabled")
    if config["batch_size"] <= 0:
        warnings.append("BATCH_SIZE must be positive, using default")
        config["batch_size"] = DEFAULT_CONFIG["batch_size"]
    if config["log_level"] not in ("DEBUG", "INFO", "WARNING", "ERROR"):
        warnings.append(f"Unknown LOG_LEVEL '{config['log_level']}', defaulting to INFO")
        config["log_level"] = "INFO"
    return warnings


def process_batch(data: list[int], config: dict) -> dict:
    """Process a batch of data according to configuration."""
    batch_size = config["batch_size"]
    results = []
    for i in range(0, len(data), batch_size):
        batch = data[i:i + batch_size]
        results.append({
            "batch_index": i // batch_size,
            "count": len(batch),
            "sum": sum(batch),
            "avg": sum(batch) / len(batch) if batch else 0,
        })
    return {
        "app_name": config["app_name"],
        "total_records": len(data),
        "batches_processed": len(results),
        "batch_results": results,
    }


def main() -> None:
    print("Loading configuration...")
    config = load_config()

    warnings = validate_config(config)
    for w in warnings:
        print(f"  WARNING: {w}")

    print(f"\nActive configuration:")
    for key, value in config.items():
        if key == "api_key" and value:
            print(f"  {key}: ***hidden***")
        else:
            print(f"  {key}: {value}")

    # Process sample data
    data = list(range(1, 51))
    print(f"\nProcessing {len(data)} records in batches of {config['batch_size']}...")
    results = process_batch(data, config)

    if config["output_format"] == "json":
        output = json.dumps(results, indent=2)
    else:
        output = str(results)

    print(f"\nResults ({config['output_format']}):")
    print(output)


if __name__ == "__main__":
    main()
