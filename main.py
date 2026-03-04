from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import math
from enum import Enum
from typing import Tuple
from models import (
    CollectorRequest,
    PoolRequest,
    CollectorResources,
    PoolResources,
    DataRetention,
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


class ResourceType(Enum):
    CPU = "cpu"
    MEMORY = "memory"


# Helpers
def format_k8s_resource(bytes_val: float) -> str:
    """Formats bytes to K8s resource string (Ki, Mi, Gi) matching regex ^[0-9]+[KMG]i$"""
    if bytes_val <= 0:
        return "0Gi"

    if bytes_val < 1024 * 1024:
        val = math.ceil(bytes_val / 1024)
        return f"{val}Ki"
    elif bytes_val < 1024 * 1024 * 1024:
        val = math.ceil(bytes_val / (1024 * 1024))
        return f"{val}Mi"
    else:
        val = math.ceil(bytes_val / (1024 * 1024 * 1024))
        return f"{val}Gi"


def format_cpu(cores: float) -> str:
    """Formats CPU to '1' (if whole number) or '100m' (if fractional)."""
    if cores <= 0.1:
        return "100m"  # fallback minimum

    # Handle int directly or float that is equivalent to int
    if isinstance(cores, int) or cores.is_integer():
        return str(int(cores))

    # Fractional - return in millicores
    millicores = int(cores * 1000)
    return f"{millicores}m"


def calculate_limit_multiplier(base_multiplier: float, resource_value: float,
                                resource_type: ResourceType) -> float:
    """
    Adjusts buffer multiplier based on resource scale.
    - Very low resources: add minimum absolute buffer
    - Very high resources: reduce percentage buffer (diminishing returns)
    """
    if resource_type == ResourceType.CPU:
        if resource_value < 0.5:
            min_buffer = 0.3
            percentage_buffer = resource_value * (base_multiplier - 1)
            actual_buffer = max(percentage_buffer, min_buffer)
            return 1 + (actual_buffer / resource_value)

    elif resource_type == ResourceType.MEMORY:
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
    adjusted_cpu_mult = calculate_limit_multiplier(cpu_limit_multiplier, cpu, ResourceType.CPU)
    adjusted_mem_mult = calculate_limit_multiplier(memory_limit_multiplier, memory_bytes, ResourceType.MEMORY)

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


def create_resources_with_storage(cpu: float, memory_bytes: float, replicas: int,
                                  storage_bytes: float,
                                  cpu_limit_multiplier: float = 1.0,
                                  memory_limit_multiplier: float = 1.0) -> ResourcesWithStorage:
    """
    Delegates to create_resources and adds storage to produce a ResourcesWithStorage object.
    """
    res = create_resources(cpu, memory_bytes, replicas, cpu_limit_multiplier, memory_limit_multiplier)
    return ResourcesWithStorage(
        requests=res.requests,
        limits=res.limits,
        replicas=res.replicas,
        storage=format_k8s_resource(storage_bytes)
    )


@app.post("/api/calculate/collector_resources", response_model=CollectorResources)
async def calculate_collector(req: CollectorRequest):
    """
    Calculates the resources required for the collector.
    """
    dps = req.dps

    # Estimate OTel Collector resources from DPS using linear scaling:
    # ~1 CPU per 25k samples/sec and ~1 GiB RAM per 5k samples/sec, plus a 512 MiB base footprint.
    otel_cpu = dps / 25000
    otel_ram_bytes = (512 * 1024 * 1024) + ((dps / 5000) * 1024 * 1024 * 1024)

    otel_resources = create_resources(
        otel_cpu,
        otel_ram_bytes,
        1,
        cpu_limit_multiplier=1.2,
        memory_limit_multiplier=1.3
    )

    return CollectorResources(
        requests=otel_resources.requests,
        limits=otel_resources.limits,
        replicas=1,
        dps=dps,
        ephemeral_storage=DEFAULT_EPHEMERAL_STORAGE
    )


def _calc_router(DPS: int) -> Resources:
    """
    Router: 1 core per 25k DPS, 2 GiB RAM/pod, min 2 replicas HA, cap 4 CPU/pod.
    """
    ROUTER_CPU_PER_DPS = 1 / 25000
    ROUTER_MEMORY_PER_POD = 2 * 1024 * 1024 * 1024
    ROUTER_MIN_REPLICAS = 2
    MAX_CPU_PER_POD = 4

    total_cpu = DPS * ROUTER_CPU_PER_DPS
    replicas = max(math.ceil(total_cpu / MAX_CPU_PER_POD), ROUTER_MIN_REPLICAS)
    cpu_per_pod = total_cpu / replicas

    return create_resources(
        cpu_per_pod,
        ROUTER_MEMORY_PER_POD,
        replicas,
        cpu_limit_multiplier=1.3,
        memory_limit_multiplier=1.15
    )


def _calc_ingestor(DPS: int, ACTIVE_TS: float) -> ResourcesWithStorage:
    """
    Ingestor: CPU = DPS/12k + 20% query overhead, RAM = 12 KiB/series + 75% headroom,
    PVC covers WAL (2h) + blocks (4h), sharded at 4M series/replica, min 5 Gi PVC.
    """
    BYTES_PER_SERIES = 12 * 1024
    # Receiver keeps 6h of local data; the head block covers the first 2h,
    # leaving 4h worth of completed blocks on disk (receiver_retention_hours - head_hours).
    BLOCK_HOURS = 4
    CPU_PER_DPS_INGEST = 1 / 12000
    MAX_SERIES_PER_REPLICA = 4000000
    MIN_PVC_BYTES = 5 * 1024**3

    cpu = DPS * CPU_PER_DPS_INGEST * 1.2        # +20% query cost
    memory = ACTIVE_TS * BYTES_PER_SERIES * 1.75  # +75% query headroom

    wal_bytes = DPS * 7200 * 30
    block_bytes = DPS * BLOCK_HOURS * 3600 * 2
    disk_bytes = max((wal_bytes + block_bytes) * 1.2, MIN_PVC_BYTES)

    replicas = math.ceil(ACTIVE_TS / MAX_SERIES_PER_REPLICA)

    return create_resources_with_storage(
        cpu,
        memory,
        replicas,
        storage_bytes=disk_bytes,
        cpu_limit_multiplier=1.25,
        memory_limit_multiplier=1.4
    )


def _calc_s3(ACTIVE_TS: float, SCRAPE_INTERVAL: int,
             RET_RAW_DAYS: int, RET_5M_DAYS: int, RET_1H_DAYS: int) -> float:
    """
    S3 storage: models storage efficiency gains as cardinality grows (baseline <200k series,
    up to ~15% compression gain at 2M+ series). Returns total bytes.
    """
    if ACTIVE_TS < 200000:
        scale_multiplier = 1.0
    else:
        scale_factor = min(1.0, (ACTIVE_TS - 200000) / 1800000)
        scale_multiplier = 0.599 - (scale_factor * 0.0806)

    samples_per_day = 86400 / SCRAPE_INTERVAL
    raw_bytes_per_series_per_day = samples_per_day * 6 * scale_multiplier
    downsample_5m_per_series_per_day = 3000 * scale_multiplier
    downsample_1h_per_series_per_day = 300 * scale_multiplier

    s3_raw = ACTIVE_TS * raw_bytes_per_series_per_day   * RET_RAW_DAYS
    s3_5m  = ACTIVE_TS * downsample_5m_per_series_per_day * RET_5M_DAYS
    s3_1h  = ACTIVE_TS * downsample_1h_per_series_per_day * RET_1H_DAYS

    return s3_raw + s3_5m + s3_1h


def _calc_compactor(DPS: int, ACTIVE_TS: float) -> ResourcesWithStorage:
    """
    Compactor: scratch = 28 days of daily-generated bytes, RAM/CPU scale log10
    with active series (base 2 GB/2 CPU, CPU capped at 8).
    """
    daily_gen_bytes = DPS * 86400 * 1.5
    scratch_bytes = daily_gen_bytes * 28

    series_in_thousands = max(10, ACTIVE_TS / 1000)
    ram_gb = 2 + (math.log10(series_in_thousands) * 5)
    cpu    = max(0.1, min(8, 2 + (math.log10(series_in_thousands) * 1.2)))
    ram_bytes = ram_gb * 1024**3

    return create_resources_with_storage(
        cpu,
        ram_bytes,
        1,
        storage_bytes=scratch_bytes,
        cpu_limit_multiplier=1.3,
        memory_limit_multiplier=1.5
    )


def _calc_store(ACTIVE_TS: float, total_s3_bytes: float) -> ResourcesWithStorage:
    """
    Store Gateway: RAM = 2 GB baseline + per-series index metadata (2 KB→1.4 KB)
    + 40% headroom. CPU = 1 core/1.5M series. PVC = 5–10% of S3 total.
    """
    base_bytes_per_series = 2000
    min_bytes_per_series  = 1400

    series_scale = min(1.0, ACTIVE_TS / 5000000)
    bytes_per_series = base_bytes_per_series - (
        series_scale * (base_bytes_per_series - min_bytes_per_series)
    )

    index_cache_bytes = ACTIVE_TS * bytes_per_series
    baseline_bytes    = 2 * 1024**3
    ram       = (baseline_bytes + index_cache_bytes) * 1.4
    cpu       = max(0.1, ACTIVE_TS / 1500000)
    pvc_ratio = 0.10 - min(0.05, ACTIVE_TS / 10000000 * 0.05)
    pvc       = total_s3_bytes * pvc_ratio

    return create_resources_with_storage(
        cpu,
        ram,
        1,
        storage_bytes=pvc,
        cpu_limit_multiplier=1.2,
        memory_limit_multiplier=1.35
    )


def _calc_frontend_and_querier(DPS: int, ACTIVE_TS: float,
                                RETENTION: int) -> Tuple[Resources, Resources]:
    """
    Frontend & Querier share hot-window weighted sample count and working_set_scale.
    Frontend: result-cache heavy, ~1 CPU + scale/3, 1.5 GB + 2× scale RAM.
    Querier: heavier execution, 2 CPU + 0.7× scale, 2 GB + cardinality + 1.5× scale RAM.
    """
    # Hot-window weighting
    hot_weights = [
        (1,  0.55),   # 1 day  → 55% of queries
        (2,  0.25),   # +2 days → 25%
        (4,  0.15),   # +4 days → 15%
        (23, 0.05),   # remainder up to 30d → 5%
    ]
    remaining = min(RETENTION, 30)
    weighted_days = 0.0
    for days, weight in hot_weights:
        if remaining <= 0:
            break
        used = min(days, remaining)
        weighted_days += used * weight
        remaining -= used

    hot_samples       = DPS * 86400 * weighted_days
    working_set_scale = 1.3 * (hot_samples / 1e9) ** 0.5

    # Frontend
    frontend_replicas = max(1, math.ceil(working_set_scale / 3))
    frontend_cpu      = 1 + (working_set_scale / 3)
    frontend_ram      = (1.5 + working_set_scale * 2.0) * 1024**3

    frontend_res = create_resources(
        frontend_cpu,
        frontend_ram,
        frontend_replicas,
        cpu_limit_multiplier=1.1,
        memory_limit_multiplier=1.4
    )

    # Querier
    querier_replicas = max(
        1,
        math.ceil(working_set_scale / 2),
        math.ceil(ACTIVE_TS / 4000000)
    )
    querier_cpu = 2 + (working_set_scale * 0.7)
    querier_ram = (2 + (ACTIVE_TS / 2000000) + (working_set_scale * 1.5)) * 1024**3

    querier_res = create_resources(
        querier_cpu,
        querier_ram,
        querier_replicas,
        cpu_limit_multiplier=1.2,
        memory_limit_multiplier=1.45
    )

    return frontend_res, querier_res


@app.post("/api/calculate/pool_resources", response_model=PoolResources, response_model_exclude_none=True)
async def calculate_pool(req: PoolRequest):
    """
    Orchestrates per-component sizing and assembles the final PoolResources response.
    """
    DPS             = req.dps
    SCRAPE_INTERVAL = req.scrape_interval
    ACTIVE_TS       = DPS * SCRAPE_INTERVAL
    RETENTION       = req.retention
    RET_RAW_DAYS    = min(30, RETENTION)
    RET_5M_DAYS     = RET_RAW_DAYS + max(0, math.ceil((RETENTION - RET_RAW_DAYS) / 2))
    RET_1H_DAYS     = RETENTION

    router_res                = _calc_router(DPS)
    ingestor_res              = _calc_ingestor(DPS, ACTIVE_TS)
    total_s3_bytes            = _calc_s3(ACTIVE_TS, SCRAPE_INTERVAL, RET_RAW_DAYS, RET_5M_DAYS, RET_1H_DAYS)
    compactor_res             = _calc_compactor(DPS, ACTIVE_TS)
    store_res                 = _calc_store(ACTIVE_TS, total_s3_bytes)
    frontend_res, querier_res = _calc_frontend_and_querier(DPS, ACTIVE_TS, RETENTION)

    return PoolResources(
        receiver_router=router_res,
        query=querier_res,
        query_frontend=frontend_res,
        receiver_ingestor=ingestor_res,
        store=store_res,
        compactor=compactor_res,
        s3=format_k8s_resource(total_s3_bytes),
        dps=DPS,
        data_retention=DataRetention(
            raw_data=f"{RET_RAW_DAYS}d",
            downsample_5m=f"{RET_5M_DAYS}d",
            downsample_1h=f"{RET_1H_DAYS}d"
        )
    )


app.mount("/", StaticFiles(directory=".", html=True), name="static")
