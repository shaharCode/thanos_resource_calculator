from fastapi.testclient import TestClient
from main import app
import json

client = TestClient(app)

def test_collector():
    print("Testing Collector Endpoint...")
    payload = {
        "activeSeries": 100000,
        "interval": 60,
        "perfFactor": 1.3
    }
    response = client.post("/api/calculate/collector_resources", json=payload)
    if response.status_code == 200:
        print("Collector Response:")
        print(json.dumps(response.json(), indent=2))
    else:
        print(f"Failed: {response.status_code}")
        print(response.text)

def test_pool():
    print("\nTesting Pool Endpoint...")
    payload = {
        "activeSeries": 100000,
        "interval": 60,
        "qps": 10,
        "perfFactor": 1.3,
        "queryComplexity": 50000000,
        "retLocalHours": 6,
        "retRawDays": 14,
        "ret5mDays": 30,
        "ret1hDays": 90
    }
    response = client.post("/api/calculate/pool_resources", json=payload)
    if response.status_code == 200:
        print("Pool Response:")
        print(json.dumps(response.json(), indent=2))
    else:
        print(f"Failed: {response.status_code}")
        print(response.text)

if __name__ == "__main__":
    test_collector()
    test_pool()
