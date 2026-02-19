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

def calculate_limit_multiplier(base_multiplier: float, resource_value: float, 
                                resource_type: str) -> float:
    """
    Adjusts buffer multiplier based on resource scale.
    - Very low resources: add minimum absolute buffer
    - Very high resources: reduce percentage buffer (diminishing returns)
    """
    if resource_type == "cpu":
        if resource_value < 0.5:
            min_buffer = 0.3
            percentage_buffer = resource_value * (base_multiplier - 1)
            actual_buffer = max(percentage_buffer, min_buffer)
            return 1 + (actual_buffer / resource_value)
    
    elif resource_type == "memory":
        memory_gb = resource_value / (1024 ** 3)
        
        if memory_gb < 2:
            min_buffer_bytes = 1 * 1024 ** 3
            percentage_buffer = resource_value * (base_multiplier - 1)
            actual_buffer = max(percentage_buffer, min_buffer_bytes)
            return 1 + (actual_buffer / resource_value)
        
        elif memory_gb > 100:
            reduced_multiplier = 1 + ((base_multiplier - 1) * 0.7)
            return reduced_multiplier
    
    return base_multiplier


def create_resources(cpu: float, memory_bytes: float, replicas: int,
                     cpu_limit_multiplier: float = 1.0,
                     memory_limit_multiplier: float = 1.0) -> Resources:
    """
    Creates a Resources object with calculated requests and limits.
    """
    cpu_str = format_cpu(cpu)
    memory_str = format_k8s_resource(memory_bytes)
    
    # Apply edge case adjustments
    adjusted_cpu_mult = calculate_limit_multiplier(cpu_limit_multiplier, cpu, "cpu")
    adjusted_mem_mult = calculate_limit_multiplier(memory_limit_multiplier, memory_bytes, "memory")
    
    # Calculate limit values
    cpu_limit = cpu * adjusted_cpu_mult
    memory_limit = memory_bytes * adjusted_mem_mult
    
    # Validation: ensure limits >= requests
    assert cpu_limit >= cpu, f"CPU limit ({cpu_limit}) must be >= request ({cpu})"
    assert memory_limit >= memory_bytes, f"Memory limit ({memory_limit}) must be >= request ({memory_bytes})"
    
    requests = BasicResources(cpu=cpu_str, memory=memory_str)
    limits = BasicResources(
        cpu=format_cpu(cpu_limit),
        memory=format_k8s_resource(memory_limit)
    )
    
    return Resources(
        requests=requests,
        limits=limits,
        replicas=replicas
    )


def create_resources_with_storage(cpu: float, memory_bytes: float, replicas: int, storage_bytes: float,
                                  cpu_limit_multiplier: float = 1.0,
                                  memory_limit_multiplier: float = 1.0) -> ResourcesWithStorage:
    """
    Creates a ResourcesWithStorage object with calculated requests and limits.
    """
    cpu_str = format_cpu(cpu)
    memory_str = format_k8s_resource(memory_bytes)
    
    # Apply edge case adjustments
    adjusted_cpu_mult = calculate_limit_multiplier(cpu_limit_multiplier, cpu, "cpu")
    adjusted_mem_mult = calculate_limit_multiplier(memory_limit_multiplier, memory_bytes, "memory")
    
    # Calculate limit values
    cpu_limit = cpu * adjusted_cpu_mult
    memory_limit = memory_bytes * adjusted_mem_mult
    
    # Validation: ensure limits >= requests
    assert cpu_limit >= cpu, f"CPU limit ({cpu_limit}) must be >= request ({cpu})"
    assert memory_limit >= memory_bytes, f"Memory limit ({memory_limit}) must be >= request ({memory_bytes})"
    
    requests = BasicResources(cpu=cpu_str, memory=memory_str)
    limits = BasicResources(
        cpu=format_cpu(cpu_limit),
        memory=format_k8s_resource(memory_limit)
    )
    
    storage_str = format_k8s_resource(storage_bytes)

    return ResourcesWithStorage(
        requests=requests,
        limits=limits,
        replicas=replicas,
        storage=storage_str
    )


@app.post("/api/calculate/collector_resources", response_model=CollectorResources)
async def calculate_collector(req: CollectorRequest):
    """
    Calculates the resources required for the collector.
    """
    dps = req.dps
    
    # OTel Logic
    # Estimate OTel Collector resources from DPS using linear scaling:
    # ~1 CPU per 25k samples/sec and ~1 GiB RAM per 5k samples/sec, plus a 512 MiB base footprint.
    otel_cpu = (dps / 25000)
    otel_ram_bytes = (512 * 1024 * 1024) + ((dps / 5000) * 1024 * 1024 * 1024)
    
    otel_resources = create_resources(
        otel_cpu, 
        otel_ram_bytes, 
        1,
        cpu_limit_multiplier=1.2,
        memory_limit_multiplier=1.3
    )
    
    # Add ephemeral storage to requests and limits
    otel_resources.requests.ephemeralStorage = otel_resources.limits.ephemeralStorage = DEFAULT_EPHEMERAL_STORAGE 
    
    return CollectorResources(
        requests=otel_resources.requests,
        limits=otel_resources.limits,
        replicas=1,
        dps=math.ceil(dps)
    )


@app.post("/api/calculate/pool_resources", response_model=PoolResources, response_model_exclude_none=True)
async def calculate_pool(req: PoolRequest):
    """
    Calculates the resources required for the pool.
    """
    # Constants
    SCRAPE_INTERVAL = req.scrape_interval
    DPS = req.dps
    ACTIVE_TS = DPS * SCRAPE_INTERVAL
    RETENTION = req.retention
    RET_RAW_DAYS = min(30, RETENTION)
    RET_5M_DAYS = RET_RAW_DAYS + max(0, (RETENTION - RET_RAW_DAYS)/2)
    RET_1H_DAYS = RETENTION
    
    # --- Router ---
    # Estimate Router CPU as 1 core per 25k DPS
    # scale replicas based on total CPU (min 2 for HA), and assign 2 GiB RAM per pod.
    ROUTER_CPU_PER_DPS = 1 / 25000
    ROUTER_MEMORY_PER_POD = 2 * 1024 * 1024 * 1024
    ROUTER_MIN_REPLICAS = 2

    total_cpu = DPS * ROUTER_CPU_PER_DPS

    replicas = math.ceil(total_cpu)

    if replicas < ROUTER_MIN_REPLICAS:
        replicas = ROUTER_MIN_REPLICAS

    cpu_per_pod = total_cpu / replicas

    router_res = create_resources(
        cpu_per_pod, 
        ROUTER_MEMORY_PER_POD, 
        replicas,
        cpu_limit_multiplier=1.3,
        memory_limit_multiplier=1.15
    )

    # --- Receiver Ingestor ---
    # Receive ingestor sizing model: CPU scales with DPS (12k DPS/core + 20% query cost),
    # memory scales with active series (~12 KiB/series + 75% query headroom),
    # disk covers WAL (2h) + blocks (6h total retention), min 5 Gi PVC,
    # and shard at 4M series per replica.
    BYTES_PER_SERIES = 12 * 1024
    HEAD_HOURS = 2
    RETENTION_HOURS = 6
    CPU_PER_DPS_INGEST = 1 / 12000
    MAX_SERIES_PER_REPLICA = 4000000
    MIN_PVC_BYTES = 5 * 1024**3
    
    ingestor_cpu = DPS * CPU_PER_DPS_INGEST
    query_cpu = ingestor_cpu * 0.2
    ingestor_cpu += query_cpu

    ingestor_memory = ACTIVE_TS * BYTES_PER_SERIES
    query_memory = ingestor_memory * 0.75
    ingestor_memory += query_memory

    ingestor_wal_bytes = DPS * 7200 * 30
    ingestor_block_bytes = DPS * (RETENTION_HOURS - HEAD_HOURS) * 3600 * 2
    ingestor_disk_bytes = (ingestor_wal_bytes + ingestor_block_bytes) * 1.2
    ingestor_disk_bytes = max(ingestor_disk_bytes, MIN_PVC_BYTES)

    ingestor_replicas = math.ceil(ACTIVE_TS / MAX_SERIES_PER_REPLICA)

    ingestor_res = create_resources_with_storage(
        ingestor_cpu, 
        ingestor_memory, 
        ingestor_replicas, 
        ingestor_disk_bytes,
        cpu_limit_multiplier=1.25,
        memory_limit_multiplier=1.4
    )

    # --- S3 Storage ---
    # Model improved storage efficiency as cardinality grows:
    # baseline below 200k series, then gradually reduce per-series storage cost
    # (≈15% max gain by 2M series) due to better TSDB compression and index amortization.

    if ACTIVE_TS < 200000:
        scale_multiplier = 1
    else: 
        # Linearly scale efficiency from 200k → 2M active series
        scale_factor = min(1, (ACTIVE_TS - 200000) / 1800000)
        # Empirically derived storage efficiency scaling (from test environments)
        scale_multiplier = 0.599 - (scale_factor * 0.0806)

    samples_per_day = 86400 / SCRAPE_INTERVAL
    bytes_per_sample = 6

    raw_bytes_per_series_per_day = samples_per_day * bytes_per_sample * scale_multiplier
    downsample_5m_per_series_per_day = 3000 * scale_multiplier
    downsample_1h_per_series_per_day = 300 * scale_multiplier

    s3_raw_bytes = ACTIVE_TS * raw_bytes_per_series_per_day * RET_RAW_DAYS
    s3_5m_bytes = ACTIVE_TS * downsample_5m_per_series_per_day * RET_5M_DAYS
    s3_1h_bytes = ACTIVE_TS * downsample_1h_per_series_per_day * RET_1H_DAYS

    total_s3_bytes = s3_raw_bytes + s3_5m_bytes + s3_1h_bytes

    # --- Compactor ---
    # Estimate Thanos Compactor resources: 
    # scratch space = 2× largest 14-day block (28 days of daily generated bytes),
    # RAM/CPU scale logarithmically with active series (min 10k),
    # base 2GB/2CPU, capped at 8 CPU, to safely handle block compaction.
    daily_gen_bytes = DPS * 86400 * 1.5
    compactor_scratch_bytes = daily_gen_bytes * 28
    
    series_in_thousands = max(10, ACTIVE_TS / 1000)
    compactor_ram_gb = 2 + (math.log10(series_in_thousands) * 5)
    compactor_cpu = 2 + (math.log10(series_in_thousands) * 1.2)
    compactor_cpu = max(0.1, min(8, compactor_cpu))
    compactor_ram_bytes = compactor_ram_gb * 1024 * 1024 * 1024
    
    compactor_res = create_resources_with_storage(
        compactor_cpu, 
        compactor_ram_bytes, 
        1, 
        compactor_scratch_bytes,
        cpu_limit_multiplier=1.3,
        memory_limit_multiplier=1.5
    )

    # --- Store Gateway Sizing (Cardinality-Driven Model) ---
    # RAM = 2GB baseline + per-series index metadata (smoothly scaled 2KB → 1.4KB 
    # small clusters -> large clusters) + 30% headroom for query working memory.
    # CPU ≈ 1 core per 1M active series (min 0.1).
    # PVC scales smoothly from 10% (small clusters) to 5% (≥10M series).

    base_bytes_per_series = 2000
    min_bytes_per_series = 1400    

    series_scale = min(1.0, ACTIVE_TS / 5000000)
    bytes_per_series = base_bytes_per_series - (
        series_scale * (base_bytes_per_series - min_bytes_per_series)
    )

    # --- Memory ---
    index_cache_bytes = ACTIVE_TS * bytes_per_series
    baseline_bytes = 2 * 1024**3
    store_ram = (baseline_bytes + index_cache_bytes) * 1.3

    # --- CPU ---
    store_cpu = max(0.1, ACTIVE_TS / 1000000)

    # --- PVC ---
    pvc_ratio = 0.10 - min(0.05, ACTIVE_TS / 10000000 * 0.05)
    store_pvc = total_s3_bytes * pvc_ratio
    
    store_res = create_resources_with_storage(
        store_cpu, 
        store_ram, 
        1, 
        store_pvc,
        cpu_limit_multiplier=1.2,
        memory_limit_multiplier=1.35
    )

    # --- Frontend ---
    base_cpu_per_pod = 1 + (ACTIVE_TS / 1500000)
    base_ram_gb_per_pod = 2 + (ACTIVE_TS / 100000) + (complexity_bytes / 1024 / 1024 / 1024 * 0.5)
    
    frontend_replicas = max(1, math.ceil(qps / 25))
    
    frontend_cpu_per_pod = base_cpu_per_pod * perf_factor
    frontend_ram_per_pod = base_ram_gb_per_pod * 1024 * 1024 * 1024 * perf_factor
    
    frontend_res = create_resources(
        frontend_cpu_per_pod, 
        frontend_ram_per_pod, 
        frontend_replicas,
        cpu_limit_multiplier=1.1,
        memory_limit_multiplier=1.2
    )

    # --- Querier ---
    querier_replicas = 1 + math.floor(qps / 20)
    querier_cpu_total = (querier_replicas * 2.5) * perf_factor
    querier_ram_bytes_total = ((ACTIVE_TS / 100000) * 1024 * 1024 * 1024) + (qps * complexity_bytes * perf_factor)
    
    querier_ram_per_pod = querier_ram_bytes_total / querier_replicas
    querier_cpu_per_pod = querier_cpu_total / querier_replicas
    
    querier_res = create_resources(
        querier_cpu_per_pod, 
        querier_ram_per_pod, 
        querier_replicas,
        cpu_limit_multiplier=1.2,
        memory_limit_multiplier=1.4
    )

    return PoolResources(
        receiver_router=router_res,
        query=querier_res,
        query_frontend=frontend_res,
        receiver_ingestor=ingestor_res,
        store=store_res,
        compactor=compactor_res,
        s3=format_k8s_resource(total_s3_bytes),
        dps=DPS
    )

app.mount("/", StaticFiles(directory=".", html=True), name="static")
