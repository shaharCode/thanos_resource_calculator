from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import math
from models import (
    CollectorRequest,
    PoolRequest,
    CollectorResources,
    PoolResources,
    Resources,
    ResourcesWithStorage,
    BasicResources
)

DEFAULT_EPHEMERAL_STORAGE = "512Mi"

app = FastAPI(
    title="Thanos Resource Calculator",
    description="API for calculating resources for Thanos components and OTel Collector."
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Helpers
def format_k8s_resource(bytes_val: float) -> str:
    """Formats bytes to K8s resource string (Ki, Mi, Gi) matching regex ^[0-9]+[KMG]i$"""
    if bytes_val <= 0:
        return "0Gi"
    
    if bytes_val < 1024*1024:
        val = math.ceil(bytes_val / 1024)
        return f"{val}Ki"
    elif bytes_val < 1024*1024*1024:
        val = math.ceil(bytes_val / (1024*1024))
        return f"{val}Mi"
    else:
        val = math.ceil(bytes_val / (1024*1024*1024))
        return f"{val}Gi"

def format_cpu(cores: float) -> str:
    """Formats CPU to '1' (if whole number) or '100m' (if fractional)."""
    if cores <= 0.1:
        return "100m" # fallback minimum
    
    # Handle int directly or float that is equivalent to int
    if isinstance(cores, int) or cores.is_integer():
        return str(int(cores))
    
    # Fractional - return in millicores
    millicores = int(cores * 1000)
    return f"{millicores}m"

def create_resources(cpu: float, memory_bytes: float, replicas: int) -> Resources:
    cpu_str = format_cpu(cpu)
    
    basic = BasicResources(
        cpu=cpu_str,
        memory=format_k8s_resource(memory_bytes),
    )
    
    return Resources(
        requests=basic,
        limits=basic,
        replicas=replicas
    )

def create_resources_with_storage(cpu: float, memory_bytes: float, replicas: int, storage_bytes: float) -> ResourcesWithStorage:
    cpu_str = format_cpu(cpu)
    
    basic = BasicResources(
        cpu=cpu_str,
        memory=format_k8s_resource(memory_bytes),
    )
    
    storage_str = format_k8s_resource(storage_bytes)

    return ResourcesWithStorage(
        requests=basic,
        limits=basic,
        replicas=replicas,
        storage=storage_str
    )

@app.post("/api/calculate/collector_resources", response_model=CollectorResources)
async def calculate_collector(req: CollectorRequest):
    dps = req.activeSeries / req.interval
    
    # OTel Logic
    otel_cpu = (dps / 25000.0)
    otel_ram_bytes = (512 * 1024 * 1024) + ((dps / 5000.0) * 1024 * 1024 * 1024)
    
    basic = BasicResources(
        cpu=format_cpu(otel_cpu),
        memory=format_k8s_resource(otel_ram_bytes),
        ephemeralStorage=DEFAULT_EPHEMERAL_STORAGE
    )
    
    return CollectorResources(
        requests=basic,
        limits=basic,
        replicas=1, 
        dps=math.ceil(dps)
    )

@app.post("/api/calculate/pool_resources", response_model=PoolResources, response_model_exclude_none=True)
async def calculate_pool(req: PoolRequest):
    # Inputs
    active_series = req.activeSeries
    interval = req.interval if req.interval > 0 else 1
    qps = req.qps
    perf_factor = req.perfFactor
    complexity_bytes = req.queryComplexity
    
    dps = active_series / interval

    # --- Router ---
    router_replicas = math.ceil(dps / 30000)
    if router_replicas < 2:
        router_replicas = 2
    
    router_cpu_per_pod = 1 * perf_factor
    router_ram_per_pod_bytes = 2 * 1024 * 1024 * 1024 # 2 GiB assumption
    
    router_res = create_resources(router_cpu_per_pod, router_ram_per_pod_bytes, router_replicas)

    # --- Ingestor / Receiver ---
    max_series_per_pod = 4000000
    ingestor_shards = max(1, math.ceil(active_series / max_series_per_pod))

    receive_query_ram_overhead = qps * complexity_bytes
    thanos_ram_bytes_total = (active_series * 6144 * 2) + receive_query_ram_overhead
    ingestor_ram_per_pod = thanos_ram_bytes_total / ingestor_shards

    wal_bytes = dps * 7200 * 3 * 6
    local_tsdb_bytes = 0
    if req.retLocalHours > 2:
        retention_seconds = (req.retLocalHours - 2) * 3600
        local_tsdb_bytes = dps * retention_seconds * 6
    
    total_receiver_disk = wal_bytes + local_tsdb_bytes
    receiver_disk_per_pod = total_receiver_disk / ingestor_shards

    receive_ingest_cpu = dps / 15000
    receive_query_cpu = qps / 5
    receive_cpu_total = (receive_ingest_cpu + receive_query_cpu) * perf_factor
    receive_cpu_per_pod = receive_cpu_total / ingestor_shards
    
    receiver_res = create_resources_with_storage(receive_cpu_per_pod, ingestor_ram_per_pod, ingestor_shards, receiver_disk_per_pod)

    # --- S3 Storage ---
    if active_series < 200000:
        scale_multiplier = 1.0
    else:
        scale_factor = min(1.0, (active_series - 200000) / 1800000)
        scale_multiplier = (0.52 / 0.868) - (scale_factor * 0.07 / 0.868)
    
    scale_multiplier *= 1.10

    raw_bytes_per_series_per_day = 38_000 * scale_multiplier
    downsample_5m_per_series_per_day = 3_000 * scale_multiplier
    downsample_1h_per_series_per_day = 300 * scale_multiplier
    
    s3_raw_bytes = active_series * raw_bytes_per_series_per_day * req.retRawDays
    s3_5m_bytes = active_series * downsample_5m_per_series_per_day * req.ret5mDays
    s3_1h_bytes = active_series * downsample_1h_per_series_per_day * req.ret1hDays
    total_s3_bytes = s3_raw_bytes + s3_5m_bytes + s3_1h_bytes

    # --- Compactor ---
    daily_gen_bytes = dps * 86400 * 1.5
    max_block_days = min(req.retRawDays, 14)
    compactor_scratch_bytes = daily_gen_bytes * max_block_days * 3
    
    series_in_thousands = max(10, active_series / 1000)
    compactor_ram_gb = 2 + (math.log10(series_in_thousands) * 5)
    compactor_cpu = 2 + (math.log10(series_in_thousands) * 1.2)
    compactor_cpu = max(0.1, min(8.0, compactor_cpu))
    compactor_ram_bytes = compactor_ram_gb * 1024 * 1024 * 1024
    
    compactor_res = create_resources_with_storage(compactor_cpu, compactor_ram_bytes, 1, compactor_scratch_bytes)

    # --- Store ---
    store_cache_bytes = (total_s3_bytes * 0.002) + (2 * 1024 * 1024 * 1024)
    store_query_overhead = qps * complexity_bytes
    store_ram_total = store_cache_bytes + store_query_overhead
    
    base_store_cpu = (active_series / 1500000) + (qps / 15)
    store_cpu = base_store_cpu * perf_factor
    store_cpu = max(0.1, store_cpu)
    
    store_replicas = 1
    
    store_ram_per_pod = store_ram_total / store_replicas
    store_pvc_per_replica = total_s3_bytes * 0.10
    
    store_res = create_resources_with_storage(store_cpu, store_ram_per_pod, store_replicas, store_pvc_per_replica)

    # --- Frontend ---
    base_cpu_per_pod = 1 + (active_series / 1500000)
    base_ram_gb_per_pod = 2 + (active_series / 100000) + (complexity_bytes / 1024 / 1024 / 1024 * 0.5)
    
    frontend_replicas = max(1, math.ceil(qps / 25))
    
    frontend_cpu_per_pod = base_cpu_per_pod * perf_factor
    frontend_ram_per_pod = base_ram_gb_per_pod * 1024 * 1024 * 1024 * perf_factor
    
    frontend_res = create_resources(frontend_cpu_per_pod, frontend_ram_per_pod, frontend_replicas)

    # --- Querier ---
    querier_replicas = 1 + math.floor(qps / 20)
    querier_cpu_total = (querier_replicas * 2.5) * perf_factor
    querier_ram_bytes_total = ((active_series / 100000) * 1024 * 1024 * 1024) + (qps * complexity_bytes * perf_factor)
    
    querier_ram_per_pod = querier_ram_bytes_total / querier_replicas
    querier_cpu_per_pod = querier_cpu_total / querier_replicas
    
    querier_res = create_resources(querier_cpu_per_pod, querier_ram_per_pod, querier_replicas)

    return PoolResources(
        router=router_res,
        query=querier_res,
        query_frontend=frontend_res,
        receiver=receiver_res,
        store=store_res,
        compactor=compactor_res,
        s3=format_k8s_resource(total_s3_bytes)
    )

app.mount("/", StaticFiles(directory=".", html=True), name="static")
