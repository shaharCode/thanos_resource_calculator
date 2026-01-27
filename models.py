from pydantic import BaseModel
from typing import Dict, Optional

class CalculationRequest(BaseModel):
    activeSeries: int
    interval: int
    qps: int
    perfFactor: float
    queryComplexity: int
    retLocalHours: int
    retRawDays: int
    ret5mDays: int
    ret1hDays: int

class ResourceMetrics(BaseModel):
    dps: int
    
    # OTel
    otelCpu: int
    otelRamBytes: int
    
    # Router
    routerReplicas: int
    routerCpu: int
    routerRamBytes: int
    
    # Ingestor
    ingestorShards: int
    thanosRamBytes: int
    ingestorRamPerPod: int
    totalReceiverDisk: int
    receiverDiskPerPod: int
    receiveCpu: int
    receiveCpuPerPod: float
    
    # Compactor
    compactorScratchBytes: int
    compactorRamGB: int
    compactorCpu: int
    
    # Store
    storeReplicas: int
    storeRamTotal: int
    storeRamPerPod: int
    storeCpu: int
    storeCpuPerPod: float
    storePvcTotal: int
    storePvcPerReplica: int
    storePartitionTip: bool
    
    # Frontend
    frontendReplicas: int
    frontendCpu: int
    frontendCpuPerPod: float
    frontendRamBytes: int
    
    # Querier
    querierReplicas: int
    querierCpu: int
    querierCpuPerPod: float
    querierRamBytes: int
    querierRamPerPod: int
    
    # S3
    s3RawBytes: int
    s35mBytes: int
    s31hBytes: int
    totalS3Bytes: int
    
    # Totals
    totalThanosPods: int
    finalTotalCpu: int
    totalRam: int
    totalPvc: int
    
    # Safety
    safeReceiveRequestLimit: float
    safeReceiveConcurrency: int
    safeQueryConcurrent: int
    safeStoreConcurrency: int
    safeStoreSampleLimit: float

class CalculationResponse(BaseModel):
    metrics: ResourceMetrics
    configs: Dict[str, str]
    explanation: str
