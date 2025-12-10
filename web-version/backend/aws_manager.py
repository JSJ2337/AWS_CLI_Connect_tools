"""
기존 EC2Menu v5.1.9의 AWS 관리 클래스들을 웹 API용으로 래핑
"""
import sys
import os
from pathlib import Path

# 상위 디렉토리의 원본 스크립트를 import
parent_dir = Path(__file__).parent.parent
sys.path.append(str(parent_dir))

try:
    # 기존 스크립트에서 필요한 클래스들 import
    from ec2menu_v5_1_9 import (
        AWSManager as OriginalAWSManager,
        FileTransferManager as OriginalFileTransferManager,
        BatchJobManager as OriginalBatchJobManager,
        PerformanceCache,
        Colors,
        colored_text,
        sort_instances,
        load_history,
        save_history,
        add_to_history
    )
except ImportError as e:
    print(f"원본 스크립트 import 실패: {e}")
    print("ec2menu_v5.1.9.py 파일이 상위 디렉토리에 있는지 확인하세요.")
    sys.exit(1)

from typing import List, Dict, Optional, Any
import asyncio
import json
from models import (
    EC2Instance, RDSInstance, ECSCluster, ECSTask, CacheCluster,
    FileTransferResult, BatchJobResult
)

class WebAWSManager:
    """기존 AWSManager를 웹 API용으로 래핑한 클래스"""
    
    def __init__(self, profile: str):
        self.original_manager = OriginalAWSManager(profile)
        self.profile = profile
    
    async def list_regions(self) -> List[str]:
        """리전 목록 조회 (기본 리전 지정으로 수정)"""
        try:
            # 기본 리전(us-east-1)을 사용하여 EC2 클라이언트 생성
            session = self.original_manager.session
            ec2 = session.client('ec2', region_name='us-east-1')
            resp = ec2.describe_regions(AllRegions=False)
            regions = [r['RegionName'] for r in resp.get('Regions', [])]
            return regions
        except Exception as e:
            print(f"❌ AWS 리전 목록 조회 실패: {e}")
            # 기본 리전 목록 반환
            return [
                'us-east-1', 'us-east-2', 'us-west-1', 'us-west-2',
                'eu-west-1', 'eu-west-2', 'eu-central-1', 'ap-northeast-1',
                'ap-northeast-2', 'ap-southeast-1', 'ap-southeast-2'
            ]
    
    async def list_instances(self, region: str, force_refresh: bool = False) -> List[EC2Instance]:
        """EC2 인스턴스 목록을 웹 형식으로 변환"""
        raw_instances = self.original_manager.list_instances(region, force_refresh)
        
        web_instances = []
        for inst in raw_instances:
            # 태그에서 Name 추출
            name = None
            tags = {}
            for tag in inst.get('Tags', []):
                tags[tag['Key']] = tag['Value']
                if tag['Key'] == 'Name':
                    name = tag['Value']
            
            web_instance = EC2Instance(
                instance_id=inst['InstanceId'],
                name=name,
                instance_type=inst['InstanceType'],
                state=inst['State']['Name'],
                public_ip=inst.get('PublicIpAddress'),
                private_ip=inst.get('PrivateIpAddress'),
                platform=inst.get('Platform', 'linux'),
                region=inst.get('_region', region),
                tags=tags
            )
            web_instances.append(web_instance)
        
        return web_instances
    
    async def list_instances_multi_region(self, regions: List[str], force_refresh: bool = False) -> List[EC2Instance]:
        """멀티 리전 인스턴스 목록 조회"""
        raw_instances = self.original_manager.list_instances_multi_region(regions, force_refresh)
        
        web_instances = []
        for inst in raw_instances:
            # 태그에서 Name 추출
            name = None
            tags = {}
            for tag in inst.get('Tags', []):
                tags[tag['Key']] = tag['Value']
                if tag['Key'] == 'Name':
                    name = tag['Value']
            
            web_instance = EC2Instance(
                instance_id=inst['InstanceId'],
                name=name,
                instance_type=inst['InstanceType'],
                state=inst['State']['Name'],
                public_ip=inst.get('PublicIpAddress'),
                private_ip=inst.get('PrivateIpAddress'),
                platform=inst.get('Platform', 'linux'),
                region=inst.get('_region'),
                tags=tags
            )
            web_instances.append(web_instance)
        
        return web_instances
    
    async def get_rds_endpoints(self, region: str, force_refresh: bool = False) -> List[RDSInstance]:
        """RDS 인스턴스 목록을 웹 형식으로 변환"""
        raw_dbs = self.original_manager.get_rds_endpoints(region, force_refresh)
        
        web_dbs = []
        for db in raw_dbs:
            web_db = RDSInstance(
                db_instance_id=db['Id'],
                engine=db['Engine'],
                endpoint=db['Endpoint'],
                port=db['Port'],
                status=db.get('Status', 'unknown'),
                region=db.get('_region', region),
                db_name=db.get('DBName')
            )
            web_dbs.append(web_db)
        
        return web_dbs
    
    async def get_rds_endpoints_multi_region(self, regions: List[str], force_refresh: bool = False) -> List[RDSInstance]:
        """멀티 리전 RDS 목록 조회"""
        raw_dbs = self.original_manager.get_rds_endpoints_multi_region(regions, force_refresh)
        
        web_dbs = []
        for db in raw_dbs:
            web_db = RDSInstance(
                db_instance_id=db['Id'],
                engine=db['Engine'],
                endpoint=db['Endpoint'],
                port=db['Port'],
                status=db.get('Status', 'unknown'),
                region=db.get('_region'),
                db_name=db.get('DBName')
            )
            web_dbs.append(web_db)
        
        return web_dbs
    
    async def list_ecs_clusters(self, region: str, force_refresh: bool = False) -> List[ECSCluster]:
        """ECS 클러스터 목록을 웹 형식으로 변환"""
        raw_clusters = self.original_manager.list_ecs_clusters(region, force_refresh)
        
        web_clusters = []
        for cluster in raw_clusters:
            web_cluster = ECSCluster(
                cluster_name=cluster['clusterName'],
                status=cluster['status'],
                running_tasks=cluster.get('runningTasksCount', 0),
                pending_tasks=cluster.get('pendingTasksCount', 0),
                region=cluster.get('_region', region)
            )
            web_clusters.append(web_cluster)
        
        return web_clusters
    
    async def list_ecs_tasks(self, region: str, cluster_name: str, service_name: str = None, force_refresh: bool = False) -> List[ECSTask]:
        """ECS 태스크 목록을 웹 형식으로 변환"""
        raw_tasks = self.original_manager.list_ecs_tasks(region, cluster_name, service_name, force_refresh)
        
        web_tasks = []
        for task in raw_tasks:
            # 컨테이너 이름 추출
            container_name = "unknown"
            if task.get('containers'):
                container_name = task['containers'][0].get('name', 'unknown')
            
            web_task = ECSTask(
                task_arn=task['taskArn'],
                task_definition=task['taskDefinitionArn'].split('/')[-1],
                cluster_name=cluster_name,
                container_name=container_name,
                status=task.get('lastStatus', 'unknown'),
                region=task.get('_region', region)
            )
            web_tasks.append(web_task)
        
        return web_tasks
    
    async def list_cache_clusters(self, region: str, force_refresh: bool = False) -> List[CacheCluster]:
        """ElastiCache 클러스터 목록을 웹 형식으로 변환"""
        raw_clusters = self.original_manager.list_cache_clusters(region, force_refresh)
        
        web_clusters = []
        for cluster in raw_clusters:
            web_cluster = CacheCluster(
                cluster_id=cluster['Id'],
                engine=cluster['Engine'],
                endpoint=cluster['Endpoint'],
                port=cluster['Port'],
                status=cluster.get('Status', 'unknown'),
                region=cluster.get('_region', region)
            )
            web_clusters.append(web_cluster)
        
        return web_clusters
    
    async def get_jump_hosts(self, region: str) -> List[EC2Instance]:
        """점프 호스트 목록 조회 (Role=jumphost 태그 필터링)"""
        raw_instances = self.original_manager.list_ssm_managed(region, {'Role': 'jumphost'})
        
        web_instances = []
        for inst in raw_instances:
            # 태그에서 Name 추출
            name = None
            tags = {}
            for tag in inst.get('Tags', []):
                tags[tag['Key']] = tag['Value']
                if tag['Key'] == 'Name':
                    name = tag['Value']
            
            web_instance = EC2Instance(
                instance_id=inst['InstanceId'],
                name=name,
                instance_type=inst['InstanceType'],
                state=inst['State']['Name'],
                public_ip=inst.get('PublicIpAddress'),
                private_ip=inst.get('PrivateIpAddress'),
                platform=inst.get('Platform', 'linux'),
                region=region,
                tags=tags
            )
            web_instances.append(web_instance)
        
        return web_instances

class WebFileTransferManager:
    """기존 FileTransferManager를 웹 API용으로 래핑한 클래스"""
    
    def __init__(self, aws_manager: WebAWSManager):
        self.original_manager = OriginalFileTransferManager(aws_manager.original_manager)
        self.aws_manager = aws_manager
    
    async def upload_file_to_s3(self, local_path: str, s3_key: str) -> bool:
        """S3에 파일 업로드"""
        return self.original_manager.upload_file_to_s3(local_path, s3_key)
    
    async def download_file_from_s3_to_ec2(self, s3_key: str, remote_path: str, instance_id: str, instance_name: str) -> FileTransferResult:
        """S3에서 EC2로 파일 다운로드"""
        result = self.original_manager.download_file_from_s3_to_ec2(s3_key, remote_path, instance_id, instance_name)
        
        return FileTransferResult(
            instance_id=result.instance_id,
            instance_name=result.instance_name,
            local_path=result.local_path,
            remote_path=result.remote_path,
            file_size=result.file_size,
            status=result.status,
            error_message=result.error_message,
            transfer_time=result.transfer_time
        )

class WebBatchJobManager:
    """기존 BatchJobManager를 웹 API용으로 래핑한 클래스"""
    
    def __init__(self, file_transfer_manager: WebFileTransferManager):
        self.original_manager = OriginalBatchJobManager(file_transfer_manager.original_manager)
        self.file_transfer_manager = file_transfer_manager
    
    async def start_batch_transfer(self, instances: List[Dict], local_file_path: str, remote_path: str) -> str:
        """배치 파일 전송 시작"""
        job_id = self.original_manager.start_batch_transfer(instances, local_file_path, remote_path)
        return job_id
    
    async def get_job_status(self, job_id: str) -> Optional[BatchJobResult]:
        """배치 작업 상태 조회"""
        result = self.original_manager.get_job_status(job_id)
        if not result:
            return None
        
        web_results = []
        for file_result in result.results:
            web_result = FileTransferResult(
                instance_id=file_result.instance_id,
                instance_name=file_result.instance_name,
                local_path=file_result.local_path,
                remote_path=file_result.remote_path,
                file_size=file_result.file_size,
                status=file_result.status,
                error_message=file_result.error_message,
                transfer_time=file_result.transfer_time
            )
            web_results.append(web_result)
        
        return BatchJobResult(
            job_id=result.job_id,
            total_instances=result.total_instances,
            completed=result.completed,
            failed=result.failed,
            results=web_results,
            status=result.status
        )