#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EC2, RDS, ElastiCache, ECS 접속 자동화 스크립트 v5.2.0 (macOS 전용)

v5.2.0 macOS 버전:
- 🍎 macOS 네이티브 지원 (pathlib 경로 처리)
- 🖥️ iTerm2/Terminal.app 통합 (새 탭에서 자동 접속)
- 🪟 Windows App을 통한 RDP 접속 (.rdp 파일 자동 생성)
- 🗑️ WSL/Windows 관련 코드 제거

주요 기능:
- 📁 S3 경유 파일 전송: 대용량 파일 (80MB+) 업로드/다운로드
- 🚀 배치 작업: 여러 인스턴스에 동시 명령 실행
- 📊 진행률 표시: 실시간 전송 상태 및 속도
- 🎨 컬러 테마: 상태별 색깔 구분 (running=녹색, stopped=빨강)
- 🗄️ 멀티 리전 통합 뷰 (여러 리전의 인스턴스 한 번에 조회)
- 📜 연결 히스토리 (최근 접속한 인스턴스 기록 및 빠른 재접속)
- 🐳 ECS Fargate 컨테이너 접속 (ECS Exec 활용)
- 🔑 DB 비밀번호 세션 임시 저장 (메모리만, 종료 시 삭제)
- 🏃 Role=jumphost 태그 기반 점프 호스트 자동 선택
"""
import os
import sys
import argparse
import configparser
import concurrent.futures
import logging
import readline
import subprocess
import time
import threading
from pathlib import Path
import getpass
import json
from datetime import datetime, timedelta
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Any
import uuid
import atexit

import boto3
from botocore.exceptions import ClientError, ProfileNotFound, NoCredentialsError

# 컬러 지원 라이브러리
try:
    from colorama import init, Fore, Back, Style
    init(autoreset=True)  # 색상 자동 리셋
    COLOR_SUPPORT = True
except ImportError:
    print("💡 더 나은 사용자 경험을 위해 colorama를 설치하세요: pip install colorama")
    COLOR_SUPPORT = False
    # colorama가 없을 때 빈 클래스로 대체
    class MockColor:
        def __getattr__(self, name): return ""
    Fore = Back = Style = MockColor()

# ----------------------------------------------------------------------------
# 컬러 테마 설정 (v5.0.2 원본)
# ----------------------------------------------------------------------------
class Colors:
    # 서비스별 색깔
    EC2 = Fore.BLUE
    RDS = Fore.YELLOW  
    CACHE = Fore.MAGENTA
    ECS = Fore.CYAN
    
    # 상태별 색깔
    RUNNING = Fore.GREEN
    STOPPED = Fore.RED
    PENDING = Fore.YELLOW
    WARNING = Fore.YELLOW
    ERROR = Fore.RED
    SUCCESS = Fore.GREEN
    INFO = Fore.CYAN
    
    # UI 요소
    HEADER = Style.BRIGHT + Fore.WHITE
    MENU = Fore.WHITE
    PROMPT = Fore.CYAN
    RESET = Style.RESET_ALL

def colored_text(text, color=""):
    """색깔 적용된 텍스트 반환"""
    if COLOR_SUPPORT and color:
        return f"{color}{text}{Colors.RESET}"
    return text

def get_status_color(status):
    """상태에 따른 색깔 반환"""
    status_lower = status.lower()
    if status_lower in ['running', 'available', 'active']:
        return Colors.RUNNING
    elif status_lower in ['stopped', 'terminated', 'inactive']:
        return Colors.STOPPED
    elif status_lower in ['pending', 'starting', 'stopping']:
        return Colors.PENDING
    return ""

# ----------------------------------------------------------------------------
# 캐싱 시스템 (v5.1.0 신규)
# ----------------------------------------------------------------------------
@dataclass
class CacheEntry:
    data: Any
    timestamp: datetime
    ttl_seconds: int = 300  # Config.CACHE_TTL_SECONDS로 설정됨

    def is_expired(self) -> bool:
        return datetime.now() - self.timestamp > timedelta(seconds=self.ttl_seconds)

class PerformanceCache:
    def __init__(self):
        self._cache: Dict[str, CacheEntry] = {}
        self._lock = threading.RLock()
        self._background_refresh_active = {}
    
    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            entry = self._cache.get(key)
            if entry and not entry.is_expired():
                return entry.data
            return None
    
    def set(self, key: str, data: Any, ttl_seconds: Optional[int] = None):
        if ttl_seconds is None:
            ttl_seconds = Config.CACHE_TTL_SECONDS
        with self._lock:
            self._cache[key] = CacheEntry(data, datetime.now(), ttl_seconds)
    
    def invalidate(self, key: str):
        with self._lock:
            self._cache.pop(key, None)
    
    def clear(self):
        with self._lock:
            self._cache.clear()
    
    def start_background_refresh(self, key: str, refresh_func, *args, **kwargs):
        """백그라운드에서 캐시 새로고침 (스레드 안전)"""
        with self._lock:
            if key in self._background_refresh_active:
                return
            self._background_refresh_active[key] = True

        def refresh_worker():
            try:
                new_data = refresh_func(*args, **kwargs)
                self.set(key, new_data)
            except Exception as e:
                logging.warning(f"백그라운드 새로고침 실패 ({key}): {e}")
            finally:
                with self._lock:
                    self._background_refresh_active.pop(key, None)

        threading.Thread(target=refresh_worker, daemon=True).start()

# 전역 캐시 인스턴스
_cache = PerformanceCache()

# ----------------------------------------------------------------------------
# 플랫폼 감지 함수 (v5.2.0 macOS 버전)
# ----------------------------------------------------------------------------
import platform

# 플랫폼 상수 (macOS 전용)
IS_MAC = platform.system() == 'Darwin'

def normalize_file_path(path_str):
    """파일 경로 정규화 (따옴표 제거, 경로 확장)"""
    # 따옴표 제거
    if (path_str.startswith('"') and path_str.endswith('"')) or \
       (path_str.startswith("'") and path_str.endswith("'")):
        path_str = path_str[1:-1]

    # pathlib로 경로 정규화 및 확장
    return str(Path(path_str).expanduser().resolve())

# ----------------------------------------------------------------------------
# 설정 및 기본값 (v5.2.0 macOS 버전)
# ----------------------------------------------------------------------------

class Config:
    """애플리케이션 설정 (매직 넘버 제거 및 중앙 관리)"""
    # 파일 경로
    AWS_CONFIG_PATH = Path("~/.aws/config").expanduser()
    AWS_CRED_PATH = Path("~/.aws/credentials").expanduser()
    LOG_PATH = Path.home() / ".ec2menu.log"
    HISTORY_PATH = Path.home() / ".ec2menu_history.json"
    BATCH_RESULTS_PATH = Path.home() / ".ec2menu_batch_results.json"

    # 성능 설정
    DEFAULT_WORKERS = 20
    CACHE_TTL_SECONDS = 300  # 5분

    # 배치 작업 설정
    BATCH_MAX_RETRIES = 3
    BATCH_TIMEOUT_SECONDS = 600  # 10분
    BATCH_MAX_WAIT_ATTEMPTS = 200
    BATCH_CONCURRENT_JOBS = 5

    # 페이지네이션 설정
    EC2_PAGE_SIZE = 100
    MAX_PAGINATION_PAGES = 100

    # 포트 설정
    PORT_RANGE_START = 10000
    PORT_RANGE_END = 19999
    RDS_PORT_START = 11000

    # SSM 설정
    SSM_TIMEOUT_SECONDS = 600

    # 히스토리 설정
    HISTORY_MAX_SIZE = 100

    # 입력 재시도 설정
    MAX_INPUT_RETRIES = 5  # 잘못된 입력 최대 5회까지 허용

    # 대기 시간 설정 (초)
    WAIT_PORT_READY = 2  # 포트 포워딩 준비 대기
    WAIT_APP_LAUNCH = 0.8  # 애플리케이션 실행 대기
    WAIT_RDP_READY = 2  # RDP 클라이언트 준비 대기

    # macOS용 도구 경로 (환경변수 우선)
    DB_TOOL_PATH = os.environ.get('DB_TOOL_PATH', "mysql")
    DBEAVER_PATH = os.environ.get('DBEAVER_PATH', '/Applications/DBeaver.app/Contents/MacOS/dbeaver')
    CACHE_REDIS_CLI = os.environ.get('CACHE_REDIS_CLI', "redis-cli")
    CACHE_MEMCACHED_CLI = os.environ.get('CACHE_MEMCACHED_CLI', "telnet")

    # 디버그 모드
    DEBUG_MODE = os.environ.get('EC2MENU_DEBUG', '0') == '1'

# 하위 호환성을 위한 별칭
AWS_CONFIG_PATH = Config.AWS_CONFIG_PATH
AWS_CRED_PATH = Config.AWS_CRED_PATH
LOG_PATH = Config.LOG_PATH
HISTORY_PATH = Config.HISTORY_PATH
BATCH_RESULTS_PATH = Config.BATCH_RESULTS_PATH
DEFAULT_WORKERS = Config.DEFAULT_WORKERS
DEFAULT_DB_TOOL_PATH = Config.DB_TOOL_PATH
DEFAULT_CACHE_REDIS_CLI = Config.CACHE_REDIS_CLI
DEFAULT_CACHE_MEMCACHED_CLI = Config.CACHE_MEMCACHED_CLI

# 전역 변수
_stored_credentials = {}
_sort_key = 'Name'  # 기본 정렬 키
_sort_reverse = False  # 기본 오름차순
_temp_files_to_cleanup = []  # 프로그램 종료 시 삭제할 임시 파일

# ----------------------------------------------------------------------------
# 로거 설정 (v4.40 수정)
# ----------------------------------------------------------------------------
def setup_logger(debug: bool):
    level = logging.DEBUG if debug else logging.INFO
    fmt   = "%(asctime)s [%(levelname)s] %(message)s"
    handlers = [logging.StreamHandler(sys.stdout), logging.FileHandler(LOG_PATH, encoding="utf-8")]
    # style='%'를 명시하여 boto3 내부 로그와의 충돌 방지
    logging.basicConfig(level=level, format=fmt, handlers=handlers, style='%')

def cleanup_temp_files():
    """프로그램 종료 시 임시 파일 정리"""
    global _temp_files_to_cleanup
    for file_path in _temp_files_to_cleanup:
        try:
            if file_path.exists():
                file_path.unlink()
                logging.info(f"임시 파일 삭제됨: {file_path}")
        except Exception as e:
            logging.warning(f"임시 파일 삭제 실패: {file_path} - {e}")

# 프로그램 종료 시 자동 정리 등록
atexit.register(cleanup_temp_files)

# ----------------------------------------------------------------------------
# 파일 전송 관리 (v5.1.3 신규)
# ----------------------------------------------------------------------------
@dataclass
class FileTransferResult:
    """파일 전송 결과"""
    instance_id: str
    instance_name: str
    local_path: str
    remote_path: str
    file_size: int
    status: str  # SUCCESS, FAILED, TIMEOUT
    error_message: str = ""
    transfer_time: float = 0.0
    timestamp: datetime | None = None

class FileTransferManager:
    def __init__(self, manager):
        self.aws_manager = manager
        self.temp_bucket = None
        self.transfer_history: List[FileTransferResult] = []
        # atexit에 버킷 정리 함수 등록
        atexit.register(self.cleanup_temp_bucket)
    
    def get_or_create_temp_bucket(self):
        """임시 S3 버킷 생성 또는 기존 버킷 사용"""
        if self.temp_bucket:
            return self.temp_bucket
            
        try:
            s3 = self.aws_manager.session.client('s3')
            
            # 버킷 이름 생성 (계정 ID + 랜덤)
            account_id = self.aws_manager.session.client('sts').get_caller_identity()['Account']
            bucket_name = f"ec2menu-temp-{account_id}-{uuid.uuid4().hex[:8]}"
            
            # 버킷 생성 (리전에 따른 LocationConstraint 설정)
            region = self.aws_manager.session.region_name or 'us-east-1'
            if region == 'us-east-1':
                s3.create_bucket(Bucket=bucket_name)
            else:
                s3.create_bucket(
                    Bucket=bucket_name,
                    CreateBucketConfiguration={'LocationConstraint': region}
                )
            
            # 공개 접근 차단 설정 (보안 강화)
            s3.put_public_access_block(
                Bucket=bucket_name,
                PublicAccessBlockConfiguration={
                    'BlockPublicAcls': True,
                    'IgnorePublicAcls': True,
                    'BlockPublicPolicy': True,
                    'RestrictPublicBuckets': True
                }
            )

            # 수명 주기 정책 설정 (1일 후 자동 삭제)
            lifecycle_config = {
                'Rules': [{
                    'ID': 'temp-files-cleanup',
                    'Status': 'Enabled',
                    'Expiration': {'Days': 1},
                    'Filter': {'Prefix': 'temp-files/'}
                }]
            }
            s3.put_bucket_lifecycle_configuration(
                Bucket=bucket_name,
                LifecycleConfiguration=lifecycle_config
            )

            self.temp_bucket = bucket_name
            print(colored_text(f"✅ 임시 S3 버킷 생성: {bucket_name}", Colors.SUCCESS))
            return bucket_name
            
        except ClientError as e:
            print(colored_text(f"❌ S3 버킷 생성 실패: {str(e)}", Colors.ERROR))
            return None
    
    def upload_file_to_s3(self, local_path: str, s3_key: str) -> bool:
        """로컬 파일을 S3에 업로드"""
        try:
            s3 = self.aws_manager.session.client('s3')
            bucket_name = self.get_or_create_temp_bucket()
            
            if not bucket_name:
                return False
            
            file_size = os.path.getsize(local_path)
            print(colored_text(f"📤 S3 업로드 시작: {os.path.basename(local_path)} ({self._format_size(file_size)})", Colors.INFO))
            
            start_time = time.time()
            
            # S3 업로드 (진행률 콜백 포함)
            def progress_callback(bytes_transferred):
                progress = (bytes_transferred / file_size) * 100
                elapsed = time.time() - start_time
                speed = bytes_transferred / elapsed if elapsed > 0 else 0
                print(f"\r📊 업로드 진행: {progress:.1f}% ({self._format_size(bytes_transferred)}/{self._format_size(file_size)}) - {self._format_speed(speed)}", end="", flush=True)
            
            s3.upload_file(
                local_path, bucket_name, s3_key,
                Callback=progress_callback
            )
            
            print()  # 새 줄
            elapsed = time.time() - start_time
            print(colored_text(f"✅ S3 업로드 완료 - {elapsed:.1f}초", Colors.SUCCESS))
            return True
            
        except Exception as e:
            print(colored_text(f"❌ S3 업로드 실패: {str(e)}", Colors.ERROR))
            return False
    
    def download_file_from_s3_to_ec2(self, s3_key: str, remote_path: str, instance_id: str, instance_name: str) -> FileTransferResult:
        """S3에서 EC2로 파일 다운로드"""
        start_time = time.time()
        
        try:
            bucket_name = self.temp_bucket
            if not bucket_name:
                return FileTransferResult(
                    instance_id=instance_id,
                    instance_name=instance_name,
                    local_path="",
                    remote_path=remote_path,
                    file_size=0,
                    status="FAILED",
                    error_message="S3 버킷이 준비되지 않음",
                    timestamp=datetime.now()
                )
            
            # S3에서 EC2로 다운로드 명령
            if Config.DEBUG_MODE:
                # 디버그 모드: 상세 로그 출력
                command = f"""
                echo "=== 파일 전송 시작 ==="
                echo "S3 버킷: {bucket_name}"
                echo "S3 키: {s3_key}"
                echo "대상 경로: {remote_path}"

                # AWS CLI 설치 확인
                echo "=== AWS CLI 확인 ==="
                which aws || echo "AWS CLI not found"
                aws --version 2>/dev/null || echo "AWS CLI version check failed"

                # IAM 역할 확인
                echo "=== IAM 역할 확인 ==="
                aws sts get-caller-identity 2>/dev/null || echo "IAM role check failed"

                # S3 버킷 접근 확인
                echo "=== S3 버킷 접근 확인 ==="
                aws s3 ls s3://{bucket_name}/ 2>/dev/null || echo "S3 bucket access failed"

                # 파일 다운로드
                echo "=== 파일 다운로드 ==="
                aws s3 cp s3://{bucket_name}/{s3_key} {remote_path} --debug 2>&1

                # 결과 확인
                echo "=== 결과 확인 ==="
                if [ -f "{remote_path}" ]; then
                    echo "TRANSFER_SUCCESS: $(ls -l {remote_path} | awk '{{print $5}}')"
                    echo "File exists: YES"
                else
                    echo "TRANSFER_SUCCESS: 0"
                    echo "File exists: NO"
                fi
                echo "=== 전송 완료 ==="
                """
            else:
                # 프로덕션 모드: 간결한 출력
                command = f"""
                aws s3 cp s3://{bucket_name}/{s3_key} {remote_path} 2>&1
                if [ -f "{remote_path}" ]; then
                    echo "TRANSFER_SUCCESS: $(ls -l {remote_path} | awk '{{print $5}}')"
                else
                    echo "TRANSFER_FAILED"
                fi
                """
            
            ssm = self.aws_manager.session.client('ssm')
            response = ssm.send_command(
                InstanceIds=[instance_id],
                DocumentName='AWS-RunShellScript',
                Parameters={'commands': [command]},
                TimeoutSeconds=600  # 10분 타임아웃
            )
            
            command_id = response['Command']['CommandId']
            
            # 명령 완료 대기
            max_wait = 300  # 5분
            waited = 0
            
            while waited < max_wait:
                try:
                    result = ssm.get_command_invocation(
                        CommandId=command_id,
                        InstanceId=instance_id
                    )
                    
                    status = result['Status']
                    if status in ['Success', 'Failed', 'Cancelled', 'TimedOut']:
                        execution_time = time.time() - start_time
                        
                        if status == 'Success':
                            output = result.get('StandardOutputContent', '')
                            error_output = result.get('StandardErrorContent', '')
                            
                            # 디버깅: 전체 출력 표시
                            print(colored_text(f"🔍 SSM 명령 출력:", Colors.INFO))
                            print(colored_text(f"STDOUT:\n{output}", Colors.INFO))
                            if error_output:
                                print(colored_text(f"STDERR:\n{error_output}", Colors.WARNING))
                            
                            # 파일 크기 추출
                            file_size = 0
                            for line in output.split('\n'):
                                if line.startswith('TRANSFER_SUCCESS:'):
                                    try:
                                        file_size = int(line.split(':')[1].strip())
                                    except:
                                        pass
                            
                            return FileTransferResult(
                                instance_id=instance_id,
                                instance_name=instance_name,
                                local_path="",
                                remote_path=remote_path,
                                file_size=file_size,
                                status="SUCCESS",
                                transfer_time=execution_time,
                                timestamp=datetime.now()
                            )
                        else:
                            output = result.get('StandardOutputContent', '')
                            error_msg = result.get('StandardErrorContent', '알 수 없는 오류')
                            
                            # 디버깅: 실패 시에도 전체 출력 표시
                            print(colored_text(f"❌ SSM 명령 실패 ({status}):", Colors.ERROR))
                            print(colored_text(f"STDOUT:\n{output}", Colors.INFO))
                            print(colored_text(f"STDERR:\n{error_msg}", Colors.ERROR))
                            
                            return FileTransferResult(
                                instance_id=instance_id,
                                instance_name=instance_name,
                                local_path="",
                                remote_path=remote_path,
                                file_size=0,
                                status="FAILED",
                                error_message=error_msg,
                                transfer_time=execution_time,
                                timestamp=datetime.now()
                            )
                    
                    time.sleep(3)
                    waited += 3
                    
                except ClientError:
                    time.sleep(Config.WAIT_PORT_READY)
                    waited += 2
                    continue
            
            # 타임아웃
            return FileTransferResult(
                instance_id=instance_id,
                instance_name=instance_name,
                local_path="",
                remote_path=remote_path,
                file_size=0,
                status="TIMEOUT",
                error_message=f"명령 실행 타임아웃 ({max_wait}초)",
                transfer_time=time.time() - start_time,
                timestamp=datetime.now()
            )
            
        except Exception as e:
            return FileTransferResult(
                instance_id=instance_id,
                instance_name=instance_name,
                local_path="",
                remote_path=remote_path,
                file_size=0,
                status="FAILED",
                error_message=str(e),
                transfer_time=time.time() - start_time,
                timestamp=datetime.now()
            )
    
    def upload_file_to_multiple_instances(self, local_path: str, remote_path: str, instances: List[dict]) -> List[FileTransferResult]:
        """여러 인스턴스에 파일 업로드 (macOS용)"""
        # 경로 정규화 (따옴표 제거 및 확장)
        local_path = normalize_file_path(local_path)

        # 파일 존재 확인
        local_path_obj = Path(local_path)
        if not local_path_obj.exists():
            print(colored_text(f"❌ 로컬 파일이 존재하지 않습니다: {local_path}", Colors.ERROR))
            return []
        
        # S3 키 생성
        filename = os.path.basename(local_path)
        s3_key = f"temp-files/{uuid.uuid4().hex}/{filename}"
        
        # S3에 업로드
        if not self.upload_file_to_s3(local_path, s3_key):
            return []
        
        print(colored_text(f"\n🚀 {len(instances)}개 인스턴스에 파일 전송 시작", Colors.INFO))

        results = []

        try:
            # 병렬로 각 인스턴스에 다운로드
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(instances), 5)) as executor:
                future_to_instance = {
                    executor.submit(
                        self.download_file_from_s3_to_ec2,
                        s3_key, remote_path,
                        inst['raw']['InstanceId'],
                        inst['Name']
                    ): inst
                    for inst in instances
                }

                for future in concurrent.futures.as_completed(future_to_instance):
                    try:
                        result = future.result()
                        results.append(result)

                        # 실시간 결과 출력
                        status_color = Colors.SUCCESS if result.status == 'SUCCESS' else Colors.ERROR
                        size_str = self._format_size(result.file_size) if result.file_size > 0 else ""
                        print(f"{colored_text(result.status, status_color)} {result.instance_name} ({result.instance_id}) {size_str} - {result.transfer_time:.1f}s")

                    except Exception as e:
                        instance = future_to_instance[future]
                        print(colored_text(f"ERROR {instance['Name']} ({instance['raw']['InstanceId']}) - {str(e)}", Colors.ERROR))

            # 결과 저장
            self.transfer_history.extend(results)

            return results

        finally:
            # 항상 S3 임시 파일 정리 (예외 발생 여부와 무관)
            self.cleanup_s3_file(s3_key)
    
    def cleanup_s3_file(self, s3_key: str):
        """S3 임시 파일 삭제"""
        try:
            if self.temp_bucket:
                s3 = self.aws_manager.session.client('s3')
                s3.delete_object(Bucket=self.temp_bucket, Key=s3_key)
                print(colored_text("🗑️  S3 임시 파일 정리 완료", Colors.SUCCESS))
        except Exception as e:
            print(colored_text(f"⚠️  S3 파일 정리 실패: {str(e)}", Colors.WARNING))

    def cleanup_temp_bucket(self):
        """프로그램 종료 시 임시 S3 버킷 삭제"""
        if not self.temp_bucket:
            return

        try:
            s3 = self.aws_manager.session.client('s3')

            # 버킷 내 모든 객체 삭제
            try:
                objects = s3.list_objects_v2(Bucket=self.temp_bucket)
                if 'Contents' in objects:
                    for obj in objects['Contents']:
                        s3.delete_object(Bucket=self.temp_bucket, Key=obj['Key'])
            except Exception:
                pass  # 객체가 없거나 이미 삭제됨

            # 버킷 삭제
            s3.delete_bucket(Bucket=self.temp_bucket)
            logging.info(f"임시 S3 버킷 삭제됨: {self.temp_bucket}")
        except Exception as e:
            logging.warning(f"임시 S3 버킷 삭제 실패: {self.temp_bucket} - {e}")

    def _format_size(self, size_bytes: int) -> str:
        """바이트를 읽기 쉬운 형태로 변환"""
        if size_bytes == 0:
            return "0B"
        size_float = float(size_bytes)
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_float < 1024.0:
                return f"{size_float:.1f}{unit}"
            size_float /= 1024.0
        return f"{size_float:.1f}TB"
    
    def _format_speed(self, bytes_per_sec: float) -> str:
        """전송 속도를 읽기 쉬운 형태로 변환"""
        return f"{self._format_size(int(bytes_per_sec))}/s"

# ----------------------------------------------------------------------------
# 배치 작업 관리 (v5.1.0 신규)
# ----------------------------------------------------------------------------
@dataclass
class BatchJobResult:
    command: str
    instance_id: str
    instance_name: str
    status: str  # SUCCESS, FAILED, TIMEOUT
    output: str
    error: str
    execution_time: float
    timestamp: datetime

class BatchJobManager:
    def __init__(self, manager):
        self.aws_manager = manager
        self.results_history: List[BatchJobResult] = []
    
    def _validate_ssm_instances(self, instances: List[dict]) -> List[dict]:
        """SSM 연결 가능한 인스턴스만 필터링"""
        validated = []
        regions_to_check = {}
        
        # 리전별로 인스턴스 그룹화
        for instance_data in instances:
            region = instance_data.get('Region', 'unknown')
            if region not in regions_to_check:
                regions_to_check[region] = []
            regions_to_check[region].append(instance_data)
        
        # 각 리전별로 SSM 상태 확인
        for region, region_instances in regions_to_check.items():
            try:
                ssm = self.aws_manager.session.client('ssm', region_name=region)
                instance_ids = [inst['raw']['InstanceId'] for inst in region_instances]
                
                # SSM 관리 인스턴스 정보 조회
                response = ssm.describe_instance_information(
                    Filters=[{
                        'Key': 'InstanceIds',
                        'Values': instance_ids
                    }]
                )
                
                # 온라인 상태인 인스턴스만 선택
                online_instances = {
                    info['InstanceId']: info['PingStatus'] 
                    for info in response['InstanceInformationList']
                    if info['PingStatus'] == 'Online'
                }
                
                # 검증된 인스턴스만 추가
                for instance_data in region_instances:
                    instance_id = instance_data['raw']['InstanceId']
                    if instance_id in online_instances:
                        validated.append(instance_data)
                    else:
                        print(colored_text(f"⚠️  {instance_data['Name']} ({instance_id}): SSM 연결 불가", Colors.WARNING))
                        
            except Exception as e:
                print(colored_text(f"❌ 리전 {region} SSM 상태 확인 실패: {str(e)}", Colors.ERROR))
                # 에러 시에는 원본 인스턴스 그대로 사용 (이전 동작 유지)
                validated.extend(region_instances)
        
        return validated
    
    def execute_batch_command(self, instances: List[dict], command: str, timeout_seconds: int = 120) -> List[BatchJobResult]:
        """여러 인스턴스에서 배치 명령 실행 (개선된 안정성)"""
        print(colored_text(f"\n🚀 {len(instances)}개 인스턴스에서 배치 작업을 시작합니다...", Colors.INFO))
        print(colored_text(f"명령: {command}", Colors.INFO))
        
        # SSM 상태 사전 확인
        print(colored_text("📋 SSM 연결 상태를 확인 중...", Colors.INFO))
        validated_instances = self._validate_ssm_instances(instances)
        
        if len(validated_instances) < len(instances):
            print(colored_text(f"⚠️  {len(instances) - len(validated_instances)}개 인스턴스가 SSM 연결 불가능 상태입니다.", Colors.WARNING))
        
        if not validated_instances:
            print(colored_text("❌ 실행 가능한 인스턴스가 없습니다.", Colors.ERROR))
            return []
            
        print(colored_text(f"✅ {len(validated_instances)}개 인스턴스에서 실행합니다.", Colors.SUCCESS))
        results = []
        
        def execute_on_instance(instance_data, retry_count=0):
            instance = instance_data['raw']
            instance_id = instance['InstanceId']
            instance_name = instance_data['Name']
            region = instance_data.get('Region', 'unknown')
            
            start_time = time.time()
            max_retries = 2
            
            try:
                ssm = self.aws_manager.session.client('ssm', region_name=region)
                
                # 재시도 로직이 포함된 SSM Run Command 실행
                response = None
                last_error = None
                
                for attempt in range(max_retries + 1):
                    try:
                        if attempt > 0:
                            print(colored_text(f"🔄 {instance_name} 재시도 ({attempt}/{max_retries})", Colors.WARNING))
                            time.sleep(1 + attempt)  # 지수적 백오프
                        
                        response = ssm.send_command(
                            InstanceIds=[instance_id],
                            DocumentName='AWS-RunShellScript',
                            Parameters={
                                'commands': [command],
                                'executionTimeout': [str(timeout_seconds)]
                            },
                            TimeoutSeconds=timeout_seconds + 30
                        )
                        break  # 성공 시 루프 탈출
                        
                    except ClientError as e:
                        last_error = e
                        error_code = e.response.get('Error', {}).get('Code', '')
                        
                        # 재시도 가능한 오류인지 확인
                        if error_code in ['Throttling', 'ThrottledException', 'ServiceUnavailable', 'InternalServerError']:
                            if attempt < max_retries:
                                continue
                        else:
                            # 재시도 불가능한 오류는 즉시 실패
                            break
                
                if not response:
                    # 모든 재시도 실패
                    execution_time = time.time() - start_time
                    return BatchJobResult(
                        command=command,
                        instance_id=instance_id,
                        instance_name=instance_name,
                        status='FAILED',
                        output='',
                        error=f'Send command failed after {max_retries + 1} attempts: {str(last_error)}',
                        execution_time=execution_time,
                        timestamp=datetime.now()
                    )
                
                command_id = response['Command']['CommandId']
                
                # 명령 완료 대기 (무한 루프 방지)
                max_wait = timeout_seconds + 30
                max_attempts = 200  # 최대 200회 확인 (약 10분)
                waited = 0
                attempt_count = 0

                while waited < max_wait and attempt_count < max_attempts:
                    attempt_count += 1
                    try:
                        result = ssm.get_command_invocation(
                            CommandId=command_id,
                            InstanceId=instance_id
                        )

                        status = result['Status']
                        if status in ['Success', 'Failed', 'Cancelled', 'TimedOut']:
                            execution_time = time.time() - start_time

                            return BatchJobResult(
                                command=command,
                                instance_id=instance_id,
                                instance_name=instance_name,
                                status='SUCCESS' if status == 'Success' else 'FAILED',
                                output=result.get('StandardOutputContent', ''),
                                error=result.get('StandardErrorContent', ''),
                                execution_time=execution_time,
                                timestamp=datetime.now()
                            )

                        time.sleep(3)
                        waited += 3

                    except ClientError as e:
                        error_code = e.response.get('Error', {}).get('Code', '')
                        if error_code == 'InvocationDoesNotExist':
                            break  # 호출이 존재하지 않으면 종료
                        # 다른 에러는 재시도
                        time.sleep(Config.WAIT_PORT_READY)
                        waited += 2
                        continue
                
                # 타임아웃
                execution_time = time.time() - start_time
                return BatchJobResult(
                    command=command,
                    instance_id=instance_id,
                    instance_name=instance_name,
                    status='TIMEOUT',
                    output='',
                    error=f'Command timed out after {max_wait} seconds (timeout: {timeout_seconds}s + buffer: 30s)',
                    execution_time=execution_time,
                    timestamp=datetime.now()
                )
                
            except ClientError as e:
                execution_time = time.time() - start_time
                return BatchJobResult(
                    command=command,
                    instance_id=instance_id,
                    instance_name=instance_name,
                    status='FAILED',
                    output='',
                    error=str(e),
                    execution_time=execution_time,
                    timestamp=datetime.now()
                )
        
        # 배치 크기 제한으로 안정성 향상 (최대 5개씩 동시 실행)
        max_concurrent = min(len(validated_instances), 5)
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_concurrent) as executor:
            future_to_instance = {executor.submit(execute_on_instance, inst): inst for inst in validated_instances}
            
            for future in concurrent.futures.as_completed(future_to_instance):
                try:
                    result = future.result()
                    results.append(result)
                    
                    # 실시간 결과 출력
                    status_color = Colors.SUCCESS if result.status == 'SUCCESS' else Colors.ERROR
                    print(f"{colored_text(result.status, status_color)} {result.instance_name} ({result.instance_id}) - {result.execution_time:.1f}s")
                    
                except Exception as e:
                    instance = future_to_instance[future]
                    print(colored_text(f"ERROR {instance['Name']} ({instance['raw']['InstanceId']}) - {str(e)}", Colors.ERROR))
        
        # 결과 저장
        self.results_history.extend(results)
        self.save_results_history()
        
        return results
    
    def show_batch_results(self, results: List[BatchJobResult]):
        """배치 작업 결과 상세 표시"""
        print(colored_text(f"\n📊 배치 작업 결과 상세:", Colors.HEADER))
        print("-" * 80)
        
        success_count = sum(1 for r in results if r.status == 'SUCCESS')
        failed_count = len(results) - success_count
        
        print(f"총 {len(results)}개 인스턴스 - {colored_text(f'성공: {success_count}', Colors.SUCCESS)}, {colored_text(f'실패: {failed_count}', Colors.ERROR)}")
        print()
        
        for result in results:
            status_color = Colors.SUCCESS if result.status == 'SUCCESS' else Colors.ERROR
            print(f"{colored_text('■', status_color)} {result.instance_name} ({result.instance_id}) - {result.execution_time:.1f}s")
            
            if result.output.strip():
                print(f"   출력: {result.output.strip()[:100]}{'...' if len(result.output.strip()) > 100 else ''}")
            
            if result.error.strip():
                print(colored_text(f"   오류: {result.error.strip()[:100]}{'...' if len(result.error.strip()) > 100 else ''}", Colors.ERROR))
            print()
    
    def save_results_history(self):
        """배치 작업 결과 히스토리 저장"""
        try:
            # 최근 100개 결과만 보관
            recent_results = self.results_history[-100:]
            
            # JSON 직렬화 가능한 형태로 변환
            serializable_results = []
            for result in recent_results:
                serializable_results.append({
                    'command': result.command,
                    'instance_id': result.instance_id,
                    'instance_name': result.instance_name,
                    'status': result.status,
                    'output': result.output,
                    'error': result.error,
                    'execution_time': result.execution_time,
                    'timestamp': result.timestamp.isoformat()
                })
            
            with open(BATCH_RESULTS_PATH, 'w', encoding='utf-8') as f:
                json.dump(serializable_results, f, ensure_ascii=False, indent=2)
                
        except Exception as e:
            logging.warning(f"배치 결과 히스토리 저장 실패: {e}")

# ----------------------------------------------------------------------------
# 인스턴스 필터링 헬퍼 함수
# ----------------------------------------------------------------------------
def filter_linux_instances(instances: List[dict], valid_choices: List[int], region: Optional[str] = None) -> List[dict]:
    """Linux 인스턴스만 필터링 (Windows 제외)"""
    selected = []
    for choice_idx in valid_choices:
        inst_data = instances[choice_idx - 1]
        inst = inst_data['raw']

        # Windows 인스턴스 제외
        if inst.get('PlatformDetails', 'Linux').lower().startswith('windows'):
            print(colored_text(
                f"⚠️  Windows 인스턴스는 배치 작업/파일 전송을 지원하지 않습니다: {inst_data['Name']}",
                Colors.WARNING
            ))
            continue

        # 리전 정보 추가 (필요 시)
        if region and 'Region' not in inst_data:
            inst_data['Region'] = inst.get('_region', region)

        selected.append(inst_data)

    return selected

# ----------------------------------------------------------------------------
# 정렬 기능 (v5.0.2 원본)
# ----------------------------------------------------------------------------
def sort_instances(instances, sort_key='Name', reverse=False):
    """인스턴스 목록 정렬"""
    try:
        if sort_key == 'Name':
            return sorted(instances, key=lambda x: x.get('Name', ''), reverse=reverse)
        elif sort_key == 'Type':
            return sorted(instances, key=lambda x: x['raw'].get('InstanceType', ''), reverse=reverse)
        elif sort_key == 'Region':
            return sorted(instances, key=lambda x: x.get('Region', ''), reverse=reverse)
        elif sort_key == 'State':
            return sorted(instances, key=lambda x: x['raw']['State']['Name'], reverse=reverse)
        else:
            return instances
    except (KeyError, TypeError):
        return instances

def show_sort_help():
    """정렬 옵션 도움말 표시"""
    print(colored_text("\n📊 정렬 옵션:", Colors.INFO))
    print("  n = 이름순 정렬")
    print("  t = 타입순 정렬") 
    print("  r = 리전순 정렬")
    print("  s = 상태순 정렬")
    print("  같은 키를 다시 누르면 역순 정렬")

# ----------------------------------------------------------------------------
# 히스토리 관리 (v5.0.1 원본)
# ----------------------------------------------------------------------------
def load_history():
    """연결 히스토리를 로드합니다."""
    try:
        if HISTORY_PATH.exists():
            with open(HISTORY_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logging.warning(f"히스토리 로드 실패: {e}")
    return {"ec2": [], "rds": [], "cache": [], "ecs": []}

def save_history(history):
    """연결 히스토리를 저장합니다."""
    try:
        with open(HISTORY_PATH, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.warning(f"히스토리 저장 실패: {e}")

def invalidate_cache_for_service(manager, region, service_type):
    """서비스 타입에 따라 캐시 무효화 (중복 제거용 헬퍼 함수)"""
    if region == 'multi-region':
        regions = manager.list_regions()
        for r in regions:
            _cache.invalidate(f"{service_type}_{manager.profile}_{r}")
    else:
        _cache.invalidate(f"{service_type}_{manager.profile}_{region}")

def add_to_history(service_type, profile, region, instance_id, instance_name):
    """히스토리에 새 항목을 추가합니다."""
    history = load_history()

    entry = {
        "profile": profile,
        "region": region,
        "instance_id": instance_id,
        "instance_name": instance_name,
        "timestamp": datetime.now().isoformat()
    }

    # 중복 제거 (같은 인스턴스 ID)
    history[service_type] = [h for h in history[service_type] if h["instance_id"] != instance_id]

    # 최신 항목을 맨 앞에 추가
    history[service_type].insert(0, entry)
    
    # 최대 10개까지만 유지
    history[service_type] = history[service_type][:10]
    
    save_history(history)

# ----------------------------------------------------------------------------
# DB 자격 증명 관리 (v5.0.1 원본)
# ----------------------------------------------------------------------------
def get_db_credentials(db_user_hint=""):
    """DB 자격 증명을 가져옵니다. 저장된 것이 있으면 재사용 옵션 제공."""
    global _stored_credentials
    
    # 저장된 자격 증명이 있는지 확인
    if _stored_credentials:
        print(colored_text("\n💾 저장된 DB 자격 증명이 있습니다.", Colors.INFO))
        use_stored = input("저장된 자격 증명을 사용하시겠습니까? (Y/n, b=뒤로): ").strip().lower()
        if use_stored == 'b':
            return None, None
        if use_stored != 'n':
            return _stored_credentials['user'], _stored_credentials['password']
    
    print(colored_text("\nℹ️ 데이터베이스에 연결할 사용자 정보를 입력하세요.", Colors.INFO))
    try:
        db_user = input(f"   DB 사용자 이름{f' ({db_user_hint})' if db_user_hint else ''} (b=뒤로): ") or db_user_hint
        if db_user.lower() == 'b':
            return None, None
        db_password = getpass.getpass("   DB 비밀번호 (입력 시 보이지 않음): ")
    except (EOFError, KeyboardInterrupt):
        print(colored_text("\n입력이 중단되었습니다.", Colors.WARNING))
        return None, None
        
    if not db_user or not db_password:
        print(colored_text("❌ 사용자 이름과 비밀번호를 모두 입력해야 합니다.", Colors.ERROR))
        return None, None
    
    # 자격 증명 저장 여부 확인
    save_creds = input("이 세션 동안 자격 증명을 저장하시겠습니까? (Y/n, b=뒤로): ").strip().lower()
    if save_creds == 'b':
        return None, None
    if save_creds != 'n':
        _stored_credentials['user'] = db_user
        _stored_credentials['password'] = db_password
        print(colored_text("✅ 자격 증명이 메모리에 저장되었습니다. (스크립트 종료 시 자동 삭제)", Colors.SUCCESS))
    
    return db_user, db_password

def clear_stored_credentials():
    """저장된 자격 증명을 삭제합니다."""
    global _stored_credentials
    _stored_credentials.clear()
    print(colored_text("🗑️ 저장된 자격 증명을 삭제했습니다.", Colors.SUCCESS))

# ----------------------------------------------------------------------------
# AWS 호출 모듈 (v5.1.0 확장 - 캐싱 및 성능 최적화)
# ----------------------------------------------------------------------------
class AWSManager:
    def __init__(self, profile: str, max_workers: int = DEFAULT_WORKERS):
        try:
            self.session = boto3.Session(profile_name=profile)
        except ProfileNotFound as e:
            print(colored_text(f"❌ AWS 프로파일 오류: {e}", Colors.ERROR))
            sys.exit(1)
        self.profile     = profile
        self.max_workers = max_workers

    def list_regions(self):
        cache_key = f"regions_{self.profile}"
        cached_data = _cache.get(cache_key)
        if cached_data:
            return cached_data

        try:
            # describe_regions는 어느 리전에서나 호출 가능하므로 기본 리전 사용
            # AWS config에 설정된 리전 또는 us-east-1 사용
            default_region = self.session.region_name or 'us-east-1'
            ec2  = self.session.client('ec2', region_name=default_region)
            resp = ec2.describe_regions(AllRegions=False)
            regions = [r['RegionName'] for r in resp.get('Regions', [])]
            _cache.set(cache_key, regions, ttl_seconds=3600)  # 1시간 캐시
            return regions
        except (ClientError, NoCredentialsError) as e:
            print(colored_text(f"❌ AWS 호출 실패 (describe_regions): {e}", Colors.ERROR))
            return []

    def list_instances(self, region: str, force_refresh: bool = False):
        cache_key = f"instances_{self.profile}_{region}"
        if not force_refresh:
            cached_data = _cache.get(cache_key)
            if cached_data:
                # 백그라운드에서 새로고침 시작
                _cache.start_background_refresh(cache_key, self._fetch_instances, region)
                return cached_data
        
        # 캐시에 없거나 강제 새로고침
        instances = self._fetch_instances(region)
        _cache.set(cache_key, instances)  # Config.CACHE_TTL_SECONDS 사용
        return instances
    
    def _fetch_instances(self, region: str):
        """실제 인스턴스 데이터를 AWS에서 가져오기 (페이지네이션 처리)"""
        try:
            ec2 = self.session.client('ec2', region_name=region)
            
            # 모든 running 인스턴스 조회 (페이지네이션 처리, 무한 루프 방지)
            insts = []
            next_token = None
            seen_tokens = set()
            max_pages = 100  # 안전장치: 최대 100페이지 (10,000개 인스턴스)

            page_count = 0
            while page_count < max_pages:
                page_count += 1
                params = {
                    'Filters': [{'Name':'instance-state-name','Values':['running']}],
                    'MaxResults': 100  # EC2 API 최대값
                }
                if next_token:
                    if next_token in seen_tokens:
                        logging.warning(f"페이지네이션 중복 토큰 감지, 종료 (region={region})")
                        break
                    seen_tokens.add(next_token)
                    params['NextToken'] = next_token

                resp = ec2.describe_instances(**params)

                for res in resp.get('Reservations', []):
                    for i in res.get('Instances', []):
                        insts.append(i)

                next_token = resp.get('NextToken')
                if not next_token:
                    break

            if page_count >= max_pages:
                logging.warning(f"페이지네이션 제한 초과 (region={region}, pages={max_pages})")
                    
            return insts
        except ClientError as e:
            logging.error(f"AWS list_instances 실패({region}): {e}")
            return []

    def list_instances_multi_region(self, regions: list, force_refresh: bool = False):
        """여러 리전의 인스턴스를 병렬로 가져옵니다."""
        all_instances = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            future_to_region = {ex.submit(self.list_instances, region, force_refresh): region for region in regions}
            for future in concurrent.futures.as_completed(future_to_region):
                region = future_to_region[future]
                try:
                    instances = future.result()
                    for inst in instances:
                        inst['_region'] = region  # 리전 정보 추가
                        all_instances.append(inst)
                except Exception as e:
                    logging.warning(f"리전 {region} 인스턴스 검색 실패: {e}")
        return all_instances

    def list_ssm_managed(self, region: str, jump_host_tags: dict | None = None):
        cache_key = f"ssm_{self.profile}_{region}_{str(jump_host_tags)}"
        cached_data = _cache.get(cache_key)
        if cached_data:
            return cached_data
        
        try:
            ssm = self.session.client('ssm', region_name=region)
            
            # 모든 SSM 관리 인스턴스 조회 (페이지네이션 처리)
            info = []
            next_token = None
            
            while True:
                params = {'MaxResults': 50}  # AWS 기본값보다 크게 설정
                if next_token:
                    params['NextToken'] = next_token
                
                response = ssm.describe_instance_information(**params)
                info.extend(response.get('InstanceInformationList', []))
                
                next_token = response.get('NextToken')
                if not next_token:
                    break
            
            instance_ids = [i['InstanceId'] for i in info]
            if not instance_ids:
                return []

            ec2 = self.session.client('ec2', region_name=region)
            resp = ec2.describe_instances(InstanceIds=instance_ids)
            
            ssm_instances = []
            for res in resp.get('Reservations', []):
                for i in res.get('Instances', []):
                    # 태그 필터링 검사
                    if jump_host_tags:
                        instance_tags = {t['Key']: t['Value'] for t in i.get('Tags', [])}
                        # 모든 필터 태그가 인스턴스에 있고 값이 일치하는지 확인
                        if not all(instance_tags.get(key) == value for key, value in jump_host_tags.items()):
                            continue
                    
                    name = next((t['Value'] for t in i.get('Tags', []) if t['Key'] == 'Name'), '')
                    ssm_instances.append({'Id': i['InstanceId'], 'Name': name})
            
            result = sorted(ssm_instances, key=lambda x: x['Name'])
            _cache.set(cache_key, result, )
            return result
        except ClientError as e:
            print(colored_text(f"❌ AWS 호출 실패 (list_ssm_managed): {e}", Colors.ERROR))
            return []

    def get_rds_endpoints(self, region: str, force_refresh: bool = False):
        cache_key = f"rds_{self.profile}_{region}"
        if not force_refresh:
            cached_data = _cache.get(cache_key)
            if cached_data:
                return cached_data
        
        try:
            rds = self.session.client('rds', region_name=region)
            dbs = rds.describe_db_instances().get('DBInstances', [])
            result = [
                {
                    'Id':       d['DBInstanceIdentifier'],
                    'Engine':   d['Engine'],
                    'Endpoint': d['Endpoint']['Address'],
                    'Port':     d['Endpoint']['Port'],
                    'DBName':   d.get('DBName')
                }
                for d in dbs
            ]
            _cache.set(cache_key, result, )
            return result
        except ClientError as e:
            print(colored_text(f"❌ AWS 호출 실패 (describe_db_instances): {e}", Colors.ERROR))
            return []

    def get_rds_endpoints_multi_region(self, regions: list, force_refresh: bool = False):
        """여러 리전의 RDS를 병렬로 가져옵니다."""
        all_dbs = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            future_to_region = {ex.submit(self.get_rds_endpoints, region, force_refresh): region for region in regions}
            for future in concurrent.futures.as_completed(future_to_region):
                region = future_to_region[future]
                try:
                    dbs = future.result()
                    for db in dbs:
                        db['_region'] = region  # 리전 정보 추가
                        all_dbs.append(db)
                except Exception as e:
                    logging.warning(f"리전 {region} RDS 검색 실패: {e}")
        return all_dbs

    def list_cache_clusters(self, region: str, force_refresh: bool = False):
        cache_key = f"cache_{self.profile}_{region}"
        if not force_refresh:
            cached_data = _cache.get(cache_key)
            if cached_data:
                return cached_data
        
        try:
            ec = self.session.client('elasticache', region_name=region)
            clus = ec.describe_cache_clusters(ShowCacheNodeInfo=True).get('CacheClusters', [])
            result = []
            for c in clus:
                ep = c.get('ConfigurationEndpoint') or (
                    c.get('CacheNodes')[0].get('Endpoint') if c.get('CacheNodes') else {}
                )
                result.append({
                    'Id':      c['CacheClusterId'],
                    'Engine':  c['Engine'],
                    'Address': ep.get('Address',''),
                    'Port':    ep.get('Port',0)
                })
            _cache.set(cache_key, result, )
            return result
        except ClientError as e:
            print(colored_text(f"❌ AWS 호출 실패 (describe_cache_clusters): {e}", Colors.ERROR))
            return []

    def list_cache_clusters_multi_region(self, regions: list, force_refresh: bool = False):
        """여러 리전의 ElastiCache를 병렬로 가져옵니다."""
        all_clusters = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            future_to_region = {ex.submit(self.list_cache_clusters, region, force_refresh): region for region in regions}
            for future in concurrent.futures.as_completed(future_to_region):
                region = future_to_region[future]
                try:
                    clusters = future.result()
                    for cluster in clusters:
                        cluster['_region'] = region  # 리전 정보 추가
                        all_clusters.append(cluster)
                except Exception as e:
                    logging.warning(f"리전 {region} ElastiCache 검색 실패: {e}")
        return all_clusters

    # ECS 관련 메서드 (v5.0.2 원본 + 캐싱)
    def list_ecs_clusters(self, region: str, force_refresh: bool = False):
        """ECS 클러스터 목록을 가져옵니다."""
        cache_key = f"ecs_clusters_{self.profile}_{region}"
        if not force_refresh:
            cached_data = _cache.get(cache_key)
            if cached_data:
                return cached_data
        
        try:
            ecs = self.session.client('ecs', region_name=region)
            clusters = ecs.list_clusters().get('clusterArns', [])
            if not clusters:
                return []
            
            # 클러스터 상세 정보 조회
            cluster_details = ecs.describe_clusters(clusters=clusters).get('clusters', [])
            result = [
                {
                    'Name': c['clusterName'],
                    'Arn': c['clusterArn'], 
                    'Status': c['status'],
                    'RunningTasks': c['runningTasksCount'],
                    'ActiveServices': c['activeServicesCount']
                }
                for c in cluster_details
            ]
            _cache.set(cache_key, result, )
            return result
        except ClientError as e:
            print(colored_text(f"❌ AWS 호출 실패 (list_ecs_clusters): {e}", Colors.ERROR))
            return []

    def list_ecs_services(self, region: str, cluster_name: str, force_refresh: bool = False):
        """ECS 서비스 목록을 가져옵니다."""
        cache_key = f"ecs_services_{self.profile}_{region}_{cluster_name}"
        if not force_refresh:
            cached_data = _cache.get(cache_key)
            if cached_data:
                return cached_data
        
        try:
            ecs = self.session.client('ecs', region_name=region)
            services = ecs.list_services(cluster=cluster_name).get('serviceArns', [])
            if not services:
                return []
            
            # 서비스 상세 정보 조회
            service_details = ecs.describe_services(cluster=cluster_name, services=services).get('services', [])
            result = [
                {
                    'Name': s['serviceName'],
                    'Arn': s['serviceArn'],
                    'Status': s['status'],
                    'RunningCount': s['runningCount'],
                    'DesiredCount': s['desiredCount'],
                    'LaunchType': s.get('launchType', 'EC2'),
                    'PlatformVersion': s.get('platformVersion', 'LATEST')
                }
                for s in service_details
            ]
            _cache.set(cache_key, result, )
            return result
        except ClientError as e:
            print(colored_text(f"❌ AWS 호출 실패 (list_ecs_services): {e}", Colors.ERROR))
            return []

    def list_ecs_tasks(self, region: str, cluster_name: str, service_name: str | None = None, force_refresh: bool = False):
        """ECS 태스크 목록을 가져옵니다."""
        cache_key = f"ecs_tasks_{self.profile}_{region}_{cluster_name}_{service_name or 'all'}"
        if not force_refresh:
            cached_data = _cache.get(cache_key)
            if cached_data:
                return cached_data
        
        try:
            ecs = self.session.client('ecs', region_name=region)
            
            list_params = {'cluster': cluster_name}
            if service_name:
                list_params['serviceName'] = service_name
                
            tasks = ecs.list_tasks(**list_params).get('taskArns', [])
            if not tasks:
                return []
            
            # 태스크 상세 정보 조회
            task_details = ecs.describe_tasks(cluster=cluster_name, tasks=tasks).get('tasks', [])
            
            # 태스크 정의 정보도 함께 조회
            task_definitions = {}
            for task in task_details:
                task_def_arn = task['taskDefinitionArn']
                if task_def_arn not in task_definitions:
                    try:
                        task_def = ecs.describe_task_definition(taskDefinition=task_def_arn)
                        task_definitions[task_def_arn] = task_def['taskDefinition']
                    except ClientError:
                        task_definitions[task_def_arn] = None
            
            result = []
            for task in task_details:
                task_def = task_definitions.get(task['taskDefinitionArn'])
                containers = []
                
                if task_def:
                    containers = [
                        {
                            'Name': container['name'],
                            'Image': container['image'],
                            'Status': next((c['lastStatus'] for c in task.get('containers', []) if c['name'] == container['name']), 'UNKNOWN')
                        }
                        for container in task_def.get('containerDefinitions', [])
                    ]
                
                result.append({
                    'TaskArn': task['taskArn'],
                    'TaskDefinitionArn': task['taskDefinitionArn'],
                    'LastStatus': task['lastStatus'],
                    'DesiredStatus': task['desiredStatus'],
                    'LaunchType': task.get('launchType', 'EC2'),
                    'PlatformVersion': task.get('platformVersion', 'LATEST'),
                    'Containers': containers,
                    'EnableExecuteCommand': task.get('enableExecuteCommand', False)
                })
            
            _cache.set(cache_key, result, ttl_seconds=120)  # 태스크는 짧은 TTL
            return result
        except ClientError as e:
            print(colored_text(f"❌ AWS 호출 실패 (list_ecs_tasks): {e}", Colors.ERROR))
            return []

# ----------------------------------------------------------------------------
# 공통 선택 기능 (v5.1.0 확장)
# ----------------------------------------------------------------------------
def list_profiles():
    profiles = set()
    if AWS_CONFIG_PATH.exists():
        cfg = configparser.RawConfigParser(); cfg.read(AWS_CONFIG_PATH)
        for sec in cfg.sections():
            if sec.startswith("profile "): profiles.add(sec.split(" ",1)[1])
            elif sec == 'default': profiles.add('default')
    if AWS_CRED_PATH.exists():
        cred = configparser.RawConfigParser(); cred.read(AWS_CRED_PATH)
        profiles.update(cred.sections())
    return sorted(profiles)

def choose_profile() -> str:
    """AWS 프로파일 선택 (항상 str 반환 또는 sys.exit)"""
    lst = list_profiles()
    if not lst:
        print(colored_text("❌ AWS 프로파일이 없습니다. ~/.aws/config 또는 ~/.aws/credentials 파일을 확인하세요.", Colors.ERROR))
        sys.exit(1)

    print(colored_text("\n--- [ AWS Profiles ] ---", Colors.HEADER))
    for i, p in enumerate(lst, 1):
        print(f" {i:2d}) {p}")
    print("------------------------\n")

    retry_count = 0
    while retry_count < Config.MAX_INPUT_RETRIES:
        sel = input(colored_text("사용할 프로파일 번호 입력 (b=뒤로, Enter=종료): ", Colors.PROMPT))
        if not sel:
            sys.exit(0)
        if sel.lower() == 'b':
            sys.exit(0)  # 프로파일 선택이 첫 단계이므로 종료
        if sel.isdigit() and 1 <= int(sel) <= len(lst):
            return lst[int(sel) - 1]
        retry_count += 1
        remaining = Config.MAX_INPUT_RETRIES - retry_count
        if remaining > 0:
            print(colored_text(f"❌ 올바른 번호를 입력하세요. (남은 시도: {remaining}회)", Colors.ERROR))

    # 최대 재시도 횟수 초과
    print(colored_text("❌ 최대 재시도 횟수 초과. 프로그램을 종료합니다.", Colors.ERROR))
    sys.exit(1)

def choose_region(manager: AWSManager) -> Optional[str]:
    """AWS 리전 선택 (str 또는 None 반환)"""
    regs = manager.list_regions()
    valid = []
    print(colored_text("\n⏳ EC2 인스턴스가 있는 리전을 검색 중입니다. 잠시만 기다려주세요...", Colors.INFO))
    with concurrent.futures.ThreadPoolExecutor(max_workers=manager.max_workers) as ex:
        future = {ex.submit(manager.list_instances, r): r for r in regs}
        for f in concurrent.futures.as_completed(future):
            r = future[f]
            try:
                if f.result():
                    valid.append(r)
            except Exception as e:
                logging.warning(f"리전 {r} 검색 중 오류 발생: {e}")

    if not valid:
        print(colored_text("\n⚠ EC2 인스턴스가 있는 리전이 없습니다. (활성화된 리전이 없거나, 모든 리전에 실행중인 인스턴스가 없습니다)", Colors.WARNING))
        return None

    print(colored_text("\n--- [ AWS Regions with EC2 ] ---", Colors.HEADER))
    valid_sorted = sorted(valid)
    for i, r in enumerate(valid_sorted, 1):
        print(f" {i:2d}) {r}")
    print(f" {colored_text('99', Colors.INFO)}) 🌏 모든 리전 통합 뷰")
    print("--------------------------------\n")

    retry_count = 0
    while retry_count < Config.MAX_INPUT_RETRIES:
        sel = input(colored_text("사용할 리전 번호 입력 (Enter=뒤로): ", Colors.PROMPT))
        if not sel:
            return None
        if sel == '99':
            return 'multi-region'
        if sel.isdigit() and 1 <= int(sel) <= len(valid_sorted):
            return valid_sorted[int(sel) - 1]
        retry_count += 1
        remaining = Config.MAX_INPUT_RETRIES - retry_count
        if remaining > 0:
            print(colored_text(f"❌ 올바른 번호를 입력하세요. (남은 시도: {remaining}회)", Colors.ERROR))

    # 최대 재시도 횟수 초과
    print(colored_text("❌ 최대 재시도 횟수 초과. 메뉴로 돌아갑니다.", Colors.ERROR))
    return None

def choose_jump_host(manager: AWSManager, region: str) -> Optional[str]:
    """사용자에게 SSM 관리 인스턴스(Jump Host)를 선택하게 합니다. Role=jumphost 태그가 있는 EC2만 표시합니다."""
    # Role=jumphost 태그가 있는 SSM 인스턴스만 가져오기
    jump_host_tags = {"Role": "jumphost"}
    ssm_targets = manager.list_ssm_managed(region, jump_host_tags)

    if not ssm_targets:
        print(colored_text("⚠ Role=jumphost 태그가 있는 SSM 관리 인스턴스가 없습니다.", Colors.WARNING))
        print("   점프 호스트로 사용할 EC2에 'Role=jumphost' 태그를 추가해주세요.")
        return None

    if len(ssm_targets) == 1:
        print(colored_text(f"\n(info) 유일한 Jump Host '{ssm_targets[0]['Name']} ({ssm_targets[0]['Id']})'를 사용합니다.", Colors.INFO))
        return ssm_targets[0]['Id']

    print(colored_text("\n--- [ Select Jump Host (Role=jumphost) ] ---", Colors.HEADER))
    for i, target in enumerate(ssm_targets, 1):
        print(f" {i:2d}) {target['Name']} ({target['Id']})")
    print("--------------------------------------------\n")

    retry_count = 0
    while retry_count < Config.MAX_INPUT_RETRIES:
        sel = input(colored_text("사용할 Jump Host 번호 입력 (b=뒤로): ", Colors.PROMPT))
        if sel.lower() == 'b':
            return None
        if sel.isdigit() and 1 <= int(sel) <= len(ssm_targets):
            return ssm_targets[int(sel) - 1]['Id']
        retry_count += 1
        remaining = Config.MAX_INPUT_RETRIES - retry_count
        if remaining > 0:
            print(colored_text(f"❌ 올바른 번호를 입력하세요. (남은 시도: {remaining}회)", Colors.ERROR))

    # 최대 재시도 횟수 초과
    print(colored_text("❌ 최대 재시도 횟수 초과. 메뉴로 돌아갑니다.", Colors.ERROR))
    return None

def show_recent_connections():
    """최근 연결 목록을 표시하고 선택할 수 있게 합니다."""
    history = load_history()
    
    all_recent = []
    for service_type, entries in history.items():
        for entry in entries:
            entry['service_type'] = service_type
            all_recent.append(entry)
    
    # 시간순 정렬
    all_recent.sort(key=lambda x: x['timestamp'], reverse=True)
    
    if not all_recent:
        print(colored_text("\n⚠ 최근 연결 기록이 없습니다.", Colors.WARNING))
        return None
    
    print(colored_text("\n--- [ Recent Connections ] ---", Colors.HEADER))
    for i, entry in enumerate(all_recent[:10], 1):  # 최대 10개
        service_icons = {"ec2": "🖥️", "rds": "🗄️", "cache": "⚡", "ecs": "🐳"}
        service_icon = service_icons.get(entry['service_type'], "📦")
        timestamp = datetime.fromisoformat(entry['timestamp']).strftime('%m-%d %H:%M')
        print(f" {i:2d}) {service_icon} {entry['instance_name']} ({entry['instance_id']}) [{entry['region']}] - {timestamp}")
    print("------------------------------\n")
    
    while True:
        sel = input(colored_text("재접속할 항목 번호 입력 (Enter=뒤로): ", Colors.PROMPT))
        if not sel:
            return None
        if sel.isdigit() and 1 <= int(sel) <= len(all_recent[:10]):
            return all_recent[int(sel) - 1]
        print(colored_text("❌ 올바른 번호를 입력하세요.", Colors.ERROR))

def reconnect_to_instance(manager: AWSManager, entry: dict):
    """히스토리 항목에 따라 직접 인스턴스에 재접속합니다."""
    service_type = entry['service_type']
    region = entry['region']
    instance_id = entry['instance_id']
    instance_name = entry['instance_name']
    
    print(colored_text(f"\n🔄 {instance_name}({instance_id})에 재접속을 시도합니다...", Colors.INFO))
    
    try:
        if service_type == 'ec2':
            # EC2 재접속
            ec2 = manager.session.client('ec2', region_name=region)
            resp = ec2.describe_instances(InstanceIds=[instance_id])
            
            if not resp.get('Reservations'):
                print(colored_text(f"❌ 인스턴스 {instance_id}를 찾을 수 없습니다.", Colors.ERROR))
                return
            
            instance = resp['Reservations'][0]['Instances'][0]
            
            if instance['State']['Name'] != 'running':
                print(colored_text(f"❌ 인스턴스가 실행 중이 아닙니다. 상태: {instance['State']['Name']}", Colors.ERROR))
                return
            
            # Windows/Linux 판단하여 접속
            if instance.get('PlatformDetails', 'Linux').lower().startswith('windows'):
                # Windows RDP 접속
                local_port = 10000 + (int(instance_id[-3:], 16) % 1000)
                print(colored_text(f"(info) Windows 인스턴스 RDP 연결을 시작합니다 (localhost:{local_port})...", Colors.INFO))

                proc = start_port_forward(manager.profile, region, instance_id, local_port)
                launch_rdp(local_port)
                
                print("(info) RDP 창을 닫은 후, 이 터미널로 돌아와 Enter를 누르면 RDP 연결이 종료됩니다.")
                input("\n[Press Enter to terminate RDP connection]...\n")
                proc.terminate()
                print(colored_text("🔌 RDP 포트 포워딩 연결을 종료했습니다.", Colors.SUCCESS))
            else:
                # Linux SSH 접속
                print(colored_text("(info) Linux 인스턴스 SSM 연결을 시작합니다...", Colors.INFO))
                launch_linux_wt(manager.profile, region, instance_id)
                print(colored_text("✅ 새 터미널에서 SSM 세션이 시작되었습니다.", Colors.SUCCESS))
        
        elif service_type == 'rds':
            # RDS 재접속 (기존 코드와 동일)
            rds = manager.session.client('rds', region_name=region)
            dbs = rds.describe_db_instances(DBInstanceIdentifier=instance_id).get('DBInstances', [])
            
            if not dbs:
                print(colored_text(f"❌ RDS 인스턴스 {instance_id}를 찾을 수 없습니다.", Colors.ERROR))
                return
            
            db = dbs[0]
            
            # DB 자격 증명 가져오기
            db_user, db_password = get_db_credentials()
            if not db_user or not db_password:
                return
            
            # 점프 호스트 선택
            tgt = choose_jump_host(manager, region)
            if not tgt:
                return
            
            # 포트 포워딩 및 DB 클라이언트 실행
            local_port = 11000
            print(colored_text(f"🔹 포트 포워딩: [localhost:{local_port}] -> [{db['DBInstanceIdentifier']}:{db['Endpoint']['Port']}]", Colors.INFO))

            params_dict = {
                "host": [db["Endpoint"]["Address"]],
                "portNumber": [str(db["Endpoint"]["Port"])],
                "localPortNumber": [str(local_port)]
            }
            params = json.dumps(params_dict)
            proc = subprocess.Popen(
                create_ssm_forward_command(manager.profile, region, tgt, 'AWS-StartPortForwardingSessionToRemoteHost', params),
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            time.sleep(Config.WAIT_PORT_READY)

            # DB 클라이언트 실행 (mysql, DBeaver 등)
            if DEFAULT_DB_TOOL_PATH and Path(DEFAULT_DB_TOOL_PATH).exists():
                network_type_map = {
                    'postgres': 'postgresql', 'mysql': 'mysql',
                    'mariadb': 'mariadb', 'sqlserver': 'mssql',
                }
                network_type = next((v for k, v in network_type_map.items() if k in db['Engine']), 'mysql')

                command = [
                    DEFAULT_DB_TOOL_PATH, f"--description={db['DBInstanceIdentifier']}", f"-n={network_type}",
                    f"-h=localhost", f"-P={local_port}", f"-u={db_user}", f"-p={db_password}",
                ]
                if db.get('DBName'):
                    command.append(f"-d={db['DBName']}")

                subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                print(colored_text("✅ DB 클라이언트가 실행되었습니다.", Colors.SUCCESS))
            
            print("(완료되면 이 창에서 Enter 키를 눌러 연결을 종료합니다)")
            input("[Press Enter to terminate connection]...\n")
            proc.terminate()
            print(colored_text("🔌 포트 포워딩 연결을 종료했습니다.", Colors.SUCCESS))
        
        elif service_type == 'cache':
            # ElastiCache 재접속 (기존 코드와 동일)
            ec = manager.session.client('elasticache', region_name=region)
            clusters = ec.describe_cache_clusters(CacheClusterId=instance_id, ShowCacheNodeInfo=True).get('CacheClusters', [])
            
            if not clusters:
                print(colored_text(f"❌ ElastiCache 클러스터 {instance_id}를 찾을 수 없습니다.", Colors.ERROR))
                return
            
            cluster = clusters[0]
            ep = cluster.get('ConfigurationEndpoint') or (
                cluster.get('CacheNodes')[0].get('Endpoint') if cluster.get('CacheNodes') else {}
            )
            
            # 점프 호스트 선택
            tgt = choose_jump_host(manager, region)
            if not tgt:
                return
            
            # 포트 포워딩
            local_port = 12000
            print(colored_text(f"🔹 포트 포워딩: [localhost:{local_port}] -> [{cluster['CacheClusterId']}:{ep.get('Port',0)}]", Colors.INFO))
            
            params_dict = {
                "host": [ep.get('Address','')],
                "portNumber": [str(ep.get('Port',0))],
                "localPortNumber": [str(local_port)]
            }
            params = json.dumps(params_dict)
            proc = subprocess.Popen(
                create_ssm_forward_command(manager.profile, region, tgt, 'AWS-StartPortForwardingSessionToRemoteHost', params),
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            time.sleep(Config.WAIT_PORT_READY)
            
            print(colored_text(f"✅ 포트 포워딩이 활성화되었습니다.", Colors.SUCCESS))
            print(f"   Engine: {cluster['Engine']}")
            print(f"   Address: localhost:{local_port}")
            
            # 클라이언트 실행 시도
            try:
                tool = DEFAULT_CACHE_REDIS_CLI if cluster['Engine'].startswith('redis') else DEFAULT_CACHE_MEMCACHED_CLI
                args = [tool, '-h', '127.0.0.1', '-p', str(local_port)] if 'redis' in tool else [tool, '127.0.0.1', str(local_port)]
                # macOS에서 새 터미널 탭으로 실행
                launch_terminal_session(args)
                print(colored_text("✅ 로컬 클라이언트가 새 터미널 탭에서 실행되었습니다.", Colors.SUCCESS))
            except Exception as e:
                logging.warning(f"캐시 클라이언트 실행 실패: {e}")
            
            print("(완료되면 이 창에서 Enter 키를 눌러 연결을 종료합니다)")
            input("[Press Enter to terminate connection]...\n")
            proc.terminate()
            print(colored_text("🔌 포트 포워딩 연결을 종료했습니다.", Colors.SUCCESS))
        
        elif service_type == 'ecs':
            # ECS 재접속 (v5.0.2 원본)
            print(colored_text(f"🐳 ECS 컨테이너 {instance_name}에 재접속합니다...", Colors.INFO))
            # instance_id는 "cluster:service:task:container" 형식으로 저장됨
            parts = instance_id.split(':')
            if len(parts) >= 4:
                cluster_name, service_name, task_arn, container_name = parts[0], parts[1], parts[2], parts[3]
                launch_ecs_exec(manager.profile, region, cluster_name, task_arn, container_name)
            else:
                print(colored_text("❌ ECS 접속 정보가 올바르지 않습니다.", Colors.ERROR))
    
    except ClientError as e:
        print(colored_text(f"❌ AWS 호출 실패: {e}", Colors.ERROR))
    except Exception as e:
        print(colored_text(f"❌ 재접속 실패: {e}", Colors.ERROR))
        logging.error(f"재접속 실패: {e}", exc_info=True)

# ----------------------------------------------------------------------------
# SSM 호출 함수 (v4.41 수정)
# ----------------------------------------------------------------------------
def ssm_cmd(profile, region, iid):
    """리눅스 인스턴스 접속용 SSM 세션 명령어 구성"""
    cmd = [
        'aws', 'ssm', 'start-session',
        '--region', region,
        '--target', iid,
        '--document-name', 'AWS-StartInteractiveCommand',
        '--parameters', '{"command":["bash -l"]}'
    ]
    if profile != 'default':
        cmd[1:1] = ['--profile', profile]
    return cmd

def create_ssm_forward_command(profile, region, target, document, parameters):
    """SSM 포트 포워딩 세션 명령어를 생성합니다."""
    cmd = [
        'aws', 'ssm', 'start-session',
        '--region', region,
        '--target', target,
        '--document-name', document,
        '--parameters', parameters
    ]
    if profile != 'default':
        cmd[1:1] = ['--profile', profile]
    return cmd

def start_port_forward(profile, region, iid, port):
    cmd = [
        'aws', 'ssm', 'start-session',
        '--region', region,
        '--target', iid,
        '--document-name', 'AWS-StartPortForwardingSession',
        '--parameters', f'{{"portNumber":["3389"],"localPortNumber":["{port}"]}}'
    ]
    if profile != 'default':
        cmd[1:1] = ['--profile', profile]
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)

def wait_for_port(port, timeout=30):
    """포트가 LISTEN 상태가 될 때까지 대기"""
    import socket
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex(('localhost', port))
            sock.close()
            if result == 0:
                return True
        except:
            pass
        time.sleep(0.5)
    return False

def launch_rdp(port):
    """macOS에서 RDP 접속 - Windows App 사용"""
    # 포트가 준비될 때까지 대기
    print(colored_text(f'⏳ 포트 {port}가 준비될 때까지 대기 중...', Colors.INFO))
    if not wait_for_port(port):
        print(colored_text(f'\n❌ 포트 {port}가 준비되지 않았습니다.', Colors.ERROR))
        return

    print(colored_text('✅ 포트가 준비되었습니다.', Colors.SUCCESS))

    print(colored_text(f'\n📊 RDP 연결 정보:', Colors.HEADER))
    print(colored_text(f'   호스트: localhost:{port}', Colors.INFO))
    print(colored_text(f'   사용자: Administrator', Colors.INFO))
    print(colored_text(f'   (비밀번호는 별도로 확인하세요)', Colors.WARNING))

    # .rdp 파일 생성 (pathlib 사용)
    import tempfile
    rdp_file = Path(tempfile.gettempdir()) / f'ec2menu_{port}.rdp'
    rdp_content = f"""screen mode id:i:2
desktopwidth:i:1920
desktopheight:i:1080
session bpp:i:32
compression:i:1
keyboardhook:i:2
displayconnectionbar:i:1
disable wallpaper:i:1
disable full window drag:i:1
disable menu anims:i:1
disable themes:i:0
disable cursor setting:i:0
bitmapcachepersistenable:i:1
full address:s:localhost:{port}
audiomode:i:0
redirectprinters:i:0
redirectcomports:i:0
redirectsmartcards:i:0
redirectclipboard:i:1
redirectposdevices:i:0
autoreconnection enabled:i:1
authentication level:i:0
prompt for credentials:i:0
negotiate security layer:i:1
remoteapplicationmode:i:0
username:s:Administrator
"""

    with open(rdp_file, 'w') as f:
        f.write(rdp_content)

    # 파일 권한을 600으로 설정 (소유자만 읽기/쓰기)
    os.chmod(rdp_file, 0o600)

    # atexit 정리 목록에 추가
    global _temp_files_to_cleanup
    _temp_files_to_cleanup.append(rdp_file)

    print(colored_text(f'\n📄 RDP 연결 파일 생성: {rdp_file}', Colors.INFO))

    try:
        # Windows App 또는 Microsoft Remote Desktop으로 열기
        if Path('/Applications/Windows App.app').exists():
            print(colored_text('✅ Windows App으로 연결합니다...', Colors.SUCCESS))
            subprocess.run(['open', '-a', 'Windows App', str(rdp_file)])
            time.sleep(Config.WAIT_PORT_READY)  # 앱이 파일을 읽을 시간 대기
        elif Path('/Applications/Microsoft Remote Desktop.app').exists():
            print(colored_text('✅ Microsoft Remote Desktop으로 연결합니다...', Colors.SUCCESS))
            subprocess.run(['open', '-a', 'Microsoft Remote Desktop', str(rdp_file)])
            time.sleep(Config.WAIT_PORT_READY)  # 앱이 파일을 읽을 시간 대기
        else:
            print(colored_text('\n⚠️ RDP 클라이언트가 설치되지 않았습니다.', Colors.WARNING))
            print(colored_text('\n권장: App Store에서 "Microsoft Remote Desktop" 설치', Colors.INFO))
            print(colored_text(f'\n수동 연결 정보:', Colors.INFO))
            print(colored_text(f'   호스트: localhost:{port}', Colors.INFO))
            print(colored_text(f'   사용자: Administrator', Colors.INFO))
            return
    finally:
        # .rdp 파일 즉시 삭제 시도
        try:
            if rdp_file.exists():
                rdp_file.unlink()
                _temp_files_to_cleanup.remove(rdp_file)  # 정리 목록에서 제거
                print(colored_text(f'🗑️  임시 RDP 파일 삭제됨', Colors.INFO))
        except Exception as e:
            # 삭제 실패 시 경고 로그 기록 (atexit에서 재시도)
            logging.warning(f"RDP 파일 즉시 삭제 실패 (프로그램 종료 시 재시도): {rdp_file} - {e}")

def check_iterm2():
    """iTerm2 설치 확인"""
    iterm_path = '/Applications/iTerm.app'
    return os.path.exists(iterm_path)

def launch_terminal_session(command_list, use_iterm=True):
    """macOS에서 새 터미널 탭에서 명령 실행 (iTerm2 또는 Terminal.app)"""
    import shlex
    # 명령어 리스트를 쉘 명령어 문자열로 변환
    # shlex.quote()로 공백/특수문자 포함 인자를 적절히 보호
    cmd_str = ' '.join(shlex.quote(arg) for arg in command_list)

    # AppleScript 문자열 리터럴용 이스케이프
    # AppleScript에서 쌍따옴표 문자열 사용 시 내부 쌍따옴표만 이스케이프 필요
    applescript_safe = cmd_str.replace('\\', '\\\\').replace('"', '\\"')

    if use_iterm and check_iterm2():
        # iTerm2가 실행 중인지 확인
        is_running = subprocess.run(
            ['osascript', '-e', 'tell application "System Events" to (name of processes) contains "iTerm2"'],
            capture_output=True, text=True
        ).stdout.strip() == 'true'

        # iTerm2 창 개수 확인
        if is_running:
            window_count_result = subprocess.run(
                ['osascript', '-e', 'tell application "iTerm" to count windows'],
                capture_output=True, text=True
            )
            window_count = int(window_count_result.stdout.strip()) if window_count_result.stdout.strip().isdigit() else 0
        else:
            window_count = 0

        try:
            if not is_running or window_count == 0:
                # iTerm2가 실행 중이 아니거나 창이 없음 → open으로 실행하고 기본 세션에 명령 실행
                subprocess.run(['open', '-a', 'iTerm'], check=True)
                time.sleep(Config.WAIT_APP_LAUNCH)  # iTerm2가 완전히 시작될 때까지 대기
                applescript = f'''
                tell application "iTerm"
                    tell current session of current window
                        write text "{applescript_safe}"
                    end tell
                end tell
                '''
                subprocess.run(['osascript', '-e', applescript], check=True)
            else:
                # iTerm2가 이미 실행 중이고 창이 있음 → 새 탭 추가
                applescript = f'''
                tell application "iTerm"
                    tell current window
                        create tab with default profile
                        tell current session
                            write text "{applescript_safe}"
                        end tell
                    end tell
                end tell
                '''
                subprocess.run(['osascript', '-e', applescript], check=True)
        except subprocess.CalledProcessError as e:
            logging.error(f"iTerm2 AppleScript 실행 실패: {e}")
            print(colored_text(f"❌ iTerm2 실행 중 오류 발생. 수동으로 터미널을 열고 다음 명령을 실행하세요:", Colors.ERROR))
            print(colored_text(f"   {cmd_str}", Colors.INFO))
    else:
        # Terminal.app 사용
        try:
            applescript = f'''
            tell application "Terminal"
                activate
                do script "{applescript_safe}"
            end tell
            '''
            subprocess.run(['osascript', '-e', applescript], check=True)
        except subprocess.CalledProcessError as e:
            logging.error(f"Terminal.app AppleScript 실행 실패: {e}")
            print(colored_text(f"❌ Terminal.app 실행 중 오류 발생. 수동으로 터미널을 열고 다음 명령을 실행하세요:", Colors.ERROR))
            print(colored_text(f"   {cmd_str}", Colors.INFO))

def launch_linux_wt(profile, region, iid):
    """리눅스 인스턴스에 새 터미널 탭으로 접속 (macOS용)"""
    cmd = ssm_cmd(profile, region, iid)
    # iTerm2 사용 (use_iterm=True로 복원)
    launch_terminal_session(cmd, use_iterm=True)

# ----------------------------------------------------------------------------
# ECS 호출 함수 (v5.0.2 원본)
# ----------------------------------------------------------------------------
def ecs_exec_cmd(profile, region, cluster, task_arn, container):
    """ECS Exec 명령어 구성"""
    cmd = [
        'aws', 'ecs', 'execute-command',
        '--region', region,
        '--cluster', cluster,
        '--task', task_arn,
        '--container', container,
        '--interactive',
        '--command', '/bin/bash'
    ]
    if profile != 'default':
        cmd[1:1] = ['--profile', profile]
    return cmd

def launch_ecs_exec(profile, region, cluster, task_arn, container):
    """ECS 컨테이너에 새 터미널로 접속 (macOS용)"""
    cmd = ecs_exec_cmd(profile, region, cluster, task_arn, container)
    launch_terminal_session(cmd)

# ----------------------------------------------------------------------------
# EC2 메뉴 (v5.1.0 확장 - 배치 작업 지원)
# ----------------------------------------------------------------------------
def ec2_menu(manager: AWSManager, region: str):
    global _sort_key, _sort_reverse
    procs = []
    batch_manager = BatchJobManager(manager)
    file_transfer_manager = FileTransferManager(manager)
    
    try:
        while True:
            force_refresh = False
            if region == 'multi-region':
                # 멀티 리전 모드
                regions = manager.list_regions()
                insts_raw = manager.list_instances_multi_region(regions, force_refresh)
                if not insts_raw:
                    print(colored_text("\n⚠ 모든 리전에 실행 중인 EC2 인스턴스가 없습니다.", Colors.WARNING))
                    break
                region_display = "All Regions"
            else:
                # 단일 리전 모드
                insts_raw = manager.list_instances(region, force_refresh)
                if not insts_raw:
                    print(colored_text("\n⚠ 이 리전에는 실행 중인 EC2 인스턴스가 없습니다.", Colors.WARNING))
                    break
                region_display = region

            insts_display = []
            for i in insts_raw:
                name = next((t['Value'] for t in i.get('Tags', []) if t['Key'] == 'Name'), '')
                instance_region = i.get('_region', region)
                insts_display.append({
                    'raw': i, 'Name': name,
                    'PublicIp': i.get('PublicIpAddress', '-'),
                    'PrivateIp': i.get('PrivateIpAddress', '-'),
                    'Region': instance_region
                })
            
            # 정렬 적용
            insts = sort_instances(insts_display, _sort_key, _sort_reverse)

            # 테이블 헤더 출력
            print(colored_text("\n--- [ EC2 Instances ] ---", Colors.HEADER))
            if region == 'multi-region':
                print(f" {'No':<3} {colored_text('Name', Colors.EC2):<25} {'Instance ID':<20} {'Region':<15} {'Type':<15} {'State':<10} {'OS':<15} {'Private IP':<16} {'Public IP':<16}")
                print("-" * 145)
            else:
                print(f" {'No':<3} {colored_text('Name', Colors.EC2):<25} {'Instance ID':<20} {'Type':<15} {'State':<10} {'OS':<15} {'Private IP':<16} {'Public IP':<16}")
                print("-" * 130)

            for idx, i_data in enumerate(insts, 1):
                i = i_data['raw']
                instance_type = i.get('InstanceType', '-')
                state = i['State']['Name']
                platform = i.get('PlatformDetails', 'Linux/UNIX')
                
                # 상태별 색깔 적용
                state_colored = colored_text(state, get_status_color(state))
                
                if region == 'multi-region':
                    print(f" {idx:<3} {i_data['Name']:<25} {i['InstanceId']:<20} {i_data['Region']:<15} {instance_type:<15} {state_colored:<10} {platform:<15} {i_data['PrivateIp']:<16} {i_data['PublicIp']:<16}")
                else:
                    print(f" {idx:<3} {i_data['Name']:<25} {i['InstanceId']:<20} {instance_type:<15} {state_colored:<10} {platform:<15} {i_data['PrivateIp']:<16} {i_data['PublicIp']:<16}")
            
            if region == 'multi-region':
                print("-" * 145)
            else:
                print("-" * 130)
                
            print(f"Profile: {manager.profile} | Region: {region_display} | Sort: {_sort_key}{'↓' if _sort_reverse else '↑'}")
            show_sort_help()
            print(colored_text("\n💡 배치 작업: 여러 번호 선택 후 'batch' 입력", Colors.INFO))
            print(colored_text("📁 파일 전송: 여러 번호 선택 후 'upload' 입력", Colors.INFO))

            sel = input(colored_text("\n접속할 인스턴스 번호 입력 (r=새로고침, b=메인, n/t/s=정렬, batch=배치작업, upload=파일전송, 예: 1,2,3): ", Colors.PROMPT)).strip().lower()
            
            if not sel or sel == 'b':
                break
            elif sel == 'r':
                print(colored_text("🔄 목록을 새로고침합니다...", Colors.INFO))
                # 캐시 무효화 후 다음 루프에서 새로고침
                invalidate_cache_for_service(manager, region, "instances")
                force_refresh = True
                continue
            elif sel in ['n', 't', 's', 'r']:
                # 정렬 처리
                sort_map = {'n': 'Name', 't': 'Type', 's': 'State', 'r': 'Region'}
                new_sort_key = sort_map.get(sel, 'Name')
                if new_sort_key == _sort_key:
                    _sort_reverse = not _sort_reverse  # 같은 키면 역순 토글
                else:
                    _sort_key = new_sort_key
                    _sort_reverse = False
                continue
            elif sel == 'batch':
                # 배치 작업 모드
                print(colored_text("\n📋 배치 작업 모드", Colors.HEADER))
                batch_sel = input(colored_text("배치 작업할 인스턴스 번호들 입력 (b=뒤로, 예: 1,2,3,5): ", Colors.PROMPT)).strip()
                
                if not batch_sel:
                    continue
                if batch_sel.lower() == 'b':
                    continue
                
                try:
                    choices = [int(x.strip()) for x in batch_sel.split(',') if x.strip().isdigit()]
                    valid_choices = [c for c in choices if 1 <= c <= len(insts)]
                    if not valid_choices:
                        print(colored_text("❌ 유효한 번호를 입력하세요.", Colors.ERROR))
                        continue
                        
                    # Linux 인스턴스만 필터링
                    selected_instances = []
                    for choice_idx in valid_choices:
                        inst_data = insts[choice_idx - 1]
                        inst = inst_data['raw']
                        if not inst.get('PlatformDetails', 'Linux').lower().startswith('windows'):
                            selected_instances.append(inst_data)
                        else:
                            print(colored_text(f"⚠ Windows 인스턴스 {inst_data['Name']}는 배치 작업에서 제외됩니다.", Colors.WARNING))
                    
                    if not selected_instances:
                        print(colored_text("❌ 배치 작업할 Linux 인스턴스가 없습니다.", Colors.ERROR))
                        continue
                    
                    # 배치 명령 입력
                    print(colored_text(f"\n{len(selected_instances)}개 Linux 인스턴스에서 실행할 명령을 입력하세요:", Colors.INFO))
                    for inst in selected_instances:
                        print(f"  - {inst['Name']} ({inst['raw']['InstanceId']})")
                    
                    batch_command = input(colored_text("\n실행할 명령 (b=뒤로): ", Colors.PROMPT)).strip()
                    if not batch_command:
                        print(colored_text("❌ 명령을 입력해야 합니다.", Colors.ERROR))
                        continue
                    if batch_command.lower() == 'b':
                        continue
                    
                    # 배치 작업 실행
                    results = batch_manager.execute_batch_command(selected_instances, batch_command)
                    
                    # 결과 표시
                    batch_manager.show_batch_results(results)
                    
                    input(colored_text("\n[Press Enter to continue]...", Colors.PROMPT))
                    continue
                    
                except ValueError:
                    print(colored_text("❌ 숫자와 쉼표만 입력하세요.", Colors.ERROR))
                    continue
            elif sel == 'upload':
                # 파일 전송 모드
                print(colored_text("\n📁 파일 전송 모드", Colors.HEADER))
                upload_sel = input(colored_text("파일 전송할 인스턴스 번호들 입력 (b=뒤로, 예: 1,2,3,5): ", Colors.PROMPT)).strip()
                
                if not upload_sel:
                    continue
                if upload_sel.lower() == 'b':
                    continue
                
                try:
                    choices = [int(x.strip()) for x in upload_sel.split(',') if x.strip().isdigit()]
                    valid_choices = [c for c in choices if 1 <= c <= len(insts)]
                    if not valid_choices:
                        print(colored_text("❌ 유효한 번호를 입력하세요.", Colors.ERROR))
                        continue
                        
                    # Linux 인스턴스만 필터링
                    selected_instances = []
                    for choice_idx in valid_choices:
                        inst_data = insts[choice_idx - 1]
                        inst = inst_data['raw']
                        if not inst.get('PlatformDetails', 'Linux').lower().startswith('windows'):
                            # 리전 정보 추가
                            if 'Region' not in inst_data:
                                inst_data['Region'] = inst.get('_region', region)
                            selected_instances.append(inst_data)
                        else:
                            print(colored_text(f"⚠️  Windows 인스턴스는 파일 전송 미지원: {inst_data['Name']}", Colors.WARNING))
                    
                    if not selected_instances:
                        print(colored_text("❌ 파일 전송 가능한 Linux 인스턴스가 없습니다.", Colors.ERROR))
                        continue
                    
                    print(colored_text(f"\n선택된 인스턴스 ({len(selected_instances)}개):", Colors.INFO))
                    for inst_data in selected_instances:
                        print(f"  - {inst_data['Name']} ({inst_data['raw']['InstanceId']})")
                    
                    # 파일 경로 입력
                    print(colored_text("\n📁 파일 선택 방법:", Colors.INFO))
                    print("  1) 직접 입력: /Users/username/Documents/file.txt")
                    print("  2) 드래그 앤 드롭: 파일을 이 창으로 끌어오기")
                    print("  3) 복사 붙여넣기: Finder에서 Option+Cmd+C로 경로 복사 후 Cmd+V")
                    
                    local_path = input(colored_text("\n업로드할 로컬 파일 경로 (b=뒤로): ", Colors.PROMPT)).strip()
                    if not local_path:
                        print(colored_text("❌ 파일 경로를 입력해야 합니다.", Colors.ERROR))
                        continue
                    if local_path.lower() == 'b':
                        continue
                    
                    # 경로 정규화 (macOS용)
                    local_path = normalize_file_path(local_path)

                    # 파일 존재 확인
                    local_path_obj = Path(local_path)
                    if not local_path_obj.exists():
                        print(colored_text(f"❌ 파일이 존재하지 않습니다: {local_path}", Colors.ERROR))
                        continue
                    
                    # 파일 크기 확인
                    file_size = os.path.getsize(local_path)
                    print(colored_text(f"📊 파일 크기: {file_transfer_manager._format_size(file_size)}", Colors.INFO))
                    
                    remote_path = input(colored_text("대상 EC2 경로 (b=뒤로): ", Colors.PROMPT)).strip()
                    if not remote_path:
                        print(colored_text("❌ 대상 경로를 입력해야 합니다.", Colors.ERROR))
                        continue
                    if remote_path.lower() == 'b':
                        continue
                    
                    # 확인
                    print(colored_text(f"\n📋 전송 정보:", Colors.HEADER))
                    print(f"로컬 파일: {local_path}")
                    print(f"대상 경로: {remote_path}")
                    print(f"대상 인스턴스: {len(selected_instances)}개")
                    
                    confirm = input(colored_text("\n전송을 시작하시겠습니까? (y/n): ", Colors.PROMPT)).strip().lower()
                    if confirm != 'y':
                        continue
                    
                    # 파일 전송 실행
                    results = file_transfer_manager.upload_file_to_multiple_instances(
                        local_path, remote_path, selected_instances
                    )
                    
                    # 결과 요약
                    success_count = sum(1 for r in results if r.status == 'SUCCESS')
                    print(colored_text(f"\n📊 전송 완료: {success_count}/{len(results)} 성공", Colors.SUCCESS if success_count == len(results) else Colors.WARNING))
                    
                    input(colored_text("\n[Press Enter to continue]...", Colors.PROMPT))
                    continue
                    
                except ValueError:
                    print(colored_text("❌ 숫자와 쉼표만 입력하세요.", Colors.ERROR))
                    continue

            try:
                choices = [int(x.strip()) for x in sel.split(',') if x.strip().isdigit()]
                valid_choices = [c for c in choices if 1 <= c <= len(insts)]
                if not valid_choices:
                    print(colored_text("❌ 유효한 번호를 입력하세요.", Colors.ERROR))
                    continue
            except ValueError:
                print(colored_text("❌ 숫자와 쉼표만 입력하세요.", Colors.ERROR))
                continue

            rdp_started = False
            for i, choice_idx in enumerate(valid_choices):
                inst_data = insts[choice_idx - 1]
                inst = inst_data['raw']
                inst_region = inst_data['Region']
                
                # 히스토리에 추가
                add_to_history('ec2', manager.profile, inst_region, inst['InstanceId'], inst_data['Name'])
                
                if inst.get('PlatformDetails', 'Linux').lower().startswith('windows'):
                    rdp_started = True
                    local_port = 10000 + (int(inst['InstanceId'][-3:], 16) % 1000) + i
                    print(colored_text(f"\n(info) Windows 인스턴스 RDP 연결을 시작합니다 (localhost:{local_port})...", Colors.INFO))

                    proc = start_port_forward(manager.profile, inst_region, inst['InstanceId'], local_port)
                    procs.append(proc)
                    launch_rdp(local_port)
                else:
                    print(colored_text(f"\n(info) Linux 인스턴스 SSM 연결을 시작합니다...", Colors.INFO))
                    launch_linux_wt(manager.profile, inst_region, inst['InstanceId'])
                    print(colored_text("(info) 새 터미널에서 SSM 세션이 시작되었습니다. 이 창에서는 다른 작업을 계속할 수 있습니다.", Colors.SUCCESS))
            
            if rdp_started:
                print("\n(info) RDP 창을 닫은 후, 이 터미널로 돌아와 Enter를 누르면 모든 RDP 연결이 종료됩니다.")
                input("\n[Press Enter to terminate all RDP connection processes]...\n")
                break 
            else:
                time.sleep(Config.WAIT_PORT_READY)

    finally:
        if procs:
            for proc in procs:
                proc.terminate()
                try:
                    proc.wait(timeout=5)  # 5초 대기
                except subprocess.TimeoutExpired:
                    logging.warning(f"프로세스 종료 타임아웃 (PID={proc.pid}), 강제 종료")
                    proc.kill()
                    proc.wait()  # 좀비 프로세스 방지
            print(colored_text("🔌 모든 RDP 포트 포워딩 연결을 종료했습니다.", Colors.SUCCESS))

# ----------------------------------------------------------------------------
# ECS 메뉴 (v5.0.2 원본 + 캐싱)
# ----------------------------------------------------------------------------
def ecs_menu(manager: AWSManager, region: str):
    """ECS 클러스터/서비스/태스크/컨테이너 메뉴"""
    while True:
        if region == 'multi-region':
            print(colored_text("⚠ ECS는 현재 멀티 리전 모드를 지원하지 않습니다. 단일 리전을 선택해주세요.", Colors.WARNING))
            return
        
        # 1. ECS 클러스터 목록
        clusters = manager.list_ecs_clusters(region)
        if not clusters:
            print(colored_text(f"\n⚠ 리전 {region}에 ECS 클러스터가 없습니다.", Colors.WARNING))
            return

        print(colored_text(f"\n--- [ ECS Clusters ({region}) ] ---", Colors.HEADER))
        for idx, cluster in enumerate(clusters, 1):
            status_color = get_status_color(cluster['Status'])
            status_colored = colored_text(cluster['Status'], status_color)
            print(f" {idx:2d}) {colored_text(cluster['Name'], Colors.ECS)} ({status_colored}) - Tasks: {cluster['RunningTasks']}, Services: {cluster['ActiveServices']}")
        print("---------------------------\n")

        cluster_sel = input(colored_text("ECS 클러스터 번호 입력 (b=뒤로): ", Colors.PROMPT)).strip().lower()
        if not cluster_sel or cluster_sel == 'b':
            return
        
        if not cluster_sel.isdigit() or not (1 <= int(cluster_sel) <= len(clusters)):
            print(colored_text("❌ 유효한 번호를 입력하세요.", Colors.ERROR))
            continue

        selected_cluster = clusters[int(cluster_sel) - 1]
        cluster_name = selected_cluster['Name']

        # 2. ECS 서비스 목록
        while True:
            services = manager.list_ecs_services(region, cluster_name)
            if not services:
                print(colored_text(f"\n⚠ 클러스터 {cluster_name}에 ECS 서비스가 없습니다.", Colors.WARNING))
                break

            print(colored_text(f"\n--- [ ECS Services in {cluster_name} ] ---", Colors.HEADER))
            for idx, service in enumerate(services, 1):
                status_color = get_status_color(service['Status'])
                status_colored = colored_text(service['Status'], status_color)
                launch_type_colored = colored_text(service['LaunchType'], Colors.INFO)
                print(f" {idx:2d}) {service['Name']} ({status_colored}) - {launch_type_colored} - Running: {service['RunningCount']}/{service['DesiredCount']}")
            print("---------------------------\n")

            service_sel = input(colored_text("ECS 서비스 번호 입력 (b=뒤로): ", Colors.PROMPT)).strip().lower()
            if not service_sel or service_sel == 'b':
                break
            
            if not service_sel.isdigit() or not (1 <= int(service_sel) <= len(services)):
                print(colored_text("❌ 유효한 번호를 입력하세요.", Colors.ERROR))
                continue

            selected_service = services[int(service_sel) - 1]
            service_name = selected_service['Name']

            # 3. ECS 태스크 목록
            while True:
                tasks = manager.list_ecs_tasks(region, cluster_name, service_name)
                if not tasks:
                    print(colored_text(f"\n⚠ 서비스 {service_name}에 실행 중인 태스크가 없습니다.", Colors.WARNING))
                    break

                print(colored_text(f"\n--- [ ECS Tasks in {service_name} ] ---", Colors.HEADER))
                for idx, task in enumerate(tasks, 1):
                    task_id = task['TaskArn'].split('/')[-1]
                    status_color = get_status_color(task['LastStatus'])
                    status_colored = colored_text(task['LastStatus'], status_color)
                    exec_enabled = colored_text("✅", Colors.SUCCESS) if task['EnableExecuteCommand'] else colored_text("❌", Colors.ERROR)
                    print(f" {idx:2d}) {task_id} ({status_colored}) - Exec: {exec_enabled}")
                    
                    # 컨테이너 정보 표시
                    for container in task['Containers']:
                        container_status_color = get_status_color(container['Status'])
                        container_status_colored = colored_text(container['Status'], container_status_color)
                        print(f"      └─ 📦 {container['Name']} ({container_status_colored})")
                
                print("---------------------------\n")

                task_sel = input(colored_text("ECS 태스크 번호 입력 (b=뒤로): ", Colors.PROMPT)).strip().lower()
                if not task_sel or task_sel == 'b':
                    break
                
                if not task_sel.isdigit() or not (1 <= int(task_sel) <= len(tasks)):
                    print(colored_text("❌ 유효한 번호를 입력하세요.", Colors.ERROR))
                    continue

                selected_task = tasks[int(task_sel) - 1]
                
                if not selected_task['EnableExecuteCommand']:
                    print(colored_text("❌ 이 태스크는 ECS Exec이 활성화되지 않았습니다.", Colors.ERROR))
                    print("서비스 설정에서 enableExecuteCommand를 true로 설정하세요.")
                    continue

                # 4. 컨테이너 선택 및 접속
                containers = selected_task['Containers']
                if len(containers) == 1:
                    # 컨테이너가 하나면 바로 접속
                    container = containers[0]
                    print(colored_text(f"\n🐳 컨테이너 '{container['Name']}'에 접속합니다...", Colors.INFO))
                    
                    # 히스토리에 추가
                    task_id = selected_task['TaskArn'].split('/')[-1]
                    history_id = f"{cluster_name}:{service_name}:{task_id}:{container['Name']}"
                    add_to_history('ecs', manager.profile, region, history_id, f"{service_name}/{container['Name']}")
                    
                    launch_ecs_exec(manager.profile, region, cluster_name, selected_task['TaskArn'], container['Name'])
                    print(colored_text("✅ 새 터미널에서 ECS Exec 세션이 시작되었습니다.", Colors.SUCCESS))
                    time.sleep(Config.WAIT_PORT_READY)
                else:
                    # 여러 컨테이너가 있으면 선택
                    print(colored_text(f"\n--- [ Containers in Task ] ---", Colors.HEADER))
                    for idx, container in enumerate(containers, 1):
                        container_status_color = get_status_color(container['Status'])
                        container_status_colored = colored_text(container['Status'], container_status_color)
                        print(f" {idx:2d}) {container['Name']} ({container_status_colored})")
                    print("------------------------------\n")

                    container_sel = input(colored_text("접속할 컨테이너 번호 입력 (b=뒤로): ", Colors.PROMPT)).strip().lower()
                    if not container_sel or container_sel == 'b':
                        continue
                    
                    if not container_sel.isdigit() or not (1 <= int(container_sel) <= len(containers)):
                        print(colored_text("❌ 유효한 번호를 입력하세요.", Colors.ERROR))
                        continue

                    selected_container = containers[int(container_sel) - 1]
                    print(colored_text(f"\n🐳 컨테이너 '{selected_container['Name']}'에 접속합니다...", Colors.INFO))
                    
                    # 히스토리에 추가
                    task_id = selected_task['TaskArn'].split('/')[-1]
                    history_id = f"{cluster_name}:{service_name}:{task_id}:{selected_container['Name']}"
                    add_to_history('ecs', manager.profile, region, history_id, f"{service_name}/{selected_container['Name']}")
                    
                    launch_ecs_exec(manager.profile, region, cluster_name, selected_task['TaskArn'], selected_container['Name'])
                    print(colored_text("✅ 새 터미널에서 ECS Exec 세션이 시작되었습니다.", Colors.SUCCESS))
                    time.sleep(Config.WAIT_PORT_READY)

# ----------------------------------------------------------------------------
# RDS 접속 (v5.0.2 원본 + 캐싱)
# ----------------------------------------------------------------------------
def connect_to_rds(manager: AWSManager, tool_path: str, region: str):
    while True:
        if region == 'multi-region':
            # 멀티 리전 모드
            regions = manager.list_regions()
            dbs = manager.get_rds_endpoints_multi_region(regions)
            region_display = "All Regions"
        else:
            # 단일 리전 모드
            dbs = manager.get_rds_endpoints(region)
            region_display = region
            
        if not dbs:
            print(colored_text(f"\n⚠ {region_display}에 RDS 인스턴스가 없습니다", Colors.WARNING))
            return

        print(colored_text(f"\n--- [ RDS Instances ({region_display}) ] ---", Colors.HEADER))
        for idx, db in enumerate(dbs, 1):
            engine_display = db['Engine']
            if 'aurora-mysql' in engine_display: engine_display = 'aurora (mysql)'
            elif 'aurora-postgresql' in engine_display: engine_display = 'aurora (postgres)'
            
            if region == 'multi-region':
                print(f" {idx:2d}) {colored_text(db['Id'], Colors.RDS)} ({engine_display}) [{db['_region']}]")
            else:
                print(f" {idx:2d}) {colored_text(db['Id'], Colors.RDS)} ({engine_display})")
        print("---------------------------\n")

        sel = input(colored_text("접속할 DB 번호 입력 (r=새로고침, b=뒤로, 예: 1,2,3): ", Colors.PROMPT)).strip().lower()
        if not sel or sel == 'b': 
            return
        if sel == 'r':
            print(colored_text("🔄 목록을 새로고침합니다...", Colors.INFO))
            # 캐시 무효화
            invalidate_cache_for_service(manager, region, "rds")
            continue

        try:
            choices = [int(x.strip()) for x in sel.split(',') if x.strip().isdigit()]
            valid_choices = [c for c in choices if 1 <= c <= len(dbs)]
            if not valid_choices:
                print(colored_text("❌ 유효한 번호를 입력하세요.", Colors.ERROR))
                continue
        except ValueError:
            print(colored_text("❌ 숫자와 쉼표만 입력하세요.", Colors.ERROR))
            continue

        # DB 자격 증명 가져오기
        db_user, db_password = get_db_credentials()
        if not db_user or not db_password:
            continue

        # 첫 번째 선택된 DB의 리전에서 점프 호스트 선택 (멀티 리전의 경우)
        target_region = dbs[valid_choices[0] - 1].get('_region', region)
        if region == 'multi-region':
            print(colored_text(f"\n📍 리전 {target_region}에서 점프 호스트를 선택합니다.", Colors.INFO))
        
        tgt = choose_jump_host(manager, target_region)
        if not tgt:
            continue

        print(colored_text(f"\n(info) SSM 인스턴스 '{tgt}'를 통해 포트 포워딩을 시작합니다.", Colors.INFO))

        procs = []
        try:
            for i, choice_idx in enumerate(valid_choices):
                db = dbs[choice_idx - 1]
                db_region = db.get('_region', region)
                local_port = 11000 + i
                print(colored_text(f"🔹 포트 포워딩: [localhost:{local_port}] -> [{db['Id']}:{db['Port']}] ({db_region})", Colors.INFO))
                
                # 히스토리에 추가
                add_to_history('rds', manager.profile, db_region, db['Id'], db['Id'])
                
                params_dict = {
                    "host": [db["Endpoint"]],
                    "portNumber": [str(db["Port"])],
                    "localPortNumber": [str(local_port)]
                }
                params = json.dumps(params_dict)
                proc = subprocess.Popen(
                    create_ssm_forward_command(manager.profile, target_region, tgt, 'AWS-StartPortForwardingSessionToRemoteHost', params),
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                procs.append(proc)
            
            time.sleep(Config.WAIT_PORT_READY)

            print(colored_text("\n✅ 모든 포트 포워딩 활성화. DBeaver로 자동 연결합니다...", Colors.SUCCESS))

            # DBeaver 자동 연결 (환경변수 지원)
            dbeaver_path = os.environ.get('DBEAVER_PATH', '/Applications/DBeaver.app/Contents/MacOS/dbeaver')
            if Path(dbeaver_path).exists():
                for i, choice_idx in enumerate(valid_choices):
                    db = dbs[choice_idx - 1]
                    local_port = 11000 + i

                    # 엔진 타입에 따른 드라이버 매핑
                    driver_map = {
                        'postgres': 'postgresql',
                        'mysql': 'mysql8',
                        'mariadb': 'mariaDB',
                        'aurora-mysql': 'mysql8',
                        'aurora-postgresql': 'postgresql',
                    }
                    driver = 'mysql8'
                    for key, val in driver_map.items():
                        if key in db['Engine'].lower():
                            driver = val
                            break

                    # DBeaver 연결 스펙 생성
                    db_name = db.get('DBName', '')
                    # 데이터베이스 이름이 있을 때만 database 파라미터 포함
                    if db_name:
                        conn_spec = f"driver={driver}|host=localhost|port={local_port}|database={db_name}|user={db_user}|password={db_password}|name={db['Id']}"
                    else:
                        conn_spec = f"driver={driver}|host=localhost|port={local_port}|user={db_user}|password={db_password}|name={db['Id']}"

                    # DBeaver 실행
                    subprocess.Popen(
                        [dbeaver_path, '-nosplash', '-con', conn_spec],
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )
                    print(colored_text(f"✅ DBeaver 연결 시작: {db['Id']} (localhost:{local_port})", Colors.SUCCESS))

                # DBeaver 창을 포그라운드로 활성화
                time.sleep(1)  # DBeaver가 시작될 시간 대기
                subprocess.run(['osascript', '-e', 'tell application "DBeaver" to activate'])
            elif tool_path and Path(tool_path).exists():
                # mysql CLI 같은 도구가 있으면 실행
                for i, choice_idx in enumerate(valid_choices):
                    db = dbs[choice_idx - 1]
                    local_port = 11000 + i
                    command = [
                        tool_path, '-h', 'localhost', '-P', str(local_port),
                        '-u', db_user, f'-p{db_password}'
                    ]
                    if db.get('DBName'):
                        command.append(db['DBName'])
                    subprocess.Popen(command)
                    print(colored_text(f"✅ {tool_path} 연결 시작: {db['Id']}", Colors.SUCCESS))
            else:
                # DB 도구 없음: 연결 정보만 표시
                print(colored_text("\n📊 데이터베이스 연결 정보:", Colors.HEADER))
                for i, choice_idx in enumerate(valid_choices):
                    db = dbs[choice_idx - 1]
                    local_port = 11000 + i
                    print(colored_text(f"\n  [{i+1}] {db['Id']}", Colors.INFO))
                    print(colored_text(f"      호스트: localhost", Colors.INFO))
                    print(colored_text(f"      포트: {local_port}", Colors.INFO))
                    print(colored_text(f"      사용자: {db_user}", Colors.INFO))
                    print(colored_text(f"      비밀번호: {db_password}", Colors.INFO))
                    if db.get('DBName'):
                        print(colored_text(f"      데이터베이스: {db['DBName']}", Colors.INFO))
                print(colored_text(f"\n💡 DBeaver를 설치하면 자동 연결이 가능합니다.", Colors.INFO))

            print("\n(완료되면 이 창에서 Enter 키를 눌러 연결을 모두 종료합니다)")
            input("[Press Enter to terminate all connections]...\n")
            break

        finally:
            if procs:
                for proc in procs:
                    proc.terminate()
                print(colored_text("🔌 모든 포트 포워딩 연결을 종료했습니다.", Colors.SUCCESS))

# ----------------------------------------------------------------------------
# ElastiCache 접속 (v5.0.2 원본 + 캐싱)
# ----------------------------------------------------------------------------
def connect_to_cache(manager: AWSManager, region: str):
    while True:
        if region == 'multi-region':
            # 멀티 리전 모드
            regions = manager.list_regions()
            clus = manager.list_cache_clusters_multi_region(regions)
            region_display = "All Regions"
        else:
            # 단일 리전 모드
            clus = manager.list_cache_clusters(region)
            region_display = region
            
        if not clus:
            print(colored_text(f"\n⚠ {region_display}에 ElastiCache 클러스터가 없습니다", Colors.WARNING))
            time.sleep(1)
            break

        print(colored_text(f"\n--- [ ElastiCache Clusters ({region_display}) ] ---", Colors.HEADER))
        for idx, c in enumerate(clus, 1):
            if region == 'multi-region':
                print(f" {idx:2d}) {colored_text(c['Id'], Colors.CACHE)} ({c['Engine']}) [{c['_region']}]")
            else:
                print(f" {idx:2d}) {colored_text(c['Id'], Colors.CACHE)} ({c['Engine']})")
        print("--------------------------------\n")

        sel = input(colored_text("접속할 클러스터 번호 입력 (r=새로고침, b=뒤로): ", Colors.PROMPT)).strip().lower()
        if not sel or sel == 'b': 
            break
        if sel == 'r':
            print(colored_text("🔄 목록을 새로고침합니다...", Colors.INFO))
            # 캐시 무효화
            invalidate_cache_for_service(manager, region, "cache")
            continue
        
        if not sel.isdigit() or not (1 <= int(sel) <= len(clus)):
            print(colored_text("❌ 유효한 번호를 입력하세요.", Colors.ERROR))
            time.sleep(1)
            continue

        idx = int(sel) - 1
        c = clus[idx]
        cache_region = c.get('_region', region)
        
        # 히스토리에 추가
        add_to_history('cache', manager.profile, cache_region, c['Id'], c['Id'])

        tgt = choose_jump_host(manager, cache_region)
        if not tgt:
            break

        local_port = 12000 + idx
        
        print(colored_text(f"\n(info) SSM 인스턴스 '{tgt}'를 통해 포트 포워딩을 시작합니다.", Colors.INFO))
        print(colored_text(f"🔹 포트 포워딩: [localhost:{local_port}] -> [{c['Id']}:{c['Port']}] ({cache_region})", Colors.INFO))

        proc = None
        try:
            params_dict = {
                "host": [c["Address"]],
                "portNumber": [str(c["Port"])],
                "localPortNumber": [str(local_port)]
            }
            params = json.dumps(params_dict)
            proc = subprocess.Popen(
                create_ssm_forward_command(manager.profile, cache_region, tgt, 'AWS-StartPortForwardingSessionToRemoteHost', params),
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(Config.WAIT_PORT_READY)
            
            print(colored_text("\n✅ 포트 포워딩이 활성화되었습니다. 클라이언트에서 아래 주소로 접속하세요.", Colors.SUCCESS))
            print(f"   Engine: {c['Engine']}")
            print(f"   Address: localhost:{local_port}")
            
            tool_launched = False
            try:
                tool = DEFAULT_CACHE_REDIS_CLI if c['Engine'].startswith('redis') else DEFAULT_CACHE_MEMCACHED_CLI
                args = [tool, '-h', '127.0.0.1', '-p', str(local_port)] if 'redis' in tool else [tool, '127.0.0.1', str(local_port)]
                # macOS에서 새 터미널 탭으로 실행
                launch_terminal_session(args)
                tool_launched = True
            except Exception as e:
                logging.warning(f"캐시 클라이언트 실행 실패: {e}")

            if tool_launched:
                print(colored_text("   (로컬 클라이언트가 새 터미널 탭에서 실행되었습니다)", Colors.SUCCESS))
                
            print("   (완료되면 이 창에서 Enter 키를 눌러 연결을 종료합니다)")
            input("\n[Press Enter to terminate the connection]...\n")
            break

        finally:
            if proc:
                proc.terminate()
            print(colored_text("🔌 포트 포워딩 연결을 종료했습니다.", Colors.SUCCESS))
            time.sleep(1)

# ----------------------------------------------------------------------------
# Main 흐름 (v5.1.0 확장)
# ----------------------------------------------------------------------------
def main():
    global _stored_credentials
    
    # macOS 플랫폼 체크
    if not IS_MAC:
        print(colored_text("❌ 이 스크립트는 macOS 전용입니다.", Colors.ERROR))
        print(colored_text("   Windows/Linux용 버전을 사용해주세요.", Colors.INFO))
        sys.exit(1)

    parser = argparse.ArgumentParser(description='AWS EC2/RDS/ElastiCache/ECS 연결 도구 v5.2.0 (macOS)')
    parser.add_argument('-p', '--profile', help='AWS 프로파일 이름')
    parser.add_argument('-d', '--debug', action='store_true', help='디버그 모드')
    parser.add_argument('-r', '--region', help='AWS 리전 이름')
    args = parser.parse_args()

    setup_logger(args.debug)

    try:
        profile = args.profile or choose_profile()
        manager = AWSManager(profile)

        while True:
            region = args.region or choose_region(manager)
            args.region = None
            if not region:
                sel = input(colored_text("프로파일을 다시 선택하시겠습니까? (y/N): ", Colors.PROMPT)).strip().lower()
                if sel == 'y':
                    profile = choose_profile()
                    manager = AWSManager(profile)
                    continue
                else:
                    sys.exit(0)

            while True:
                region_display = "All Regions" if region == 'multi-region' else region
                print(colored_text(f"\n--- [ Main Menu ] ---", Colors.HEADER))
                print(f"Profile: {colored_text(profile, Colors.INFO)} | Region: {colored_text(region_display, Colors.INFO)}")
                print("---------------------")
                print(f" 1) {colored_text('🖥️ EC2', Colors.EC2)} 인스턴스 연결 {colored_text('(배치 작업 지원)', Colors.SUCCESS)}")
                print(f" 2) {colored_text('🗄️ RDS', Colors.RDS)} 데이터베이스 연결")
                print(f" 3) {colored_text('⚡ ElastiCache', Colors.CACHE)} 클러스터 연결")
                print(f" 4) {colored_text('🐳 ECS', Colors.ECS)} 컨테이너 연결")
                print(f" h) {colored_text('📚 최근 연결 기록', Colors.INFO)}")
                if _stored_credentials:
                    print(f" c) {colored_text('🗑️ 저장된 DB 자격증명 삭제', Colors.WARNING)}")
                print("---------------------")
                sel = input(colored_text("선택 (b=리전 재선택, Enter=종료): ", Colors.PROMPT)).strip().lower()

                if sel == '1':
                    ec2_menu(manager, region)
                elif sel == '2':
                    connect_to_rds(manager, DEFAULT_DB_TOOL_PATH, region)
                elif sel == '3':
                    connect_to_cache(manager, region)
                elif sel == '4':
                    ecs_menu(manager, region)
                elif sel == 'h':
                    recent = show_recent_connections()
                    if recent:
                        # 최근 연결 항목으로 직접 접속 시도
                        temp_manager = AWSManager(recent['profile'])
                        reconnect_to_instance(temp_manager, recent)
                elif sel == 'c' and _stored_credentials:
                    clear_stored_credentials()
                elif sel == 'b':
                    break
                elif not sel:
                    sys.exit(0)
                else:
                    print(colored_text("❌ 잘못된 선택입니다.", Colors.ERROR))
    
    finally:
        # 프로그램 종료 시 저장된 자격 증명 삭제
        _stored_credentials.clear()

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print(colored_text("\n\n사용자 요청으로 프로그램을 종료합니다.", Colors.INFO))
        # 프로그램 종료 시 저장된 자격 증명 삭제
        _stored_credentials.clear()
        sys.exit(0)
    except Exception as e:
        logging.error(f"예상치 못한 오류 발생: {e}", exc_info=True)
        # 프로그램 종료 시 저장된 자격 증명 삭제
        _stored_credentials.clear()
        sys.exit(1)