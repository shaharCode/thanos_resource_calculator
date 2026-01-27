from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import math
from models import CalculationRequest, CalculationResponse, ResourceMetrics

app = FastAPI()

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

def format_mib(bytes_val):
    if bytes_val == 0:
        return '0MiB'
    return f"{math.floor(bytes_val / (1024 * 1024))}MiB"

@app.post("/api/calculate", response_model=CalculationResponse)
async def calculate(req: CalculationRequest):
    # Inputs
    active_series = req.activeSeries
    interval = req.interval if req.interval > 0 else 1
    replication = 1
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
    otel_cpu = math.ceil((dps / 10000) * perf_factor)
    otel_cpu = 1 if otel_cpu < 1 else otel_cpu
    otel_ram_bytes = (512 * 1024 * 1024) + ((dps / 10000) * 1024 * 1024 * 1024)

    # Router
    router_replicas = math.ceil(dps / 30000)
    if router_replicas < 2:
        router_replicas = 2
    router_cpu = math.ceil((router_replicas * 1) * perf_factor)
    router_ram_bytes = router_replicas * 1 * 1024 * 1024 * 1024

    # Ingestor
    total_replicated_series = active_series * replication
    max_series_per_pod = 4000000
    ingestor_shards = math.ceil(total_replicated_series / max_series_per_pod)
    if ingestor_shards < replication:
        ingestor_shards = replication

    max_receiver_query_mem = 300 * 1024 * 1024
    effective_receiver_complexity = min(complexity_bytes, max_receiver_query_mem)
    receive_query_ram_overhead = qps * effective_receiver_complexity
    thanos_ram_bytes = (total_replicated_series * 4096) + receive_query_ram_overhead
    ingestor_ram_per_pod = thanos_ram_bytes / ingestor_shards

    wal_bytes = dps * 7200 * 3 * replication * 1.5
    local_tsdb_bytes = 0
    if ret_local_hours > 2:
        retention_seconds = (ret_local_hours - 2) * 3600
        local_tsdb_bytes = dps * retention_seconds * 1.5 * replication
    
    total_receiver_disk = wal_bytes + local_tsdb_bytes
    receiver_disk_per_pod = total_receiver_disk / ingestor_shards

    receive_ingest_cpu = (dps * replication) / 15000
    receive_query_cpu = qps / 5
    receive_cpu = math.ceil((receive_ingest_cpu + receive_query_cpu) * perf_factor)
    receive_cpu_per_pod = receive_cpu / ingestor_shards

    # Safety limits
    safe_receive_request_limit = max(20000000, active_series * 20)
    safe_receive_concurrency = max(50, math.ceil((active_series / interval) / 250))
    # scale_series_limit = max(50000, min(500000, math.ceil(active_series / 50))) # logic from JS used for display? No, config only/info.

    # S3
    s3_raw_bytes = dps * 86400 * ret_raw_days * 1.5
    s3_5m_bytes = (dps / 300) * 86400 * ret_5m_days * 5 * 2
    s3_1h_bytes = (dps / 3600) * 86400 * ret_1h_days * 5 * 2
    total_s3_bytes = s3_raw_bytes + s3_5m_bytes + s3_1h_bytes

    # Compactor
    daily_gen_bytes = dps * 86400 * 1.5
    max_block_days = min(ret_raw_days, 14)
    compactor_scratch_bytes = daily_gen_bytes * max_block_days * 3
    
    compactor_ram_gb = 2
    if active_series > 1000000:
        compactor_ram_gb = 8
    if active_series > 5000000:
        compactor_ram_gb = 16
    compactor_ram_bytes = compactor_ram_gb * 1024 * 1024 * 1024
    compactor_cpu = 1

    # Store
    store_cache_bytes = (total_s3_bytes * 0.002) + (1 * 1024 * 1024 * 1024)
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

    store_partition_tip = False
    if store_ram_total > 32 * 1024 * 1024 * 1024:
        store_partition_tip = True

    # Frontend
    frontend_replicas = 1 + math.floor(qps / 50)
    frontend_cpu = math.ceil((frontend_replicas * 1) * perf_factor)
    frontend_ram_bytes = frontend_replicas * 2 * 1024 * 1024 * 1024
    frontend_cpu_per_pod = frontend_cpu / frontend_replicas

    # Querier
    querier_replicas = 1 + math.floor(qps / 20)
    querier_cpu = math.ceil((querier_replicas * 2) * perf_factor)
    querier_ram_bytes = (1 * 1024 * 1024 * 1024) + (qps * complexity_bytes)
    querier_ram_per_pod = querier_ram_bytes / querier_replicas
    querier_cpu_per_pod = querier_cpu / querier_replicas

    # Querier Safety
    safe_query_concurrent = max(20, math.ceil(qps * 2))
    safe_store_concurrency = max(20, math.ceil(qps * 2))
    safe_store_sample_limit = max(5000000, math.ceil(active_series * 1.5))

    # Totals
    total_thanos_pods = router_replicas + ingestor_shards + 1 + store_replicas + frontend_replicas + querier_replicas
    final_total_cpu = otel_cpu + router_cpu + receive_cpu + compactor_cpu + store_cpu + frontend_cpu + querier_cpu
    total_ram = otel_ram_bytes + router_ram_bytes + thanos_ram_bytes + store_ram_total + frontend_ram_bytes + querier_ram_bytes + compactor_ram_bytes
    total_pvc = total_receiver_disk + compactor_scratch_bytes + store_pvc_total

    # Config Generation
    configs = {}
    
    configs['receive'] = f"""# Thanos Receiver Ingestor ({ingestor_shards} Replicas)
# -----------------------------------------------------
# Note: request limits (series/samples) should be set in
# a limits configuration file (e.g. --receive.tenant-limit-config-file)
# or via --receive.default-tenant-limit.* flags if available.

args:
  - receive
  - --tsdb.retention.time={ret_local_hours}h
  - --receive.remote-write.server-max-concurrency={safe_receive_concurrency}
  - --store.limits.request-samples={safe_receive_request_limit:.1e}
  - --objstore.config-file=/etc/thanos/bucket.yml
  - --auto-gomemlimit.ratio=0.9

env:
  - name: GOGC
    value: "100"
"""

    configs['store'] = f"""# Thanos Store Gateway ({store_replicas} Replicas)
# -----------------------------------------------------
args:
  - store
  - --index-cache-size={format_mib(store_ram_per_pod * 0.5)}  # ~50% of Pod RAM for Cache
  - --chunk-pool-size={format_mib(store_ram_per_pod * 0.3)}   # ~30% for Chunk Pool
  - --store.grpc.series-max-concurrency={safe_store_concurrency}
  - --store.grpc.series-sample-limit={safe_store_sample_limit:.1e}
  - --objstore.config-file=/etc/thanos/bucket.yml
  - --auto-gomemlimit.ratio=0.9

env:
  # No GOMEMLIMIT env needed if using auto-gomemlimit flag
"""

    configs['query'] = f"""# Thanos Querier ({querier_replicas} Replicas)
# -----------------------------------------------------
args:
  - query
  - --query.max-concurrent={safe_query_concurrent}
  - --query.timeout=2m
  - --query.replica-label=replica
  - --auto-gomemlimit.ratio=0.9
  
env:
  # No GOMEMLIMIT env needed if using auto-gomemlimit flag
"""

    configs['compactor'] = f"""# Thanos Compactor (Singleton)
# -----------------------------------------------------
args:
  - compact
  - --compact.concurrency=1
  - --retention.resolution-raw={ret_raw_days}d
  - --retention.resolution-5m={ret_5m_days}d
  - --retention.resolution-1h={ret_1h_days}d
  - --objstore.config-file=/etc/thanos/bucket.yml
  - --auto-gomemlimit.ratio=0.9

env:
  # No GOMEMLIMIT env needed if using auto-gomemlimit flag
"""

    configs['frontend'] = f"""# Thanos Query Frontend ({frontend_replicas} Replicas)
# -----------------------------------------------------
args:
  - query-frontend
  - --query-range.split-interval=24h
  - --query-range.align-range-with-step=true
  - --query-range.max-retries-per-request=5
  - --query-range.response-cache-config-file=/etc/thanos/cache.yml
  - --auto-gomemlimit.ratio=0.9

env:
  # No GOMEMLIMIT env needed if using auto-gomemlimit flag
"""

    # Explanation
    perf_text = "Cost Optimized" if perf_factor == 1.0 else ("Low Latency" if perf_factor == 2.0 else "Balanced")
    explanation = f"""
        <div style="margin-bottom:8px; color:var(--perf-color);"><strong>🚀 Performance Mode: {perf_text}</strong> <br>
        Added a {perf_factor}x CPU factor to keep utilization low and improve latency.</div>
        
        <div style="margin-bottom:8px">1. <strong>Query Complexity Factor:</strong> <br>
        Added complexity multiplier. Heavy queries (days range) double memory requirements for Querier and Store Gateway to prevent OOM.</div>

        <div style="margin-bottom:8px">2. <strong>Receiver Storage:</strong> <br>
        All data is stored on {ingestor_shards} Ingestor Pods. Total Volume: <strong>{format_bytes(total_receiver_disk)}</strong>.</div>
    """

    metrics = ResourceMetrics(
        dps=math.floor(dps),
        otelCpu=otel_cpu,
        otelRamBytes=int(otel_ram_bytes),
        routerReplicas=router_replicas,
        routerCpu=router_cpu,
        routerRamBytes=int(router_ram_bytes),
        ingestorShards=ingestor_shards,
        thanosRamBytes=int(thanos_ram_bytes),
        ingestorRamPerPod=int(ingestor_ram_per_pod),
        totalReceiverDisk=int(total_receiver_disk),
        receiverDiskPerPod=int(receiver_disk_per_pod),
        receiveCpu=receive_cpu,
        receiveCpuPerPod=float(receive_cpu_per_pod),
        compactorScratchBytes=int(compactor_scratch_bytes),
        compactorRamGB=compactor_ram_gb,
        compactorCpu=compactor_cpu,
        storeReplicas=store_replicas,
        storeRamTotal=int(store_ram_total),
        storeRamPerPod=int(store_ram_per_pod),
        storeCpu=store_cpu,
        storeCpuPerPod=float(store_cpu / store_replicas),
        storePvcTotal=int(store_pvc_total),
        storePvcPerReplica=int(store_pvc_per_replica),
        storePartitionTip=store_partition_tip,
        frontendReplicas=frontend_replicas,
        frontendCpu=frontend_cpu,
        frontendCpuPerPod=float(frontend_cpu_per_pod),
        frontendRamBytes=int(frontend_ram_bytes),
        querierReplicas=querier_replicas,
        querierCpu=querier_cpu,
        querierCpuPerPod=float(querier_cpu_per_pod),
        querierRamBytes=int(querier_ram_bytes),
        querierRamPerPod=int(querier_ram_per_pod),
        s3RawBytes=int(s3_raw_bytes),
        s35mBytes=int(s3_5m_bytes),
        s31hBytes=int(s3_1h_bytes),
        totalS3Bytes=int(total_s3_bytes),
        totalThanosPods=total_thanos_pods,
        finalTotalCpu=final_total_cpu,
        totalRam=int(total_ram),
        totalPvc=int(total_pvc),
        safeReceiveRequestLimit=safe_receive_request_limit,
        safeReceiveConcurrency=safe_receive_concurrency,
        safeQueryConcurrent=safe_query_concurrent,
        safeStoreConcurrency=safe_store_concurrency,
        safeStoreSampleLimit=safe_store_sample_limit
    )

    return CalculationResponse(
        metrics=metrics,
        configs=configs,
        explanation=explanation
    )

# Static files
app.mount("/", StaticFiles(directory=".", html=True), name="static")
