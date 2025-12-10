"""
EC2Menu Web API 서버
기존 CLI 스크립트의 모든 기능을 웹 API로 제공
"""
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import logging
import asyncio
from typing import List, Optional
import os
from pathlib import Path
import json

# 모델 및 관리자 클래스 import
from models import *
from aws_manager import WebAWSManager, WebFileTransferManager, WebBatchJobManager
from websocket_terminal import SSMWebSocketManager, RDPTunnelManager
# from guacamole_manager import guacamole_manager  # 네이티브 RDP 사용으로 주석처리

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# FastAPI 앱 생성
app = FastAPI(
    title="EC2Menu Web API",
    description="AWS 리소스 관리를 위한 웹 API",
    version="1.0.0"
)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],  # React 개발 서버
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 전역 관리자 인스턴스들
aws_managers: dict = {}  # profile별 AWSManager 캐시
ssm_websocket_manager = SSMWebSocketManager()
rdp_tunnel_manager = RDPTunnelManager()

def get_aws_manager(profile: str) -> WebAWSManager:
    """AWS 매니저 인스턴스 가져오기 (캐싱)"""
    if profile not in aws_managers:
        aws_managers[profile] = WebAWSManager(profile)
    return aws_managers[profile]

# ============================================================================
# 프로파일 및 리전 관련 API
# ============================================================================

@app.get("/api/profiles", response_model=ProfileListResponse)
async def list_profiles():
    """AWS 프로파일 목록 조회"""
    try:
        # 기존 스크립트의 list_profiles 함수 사용
        import sys
        from pathlib import Path
        parent_dir = Path(__file__).parent.parent
        sys.path.append(str(parent_dir))
        from ec2menu_v5_1_9 import list_profiles
        
        profiles = list_profiles()
        default_profile = "aws-sys" if "aws-sys" in profiles else ("default" if "default" in profiles else profiles[0] if profiles else None)
        logger.info(f"프로파일 목록: {profiles}, 기본 프로파일: {default_profile}")
        return ProfileListResponse(
            profiles=profiles,
            default_profile=default_profile
        )
    except Exception as e:
        logger.error(f"프로파일 목록 조회 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/profiles/{profile}/regions", response_model=RegionListResponse)
async def list_regions(profile: str):
    """리전 목록 조회"""
    try:
        manager = get_aws_manager(profile)
        regions = await manager.list_regions()
        return RegionListResponse(regions=regions)
    except Exception as e:
        logger.error(f"리전 목록 조회 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# EC2 관련 API
# ============================================================================

@app.get("/api/profiles/{profile}/regions/{region}/instances", response_model=InstanceListResponse)
async def list_instances(profile: str, region: str, force_refresh: bool = False):
    """EC2 인스턴스 목록 조회"""
    try:
        manager = get_aws_manager(profile)
        
        if region == "multi-region":
            # 멀티 리전 조회
            all_regions = await manager.list_regions()
            instances = await manager.list_instances_multi_region(all_regions, force_refresh)
        else:
            # 단일 리전 조회
            instances = await manager.list_instances(region, force_refresh)
        
        # 인스턴스를 name 필드로 정렬 (없으면 instance_id로)
        def get_sort_key(instance):
            if hasattr(instance, 'name') and instance.name:
                return instance.name
            elif hasattr(instance, 'InstanceId'):
                return instance.InstanceId
            else:
                return getattr(instance, 'instance_id', '')

        sorted_instances = sorted(instances, key=get_sort_key)

        return InstanceListResponse(
            instances=sorted_instances,
            total_count=len(sorted_instances),
            region=region
        )
    except Exception as e:
        logger.error(f"인스턴스 목록 조회 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/profiles/{profile}/regions/{region}/jump-hosts", response_model=InstanceListResponse)
async def list_jump_hosts(profile: str, region: str):
    """점프 호스트 목록 조회 (Role=jumphost 태그 필터링)"""
    try:
        manager = get_aws_manager(profile)
        jump_hosts = await manager.get_jump_hosts(region)
        
        # 점프 호스트를 name 필드로 정렬 (없으면 instance_id로)
        def get_sort_key(instance):
            if hasattr(instance, 'name') and instance.name:
                return instance.name
            elif hasattr(instance, 'InstanceId'):
                return instance.InstanceId
            else:
                return getattr(instance, 'instance_id', '')

        sorted_jump_hosts = sorted(jump_hosts, key=get_sort_key)

        return InstanceListResponse(
            instances=sorted_jump_hosts,
            total_count=len(sorted_jump_hosts),
            region=region
        )
    except Exception as e:
        logger.error(f"점프 호스트 목록 조회 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# SSM 터미널 관련 API
# ============================================================================

@app.post("/api/profiles/{profile}/regions/{region}/instances/{instance_id}/terminal")
async def start_terminal_session(profile: str, region: str, instance_id: str):
    """SSM 터미널 세션 시작"""
    try:
        # multi-region인 경우 인스턴스의 실제 리전 찾기
        if region == "multi-region":
            manager = get_aws_manager(profile)
            all_regions = await manager.list_regions()
            instances = await manager.list_instances_multi_region(all_regions, False)

            # 해당 인스턴스의 실제 리전 찾기
            target_instance = next((inst for inst in instances if inst.instance_id == instance_id), None)
            if not target_instance:
                raise HTTPException(status_code=404, detail="인스턴스를 찾을 수 없습니다")

            actual_region = target_instance.region
        else:
            actual_region = region

        session = await ssm_websocket_manager.start_ssm_session(profile, actual_region, instance_id)
        return session
    except Exception as e:
        logger.error(f"터미널 세션 시작 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/terminal/sessions/{session_id}")
async def terminate_terminal_session(session_id: str):
    """SSM 터미널 세션 종료"""
    try:
        success = await ssm_websocket_manager.terminate_session(session_id)
        if success:
            return {"message": "세션이 성공적으로 종료되었습니다"}
        else:
            raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다")
    except Exception as e:
        logger.error(f"터미널 세션 종료 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.websocket("/ws/terminal/{session_id}")
async def websocket_terminal(websocket: WebSocket, session_id: str):
    """WebSocket 터미널 연결"""
    await websocket.accept()
    try:
        await ssm_websocket_manager.handle_websocket_connection(websocket, session_id)
    except WebSocketDisconnect:
        logger.info(f"터미널 WebSocket 연결 종료: {session_id}")
    except Exception as e:
        logger.error(f"터미널 WebSocket 오류: {e}")

# ============================================================================
# RDS 관련 API
# ============================================================================

@app.get("/api/profiles/{profile}/regions/{region}/rds", response_model=RDSListResponse)
async def list_rds_instances(profile: str, region: str, force_refresh: bool = False):
    """RDS 인스턴스 목록 조회"""
    try:
        manager = get_aws_manager(profile)
        
        if region == "multi-region":
            # 멀티 리전 조회
            all_regions = await manager.list_regions()
            databases = await manager.get_rds_endpoints_multi_region(all_regions, force_refresh)
        else:
            # 단일 리전 조회
            databases = await manager.get_rds_endpoints(region, force_refresh)
        
        return RDSListResponse(
            databases=databases,
            total_count=len(databases),
            region=region
        )
    except Exception as e:
        logger.error(f"RDS 목록 조회 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/profiles/{profile}/regions/{region}/rds/{db_instance_id}/tunnel")
async def start_rds_tunnel(profile: str, region: str, db_instance_id: str, request: RDSTunnelRequest):
    """RDS 포트 포워딩 터널 시작"""
    try:
        # RDS 정보 가져오기
        manager = get_aws_manager(profile)
        databases = await manager.get_rds_endpoints(region)
        db_info = next((db for db in databases if db.db_instance_id == db_instance_id), None)
        
        if not db_info:
            raise HTTPException(status_code=404, detail="RDS 인스턴스를 찾을 수 없습니다")
        
        # 터널 시작
        tunnel_info = await rdp_tunnel_manager.start_rds_tunnel(
            profile=profile,
            region=region,
            jump_host_id=request.jump_host_id,
            db_endpoint=db_info.endpoint,
            db_port=db_info.port
        )
        
        return tunnel_info
    except Exception as e:
        logger.error(f"RDS 터널 시작 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# ECS 관련 API
# ============================================================================

@app.get("/api/profiles/{profile}/regions/{region}/ecs/clusters", response_model=ECSListResponse)
async def list_ecs_clusters(profile: str, region: str, force_refresh: bool = False):
    """ECS 클러스터 목록 조회"""
    try:
        manager = get_aws_manager(profile)
        clusters = await manager.list_ecs_clusters(region, force_refresh)
        
        return ECSListResponse(
            clusters=clusters,
            total_count=len(clusters),
            region=region
        )
    except Exception as e:
        logger.error(f"ECS 클러스터 목록 조회 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/profiles/{profile}/regions/{region}/ecs/clusters/{cluster_name}/tasks")
async def list_ecs_tasks(profile: str, region: str, cluster_name: str, service_name: Optional[str] = None, force_refresh: bool = False):
    """ECS 태스크 목록 조회"""
    try:
        manager = get_aws_manager(profile)
        tasks = await manager.list_ecs_tasks(region, cluster_name, service_name, force_refresh)
        
        return {"tasks": tasks, "total_count": len(tasks), "cluster_name": cluster_name}
    except Exception as e:
        logger.error(f"ECS 태스크 목록 조회 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# ElastiCache 관련 API
# ============================================================================

@app.get("/api/profiles/{profile}/regions/{region}/cache", response_model=CacheListResponse)
async def list_cache_clusters(profile: str, region: str, force_refresh: bool = False):
    """ElastiCache 클러스터 목록 조회"""
    try:
        manager = get_aws_manager(profile)
        clusters = await manager.list_cache_clusters(region, force_refresh)
        
        return CacheListResponse(
            clusters=clusters,
            total_count=len(clusters),
            region=region
        )
    except Exception as e:
        logger.error(f"캐시 클러스터 목록 조회 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================

# RDP 관련 API
# ============================================================================

@app.post("/api/profiles/{profile}/regions/{region}/instances/{instance_id}/rdp")
async def start_rdp_tunnel(profile: str, region: str, instance_id: str):
    """RDP 포트 포워딩 터널 시작"""
    try:
        # multi-region인 경우 인스턴스의 실제 리전 찾기
        if region == "multi-region":
            manager = get_aws_manager(profile)
            all_regions = await manager.list_regions()
            instances = await manager.list_instances_multi_region(all_regions, False)

            # 해당 인스턴스의 실제 리전 찾기
            target_instance = next((inst for inst in instances if inst.instance_id == instance_id), None)
            if not target_instance:
                raise HTTPException(status_code=404, detail="인스턴스를 찾을 수 없습니다")

            actual_region = target_instance.region
        else:
            actual_region = region

        tunnel_info = await rdp_tunnel_manager.start_rdp_tunnel(profile, actual_region, instance_id)
        
        # .rdp 파일 내용 생성
        rdp_content = f"""full address:s:localhost:{tunnel_info['local_port']}
username:s:
screen mode id:i:2
session bpp:i:32
compression:i:1
keyboardhook:i:2
audiocapturemode:i:0
videoplaybackmode:i:1
connection type:i:7
networkautodetect:i:1
bandwidthautodetect:i:1
enableworkspacereconnect:i:0
disable wallpaper:i:0
allow font smoothing:i:0
allow desktop composition:i:0
disable full window drag:i:1
disable menu anims:i:1
disable themes:i:0
disable cursor setting:i:0
bitmapcachepersistenable:i:1"""
        
        tunnel_info['rdp_file_content'] = rdp_content
        return tunnel_info
    except Exception as e:
        logger.error(f"RDP 터널 시작 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/tunnels/{tunnel_id}")
async def terminate_tunnel(tunnel_id: str):
    """터널 종료"""
    try:
        success = await rdp_tunnel_manager.terminate_tunnel(tunnel_id)
        if success:
            return {"message": "터널이 성공적으로 종료되었습니다"}
        else:
            raise HTTPException(status_code=404, detail="터널을 찾을 수 없습니다")
    except Exception as e:
        logger.error(f"터널 종료 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# 파일 전송 관련 API
# ============================================================================

@app.post("/api/profiles/{profile}/files/upload")
async def upload_file(profile: str, file: UploadFile = File(...)):
    """파일 업로드 (S3 경유)"""
    try:
        manager = get_aws_manager(profile)
        file_manager = WebFileTransferManager(manager)
        
        # 임시 파일로 저장
        temp_dir = Path("/tmp/ec2menu-uploads")
        temp_dir.mkdir(exist_ok=True)
        temp_file_path = temp_dir / file.filename
        
        with open(temp_file_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)
        
        # S3에 업로드
        s3_key = f"temp-files/{file.filename}"
        success = await file_manager.upload_file_to_s3(str(temp_file_path), s3_key)
        
        if success:
            return {
                "message": "파일 업로드 성공",
                "filename": file.filename,
                "s3_key": s3_key,
                "file_size": len(content)
            }
        else:
            raise HTTPException(status_code=500, detail="파일 업로드 실패")
            
    except Exception as e:
        logger.error(f"파일 업로드 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/profiles/{profile}/files/transfer")
async def transfer_file_to_instances(profile: str, request: FileUploadRequest):
    """여러 인스턴스에 파일 전송"""
    try:
        manager = get_aws_manager(profile)
        file_manager = WebFileTransferManager(manager)
        batch_manager = WebBatchJobManager(file_manager)
        
        # 인스턴스 정보 조회
        instances = await manager.list_instances(request.region)
        target_instances = [inst for inst in instances if inst.instance_id in request.instance_ids]
        
        # 배치 전송 시작
        job_id = await batch_manager.start_batch_transfer(
            instances=[{"InstanceId": inst.instance_id, "Name": inst.name} for inst in target_instances],
            local_file_path="",  # S3에서 다운로드
            remote_path=request.remote_path
        )
        
        return {"job_id": job_id, "message": "배치 전송 시작"}
    except Exception as e:
        logger.error(f"파일 전송 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/batch-jobs/{job_id}")
async def get_batch_job_status(job_id: str, profile: str):
    """배치 작업 상태 조회"""
    try:
        manager = get_aws_manager(profile)
        file_manager = WebFileTransferManager(manager)
        batch_manager = WebBatchJobManager(file_manager)
        
        status = await batch_manager.get_job_status(job_id)
        if status:
            return status
        else:
            raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다")
    except Exception as e:
        logger.error(f"배치 작업 상태 조회 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# 시스템 정보 및 상태 API
# ============================================================================

@app.get("/api/status")
async def get_system_status():
    """시스템 상태 조회"""
    return {
        "status": "healthy",
        "active_sessions": len(ssm_websocket_manager.active_sessions),
        "active_tunnels": len(rdp_tunnel_manager.active_tunnels),
        "cached_managers": len(aws_managers)
    }

@app.get("/api/sessions")
async def list_active_sessions():
    """활성 세션 목록 조회"""
    return {
        "terminal_sessions": ssm_websocket_manager.list_active_sessions(),
        "tunnels": rdp_tunnel_manager.list_active_tunnels()
    }

# ============================================================================
# 앱 시작
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)