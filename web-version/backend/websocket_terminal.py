"""
AWS CLI SSM을 통한 WebSocket 터미널 관리
"""
import asyncio
import json
import uuid
import logging
import os
import pty
import subprocess
import time
from typing import Dict, Optional
import boto3
from botocore.exceptions import ClientError
from models import SSMSession

logger = logging.getLogger(__name__)

class SSMWebSocketManager:
    """AWS CLI SSM 터미널 관리자"""

    def __init__(self):
        self.active_sessions: Dict[str, Dict] = {}
        self.session_websockets: Dict[str, object] = {}
        self.session_processes: Dict[str, subprocess.Popen] = {}
    
    async def start_ssm_session(self, profile: str, region: str, instance_id: str) -> SSMSession:
        """AWS CLI 기반 SSM 세션 시작"""
        try:
            # 기존 활성 세션 정리 (새 세션 시작 전)
            await self._cleanup_existing_sessions(profile, region, instance_id)

            session_id = str(uuid.uuid4())

            # AWS CLI 명령어 구성
            cmd = [
                'aws', 'ssm', 'start-session',
                '--region', region,
                '--target', instance_id,
                '--document-name', 'AWS-StartInteractiveCommand',
                '--parameters', '{"command":["bash -l"]}'
            ]

            if profile != 'default':
                cmd[1:1] = ['--profile', profile]

            logger.info(f"AWS CLI 명령어: {' '.join(cmd)}")

            # 세션 정보 저장
            session_info = {
                'session_id': session_id,
                'instance_id': instance_id,
                'profile': profile,
                'region': region,
                'cmd': cmd,
                'status': 'active'
            }
            
            self.active_sessions[session_id] = session_info
            
            return SSMSession(
                session_id=session_id,
                instance_id=instance_id,
                websocket_url=f"ws://localhost:8000/ws/terminal/{session_id}",
                status="active"
            )
            
        except ClientError as e:
            logger.error(f"SSM 세션 시작 실패: {e}")
            raise Exception(f"SSM 세션 시작 실패: {str(e)}")
    
    async def handle_websocket_connection(self, websocket, session_id: str):
        """WebSocket 연결 처리 (AWS CLI 기반)"""
        if session_id not in self.active_sessions:
            await websocket.close(code=4004, reason="Session not found")
            return

        session_info = self.active_sessions[session_id]
        self.session_websockets[session_id] = websocket

        try:
            # AWS CLI 프로세스 시작
            master_fd, slave_fd = pty.openpty()

            # AWS CLI 환경 변수 설정 (캐시 비활성화)
            env = os.environ.copy()
            env['AWS_CLI_CACHE_DIR'] = '/tmp/aws-cli-cache'
            env['AWS_CLI_FILE_ENCODING'] = 'UTF-8'
            env['AWS_DEFAULT_OUTPUT'] = 'json'

            # 모든 프로필을 그대로 사용 (config 파일에 올바른 role_arn 설정됨)
            profile = session_info['profile']
            cmd = session_info['cmd']

            # AWS CLI 명령에 --no-cli-pager와 --no-cli-auto-prompt 추가
            if '--no-cli-pager' not in cmd:
                cmd.insert(1, '--no-cli-pager')
            if '--no-cli-auto-prompt' not in cmd:
                cmd.insert(1, '--no-cli-auto-prompt')

            process = subprocess.Popen(
                cmd,  # 수정된 명령어 사용
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                env=env,
                close_fds=True
            )

            self.session_processes[session_id] = process
            os.close(slave_fd)

            logger.info(f"AWS CLI 프로세스 시작됨: PID {process.pid}")

            # 양방향 데이터 전달
            await asyncio.gather(
                self._forward_client_to_process(websocket, master_fd),
                self._forward_process_to_client(master_fd, websocket),
                return_exceptions=True
            )

        except Exception as e:
            logger.error(f"WebSocket 연결 처리 중 오류: {e}")
            await websocket.close(code=4000, reason="Connection error")
        finally:
            # 정리
            if session_id in self.session_websockets:
                del self.session_websockets[session_id]
            await self._cleanup_session(session_id)
    
    async def _connect_to_ssm_websocket(self, session_info: Dict) -> object:
        """SSM WebSocket에 연결"""
        try:
            # SSM WebSocket URL 구성
            stream_url = session_info['stream_url']
            session_id = session_info['session_id']
            token_value = session_info['token_value']

            # WebSocket 연결 파라미터 (AWS SSM 형식)
            websocket_url = f"{stream_url}?role=publish_subscribe"

            # SSM WebSocket 연결
            ssm_websocket = await websockets.connect(
                websocket_url,
                extra_headers={
                    'User-Agent': 'EC2Menu-Web/1.0'
                }
            )

            # AWS SSM 인증 메시지 전송
            auth_message = {
                "MessageSchemaVersion": "1.0",
                "RequestId": str(uuid.uuid4()),
                "TokenValue": token_value
            }

            await ssm_websocket.send(json.dumps(auth_message))
            logger.info("AWS SSM 인증 메시지 전송 완료")
            
            return ssm_websocket
            
        except Exception as e:
            logger.error(f"SSM WebSocket 연결 실패: {e}")
            raise

    def _encode_ssm_message(self, message_type: str, data: str) -> bytes:
        """AWS SSM 바이너리 메시지 인코딩"""
        try:
            # AWS SSM 프로토콜에 따른 메시지 인코딩
            # 간단한 구현 - 실제로는 더 복잡한 프로토콜 필요
            if message_type == "input_stream_data":
                # 입력 데이터를 base64로 인코딩
                encoded_data = base64.b64encode(data.encode('utf-8'))

                # 헤더 구성 (메시지 타입, 길이 등)
                header = struct.pack('>I', len(encoded_data))
                return header + encoded_data

            return data.encode('utf-8')
        except Exception as e:
            logger.error(f"SSM 메시지 인코딩 오류: {e}")
            return data.encode('utf-8')

    def _decode_ssm_message(self, data: bytes) -> str:
        """AWS SSM 바이너리 메시지 디코딩"""
        try:
            # 간단한 디코딩 구현
            if len(data) > 4:
                # 헤더에서 길이 추출
                length = struct.unpack('>I', data[:4])[0]
                if len(data) >= 4 + length:
                    # 실제 데이터 추출 및 base64 디코딩
                    encoded_data = data[4:4+length]
                    try:
                        decoded = base64.b64decode(encoded_data).decode('utf-8')
                        return decoded
                    except:
                        return encoded_data.decode('utf-8', errors='ignore')

            return data.decode('utf-8', errors='ignore')
        except Exception as e:
            logger.error(f"SSM 메시지 디코딩 오류: {e}")
            return data.decode('utf-8', errors='ignore')

    async def _forward_client_to_process(self, client_ws, master_fd):
        """클라이언트 → AWS CLI 프로세스 데이터 전달"""
        try:
            while True:
                try:
                    message = await client_ws.receive_text()
                    logger.info(f"클라이언트로부터 메시지 수신: {message}")
                    data = json.loads(message)

                    if data.get('type') == 'input':
                        input_data = data['data']
                        logger.info(f"원본 데이터: {repr(data['data'])}")
                        logger.info(f"입력 데이터 처리: {repr(input_data)} (길이: {len(input_data)})")

                        # 빈 문자열 무시
                        if not input_data:
                            logger.info("빈 입력 데이터 무시")
                            continue

                        # DEL 키 특수 처리 (Backspace가 DEL로 전송되는 경우)
                        if input_data == '\x7f':
                            logger.info("DEL 키 입력 감지 - Backspace로 처리")
                            # Backspace로 변환 (Ctrl+H)
                            input_data = '\x08'

                        # 특수 키 처리
                        if input_data == ' ':
                            logger.info("🔵 스페이스바 입력 감지!")
                        elif input_data == '\r':
                            logger.info("🟢 엔터 키 입력 감지")
                        elif input_data == '\t':
                            logger.info("🟡 탭 키 입력 감지")
                        elif len(input_data) == 1 and ord(input_data) < 32:
                            logger.info(f"🟠 제어 문자 입력: {repr(input_data)} (ASCII: {ord(input_data)})")
                        else:
                            logger.info(f"📝 일반 문자 입력: {repr(input_data)}")

                        # 프로세스에 직접 작성
                        os.write(master_fd, input_data.encode('utf-8'))
                        logger.info("프로세스로 데이터 전송 완료")

                except Exception as e:
                    logger.error(f"클라이언트 메시지 수신 오류: {e}")
                    break

        except Exception as e:
            logger.error(f"클라이언트 → 프로세스 데이터 전달 오류: {e}")
    
    async def _forward_process_to_client(self, master_fd, client_ws):
        """AWS CLI 프로세스 → 클라이언트 데이터 전달"""
        try:
            while True:
                try:
                    # 논블로킹 읽기를 위해 asyncio 사용
                    data = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: os.read(master_fd, 1024)
                    )

                    if data:
                        output = data.decode('utf-8', errors='ignore')
                        # 스페이스 문자 포함 여부 확인
                        if ' ' in output:
                            logger.info(f"🔵 스페이스 포함 출력: {repr(output[:100])} (스페이스 개수: {output.count(' ')})")
                        else:
                            logger.info(f"프로세스 출력: {repr(output[:100])}")

                        # 클라이언트로 출력 전송
                        client_message = {
                            'type': 'output',
                            'data': output
                        }
                        await client_ws.send_text(json.dumps(client_message))
                        logger.info("클라이언트로 출력 전송 완료")
                    else:
                        # 프로세스 종료
                        break

                except OSError as e:
                    logger.info(f"프로세스 읽기 종료: {e}")
                    break
                except Exception as e:
                    logger.error(f"프로세스 출력 읽기 오류: {e}")
                    break

        except Exception as e:
            logger.error(f"프로세스 → 클라이언트 데이터 전달 오류: {e}")
    
    async def terminate_session(self, session_id: str) -> bool:
        """SSM 세션 종료"""
        if session_id not in self.active_sessions:
            return False
        
        session_info = self.active_sessions[session_id]
        
        try:
            # AWS 세션으로 SSM 세션 종료
            session = boto3.Session(profile_name=session_info['profile'])
            ssm_client = session.client('ssm', region_name=session_info['region'])
            
            ssm_client.terminate_session(SessionId=session_id)
            
            # WebSocket 연결 종료
            if session_id in self.session_websockets:
                websocket = self.session_websockets[session_id]
                await websocket.close(code=1000, reason="Session terminated")
            
            await self._cleanup_session(session_id)
            return True
            
        except Exception as e:
            logger.error(f"세션 종료 실패: {e}")
            return False
    
    async def _cleanup_session(self, session_id: str):
        """세션 정리 (로컬 프로세스 + AWS SSM 세션)"""
        try:
            # AWS SSM 세션 정리
            if session_id in self.active_sessions:
                session_info = self.active_sessions[session_id]
                await self._terminate_aws_ssm_session(session_info)
                del self.active_sessions[session_id]
                logger.info(f"AWS SSM 세션 정리 완료: {session_id}")

            # 로컬 프로세스 종료
            if session_id in self.session_processes:
                process = self.session_processes[session_id]
                try:
                    process.terminate()
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                except Exception as e:
                    logger.warning(f"프로세스 종료 실패: {e}")
                finally:
                    del self.session_processes[session_id]
                    logger.info(f"로컬 프로세스 정리 완료: {session_id}")

        except Exception as e:
            logger.error(f"세션 정리 오류: {e}")

    async def _terminate_aws_ssm_session(self, session_info: Dict):
        """AWS SSM 세션 종료"""
        try:
            profile = session_info.get('profile', 'aws-sys')
            region = session_info.get('region', 'ap-northeast-2')
            instance_id = session_info.get('instance_id')

            if not instance_id:
                logger.warning("인스턴스 ID가 없어 SSM 세션 정리를 건너뜁니다")
                return

            # 해당 인스턴스의 활성 세션 조회
            cmd = [
                'aws', 'ssm', 'describe-sessions',
                '--state', 'Active',
                '--region', region,
                '--query', f'Sessions[?Target==`{instance_id}`].SessionId',
                '--output', 'text'
            ]

            if profile != 'default':
                cmd[1:1] = ['--profile', profile]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            if result.returncode == 0 and result.stdout.strip():
                session_ids = result.stdout.strip().split()
                logger.info(f"발견된 활성 SSM 세션: {session_ids}")

                # 각 세션 종료
                for ssm_session_id in session_ids:
                    terminate_cmd = [
                        'aws', 'ssm', 'terminate-session',
                        '--session-id', ssm_session_id,
                        '--region', region
                    ]

                    if profile != 'default':
                        terminate_cmd[1:1] = ['--profile', profile]

                    terminate_result = subprocess.run(terminate_cmd, capture_output=True, text=True, timeout=30)

                    if terminate_result.returncode == 0:
                        logger.info(f"SSM 세션 종료 완료: {ssm_session_id}")
                    else:
                        logger.warning(f"SSM 세션 종료 실패: {ssm_session_id}, 오류: {terminate_result.stderr}")
            else:
                logger.info(f"인스턴스 {instance_id}에 활성 SSM 세션이 없습니다")

        except subprocess.TimeoutExpired:
            logger.error("SSM 세션 종료 시간 초과")
        except Exception as e:
            logger.error(f"SSM 세션 종료 오류: {e}")

    async def _cleanup_existing_sessions(self, profile: str, region: str, instance_id: str):
        """새 세션 시작 전 기존 세션 정리"""
        try:
            logger.info(f"인스턴스 {instance_id}의 기존 세션 정리 시작")

            # 해당 인스턴스의 활성 세션 조회
            cmd = [
                'aws', 'ssm', 'describe-sessions',
                '--state', 'Active',
                '--region', region,
                '--query', f'Sessions[?Target==`{instance_id}`].SessionId',
                '--output', 'text'
            ]

            if profile != 'default':
                cmd[1:1] = ['--profile', profile]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            if result.returncode == 0 and result.stdout.strip():
                session_ids = result.stdout.strip().split()
                logger.info(f"정리할 기존 SSM 세션 발견: {session_ids}")

                # 각 세션 종료
                for ssm_session_id in session_ids:
                    terminate_cmd = [
                        'aws', 'ssm', 'terminate-session',
                        '--session-id', ssm_session_id,
                        '--region', region
                    ]

                    if profile != 'default':
                        terminate_cmd[1:1] = ['--profile', profile]

                    terminate_result = subprocess.run(terminate_cmd, capture_output=True, text=True, timeout=30)

                    if terminate_result.returncode == 0:
                        logger.info(f"기존 SSM 세션 정리 완료: {ssm_session_id}")
                    else:
                        logger.warning(f"기존 SSM 세션 정리 실패: {ssm_session_id}")

                # 세션 정리 후 잠시 대기 (AWS가 상태를 업데이트할 시간)
                await asyncio.sleep(2)
            else:
                logger.info(f"인스턴스 {instance_id}에 정리할 기존 세션이 없습니다")

        except subprocess.TimeoutExpired:
            logger.error("기존 세션 정리 시간 초과")
        except Exception as e:
            logger.error(f"기존 세션 정리 오류: {e}")

            if session_id in self.session_websockets:
                del self.session_websockets[session_id]

        except Exception as e:
            logger.error(f"세션 정리 실패: {e}")
    
    def get_session_info(self, session_id: str) -> Optional[Dict]:
        """세션 정보 조회"""
        return self.active_sessions.get(session_id)
    
    def list_active_sessions(self) -> Dict[str, Dict]:
        """활성 세션 목록 조회"""
        return self.active_sessions.copy()

class RDPTunnelManager:
    """RDS/RDP 포트 포워딩 관리자"""
    
    def __init__(self):
        self.active_tunnels: Dict[str, Dict] = {}
    
    async def start_rds_tunnel(self, profile: str, region: str, jump_host_id: str, 
                              db_endpoint: str, db_port: int) -> Dict:
        """RDS 포트 포워딩 터널 시작"""
        try:
            session = boto3.Session(profile_name=profile)
            ssm_client = session.client('ssm', region_name=region)
            
            # 로컬 포트 할당 (11000번대 사용)
            local_port = self._get_available_port()
            
            # SSM 포트 포워딩 세션 시작
            parameters = {
                'host': [db_endpoint],
                'portNumber': [str(db_port)],
                'localPortNumber': [str(local_port)]
            }
            
            response = ssm_client.start_session(
                Target=jump_host_id,
                DocumentName='AWS-StartPortForwardingSessionToRemoteHost',
                Parameters=parameters
            )
            
            tunnel_id = response['SessionId']
            
            # 터널 정보 저장
            tunnel_info = {
                'tunnel_id': tunnel_id,
                'profile': profile,
                'region': region,
                'jump_host_id': jump_host_id,
                'db_endpoint': db_endpoint,
                'db_port': db_port,
                'local_port': local_port,
                'status': 'active'
            }
            
            self.active_tunnels[tunnel_id] = tunnel_info
            
            return {
                'session_id': tunnel_id,
                'local_port': local_port,
                'db_endpoint': db_endpoint,
                'db_port': db_port,
                'status': 'active'
            }
            
        except Exception as e:
            logger.error(f"RDS 터널 시작 실패: {e}")
            raise Exception(f"RDS 터널 시작 실패: {str(e)}")
    
    async def start_rdp_tunnel(self, profile: str, region: str, instance_id: str) -> Dict:
        """RDP 포트 포워딩 터널 시작"""
        import subprocess
        try:
            session = boto3.Session(profile_name=profile)
            ssm_client = session.client('ssm', region_name=region)

            # SSM 연결 상태 확인
            try:
                response = ssm_client.describe_instance_information(
                    Filters=[
                        {
                            'Key': 'InstanceIds',
                            'Values': [instance_id]
                        }
                    ]
                )
                if not response['InstanceInformationList']:
                    raise Exception(f"인스턴스 {instance_id}가 SSM에 연결되지 않았습니다. SSM Agent가 설치되어 있고 올바른 IAM 역할이 연결되어 있는지 확인하세요.")

                instance_info = response['InstanceInformationList'][0]
                if instance_info['PingStatus'] != 'Online':
                    raise Exception(f"인스턴스 {instance_id}의 SSM 상태가 '{instance_info['PingStatus']}'입니다. 인스턴스가 실행 중이고 SSM Agent가 정상 작동하는지 확인하세요.")
            except Exception as check_error:
                if "연결되지 않았습니다" in str(check_error) or "상태가" in str(check_error):
                    raise check_error
                else:
                    raise Exception(f"SSM 연결 확인 중 오류: {str(check_error)}")

            # 로컬 포트 할당 (5000번대 사용)
            local_port = self._get_available_port(start_port=5000)

            # Docker 컨테이너에서 SSM 포트 포워딩을 위한 socat 터널링 방식
            # 1. 내부 포트는 SSM에서 사용, 외부 포트는 Guacamole에서 접근
            internal_port = local_port + 1000  # 내부 SSM 포트
            external_port = local_port         # 외부 접근 포트

            # 2. socat으로 포트 터널링 시작 (백그라운드)
            socat_cmd = [
                'socat',
                f'tcp-listen:{external_port},reuseaddr,fork',
                f'tcp:localhost:{internal_port}'
            ]

            logger.info(f"socat 터널링 시작: {' '.join(socat_cmd)}")
            socat_process = subprocess.Popen(
                socat_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                text=True
            )

            # 3. AWS CLI로 SSM 포트 포워딩 시작 (내부 포트 사용)
            aws_cmd = [
                'aws', 'ssm', 'start-session',
                '--region', region,
                '--target', instance_id,
                '--document-name', 'AWS-StartPortForwardingSession',
                '--parameters', f'{{"portNumber":["3389"],"localPortNumber":["{internal_port}"]}}'
            ]
            if profile != 'default':
                aws_cmd[1:1] = ['--profile', profile]

            logger.info(f"AWS CLI 명령 실행: {' '.join(aws_cmd)}")

            # subprocess로 실제 SSM 터널 프로세스 시작
            aws_process = subprocess.Popen(
                aws_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                text=True
            )

            # 터널 ID 생성 (프로세스 ID 기반)
            tunnel_id = f"rdp-tunnel-{aws_process.pid}-{int(time.time())}"

            # 터널 정보 저장 (두 프로세스 모두 추적)
            tunnel_info = {
                'tunnel_id': tunnel_id,
                'profile': profile,
                'region': region,
                'instance_id': instance_id,
                'local_port': external_port,  # Guacamole이 접근할 포트
                'internal_port': internal_port,  # SSM이 사용하는 포트
                'aws_process': aws_process,
                'socat_process': socat_process,
                'status': 'active'
            }

            self.active_tunnels[tunnel_id] = tunnel_info

            logger.info(f"RDP 터널 시작됨: {tunnel_id} (socat: {external_port} -> ssm: {internal_port})")

            return {
                'session_id': tunnel_id,
                'local_port': external_port,
                'instance_id': instance_id,
                'status': 'active'
            }

        except Exception as e:
            logger.error(f"RDP 터널 시작 실패: {e}")
            raise Exception(f"RDP 터널 시작 실패: {str(e)}")
    
    async def terminate_tunnel(self, tunnel_id: str) -> bool:
        """터널 종료"""
        if tunnel_id not in self.active_tunnels:
            return False

        tunnel_info = self.active_tunnels[tunnel_id]

        try:
            # AWS SSM 프로세스 종료
            if 'aws_process' in tunnel_info:
                aws_process = tunnel_info['aws_process']
                if aws_process.poll() is None:
                    aws_process.terminate()
                    try:
                        aws_process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        aws_process.kill()
                        aws_process.wait()
                    logger.info(f"AWS SSM 프로세스 종료됨: PID {aws_process.pid}")

            # socat 프로세스 종료
            if 'socat_process' in tunnel_info:
                socat_process = tunnel_info['socat_process']
                if socat_process.poll() is None:
                    socat_process.terminate()
                    try:
                        socat_process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        socat_process.kill()
                        socat_process.wait()
                    logger.info(f"socat 프로세스 종료됨: PID {socat_process.pid}")

            del self.active_tunnels[tunnel_id]
            logger.info(f"RDP 터널 정리 완료: {tunnel_id}")
            return True

        except Exception as e:
            logger.error(f"터널 종료 실패: {e}")
            return False
    
    def _get_available_port(self, start_port: int = 11000) -> int:
        """사용 가능한 포트 찾기"""
        import socket
        
        for port in range(start_port, start_port + 1000):
            if port not in [t['local_port'] for t in self.active_tunnels.values()]:
                # 포트가 실제로 사용 가능한지 확인
                try:
                    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                        s.bind(('localhost', port))
                        return port
                except OSError:
                    continue
        
        raise Exception("사용 가능한 포트를 찾을 수 없습니다")
    
    def get_tunnel_info(self, tunnel_id: str) -> Optional[Dict]:
        """터널 정보 조회"""
        return self.active_tunnels.get(tunnel_id)
    
    def list_active_tunnels(self) -> Dict[str, Dict]:
        """활성 터널 목록 조회"""
        return self.active_tunnels.copy()