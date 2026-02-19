from fastapi.testclient import TestClient
from main import app
import json

client = TestClient(app)

def test_collector():
    print("Testing Collector Endpoint...")
    payload = {
        "dps": 1667
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
        "dps": 1667,
        "scrape_interval": 60,
        "retention": 180
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
