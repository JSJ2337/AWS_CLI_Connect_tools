from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from enum import Enum

class ServiceType(str, Enum):
    EC2 = "ec2"
    RDS = "rds"
    ECS = "ecs"
    CACHE = "cache"

class InstanceStatus(str, Enum):
    RUNNING = "running"
    STOPPED = "stopped"
    PENDING = "pending"
    STOPPING = "stopping"
    STARTING = "starting"

# 요청 모델들
class ProfileRequest(BaseModel):
    profile: str

class RegionRequest(BaseModel):
    profile: str
    region: str

class InstanceListRequest(BaseModel):
    profile: str
    region: str
    force_refresh: Optional[bool] = False

class SSMSessionRequest(BaseModel):
    profile: str
    region: str
    instance_id: str

class RDSTunnelRequest(BaseModel):
    profile: str
    region: str
    db_instance_id: str
    jump_host_id: str
    db_user: str
    db_password: str

class FileUploadRequest(BaseModel):
    instance_ids: List[str]
    profile: str
    region: str
    remote_path: str

# 응답 모델들
class EC2Instance(BaseModel):
    instance_id: str
    name: Optional[str]
    instance_type: str
    state: str
    public_ip: Optional[str]
    private_ip: Optional[str]
    platform: Optional[str]
    region: Optional[str]
    tags: Optional[Dict[str, str]] = {}

class RDSInstance(BaseModel):
    db_instance_id: str
    engine: str
    endpoint: str
    port: int
    status: str
    region: Optional[str]
    db_name: Optional[str]

class ECSCluster(BaseModel):
    cluster_name: str
    status: str
    running_tasks: int
    pending_tasks: int
    region: Optional[str]

class ECSTask(BaseModel):
    task_arn: str
    task_definition: str
    cluster_name: str
    container_name: str
    status: str
    region: Optional[str]

class CacheCluster(BaseModel):
    cluster_id: str
    engine: str
    endpoint: str
    port: int
    status: str
    region: Optional[str]

class SSMSession(BaseModel):
    session_id: str
    instance_id: str
    websocket_url: str
    status: str

class RDSTunnel(BaseModel):
    session_id: str
    local_port: int
    db_endpoint: str
    db_port: int
    status: str

class FileTransferResult(BaseModel):
    instance_id: str
    instance_name: str
    local_path: str
    remote_path: str
    file_size: int
    status: str
    error_message: Optional[str] = None
    transfer_time: Optional[float] = None

class BatchJobResult(BaseModel):
    job_id: str
    total_instances: int
    completed: int
    failed: int
    results: List[FileTransferResult]
    status: str

# 통합 응답 모델들
class InstanceListResponse(BaseModel):
    instances: List[EC2Instance]
    total_count: int
    region: str

class RDSListResponse(BaseModel):
    databases: List[RDSInstance]
    total_count: int
    region: str

class ECSListResponse(BaseModel):
    clusters: List[ECSCluster]
    total_count: int
    region: str

class CacheListResponse(BaseModel):
    clusters: List[CacheCluster]
    total_count: int
    region: str

class ProfileListResponse(BaseModel):
    profiles: List[str]
    default_profile: Optional[str]

class RegionListResponse(BaseModel):
    regions: List[str]

class ConnectionHistory(BaseModel):
    service_type: ServiceType
    profile: str
    region: str
    instance_id: str
    instance_name: str
    timestamp: str

class ErrorResponse(BaseModel):
    error: str
    message: str
    details: Optional[Dict[str, Any]] = None