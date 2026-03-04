from pydantic import BaseModel, Field

RESOURCE_PATTERN = "^[0-9]+[KMG]i$"
CPU_PATTERN = "^([0-9]+)m?$"
TIME_WINDOW_REGEX = "^[0-9]+[hmdy]$"


class BasicResources (BaseModel):
    memory: str = Field(..., description="memory in Ki/Mi/Gi", pattern=RESOURCE_PATTERN)
    cpu: str = Field(..., description="cpu in cores/millicores", pattern=CPU_PATTERN)

class Resources (BaseModel):
    requests: BasicResources
    limits: BasicResources
    replicas: int = Field(..., description="number of replicas in ints", gt=0)

class ResourcesWithStorage (Resources):
    storage: str = Field(..., description="storage of PVC in Ki/Mi/Gi", pattern=RESOURCE_PATTERN)

class DatapointsPerSecond(BaseModel):
    dps: int = Field(..., description="data points per second, in ints", gt=0)

class DataRetention (BaseModel):
    raw_data: str = Field(..., description="time to store raw metrics", pattern=TIME_WINDOW_REGEX)
    downsample_5m: str = Field(..., description="time to store 5m downsampling metrics", pattern=TIME_WINDOW_REGEX)
    downsample_1h: str = Field(..., description="time to store 1h downsampling metrics", pattern=TIME_WINDOW_REGEX)

class CollectorResources (Resources, DatapointsPerSecond):
    ephemeral_storage: str = Field(description="ephemeral storage in Ki/Mi/Gi", pattern=RESOURCE_PATTERN, default=None)

    class Config:
        json_schema_extra = {
            "example": {
                "requests": {
                    "memory": "512Mi",
                    "cpu": "1",
                },
                "limits": {
                    "memory": "1Gi",
                    "cpu": "1",
                },
                "replicas": 1,
                "dps": 5000,
                "ephemeral_storage": "512Mi"
            }
        }
class PoolResources (DatapointsPerSecond):
    query: Resources
    query_frontend: Resources
    receiver_router: Resources
    receiver_ingestor: ResourcesWithStorage
    store: ResourcesWithStorage
    compactor: ResourcesWithStorage
    s3: str = Field(..., description="S3 size in Ki/Mi/Gi", pattern=RESOURCE_PATTERN)
    data_retention: DataRetention

    class Config:
        json_schema_extra = {
            "example": {
                "query": {
                    "requests": {
                        "memory": "1Gi",
                        "cpu": "1",
                    },
                    "limits": {
                        "memory": "2Gi",
                        "cpu": "2",
                    },
                    "replicas": 2
                },
                "query_frontend": {
                    "requests": {
                        "memory": "1Gi",
                        "cpu": "1",
                    },
                    "limits": {
                        "memory": "1Gi",
                        "cpu": "1",
                    },
                    "replicas": 2
                },
                "receiver_router": {
                    "requests": {
                        "memory": "1Gi",
                        "cpu": "1",
                    },
                    "limits": {
                        "memory": "2Gi",
                        "cpu": "2",
                    },
                    "replicas": 2
                },
                "receiver_ingestor": {
                    "requests": {
                        "memory": "2Gi",
                        "cpu": "2",
                    },
                    "limits": {
                        "memory": "4Gi",
                        "cpu": "4",
                    },
                    "replicas": 1,
                    "storage": "50Gi"
                },
                "store": {
                    "requests": {
                        "memory": "2Gi",
                        "cpu": "1",
                    },
                    "limits": {
                        "memory": "4Gi",
                        "cpu": "2",
                    },
                    "replicas": 1,
                    "storage": "100Gi"
                },
                "compactor": {
                    "requests": {
                        "memory": "4Gi",
                        "cpu": "2",
                    },
                    "limits": {
                        "memory": "8Gi",
                        "cpu": "4",
                    },
                    "replicas": 1,
                    "storage": "200Gi"
                },
                "s3": "500Gi",
                "data_retention": {
                    "raw_data": "30d",
                    "downsample_5m": "90d",
                    "downsample_1h": "150d"
                }
            }
        }

class CollectorRequest(DatapointsPerSecond):
    class Config:
        json_schema_extra = {
            "example": {
                "dps": 1667
            }
        }


class PoolRequest(DatapointsPerSecond):
    scrape_interval: int = Field(..., description="Scrape interval in seconds", gt=0, le=300)
    retention: int = Field(..., description="Retention in days", gt=0, le=3650)

    class Config:
        json_schema_extra = {
            "example": {
                "dps": 1667,
                "scrape_interval": 60,
                "retention": 14
            }
        }