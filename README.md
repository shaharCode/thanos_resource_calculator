# Thanos Resource Calculator

A resource sizing calculator for Thanos, now powered by a **Python (FastAPI)** backend with a modern web frontend.

## Overview
This tool helps you estimate the required CPU, RAM, and Storage for a Thanos deployment based on your metrics ingestion rate (DPS), query load (QPS), and retention policies.

## Features
- **FastAPI Backend**: Logic handled in Python for accuracy and extensibility.
- **Interactive UI**: User-friendly web interface.
- **Config Generation**: Automatically generates YAML config snippets for Thanos components.

## Installation & Running

1. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Run the Server**:
   ```bash
   uvicorn main:app --reload
   ```

3. **Open Access**:
   Open your browser to [http://127.0.0.1:8000](http://127.0.0.1:8000).

## Project Structure
- `main.py`: FastAPI server and calculation logic.
- `models.py`: Pydantic data models.
- `index.html` / `style.css` / `main.js`: Frontend assets.

## API Reference
- `POST /api/calculate`: Calculate resource requirements based on input parameters.
Values Example:
```json
{
  "activeSeries": 100000,
  "interval": 60,
  "qps": 15,
  "perfFactor": 1.3, //(1.0 - Cost Optimized, 1.3 - Balanced, 2.0 - Low Latency)
  "queryComplexity": 268435456, //52428800 (Light (Instant Queries) - 50MB), 268435456 (Medium (1h Range) - 250MB), 1610612736 (Heavy (1d-3d Range) - 1.5GB), 3221225472 (Extreme (30d+ / High Card) - 3GB)
  "retLocalHours": 6,
  "retRawDays": 14,
  "ret5mDays": 90,
  "ret1hDays": 365
}
```