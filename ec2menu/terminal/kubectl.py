"""kubectl 래퍼 및 CloudShell 유틸리티"""
from __future__ import annotations

import json
import subprocess
import webbrowser
from typing import Dict, List, Optional

from ec2menu.core.colors import Colors, colored_text
from ec2menu.core.config import IS_MAC
from ec2menu.terminal.session import launch_terminal_session


def check_kubectl_installed() -> bool:
    try:
        result = subprocess.run(
            ['kubectl', 'version', '--client', '--output=json'],
            capture_output=True, text=True, timeout=5
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def check_kubeconfig_exists(cluster_name: str) -> bool:
    try:
        result = subprocess.run(
            ['kubectl', 'config', 'get-contexts', '-o', 'name'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            contexts = result.stdout.strip().split('\n')
            return any(cluster_name in ctx for ctx in contexts)
        return False
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def update_kubeconfig(profile: str, region: str, cluster_name: str) -> bool:
    """aws eks update-kubeconfig 실행"""
    try:
        cmd = [
            'aws', 'eks', 'update-kubeconfig',
            '--region', region,
            '--name', cluster_name,
            '--profile', profile,
        ]
        print(colored_text("\n⏳ kubeconfig 업데이트 중...", Colors.INFO))
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            print(colored_text("✅ kubeconfig 업데이트 완료", Colors.SUCCESS))
            return True
        else:
            print(colored_text(f"❌ kubeconfig 업데이트 실패: {result.stderr}", Colors.ERROR))
            return False
    except subprocess.TimeoutExpired:
        print(colored_text("❌ kubeconfig 업데이트 시간 초과", Colors.ERROR))
        return False
    except FileNotFoundError:
        print(colored_text("❌ AWS CLI가 설치되어 있지 않습니다.", Colors.ERROR))
        return False


def get_kubectl_pods(namespace: str = 'default', debug: bool = False) -> List[Dict]:
    try:
        result = subprocess.run(
            ['kubectl', 'get', 'pods', '-n', namespace, '-o', 'json'],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            pods = []
            for item in data.get('items', []):
                metadata = item.get('metadata', {})
                status = item.get('status', {})
                container_statuses = status.get('containerStatuses', [])
                pods.append({
                    'Name': metadata.get('name', 'N/A'),
                    'Namespace': metadata.get('namespace', 'default'),
                    'Status': status.get('phase', 'Unknown'),
                    'Ready': f"{sum(1 for c in container_statuses if c.get('ready', False))}/{len(container_statuses)}",
                    'Restarts': sum(c.get('restartCount', 0) for c in container_statuses),
                    'Age': metadata.get('creationTimestamp', 'N/A'),
                    'Containers': [c.get('name', '') for c in container_statuses],
                })
            return pods
        else:
            if debug or result.stderr:
                print(colored_text(f"⚠ kubectl get pods 실패: {result.stderr.strip()}", Colors.WARNING))
            return []
    except subprocess.TimeoutExpired:
        print(colored_text("⚠ kubectl get pods 시간 초과 (30초)", Colors.WARNING))
        return []
    except FileNotFoundError:
        print(colored_text("⚠ kubectl이 설치되어 있지 않습니다.", Colors.WARNING))
        return []
    except json.JSONDecodeError as e:
        print(colored_text(f"⚠ kubectl 출력 파싱 실패: {e}", Colors.WARNING))
        return []


def get_kubectl_namespaces(debug: bool = False) -> List[str]:
    try:
        result = subprocess.run(
            ['kubectl', 'get', 'namespaces', '-o', 'json'],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return [item.get('metadata', {}).get('name', '') for item in data.get('items', [])]
        else:
            if debug or result.stderr:
                print(colored_text(f"⚠ kubectl get namespaces 실패: {result.stderr.strip()}", Colors.WARNING))
            return []
    except subprocess.TimeoutExpired:
        print(colored_text("⚠ kubectl get namespaces 시간 초과 (30초)", Colors.WARNING))
        return []
    except FileNotFoundError:
        print(colored_text("⚠ kubectl이 설치되어 있지 않습니다.", Colors.WARNING))
        return []
    except json.JSONDecodeError as e:
        print(colored_text(f"⚠ kubectl 출력 파싱 실패: {e}", Colors.WARNING))
        return []


def launch_kubectl_exec(pod_name: str, namespace: str, container: Optional[str] = None) -> None:
    """새 터미널에서 kubectl exec 세션 시작 (iTerm2 우선)"""
    cmd_parts = ['kubectl', 'exec', '-it', pod_name, '-n', namespace]
    if container:
        cmd_parts.extend(['-c', container])
    cmd_parts.extend(['--', '/bin/sh', '-c', 'if command -v bash > /dev/null; then exec bash; else exec sh; fi'])
    if IS_MAC:
        launch_terminal_session(cmd_parts, use_iterm=True)


def launch_kubectl_logs(pod_name: str, namespace: str,
                         container: Optional[str] = None, follow: bool = True) -> None:
    """새 터미널에서 kubectl logs 세션 시작 (iTerm2 우선)"""
    cmd_parts = ['kubectl', 'logs', pod_name, '-n', namespace]
    if container:
        cmd_parts.extend(['-c', container])
    if follow:
        cmd_parts.append('-f')
    if IS_MAC:
        launch_terminal_session(cmd_parts, use_iterm=True)


def open_cloudshell_browser(region: str) -> None:
    url = f'https://{region}.console.aws.amazon.com/cloudshell/home?region={region}'
    print(colored_text("\n🌐 CloudShell 페이지를 브라우저에서 엽니다...", Colors.INFO))
    print(colored_text(f"   URL: {url}", Colors.INFO))
    webbrowser.open(url)
    print(colored_text("✅ 브라우저에서 CloudShell에 로그인하세요.", Colors.SUCCESS))
