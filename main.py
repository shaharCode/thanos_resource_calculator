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
        # For very low CPU (<0.5 cores), ensure at least +0.3 cores buffer
        if resource_value < 0.5:
            min_buffer = 0.3
            percentage_buffer = resource_value * (base_multiplier - 1.0)
            actual_buffer = max(percentage_buffer, min_buffer)
            return 1.0 + (actual_buffer / resource_value)
    
    elif resource_type == "memory":
        memory_gb = resource_value / (1024 ** 3)
        
        # For very low memory (<2Gi), ensure at least +1Gi buffer
        if memory_gb < 2:
            min_buffer_bytes = 1 * 1024 ** 3
            percentage_buffer = resource_value * (base_multiplier - 1.0)
            actual_buffer = max(percentage_buffer, min_buffer_bytes)
            return 1.0 + (actual_buffer / resource_value)
        
        # For very high memory (>100Gi), use diminishing buffer percentages
        elif memory_gb > 100:
            # Reduce multiplier: 1.4x → 1.28x for >100Gi
            reduced_multiplier = 1.0 + ((base_multiplier - 1.0) * 0.7)
            return reduced_multiplier
    
    return base_multiplier


def create_resources(cpu: float, memory_bytes: float, replicas: int,
                     cpu_limit_multiplier: float = 1.0,
                     memory_limit_multiplier: float = 1.0) -> Resources:
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
    dps = req.dps
    
    # OTel Logic
    otel_cpu = (dps / 25000.0)
    otel_ram_bytes = (512 * 1024 * 1024) + ((dps / 5000.0) * 1024 * 1024 * 1024)
    
    otel_resources = create_resources(
        otel_cpu, 
        otel_ram_bytes, 
        1,
        cpu_limit_multiplier=1.2,
        memory_limit_multiplier=1.3
    )
    
    # Add ephemeral storage to requests and limits
    otel_resources.requests.ephemeralStorage = DEFAULT_EPHEMERAL_STORAGE
    otel_resources.limits.ephemeralStorage = DEFAULT_EPHEMERAL_STORAGE
    
    return CollectorResources(
        requests=otel_resources.requests,
        limits=otel_resources.limits,
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
    CPU_PER_DPS = 1 / 25000      # cores per DPS
    RAM_PER_POD = 2 * 1024 * 1024 * 1024
    MIN_REPLICAS = 2

    total_cpu = dps * CPU_PER_DPS

    replicas = math.ceil(total_cpu)

    if replicas < MIN_REPLICAS:
        replicas = MIN_REPLICAS

    cpu_per_pod = total_cpu / replicas

    router_res = create_resources(
        cpu_per_pod, 
        RAM_PER_POD, 
        replicas,
        cpu_limit_multiplier=1.3,
        memory_limit_multiplier=1.15
    )

    # --- Receiver Ingestor ---
    SCRAPE_INTERVAL = 30
    BYTES_PER_SERIES = 12 * 1024
    HEAD_HOURS = 2
    RETENTION_HOURS = 6
    CPU_PER_DPS_INGEST = 1 / 12000.0
    MAX_SERIES_PER_REPLICA = 4000000
    MIN_PVC_BYTES = 5 * 1024**3
    
    ingestor_cpu = dps * CPU_PER_DPS_INGEST
    query_cpu = ingestor_cpu * 0.2
    ingestor_cpu += query_cpu

    active_series = dps * SCRAPE_INTERVAL
    ingestor_memory = active_series * BYTES_PER_SERIES
    query_memory = ingestor_memory * 0.75
    ingestor_memory += query_memory

    ingestor_wal_bytes = dps * 7200 * 30
    ingestor_block_bytes = dps * (RETENTION_HOURS - HEAD_HOURS) * 3600 * 2
    ingestor_disk_bytes = (ingestor_wal_bytes + ingestor_block_bytes) * 1.2
    ingestor_disk_bytes = max(ingestor_disk_bytes, MIN_PVC_BYTES)

    ingestor_replicas = math.ceil(active_series / MAX_SERIES_PER_REPLICA)

    ingestor_res = create_resources_with_storage(
        ingestor_cpu, 
        ingestor_memory, 
        ingestor_replicas, 
        ingestor_disk_bytes,
        cpu_limit_multiplier=1.25,
        memory_limit_multiplier=1.4
    )

    # --- S3 Storage ---
    active_series = dps * SCRAPE_INTERVAL
    retention_days = req.ret1hDays #req.retentionDays

    # --- Retention mapping ---
    ret_raw_days = min(30, retention_days)
    ret_5m_days = ret_raw_days + max(0, (retention_days - ret_raw_days)/2)
    ret_1h_days = retention_days

    if active_series < 200000:
        scale_multiplier = 1.0
    else:
        scale_factor = min(1.0, (active_series - 200000) / 1800000)
        scale_multiplier = (0.52 / 0.868) - (scale_factor * 0.07 / 0.868)

    samples_per_day = 86400 / SCRAPE_INTERVAL
    bytes_per_sample = 6

    raw_bytes_per_series_per_day = samples_per_day * bytes_per_sample * scale_multiplier
    downsample_5m_per_series_per_day = 3000 * scale_multiplier
    downsample_1h_per_series_per_day = 300 * scale_multiplier

    s3_raw_bytes = active_series * raw_bytes_per_series_per_day * ret_raw_days
    s3_5m_bytes = active_series * downsample_5m_per_series_per_day * ret_5m_days
    s3_1h_bytes = active_series * downsample_1h_per_series_per_day * ret_1h_days

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
    
    compactor_res = create_resources_with_storage(
        compactor_cpu, 
        compactor_ram_bytes, 
        1, 
        compactor_scratch_bytes,
        cpu_limit_multiplier=1.3,
        memory_limit_multiplier=1.5
    )

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
    
    store_res = create_resources_with_storage(
        store_cpu, 
        store_ram_per_pod, 
        store_replicas, 
        store_pvc_per_replica,
        cpu_limit_multiplier=1.2,
        memory_limit_multiplier=1.35
    )

    # --- Frontend ---
    base_cpu_per_pod = 1 + (active_series / 1500000)
    base_ram_gb_per_pod = 2 + (active_series / 100000) + (complexity_bytes / 1024 / 1024 / 1024 * 0.5)
    
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
    querier_ram_bytes_total = ((active_series / 100000) * 1024 * 1024 * 1024) + (qps * complexity_bytes * perf_factor)
    
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
        s3=format_k8s_resource(total_s3_bytes)
    )

app.mount("/", StaticFiles(directory=".", html=True), name="static")
