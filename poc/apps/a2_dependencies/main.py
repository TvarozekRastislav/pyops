"""Sensor data processor with visualization."""

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def generate_sensor_data(n_samples: int = 100, seed: int = 42) -> pd.DataFrame:
    """Simulate sensor readings with some anomalies."""
    rng = np.random.default_rng(seed)
    timestamps = pd.date_range("2026-01-01", periods=n_samples, freq="h")
    temperature = rng.normal(loc=21.5, scale=2.0, size=n_samples)
    humidity = rng.normal(loc=55.0, scale=10.0, size=n_samples)

    anomaly_idx = rng.choice(n_samples, size=5, replace=False)
    temperature[anomaly_idx] = rng.uniform(-99, -50, size=5)

    return pd.DataFrame({
        "timestamp": timestamps,
        "sensor_id": rng.choice(["S1", "S2", "S3"], size=n_samples),
        "temperature": temperature,
        "humidity": humidity,
    })


def clean_data(df: pd.DataFrame) -> pd.DataFrame:
    """Remove anomalous temperature readings."""
    mask = (df["temperature"] > -30) & (df["temperature"] < 60)
    cleaned = df[mask].copy()
    cleaned["timestamp"] = pd.to_datetime(cleaned["timestamp"])
    return cleaned


def aggregate(df: pd.DataFrame) -> pd.DataFrame:
    """Compute per-sensor averages."""
    result = df.groupby("sensor_id")[["temperature", "humidity"]].agg(
        ["mean", "std", "min", "max"]
    )
    result.columns = ["_".join(col) for col in result.columns]
    return result.reset_index()


def plot_results(df: pd.DataFrame, output_path: str = "sensor_report.png") -> str:
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    for sensor_id, group in df.groupby("sensor_id"):
        axes[0].plot(group["timestamp"], group["temperature"], label=sensor_id, alpha=0.7)
        axes[1].plot(group["timestamp"], group["humidity"], label=sensor_id, alpha=0.7)

    axes[0].set_title("Temperature over Time")
    axes[0].set_ylabel("Temperature (C)")
    axes[0].legend()

    axes[1].set_title("Humidity over Time")
    axes[1].set_ylabel("Humidity (%)")
    axes[1].legend()

    plt.tight_layout()
    plt.savefig(output_path, dpi=100)
    plt.close(fig)
    return output_path


def main() -> None:
    print("Generating sensor data...")
    raw = generate_sensor_data(200)
    print(f"  Raw records: {len(raw)}")

    print("Cleaning data...")
    clean = clean_data(raw)
    print(f"  Clean records: {len(clean)} (removed {len(raw) - len(clean)} anomalies)")

    print("Aggregating per sensor...")
    summary = aggregate(clean)
    print(summary.to_string(index=False))

    print("Generating plot...")
    path = plot_results(clean)
    print(f"  Saved to: {path}")


if __name__ == "__main__":
    main()
