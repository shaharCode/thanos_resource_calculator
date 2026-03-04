from fastapi.testclient import TestClient
from main import app
import json

client = TestClient(app)

def test_collector():
    print("Testing Collector Endpoint...")
    payload = {"dps": 1667}
    response = client.post("/api/calculate/collector_resources", json=payload)

    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    assert "requests" in data, "Missing 'requests' in response"
    assert "limits" in data, "Missing 'limits' in response"
    assert "replicas" in data, "Missing 'replicas' in response"
    assert "dps" in data, "Missing 'dps' in response"
    assert data["dps"] == payload["dps"], f"DPS mismatch: {data['dps']} != {payload['dps']}"
    assert data["replicas"] >= 1, "Replicas must be >= 1"

    print("Collector Response:")
    print(json.dumps(data, indent=2))


def test_pool():
    print("\nTesting Pool Endpoint...")
    payload = {
        "dps": 1667,
        "scrape_interval": 60,
        "retention": 180
    }
    response = client.post("/api/calculate/pool_resources", json=payload)

    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()

    expected_keys = [
        "dps", "query", "query_frontend", "receiver_router",
        "receiver_ingestor", "store", "compactor", "s3", "data_retention"
    ]
    for key in expected_keys:
        assert key in data, f"Missing '{key}' in response"

    assert data["dps"] == payload["dps"], f"DPS mismatch: {data['dps']} != {payload['dps']}"

    for component in ["query", "query_frontend", "receiver_router"]:
        assert data[component]["replicas"] >= 1, f"{component}: replicas must be >= 1"

    for component in ["receiver_ingestor", "store", "compactor"]:
        assert "storage" in data[component], f"{component}: missing 'storage'"

    retention = data["data_retention"]
    assert retention["raw_data"].endswith("d"), "raw_data retention must end with 'd'"
    assert retention["downsample_5m"].endswith("d"), "downsample_5m retention must end with 'd'"
    assert retention["downsample_1h"].endswith("d"), "downsample_1h retention must end with 'd'"

    print("Pool Response:")
    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    test_collector()
    test_pool()
    print("\nAll assertions passed.")
