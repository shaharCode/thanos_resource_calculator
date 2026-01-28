from pydantic import BaseModel

class ComponentResources(BaseModel):
    replicas: int
    cpu: float
    ram: str


class ComponentResourcesWithPVC(ComponentResources):
    pvc: str


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
   # Components
    otel: ComponentResources
    router: ComponentResources
    ingestor: ComponentResourcesWithPVC
    compactor: ComponentResourcesWithPVC  # singleton, replicas = 1
    store: ComponentResourcesWithPVC
    frontend: ComponentResources
    querier: ComponentResources

    # S3
    S3Size: str

class CalculationResponse(BaseModel):
    resources: ResourceMetrics
