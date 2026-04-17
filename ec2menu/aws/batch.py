"""배치 작업 관리 - 여러 인스턴스에 SSM 명령 병렬 실행"""
from __future__ import annotations

import concurrent.futures
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, List

from botocore.exceptions import ClientError

from ec2menu.core.colors import Colors, colored_text
from ec2menu.core.config import Config

if TYPE_CHECKING:
    from ec2menu.aws.manager import AWSManager


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
    def __init__(self, manager: AWSManager):
        self.aws_manager = manager
        self.results_history: List[BatchJobResult] = []

    def _validate_ssm_instances(self, instances: List[dict]) -> List[dict]:
        validated: List[dict] = []
        regions_to_check: dict = {}

        for instance_data in instances:
            region = instance_data.get('Region', 'unknown')
            regions_to_check.setdefault(region, []).append(instance_data)

        for region, region_instances in regions_to_check.items():
            try:
                ssm = self.aws_manager.session.client('ssm', region_name=region)
                instance_ids = [inst['raw']['InstanceId'] for inst in region_instances]
                response = ssm.describe_instance_information(
                    Filters=[{'Key': 'InstanceIds', 'Values': instance_ids}]
                )
                online_instances = {
                    info['InstanceId']
                    for info in response['InstanceInformationList']
                    if info['PingStatus'] == 'Online'
                }
                for instance_data in region_instances:
                    iid = instance_data['raw']['InstanceId']
                    if iid in online_instances:
                        validated.append(instance_data)
                    else:
                        print(colored_text(f"⚠️  {instance_data['Name']} ({iid}): SSM 연결 불가", Colors.WARNING))
            except Exception as e:
                print(colored_text(f"❌ 리전 {region} SSM 상태 확인 실패: {str(e)}", Colors.ERROR))
                validated.extend(region_instances)

        return validated

    def execute_batch_command(self, instances: List[dict], command: str,
                               timeout_seconds: int = 120) -> List[BatchJobResult]:
        print(colored_text(f"\n🚀 {len(instances)}개 인스턴스에서 배치 작업을 시작합니다...", Colors.INFO))
        print(colored_text(f"명령: {command}", Colors.INFO))
        print(colored_text("📋 SSM 연결 상태를 확인 중...", Colors.INFO))

        validated_instances = self._validate_ssm_instances(instances)

        if len(validated_instances) < len(instances):
            print(colored_text(
                f"⚠️  {len(instances) - len(validated_instances)}개 인스턴스가 SSM 연결 불가능 상태입니다.",
                Colors.WARNING
            ))

        if not validated_instances:
            print(colored_text("❌ 실행 가능한 인스턴스가 없습니다.", Colors.ERROR))
            return []

        print(colored_text(f"✅ {len(validated_instances)}개 인스턴스에서 실행합니다.", Colors.SUCCESS))
        results: List[BatchJobResult] = []

        def execute_on_instance(instance_data: dict) -> BatchJobResult:
            instance = instance_data['raw']
            instance_id = instance['InstanceId']
            instance_name = instance_data['Name']
            region = instance_data.get('Region', 'unknown')
            max_retries = Config.BATCH_COMMAND_RETRY
            ssm = self.aws_manager.session.client('ssm', region_name=region)

            for attempt in range(max_retries + 1):
                start_time = time.time()

                if attempt > 0:
                    delay = min(Config.BATCH_RETRY_DELAY * attempt, Config.BATCH_RETRY_MAX_DELAY)
                    print(colored_text(
                        f"🔄 {instance_name} 재시도 {attempt}/{max_retries} (대기: {delay}초)", Colors.WARNING
                    ))
                    time.sleep(delay)

                try:
                    response = ssm.send_command(
                        InstanceIds=[instance_id],
                        DocumentName='AWS-RunShellScript',
                        Parameters={
                            'commands': [command],
                            'executionTimeout': [str(timeout_seconds)],
                        },
                        TimeoutSeconds=timeout_seconds + 30,
                    )
                    command_id = response['Command']['CommandId']
                    max_wait = timeout_seconds + 30
                    waited = 0
                    attempt_count = 0

                    while waited < max_wait and attempt_count < Config.BATCH_MAX_WAIT_ATTEMPTS:
                        attempt_count += 1
                        try:
                            result = ssm.get_command_invocation(CommandId=command_id, InstanceId=instance_id)
                            status = result['Status']

                            if status in ['Success', 'Failed', 'Cancelled', 'TimedOut']:
                                execution_time = time.time() - start_time
                                if status == 'Success':
                                    output = result.get('StandardOutputContent', '').strip()
                                    if attempt > 0:
                                        print(colored_text(f"✅ {instance_name} 재시도 성공!", Colors.SUCCESS))
                                    return BatchJobResult(
                                        command=command, instance_id=instance_id,
                                        instance_name=instance_name, status='SUCCESS',
                                        output=output, error='', execution_time=execution_time,
                                        timestamp=datetime.now()
                                    )
                                else:
                                    error = result.get('StandardErrorContent', '') or result.get('StatusDetails', '')
                                    if attempt < max_retries:
                                        raise Exception(f"Command {status}: {error}")
                                    return BatchJobResult(
                                        command=command, instance_id=instance_id,
                                        instance_name=instance_name, status='FAILED',
                                        output='', error=error, execution_time=execution_time,
                                        timestamp=datetime.now()
                                    )

                            time.sleep(3)
                            waited += 3
                        except ClientError as e:
                            if e.response.get('Error', {}).get('Code') == 'InvocationDoesNotExist':
                                time.sleep(2)
                                waited += 2
                                continue
                            time.sleep(Config.WAIT_PORT_READY)
                            waited += 2

                    if attempt < max_retries:
                        continue
                    execution_time = time.time() - start_time
                    return BatchJobResult(
                        command=command, instance_id=instance_id,
                        instance_name=instance_name, status='TIMEOUT',
                        output='', error=f'Command timed out after {max_wait} seconds',
                        execution_time=execution_time, timestamp=datetime.now()
                    )

                except ClientError as e:
                    if attempt < max_retries:
                        continue
                    return BatchJobResult(
                        command=command, instance_id=instance_id,
                        instance_name=instance_name, status='FAILED',
                        output='', error=str(e),
                        execution_time=time.time() - start_time, timestamp=datetime.now()
                    )
                except Exception as e:
                    if attempt < max_retries:
                        continue
                    return BatchJobResult(
                        command=command, instance_id=instance_id,
                        instance_name=instance_name, status='FAILED',
                        output='', error=str(e),
                        execution_time=time.time() - start_time, timestamp=datetime.now()
                    )

            return BatchJobResult(
                command=command, instance_id=instance_id, instance_name=instance_name,
                status='FAILED', output='', error='Max retries exceeded',
                execution_time=0.0, timestamp=datetime.now()
            )

        max_concurrent = min(len(validated_instances), Config.BATCH_CONCURRENT_JOBS)
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_concurrent) as executor:
            future_to_instance = {
                executor.submit(execute_on_instance, inst): inst
                for inst in validated_instances
            }
            for future in concurrent.futures.as_completed(future_to_instance):
                try:
                    result = future.result()
                    results.append(result)
                    status_color = Colors.SUCCESS if result.status == 'SUCCESS' else Colors.ERROR
                    print(f"{colored_text(result.status, status_color)} "
                          f"{result.instance_name} ({result.instance_id}) - {result.execution_time:.1f}s")
                except Exception as e:
                    instance = future_to_instance[future]
                    error_result = BatchJobResult(
                        command=command,
                        instance_id=instance['raw']['InstanceId'],
                        instance_name=instance['Name'],
                        status='FAILED', output='',
                        error=f"Executor error: {str(e)}",
                        execution_time=0.0, timestamp=datetime.now()
                    )
                    results.append(error_result)
                    print(colored_text(
                        f"ERROR {instance['Name']} ({instance['raw']['InstanceId']}) - {str(e)}", Colors.ERROR
                    ))

        success_count = sum(1 for r in results if r.status == 'SUCCESS')
        failed_count = len(results) - success_count
        print(colored_text(
            f"\n📊 총 {len(results)}개 인스턴스 - 성공: {success_count}, 실패: {failed_count}", Colors.INFO
        ))

        if failed_count > 0:
            failed_instances = [
                next(inst for inst in validated_instances if inst['raw']['InstanceId'] == r.instance_id)
                for r in results if r.status != 'SUCCESS'
            ]
            print(colored_text(f"\n⚠️  {failed_count}개 인스턴스에서 명령 실행이 실패했습니다.", Colors.WARNING))
            retry_choice = input(colored_text(
                "실패한 인스턴스만 다시 시도하시겠습니까? (y/N): ", Colors.PROMPT
            )).strip().lower()

            if retry_choice == 'y':
                print(colored_text(f"\n🔄 실패한 {failed_count}개 인스턴스를 다시 시도합니다...", Colors.INFO))
                retry_results = self.execute_batch_command(failed_instances, command, timeout_seconds)
                for retry_result in retry_results:
                    for i, r in enumerate(results):
                        if r.instance_id == retry_result.instance_id:
                            results[i] = retry_result
                            break
                success_count = sum(1 for r in results if r.status == 'SUCCESS')
                failed_count = len(results) - success_count
                print(colored_text(f"\n✅ 재시도 완료 - 성공: {success_count}, 실패: {failed_count}", Colors.SUCCESS))

        self.results_history.extend(results)
        self.save_results_history()
        return results

    def show_batch_results(self, results: List[BatchJobResult]) -> None:
        print(colored_text("\n📊 배치 작업 결과 상세:", Colors.HEADER))
        print("-" * 80)
        success_count = sum(1 for r in results if r.status == 'SUCCESS')
        failed_count = len(results) - success_count
        print(f"총 {len(results)}개 인스턴스 - "
              f"{colored_text(f'성공: {success_count}', Colors.SUCCESS)}, "
              f"{colored_text(f'실패: {failed_count}', Colors.ERROR)}")
        print()

        for result in results:
            status_color = Colors.SUCCESS if result.status == 'SUCCESS' else Colors.ERROR
            print(f"{colored_text('■', status_color)} "
                  f"{result.instance_name} ({result.instance_id}) - {result.execution_time:.1f}s")
            if result.output.strip():
                truncated = result.output.strip()[:100]
                print(f"   출력: {truncated}{'...' if len(result.output.strip()) > 100 else ''}")
            if result.error.strip():
                truncated = result.error.strip()[:100]
                print(colored_text(
                    f"   오류: {truncated}{'...' if len(result.error.strip()) > 100 else ''}", Colors.ERROR
                ))
            print()

    def save_results_history(self) -> None:
        try:
            recent_results = self.results_history[-100:]
            serializable = [
                {
                    'command': r.command, 'instance_id': r.instance_id,
                    'instance_name': r.instance_name, 'status': r.status,
                    'output': r.output, 'error': r.error,
                    'execution_time': r.execution_time,
                    'timestamp': r.timestamp.isoformat(),
                }
                for r in recent_results
            ]
            with open(Config.BATCH_RESULTS_PATH, 'w', encoding='utf-8') as f:
                json.dump(serializable, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.warning(f"배치 결과 히스토리 저장 실패: {e}")
