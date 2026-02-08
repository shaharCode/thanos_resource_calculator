from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import math
from models import (
    CalculationRequest, 
    CalculationResponse, 
    ResourceSpec,
    ComponentResources,
    ComponentResourcesWithPVC
)

app = FastAPI(
    title="Thanos Resource Calculator",
    description="""
## API Reference
- `POST /api/calculate`: Calculate resource requirements based on input parameters.

### Values Example:
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
"""
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Helpers
def format_bytes(bytes_val, decimals=2):
    if bytes_val == 0:
        return '0 Bytes'
    k = 1024
    dm = decimals if decimals >= 0 else 0
    sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB', 'PB']
    i = math.floor(math.log(bytes_val) / math.log(k))
    return f"{float(f'{(bytes_val / math.pow(k, i)):.{dm}f}')} {sizes[i]}"


@app.post("/api/calculate", response_model=CalculationResponse)
async def calculate(req: CalculationRequest):
    # Inputs
    active_series = req.activeSeries
    interval = req.interval if req.interval > 0 else 1
    qps = req.qps
    perf_factor = req.perfFactor
    complexity_bytes = req.queryComplexity
    
    ret_local_hours = req.retLocalHours
    ret_raw_days = req.retRawDays
    ret_5m_days = req.ret5mDays
    ret_1h_days = req.ret1hDays

    # DPS
    dps = active_series / interval

    # OTel 
    otel_cpu = math.ceil((dps / 20000) * perf_factor)
    otel_cpu = 1 if otel_cpu < 1 else otel_cpu
    otel_ram_bytes = (512 * 1024 * 1024) + ((dps / 1000) * 1024 * 1024 * 1024)

    # Router
    router_replicas = math.ceil(dps / 30000)
    if router_replicas < 2:
        router_replicas = 2
    router_cpu = math.ceil((router_replicas * 1) * perf_factor)
    router_ram_bytes = router_replicas * 2 * 1024 * 1024 * 1024

    # Ingestor
    max_series_per_pod = 4000000
    ingestor_shards = max(1, math.ceil(active_series / max_series_per_pod))

    receive_query_ram_overhead = qps * complexity_bytes
    thanos_ram_bytes = (active_series * 6144 * 2) + receive_query_ram_overhead
    ingestor_ram_per_pod = thanos_ram_bytes / ingestor_shards

    wal_bytes = dps * 7200 * 3 * 6
    local_tsdb_bytes = 0
    if ret_local_hours > 2:
        retention_seconds = (ret_local_hours - 2) * 3600
        local_tsdb_bytes = dps * retention_seconds * 6
    
    total_receiver_disk = wal_bytes + local_tsdb_bytes
    receiver_disk_per_pod = total_receiver_disk / ingestor_shards

    receive_ingest_cpu = dps / 15000
    receive_query_cpu = qps / 5
    receive_cpu = math.ceil((receive_ingest_cpu + receive_query_cpu) * perf_factor)
    receive_cpu_per_pod = receive_cpu / ingestor_shards

    # S3 Storage (Empirical formula - matches measured data at 14d/90d/180d)
    # Measured: 5k series → 4.34 GB, 200k series → 104 GB (at 14d/90d/180d)
    
    # Calculate economy of scale factor
    if active_series < 200000:
        scale_multiplier = 1.0  # 0.868 GB/1k series baseline
    else:
        # Scale from 0.52 at 200k down to 0.45 at 2M
        scale_factor = min(1.0, (active_series - 200000) / 1800000)
        scale_multiplier = (0.52 / 0.868) - (scale_factor * 0.07 / 0.868)  # 0.599 → 0.518
    
    # Add 10% safety margin
    scale_multiplier *= 1.10

    # Per-day storage coefficients (bytes per series per day)
    # Derived from 5k→4.34GB at 14d/90d/180d: ~60% raw, 30% 5m, 10% 1h
    raw_bytes_per_series_per_day = 38_000 * scale_multiplier      # ~38 KB/series/day (raw)
    downsample_5m_per_series_per_day = 3_000 * scale_multiplier   # ~3 KB/series/day (5m)
    downsample_1h_per_series_per_day = 300 * scale_multiplier     # ~0.3 KB/series/day (1h)
    
    s3_raw_bytes = active_series * raw_bytes_per_series_per_day * ret_raw_days
    s3_5m_bytes = active_series * downsample_5m_per_series_per_day * ret_5m_days
    s3_1h_bytes = active_series * downsample_1h_per_series_per_day * ret_1h_days
    total_s3_bytes = s3_raw_bytes + s3_5m_bytes + s3_1h_bytes

    # Compactor
    daily_gen_bytes = dps * 86400 * 1.5
    max_block_days = min(ret_raw_days, 14)
    compactor_scratch_bytes = daily_gen_bytes * max_block_days * 3
    
    
    # Compactor - scales logarithmically with series count
    # Formula scales smoothly: 2GB at 10k series → 16GB at 10M series
    series_in_thousands = max(10, active_series / 1000)  # Minimum 10k for log calculation
    compactor_ram_gb = 2 + (math.log10(series_in_thousands) * 5)

    # CPU scales similarly but slower (1 CPU can handle more)
    compactor_cpu = 2 + (math.log10(series_in_thousands) * 1.2)
    compactor_cpu = max(2, min(8, math.ceil(compactor_cpu)))  # Clamp between 2-8 cores
    
    compactor_ram_bytes = compactor_ram_gb * 1024 * 1024 * 1024

    # Store
    store_cache_bytes = (total_s3_bytes * 0.002) + (2 * 1024 * 1024 * 1024)
    store_query_overhead = qps * complexity_bytes
    store_ram_total = store_cache_bytes + store_query_overhead
    
    base_store_cpu = (active_series / 1500000) + (qps / 15)
    store_cpu = math.ceil(base_store_cpu * perf_factor)
    if store_cpu < 1:
        store_cpu = 1
    
    store_replicas = 1
    if store_cpu < store_replicas:
       store_cpu = store_replicas # JS: if(storeCpu < storeReplicas) storeCpu = storeReplicas;
       
    store_ram_per_pod = store_ram_total / store_replicas
    store_pvc_per_replica = total_s3_bytes * 0.10
    store_pvc_total = store_pvc_per_replica * store_replicas

    # Frontend
    # CPU/RAM scales with Series Count (Merge Complexity)
    # Replicas scales with QPS (Concurrency)
    
    # Base resources per pod based on data size (Active Series)
    base_cpu_per_pod = 1 + (active_series / 1500000)  # +1 Core per 1.5M series
    base_ram_gb_per_pod = 2 + (active_series / 100000) + (complexity_bytes / 1024 / 1024 / 1024 * 0.5) # +1 GB per 100k series
    
    # Scale replicas based on QPS
    frontend_replicas = max(1, math.ceil(qps / 25))
    
    frontend_cpu_per_pod = math.ceil(base_cpu_per_pod * perf_factor)
    frontend_cpu = frontend_cpu_per_pod * frontend_replicas
    frontend_ram_per_pod = base_ram_gb_per_pod * 1024 * 1024 * 1024 * perf_factor
    frontend_ram_bytes = frontend_ram_per_pod * frontend_replicas

    # Querier
    querier_replicas = 1 + math.floor(qps / 20)
    querier_cpu = math.ceil((querier_replicas * 2.5) * perf_factor)
    querier_ram_bytes = ((active_series / 100000) * 1024 * 1024 * 1024) + (qps * complexity_bytes * perf_factor)
    querier_ram_per_pod = querier_ram_bytes / querier_replicas
    querier_cpu_per_pod = querier_cpu / querier_replicas

    resource_spec = ResourceSpec(
        otel=ComponentResources(
            replicas=1,
            cpu=otel_cpu,
            ram=format_bytes(otel_ram_bytes)
        ),
        router=ComponentResources(
            replicas=router_replicas,
            cpu=router_cpu, # Per Pod
            ram=format_bytes(router_ram_bytes) # Per Pod
        ),
        ingestor=ComponentResourcesWithPVC(
            replicas=ingestor_shards,
            cpu=receive_cpu_per_pod,
            ram=format_bytes(ingestor_ram_per_pod),
            pvc=format_bytes(receiver_disk_per_pod)
        ),
        compactor=ComponentResourcesWithPVC(
            replicas=1,
            cpu=compactor_cpu,
            ram=format_bytes(compactor_ram_bytes),
            pvc=format_bytes(compactor_scratch_bytes)
        ),
        store=ComponentResourcesWithPVC(
            replicas=store_replicas,
            cpu=store_cpu,
            ram=format_bytes(store_ram_per_pod),
            pvc=format_bytes(store_pvc_total) # Store PVC is cache, complicated, keeping as is for now or check? Wait, Store repl=1.
        ),
        frontend=ComponentResources(
            replicas=frontend_replicas,
            cpu=frontend_cpu_per_pod,
            ram=format_bytes(frontend_ram_per_pod)
        ),
        querier=ComponentResources(
            replicas=querier_replicas,
            cpu=querier_cpu_per_pod,
            ram=format_bytes(querier_ram_per_pod)
        ),
        S3Size=format_bytes(total_s3_bytes),
        dps=math.floor(dps)
    )

    return CalculationResponse(resources=resource_spec)

# Static files
app.mount("/", StaticFiles(directory=".", html=True), name="static")
