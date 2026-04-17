"""S3 경유 파일 전송 관리"""
from __future__ import annotations

import atexit
import concurrent.futures
import logging
import os
import shlex
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional

from botocore.exceptions import ClientError

from ec2menu.core.colors import Colors, colored_text
from ec2menu.core.config import Config
from ec2menu.core.utils import normalize_file_path

if TYPE_CHECKING:
    from ec2menu.aws.manager import AWSManager


@dataclass
class FileTransferResult:
    instance_id: str
    instance_name: str
    local_path: str
    remote_path: str
    file_size: int
    status: str  # SUCCESS, FAILED, TIMEOUT
    error_message: str = ""
    transfer_time: float = 0.0
    timestamp: Optional[datetime] = None


class FileTransferManager:
    def __init__(self, manager: AWSManager):
        self.aws_manager = manager
        self.temp_bucket: Optional[str] = None
        self.transfer_history: List[FileTransferResult] = []
        atexit.register(self.cleanup_temp_bucket)

    def get_or_create_temp_bucket(self) -> Optional[str]:
        if self.temp_bucket:
            return self.temp_bucket

        try:
            s3 = self.aws_manager.session.client('s3')
            account_id = self.aws_manager.session.client('sts').get_caller_identity()['Account']
            bucket_name = f"ec2menu-temp-{account_id}-{uuid.uuid4().hex[:8]}"
            region = self.aws_manager.session.region_name or 'us-east-1'

            if region == 'us-east-1':
                s3.create_bucket(Bucket=bucket_name)
            else:
                s3.create_bucket(
                    Bucket=bucket_name,
                    CreateBucketConfiguration={'LocationConstraint': region},
                )

            s3.put_public_access_block(
                Bucket=bucket_name,
                PublicAccessBlockConfiguration={
                    'BlockPublicAcls': True,
                    'IgnorePublicAcls': True,
                    'BlockPublicPolicy': True,
                    'RestrictPublicBuckets': True,
                },
            )

            s3.put_bucket_lifecycle_configuration(
                Bucket=bucket_name,
                LifecycleConfiguration={
                    'Rules': [{
                        'ID': 'temp-files-cleanup',
                        'Status': 'Enabled',
                        'Expiration': {'Days': 1},
                        'Filter': {'Prefix': 'temp-files/'},
                    }]
                },
            )

            self.temp_bucket = bucket_name
            print(colored_text(f"✅ 임시 S3 버킷 생성: {bucket_name}", Colors.SUCCESS))
            return bucket_name
        except ClientError as e:
            print(colored_text(f"❌ S3 버킷 생성 실패: {str(e)}", Colors.ERROR))
            return None

    def upload_file_to_s3(self, local_path: str, s3_key: str) -> bool:
        try:
            s3 = self.aws_manager.session.client('s3')
            bucket_name = self.get_or_create_temp_bucket()
            if not bucket_name:
                return False

            file_size = os.path.getsize(local_path)
            print(colored_text(
                f"📤 S3 업로드 시작: {os.path.basename(local_path)} ({self._format_size(file_size)})", Colors.INFO
            ))
            start_time = time.time()

            def progress_callback(bytes_transferred: int) -> None:
                progress = (bytes_transferred / file_size) * 100
                elapsed = time.time() - start_time
                speed = bytes_transferred / elapsed if elapsed > 0 else 0
                print(
                    f"\r📊 업로드 진행: {progress:.1f}% "
                    f"({self._format_size(bytes_transferred)}/{self._format_size(file_size)}) "
                    f"- {self._format_speed(speed)}",
                    end="", flush=True
                )

            s3.upload_file(local_path, bucket_name, s3_key, Callback=progress_callback)
            print()
            elapsed = time.time() - start_time
            print(colored_text(f"✅ S3 업로드 완료 - {elapsed:.1f}초", Colors.SUCCESS))
            return True
        except Exception as e:
            print(colored_text(f"❌ S3 업로드 실패: {str(e)}", Colors.ERROR))
            return False

    def download_file_from_s3_to_ec2(self, s3_key: str, remote_path: str,
                                      instance_id: str, instance_name: str) -> FileTransferResult:
        start_time = time.time()

        def _fail(msg: str) -> FileTransferResult:
            return FileTransferResult(
                instance_id=instance_id, instance_name=instance_name,
                local_path="", remote_path=remote_path, file_size=0,
                status="FAILED", error_message=msg,
                transfer_time=time.time() - start_time, timestamp=datetime.now()
            )

        try:
            bucket_name = self.temp_bucket
            if not bucket_name:
                return _fail("S3 버킷이 준비되지 않음")

            safe_s3_key = shlex.quote(s3_key)
            safe_remote_path = shlex.quote(remote_path)

            if Config.DEBUG_MODE:
                command = (
                    f'echo "=== 파일 전송 시작 ==="\n'
                    f'aws s3 cp s3://{bucket_name}/{safe_s3_key} {safe_remote_path} --debug 2>&1\n'
                    f'if [ -f {safe_remote_path} ]; then\n'
                    f'    echo "TRANSFER_SUCCESS: $(ls -l {safe_remote_path} | awk \'{{print $5}}\')"\n'
                    f'else\n    echo "TRANSFER_FAILED"\nfi'
                )
            else:
                command = (
                    f'aws s3 cp s3://{bucket_name}/{safe_s3_key} {safe_remote_path} 2>&1\n'
                    f'if [ -f {safe_remote_path} ]; then\n'
                    f'    echo "TRANSFER_SUCCESS: $(ls -l {safe_remote_path} | awk \'{{print $5}}\')"\n'
                    f'else\n    echo "TRANSFER_FAILED"\nfi'
                )

            ssm = self.aws_manager.session.client('ssm')
            response = ssm.send_command(
                InstanceIds=[instance_id],
                DocumentName='AWS-RunShellScript',
                Parameters={'commands': [command]},
                TimeoutSeconds=600,
            )
            command_id = response['Command']['CommandId']

            max_wait = 300
            waited = 0
            while waited < max_wait:
                try:
                    result = ssm.get_command_invocation(CommandId=command_id, InstanceId=instance_id)
                    status = result['Status']
                    if status in ['Success', 'Failed', 'Cancelled', 'TimedOut']:
                        execution_time = time.time() - start_time
                        if status == 'Success':
                            output = result.get('StandardOutputContent', '')
                            file_size = 0
                            for line in output.split('\n'):
                                if line.startswith('TRANSFER_SUCCESS:'):
                                    try:
                                        file_size = int(line.split(':')[1].strip())
                                    except Exception:
                                        pass
                            return FileTransferResult(
                                instance_id=instance_id, instance_name=instance_name,
                                local_path="", remote_path=remote_path, file_size=file_size,
                                status="SUCCESS", transfer_time=execution_time, timestamp=datetime.now()
                            )
                        else:
                            error_msg = result.get('StandardErrorContent', '알 수 없는 오류')
                            return FileTransferResult(
                                instance_id=instance_id, instance_name=instance_name,
                                local_path="", remote_path=remote_path, file_size=0,
                                status="FAILED", error_message=error_msg,
                                transfer_time=execution_time, timestamp=datetime.now()
                            )
                    time.sleep(3)
                    waited += 3
                except ClientError:
                    time.sleep(Config.WAIT_PORT_READY)
                    waited += 2

            return FileTransferResult(
                instance_id=instance_id, instance_name=instance_name,
                local_path="", remote_path=remote_path, file_size=0,
                status="TIMEOUT", error_message=f"명령 실행 타임아웃 ({max_wait}초)",
                transfer_time=time.time() - start_time, timestamp=datetime.now()
            )
        except Exception as e:
            return _fail(str(e))

    def upload_file_to_multiple_instances(self, local_path: str, remote_path: str,
                                           instances: List[dict]) -> List[FileTransferResult]:
        local_path = normalize_file_path(local_path)
        local_path_obj = Path(local_path)
        if not local_path_obj.exists():
            print(colored_text(f"❌ 로컬 파일이 존재하지 않습니다: {local_path}", Colors.ERROR))
            return []

        filename = os.path.basename(local_path)
        s3_key = f"temp-files/{uuid.uuid4().hex}/{filename}"

        if not self.upload_file_to_s3(local_path, s3_key):
            return []

        print(colored_text(f"\n🚀 {len(instances)}개 인스턴스에 파일 전송 시작", Colors.INFO))
        results: List[FileTransferResult] = []

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(instances), 5)) as executor:
                future_to_instance = {
                    executor.submit(
                        self.download_file_from_s3_to_ec2,
                        s3_key, remote_path,
                        inst['raw']['InstanceId'], inst['Name']
                    ): inst
                    for inst in instances
                }
                for future in concurrent.futures.as_completed(future_to_instance):
                    try:
                        result = future.result()
                        results.append(result)
                        status_color = Colors.SUCCESS if result.status == 'SUCCESS' else Colors.ERROR
                        size_str = self._format_size(result.file_size) if result.file_size > 0 else ""
                        print(
                            f"{colored_text(result.status, status_color)} "
                            f"{result.instance_name} ({result.instance_id}) "
                            f"{size_str} - {result.transfer_time:.1f}s"
                        )
                    except Exception as e:
                        instance = future_to_instance[future]
                        print(colored_text(
                            f"ERROR {instance['Name']} ({instance['raw']['InstanceId']}) - {str(e)}", Colors.ERROR
                        ))

            self.transfer_history.extend(results)
            return results
        finally:
            self.cleanup_s3_file(s3_key)

    def cleanup_s3_file(self, s3_key: str) -> None:
        try:
            if self.temp_bucket:
                s3 = self.aws_manager.session.client('s3')
                s3.delete_object(Bucket=self.temp_bucket, Key=s3_key)
                print(colored_text("🗑️  S3 임시 파일 정리 완료", Colors.SUCCESS))
        except Exception as e:
            print(colored_text(f"⚠️  S3 파일 정리 실패: {str(e)}", Colors.WARNING))

    def cleanup_temp_bucket(self) -> None:
        if not self.temp_bucket:
            return
        if not hasattr(self, 'aws_manager') or not self.aws_manager:
            return
        if not hasattr(self.aws_manager, 'session') or not self.aws_manager.session:
            return

        try:
            s3 = self.aws_manager.session.client('s3')
            try:
                objects = s3.list_objects_v2(Bucket=self.temp_bucket)
                if 'Contents' in objects:
                    for obj in objects['Contents']:
                        s3.delete_object(Bucket=self.temp_bucket, Key=obj['Key'])
            except (ClientError, KeyError):
                pass
            s3.delete_bucket(Bucket=self.temp_bucket)
            logging.info(f"임시 S3 버킷 삭제됨: {self.temp_bucket}")
        except Exception as e:
            logging.warning(f"임시 S3 버킷 삭제 실패: {self.temp_bucket} - {e}")

    def _format_size(self, size_bytes: int) -> str:
        if size_bytes == 0:
            return "0B"
        size_float = float(size_bytes)
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_float < Config.BYTES_PER_KB:
                return f"{size_float:.1f}{unit}"
            size_float /= Config.BYTES_PER_KB
        return f"{size_float:.1f}TB"

    def _format_speed(self, bytes_per_sec: float) -> str:
        return f"{self._format_size(int(bytes_per_sec))}/s"
