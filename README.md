# Thanos Resource Calculator

A resource sizing calculator for Thanos, powered by a **Python (FastAPI)** backend with a modern web frontend.

## Overview
Estimates the required CPU, RAM, and Storage for a Thanos deployment based on your metrics ingestion rate (DPS), scrape interval, and retention policies.

## Components Sized
- **OTel Collector** — ingestion gateway
- **Receiver Router** — hash-ring based write distribution
- **Receiver Ingestor** — TSDB head + WAL
- **Store Gateway** — long-term block access from S3
- **Compactor** — block compaction and downsampling
- **Query Frontend** — query splitting and result caching
- **Querier** — fan-out query execution
- **S3 Storage** — estimated object storage footprint

## Installation & Running

1. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Run the Server**:
   ```bash
   uvicorn main:app --reload
   ```

3. **Open**:
   Open your browser to [http://127.0.0.1:8000](http://127.0.0.1:8000).

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/calculate/collector_resources` | OTel Collector sizing |
| `POST` | `/api/calculate/pool_resources` | Full Thanos pool sizing |

### Example Request (Pool)
```json
{
  "dps": 1667,
  "scrape_interval": 60,
  "retention": 180
}
```

## Project Structure
- `main.py` — FastAPI server, component sizing helpers, and route handlers.
- `models.py` — Pydantic request/response models.
- `index.html` / `style.css` / `main.js` — Frontend assets.
- `verify_endpoints.py` — Smoke tests with assertions for both API endpoints.
- `Dockerfile` — Container build definition.
