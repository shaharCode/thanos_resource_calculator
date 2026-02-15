from pydantic import BaseModel, Field
from typing import Optional

RESOURCE_PATTERN = "^[0-9]+[KMG]i$"

class BasicResources(BaseModel):
    memory: str = Field(..., description="Memory in Ki/Mi/Gi", pattern=RESOURCE_PATTERN)
    cpu: int = Field(..., description="CPU in ints", gt=0)
    ephemeralStorage: Optional[str] = Field(default=None, description="Ephemeral storage in Ki/Mi/Gi", pattern=RESOURCE_PATTERN)

class Resources(BaseModel):
    requests: BasicResources
    limits: BasicResources
    replicas: int = Field(..., description="Number of replicas in ints", gt=0)

class ResourcesWithStorage(Resources):
    storage: str = Field(..., description="Storage of PVC in Ki/Mi/Gi", pattern=RESOURCE_PATTERN)

class CollectorResources(Resources):
    dps: int = Field(..., description="Number of data points per second, in ints", gt=0)

    class Config:
        json_schema_extra = {
            "example": {
                "requests": {
                    "memory": "512Mi",
                    "cpu": 1,
                    "ephemeralStorage": "512Mi"
                },
                "limits": {
                    "memory": "1Gi",
                    "cpu": 1,
                    "ephemeralStorage": "1Gi"
                },
                "replicas": 1,
                "dps": 5000
            }
        }

class PoolResources(BaseModel):
    router: Resources
    query: Resources
    query_frontend: Resources
    receiver: ResourcesWithStorage
    store: ResourcesWithStorage
    compactor: Optional[ResourcesWithStorage]
    s3: str = Field(..., description="S3 size in Ki/Mi/Gi", pattern=RESOURCE_PATTERN)

    class Config:
        json_schema_extra = {
            "example": {
                "router": {
                    "requests": {"memory": "1Gi", "cpu": 1},
                    "limits": {"memory": "2Gi", "cpu": 2},
                    "replicas": 2
                },
                "query": {
                    "requests": {"memory": "1Gi", "cpu": 1},
                    "limits": {"memory": "2Gi", "cpu": 2},
                    "replicas": 2
                },
                "query_frontend": {
                    "requests": {"memory": "1Gi", "cpu": 1},
                    "limits": {"memory": "1Gi", "cpu": 1},
                    "replicas": 2
                },
                "receiver": {
                    "requests": {"memory": "2Gi", "cpu": 2},
                    "limits": {"memory": "4Gi", "cpu": 4},
                    "replicas": 3,
                    "storage": "50Gi"
                },
                "store": {
                    "requests": {"memory": "2Gi", "cpu": 1},
                    "limits": {"memory": "4Gi", "cpu": 2},
                    "replicas": 1,
                    "storage": "100Gi"
                },
                "compactor": {
                    "requests": {"memory": "4Gi", "cpu": 2},
                    "limits": {"memory": "8Gi", "cpu": 4},
                    "replicas": 1,
                    "storage": "200Gi"
                },
                "s3": "500Gi"
            }
        }

class CollectorRequest(BaseModel):
    activeSeries: int = Field(..., description="Number of active series", gt=0)
    interval: int = Field(..., description="Scrape interval in seconds", gt=0)
    perfFactor: float = Field(..., description="Performance factor (1.0-2.0)", ge=1.0, le=2.0)

    class Config:
        json_schema_extra = {
            "example": {
                "activeSeries": 100000,
                "interval": 60,
                "perfFactor": 1.3
            }
        }

class PoolRequest(BaseModel):
    activeSeries: int = Field(..., description="Number of active series", gt=0)
    interval: int = Field(..., description="Scrape interval in seconds", gt=0)
    qps: int = Field(..., description="Queries per second", gt=0)
    perfFactor: float = Field(..., description="Performance factor (1.0-2.0)", ge=1.0, le=2.0)
    queryComplexity: int = Field(..., description="Query complexity in bytes", gt=0)
    retLocalHours: int = Field(..., description="Local retention in hours", gt=0)
    retRawDays: int = Field(..., description="Raw retention in days", gt=0)
    ret5mDays: int = Field(..., description="5m downsampling retention in days", gt=0)
    ret1hDays: int = Field(..., description="1h downsampling retention in days", gt=0)

    class Config:
        json_schema_extra = {
            "example": {
                "activeSeries": 100000,
                "interval": 60,
                "qps": 15,
                "perfFactor": 1.3,
                "queryComplexity": 268435456,
                "retLocalHours": 6,
                "retRawDays": 14,
                "ret5mDays": 90,
                "ret1hDays": 365
            }
        }
