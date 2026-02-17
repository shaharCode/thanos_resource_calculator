from pydantic import BaseModel, Field
from typing import Optional

RESOURCE_PATTERN = "^[0-9]+[KMG]i$"
CPU_PATTERN = "^([0-9]+)m?$"

class BasicResources(BaseModel):
    memory: str = Field(..., description="Memory in Ki/Mi/Gi", pattern=RESOURCE_PATTERN)
    cpu: str = Field(..., description="CPU in cores or millicores (e.g. '1', '500m')", pattern=CPU_PATTERN)
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
                    "cpu": "1",
                    "ephemeralStorage": "512Mi"
                },
                "limits": {
                    "memory": "1Gi",
                    "cpu": "1",
                    "ephemeralStorage": "1Gi"
                },
                "replicas": 1,
                "dps": 5000
            }
        }

class PoolResources(BaseModel):
    receiver_router: Resources
    query: Resources
    query_frontend: Resources
    receiver_ingestor: ResourcesWithStorage
    store: ResourcesWithStorage
    compactor: Optional[ResourcesWithStorage]
    s3: str = Field(..., description="S3 size in Ki/Mi/Gi", pattern=RESOURCE_PATTERN)
    dps: int = Field(..., description="Number of data points per second, in ints", gt=0)

    class Config:
        json_schema_extra = {
            "example": {
                "receiver_router": {
                    "requests": {"memory": "1Gi", "cpu": "1"},
                    "limits": {"memory": "2Gi", "cpu": "2"},
                    "replicas": 2
                },
                "query": {
                    "requests": {"memory": "1Gi", "cpu": "1"},
                    "limits": {"memory": "2Gi", "cpu": "2"},
                    "replicas": 2
                },
                "query_frontend": {
                    "requests": {"memory": "1Gi", "cpu": "1"},
                    "limits": {"memory": "1Gi", "cpu": "1"},
                    "replicas": 2
                },
                "receiver_ingestor": {
                    "requests": {"memory": "2Gi", "cpu": "2"},
                    "limits": {"memory": "4Gi", "cpu": "4"},
                    "replicas": 3,
                    "storage": "50Gi"
                },
                "store": {
                    "requests": {"memory": "2Gi", "cpu": "1"},
                    "limits": {"memory": "4Gi", "cpu": "2"},
                    "replicas": 1,
                    "storage": "100Gi"
                },
                "compactor": {
                    "requests": {"memory": "4Gi", "cpu": "2"},
                    "limits": {"memory": "8Gi", "cpu": "4"},
                    "replicas": 1,
                    "storage": "200Gi"
                },
                "s3": "500Gi",
                "dps": 1667
            }
        }

class CollectorRequest(BaseModel):
    dps: float = Field(..., description="Data points per second", gt=0)

    class Config:
        json_schema_extra = {
            "example": {
                "dps": 1667
            }
        }


class PoolRequest(BaseModel):
    dps: float = Field(..., description="Data points per second", gt=0)
    scrape_interval: int = Field(..., description="Scrape interval in seconds", gt=0)
    retention: int = Field(..., description="Retention in days", gt=0)

    class Config:
        json_schema_extra = {
            "example": {
                "dps": 1667,
                "scrape_interval": 60,
                "retention": 14
            }
        }
