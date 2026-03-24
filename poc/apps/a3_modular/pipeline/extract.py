"""Extract phase - simulate data acquisition from sensors."""

import random
import datetime


def extract_records(n: int = 50, seed: int = 42) -> list[dict]:
    """Generate simulated sensor readings."""
    random.seed(seed)
    sensors = ["sensor_a", "sensor_b", "sensor_c"]
    base_time = datetime.datetime(2026, 1, 1, 0, 0, 0)

    records = []
    for i in range(n):
        ts = base_time + datetime.timedelta(minutes=i * 15)
        sensor = random.choice(sensors)
        temp = round(random.gauss(22.0, 3.0), 2)
        if random.random() < 0.1:
            temp = round(random.uniform(-200, 200), 2)

        records.append({
            "id": i + 1,
            "timestamp": ts.isoformat(),
            "sensor": sensor,
            "temperature": temp,
            "unit": "celsius",
        })
    return records
