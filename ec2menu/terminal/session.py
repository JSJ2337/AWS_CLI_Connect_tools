"""SSM, RDP, iTerm2, ECS Exec 터미널 세션 관리"""
from __future__ import annotations

import logging
import os
import shlex
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from typing import List, Optional

from ec2menu.core.colors import Colors, colored_text
from ec2menu.core.config import Config
from ec2menu.core.utils import _temp_files_lock, _temp_files_to_cleanup


def ssm_cmd(profile: str, region: str, iid: str) -> List[str]:
    """리눅스 인스턴스 접속용 SSM 세션 명령어 구성"""
    cmd = [
        'aws', 'ssm', 'start-session',
        '--region', region,
        '--target', iid,
        '--document-name', 'AWS-StartInteractiveCommand',
        '--parameters', '{"command":["bash -l"]}',
    ]
    if profile != 'default':
        cmd[1:1] = ['--profile', profile]
    return cmd


def create_ssm_forward_command(profile: str, region: str, target: str,
                                document: str, parameters: str) -> List[str]:
    """SSM 포트 포워딩 세션 명령어 생성"""
    cmd = [
        'aws', 'ssm', 'start-session',
        '--region', region,
        '--target', target,
        '--document-name', document,
        '--parameters', parameters,
    ]
    if profile != 'default':
        cmd[1:1] = ['--profile', profile]
    return cmd


def start_port_forward(profile: str, region: str, iid: str, port: int) -> subprocess.Popen:
    cmd = [
        'aws', 'ssm', 'start-session',
        '--region', region,
        '--target', iid,
        '--document-name', 'AWS-StartPortForwardingSession',
        '--parameters', f'{{"portNumber":["3389"],"localPortNumber":["{port}"]}}',
    ]
    if profile != 'default':
        cmd[1:1] = ['--profile', profile]
    return subprocess.Popen(
        cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL
    )


def wait_for_port(port: int, timeout: int = 30) -> bool:
    """포트가 LISTEN 상태가 될 때까지 대기"""
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex(('localhost', port))
            sock.close()
            if result == 0:
                return True
        except (socket.error, socket.timeout, OSError) as e:
            logging.debug(f"포트 {port} 대기 중 예외: {e}")
        time.sleep(0.5)
    return False


def launch_rdp(port: int) -> None:
    """macOS에서 RDP 접속 - Windows App 사용"""
    print(colored_text(f'⏳ 포트 {port}가 준비될 때까지 대기 중...', Colors.INFO))
    if not wait_for_port(port):
        print(colored_text(f'\n❌ 포트 {port}가 준비되지 않았습니다.', Colors.ERROR))
        return

    print(colored_text('✅ 포트가 준비되었습니다.', Colors.SUCCESS))
    print(colored_text('\n📊 RDP 연결 정보:', Colors.HEADER))
    print(colored_text(f'   호스트: localhost:{port}', Colors.INFO))
    print(colored_text('   사용자: Administrator', Colors.INFO))
    print(colored_text('   (비밀번호는 별도로 확인하세요)', Colors.WARNING))

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

    os.chmod(rdp_file, 0o600)

    with _temp_files_lock:
        _temp_files_to_cleanup.append(rdp_file)

    print(colored_text(f'\n📄 RDP 연결 파일 생성: {rdp_file}', Colors.INFO))

    try:
        if Path('/Applications/Windows App.app').exists():
            print(colored_text('✅ Windows App으로 연결합니다...', Colors.SUCCESS))
            subprocess.run(['open', '-a', 'Windows App', str(rdp_file)])
            time.sleep(Config.WAIT_PORT_READY)
        elif Path('/Applications/Microsoft Remote Desktop.app').exists():
            print(colored_text('✅ Microsoft Remote Desktop으로 연결합니다...', Colors.SUCCESS))
            subprocess.run(['open', '-a', 'Microsoft Remote Desktop', str(rdp_file)])
            time.sleep(Config.WAIT_PORT_READY)
        else:
            print(colored_text('\n⚠️ RDP 클라이언트가 설치되지 않았습니다.', Colors.WARNING))
            print(colored_text('\n권장: App Store에서 "Microsoft Remote Desktop" 설치', Colors.INFO))
            print(colored_text(f'\n수동 연결 정보:\n   호스트: localhost:{port}\n   사용자: Administrator', Colors.INFO))
            return
    finally:
        try:
            if rdp_file.exists():
                rdp_file.unlink()
                with _temp_files_lock:
                    if rdp_file in _temp_files_to_cleanup:
                        _temp_files_to_cleanup.remove(rdp_file)
                print(colored_text('🗑️  임시 RDP 파일 삭제됨', Colors.INFO))
        except Exception as e:
            logging.warning(f"RDP 파일 즉시 삭제 실패 (프로그램 종료 시 재시도): {rdp_file} - {e}")


def check_iterm2() -> bool:
    return os.path.exists('/Applications/iTerm.app')


def launch_terminal_session(command_list: List[str], use_iterm: bool = True) -> None:
    """macOS에서 새 터미널 탭에서 명령 실행 (iTerm2 또는 Terminal.app)"""
    cmd_str = ' '.join(shlex.quote(arg) for arg in command_list)
    applescript_safe = cmd_str.replace('\\', '\\\\').replace('"', '\\"')

    if use_iterm and check_iterm2():
        is_running = subprocess.run(
            ['osascript', '-e', 'tell application "System Events" to (name of processes) contains "iTerm2"'],
            capture_output=True, text=True
        ).stdout.strip() == 'true'

        window_count = 0
        if is_running:
            result = subprocess.run(
                ['osascript', '-e', 'tell application "iTerm" to count windows'],
                capture_output=True, text=True
            )
            if result.stdout.strip().isdigit():
                window_count = int(result.stdout.strip())

        try:
            if not is_running or window_count == 0:
                subprocess.run(['open', '-a', 'iTerm'], check=True)
                time.sleep(Config.WAIT_APP_LAUNCH)
                applescript = f'''
                tell application "iTerm"
                    tell current session of current window
                        write text "{applescript_safe}"
                    end tell
                end tell
                '''
                subprocess.run(['osascript', '-e', applescript], check=True)
            else:
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
            print(colored_text("❌ iTerm2 실행 중 오류 발생. 수동으로 터미널을 열고 다음 명령을 실행하세요:", Colors.ERROR))
            print(colored_text(f"   {cmd_str}", Colors.INFO))
    else:
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
            print(colored_text("❌ Terminal.app 실행 중 오류 발생. 수동으로 터미널을 열고 다음 명령을 실행하세요:", Colors.ERROR))
            print(colored_text(f"   {cmd_str}", Colors.INFO))


def launch_linux_wt(profile: str, region: str, iid: str) -> None:
    """리눅스 인스턴스에 새 터미널 탭으로 접속"""
    cmd = ssm_cmd(profile, region, iid)
    launch_terminal_session(cmd, use_iterm=True)


def ecs_exec_cmd(profile: str, region: str, cluster: str, task_arn: str, container: str) -> List[str]:
    """ECS Exec 명령어 구성"""
    cmd = [
        'aws', 'ecs', 'execute-command',
        '--region', region,
        '--cluster', cluster,
        '--task', task_arn,
        '--container', container,
        '--interactive',
        '--command', '/bin/bash',
    ]
    if profile != 'default':
        cmd[1:1] = ['--profile', profile]
    return cmd


def launch_ecs_exec(profile: str, region: str, cluster: str, task_arn: str, container: str) -> None:
    """ECS 컨테이너에 새 터미널로 접속"""
    cmd = ecs_exec_cmd(profile, region, cluster, task_arn, container)
    launch_terminal_session(cmd)
