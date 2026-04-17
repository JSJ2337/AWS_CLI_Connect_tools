"""메인 진입점 - 프로파일/리전 선택, 메인 메뉴"""
from __future__ import annotations

import argparse
import concurrent.futures
import configparser
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from botocore.exceptions import ClientError

from ec2menu.aws.manager import AWSManager
from ec2menu.core.colors import Colors, colored_text
from ec2menu.core.config import Config, IS_MAC
from ec2menu.core.utils import calculate_local_port, setup_logger
from ec2menu.menus.cloudwatch import cloudwatch_menu
from ec2menu.menus.ec2 import ec2_menu
from ec2menu.menus.ecs import ecs_menu
from ec2menu.menus.eks import eks_menu
from ec2menu.menus.elasticache import connect_to_cache
from ec2menu.menus.lambda_menu import lambda_menu
from ec2menu.menus.rds import connect_to_rds
from ec2menu.menus.s3 import s3_browser_menu
from ec2menu.terminal.kubectl import open_cloudshell_browser
from ec2menu.terminal.session import (
    create_ssm_forward_command,
    launch_ecs_exec,
    launch_linux_wt,
    launch_rdp,
    launch_terminal_session,
    start_port_forward,
)
from ec2menu.ui.credentials import _stored_credentials, clear_stored_credentials, get_db_credentials
from ec2menu.ui.history import load_history
from ec2menu.ui.menu import interactive_select

AWS_CONFIG_PATH = Path.home() / '.aws' / 'config'
AWS_CRED_PATH = Path.home() / '.aws' / 'credentials'

MENU_HELP = {
    'main': """
╔══════════════════════════════════════════════════════════════════════════════╗
║                         EC2 Menu v5.5.0 도움말                                ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ 메인 메뉴 명령어                                                               ║
║   1-6    각 서비스 메뉴 진입                                                    ║
║   h      최근 연결 기록 조회                                                    ║
║   c      저장된 DB 자격증명 삭제                                                 ║
║   b      리전 재선택                                                           ║
║   Enter  프로그램 종료                                                         ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ 명령줄 옵션                                                                    ║
║   -p, --profile    AWS 프로파일 지정                                           ║
║   -r, --region     AWS 리전 지정                                               ║
║   -s, --service    서비스 직접 진입 (ec2/rds/cache/ecs/eks/cloudwatch/lambda/s3)║
║   --no-cache       캐시 비활성화                                               ║
║   -d, --debug      디버그 모드                                                 ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ v5.5.0 주요 변경사항                                                          ║
║   - CloudWatch 통합 (대시보드, 알람, 로그 조회)                                   ║
║   - Lambda 관리 (함수 목록, 테스트 실행, 로그 조회)                               ║
║   - S3 브라우저 (버킷/객체 탐색, 업로드/다운로드, Presigned URL)                   ║
║   - v5.4.0 기능 포함 (Keychain, 캐시 TTL, 페이지네이션)                          ║
╚══════════════════════════════════════════════════════════════════════════════╝
""",
}


def list_profiles():
    profiles = set()
    if AWS_CONFIG_PATH.exists():
        cfg = configparser.RawConfigParser()
        cfg.read(AWS_CONFIG_PATH)
        for sec in cfg.sections():
            if sec.startswith("profile "):
                profiles.add(sec.split(" ", 1)[1])
            elif sec == 'default':
                profiles.add('default')
    if AWS_CRED_PATH.exists():
        cred = configparser.RawConfigParser()
        cred.read(AWS_CRED_PATH)
        profiles.update(cred.sections())
    return sorted(profiles)


def choose_profile() -> str:
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
            sys.exit(0)
        if sel.isdigit() and 1 <= int(sel) <= len(lst):
            return lst[int(sel) - 1]
        retry_count += 1
        remaining = Config.MAX_INPUT_RETRIES - retry_count
        if remaining > 0:
            print(colored_text(f"❌ 올바른 번호를 입력하세요. (남은 시도: {remaining}회)", Colors.ERROR))

    print(colored_text("❌ 최대 재시도 횟수 초과. 프로그램을 종료합니다.", Colors.ERROR))
    sys.exit(1)


def _check_region_resources(manager: AWSManager, region: str) -> Dict[str, bool]:
    result = {'ec2': False, 'ecs': False, 'eks': False, 'rds': False, 'cache': False}
    try:
        if manager.list_instances(region):
            result['ec2'] = True
    except Exception:
        pass
    try:
        if manager.list_ecs_clusters(region):
            result['ecs'] = True
    except Exception:
        pass
    try:
        if manager.list_eks_clusters(region):
            result['eks'] = True
    except Exception:
        pass
    try:
        if manager.get_rds_endpoints(region):
            result['rds'] = True
    except Exception:
        pass
    try:
        if manager.list_cache_clusters(region):
            result['cache'] = True
    except Exception:
        pass
    return result


def choose_region(manager: AWSManager) -> Optional[str]:
    regs = manager.list_regions()
    valid_regions: Dict[str, Dict[str, bool]] = {}
    print(colored_text("\n⏳ AWS 리소스가 있는 리전을 검색 중입니다. 잠시만 기다려주세요...", Colors.INFO))
    with concurrent.futures.ThreadPoolExecutor(max_workers=manager.max_workers) as ex:
        future = {ex.submit(_check_region_resources, manager, r): r for r in regs}
        for f in concurrent.futures.as_completed(future):
            r = future[f]
            try:
                resources = f.result()
                if any(resources.values()):
                    valid_regions[r] = resources
            except Exception as e:
                logging.warning(f"리전 {r} 검색 중 오류 발생: {e}")

    if not valid_regions:
        print(colored_text("\n⚠ AWS 리소스가 있는 리전이 없습니다.", Colors.WARNING))
        return None

    valid_sorted = sorted(valid_regions.keys())

    region_items = []
    for r in valid_sorted:
        resources = valid_regions[r]
        tags = []
        if resources.get('ec2'):
            tags.append('EC2')
        if resources.get('ecs'):
            tags.append('ECS')
        if resources.get('eks'):
            tags.append('EKS')
        if resources.get('rds'):
            tags.append('RDS')
        if resources.get('cache'):
            tags.append('Cache')
        tags_str = ', '.join(tags) if tags else ''
        region_items.append(f"{r:<20} [{tags_str}]")
    region_items.append("🌏 모든 리전 통합 뷰")
    region_items.append("🔙 돌아가기")

    title = "AWS Regions with Resources"
    sel = interactive_select(region_items, title=title)

    if sel == -1 or sel == len(valid_sorted) + 1:
        return None
    if sel == len(valid_sorted):
        return 'multi-region'
    return valid_sorted[sel]


def choose_jump_host(manager: AWSManager, region: str) -> Optional[str]:
    jump_host_tags = {"Role": "jumphost"}
    ssm_targets = manager.list_ssm_managed(region, jump_host_tags)

    if not ssm_targets:
        print(colored_text("⚠ Role=jumphost 태그가 있는 SSM 관리 인스턴스가 없습니다.", Colors.WARNING))
        print("   점프 호스트로 사용할 EC2에 'Role=jumphost' 태그를 추가해주세요.")
        return None

    if len(ssm_targets) == 1:
        print(colored_text(f"\n(info) 유일한 Jump Host '{ssm_targets[0]['Name']} ({ssm_targets[0]['Id']})'를 사용합니다.", Colors.INFO))
        return ssm_targets[0]['Id']

    jump_items = [f"{t['Name']:<30} ({t['Id']})" for t in ssm_targets]
    jump_items.append("🔙 돌아가기")

    title = f"Select Jump Host (Role=jumphost)  │  Region: {region}"
    sel = interactive_select(jump_items, title=title)

    if sel == -1 or sel == len(ssm_targets):
        return None
    return ssm_targets[sel]['Id']


def show_recent_connections():
    history = load_history()
    all_recent = []
    for service_type, entries in history.items():
        for entry in entries:
            entry['service_type'] = service_type
            all_recent.append(entry)

    all_recent.sort(key=lambda x: x['timestamp'], reverse=True)

    if not all_recent:
        print(colored_text("\n⚠ 최근 연결 기록이 없습니다.", Colors.WARNING))
        return None

    recent_10 = all_recent[:10]
    service_icons = {"ec2": "🖥️", "rds": "🗄️", "cache": "⚡", "ecs": "🐳"}
    recent_items = []
    for entry in recent_10:
        service_icon = service_icons.get(entry['service_type'], "📦")
        timestamp = datetime.fromisoformat(entry['timestamp']).strftime('%m-%d %H:%M')
        recent_items.append(f"{service_icon} {entry['instance_name']:<25} [{entry['region']}] {timestamp}")
    recent_items.append("🔙 돌아가기")

    sel = interactive_select(recent_items, title="Recent Connections", show_index=False)

    if sel == -1 or sel == len(recent_10):
        return None
    return recent_10[sel]


def reconnect_to_instance(manager: AWSManager, entry: dict) -> None:
    service_type = entry['service_type']
    region = entry['region']
    instance_id = entry['instance_id']
    instance_name = entry['instance_name']

    print(colored_text(f"\n🔄 {instance_name}({instance_id})에 재접속을 시도합니다...", Colors.INFO))

    try:
        if service_type == 'ec2':
            ec2 = manager.session.client('ec2', region_name=region)
            resp = ec2.describe_instances(InstanceIds=[instance_id])
            if not resp.get('Reservations'):
                print(colored_text(f"❌ 인스턴스 {instance_id}를 찾을 수 없습니다.", Colors.ERROR))
                return
            instance = resp['Reservations'][0]['Instances'][0]
            if instance['State']['Name'] != 'running':
                print(colored_text(f"❌ 인스턴스가 실행 중이 아닙니다. 상태: {instance['State']['Name']}", Colors.ERROR))
                return
            if instance.get('PlatformDetails', 'Linux').lower().startswith('windows'):
                local_port = calculate_local_port(instance_id)
                print(colored_text(f"(info) Windows 인스턴스 RDP 연결을 시작합니다 (localhost:{local_port})...", Colors.INFO))
                proc = start_port_forward(manager.profile, region, instance_id, local_port)
                launch_rdp(local_port)
                print("(info) RDP 창을 닫은 후, 이 터미널로 돌아와 Enter를 누르면 RDP 연결이 종료됩니다.")
                input("\n[Press Enter to terminate RDP connection]...\n")
                proc.terminate()
                print(colored_text("🔌 RDP 포트 포워딩 연결을 종료했습니다.", Colors.SUCCESS))
            else:
                print(colored_text("(info) Linux 인스턴스 SSM 연결을 시작합니다...", Colors.INFO))
                launch_linux_wt(manager.profile, region, instance_id)
                print(colored_text("✅ 새 터미널에서 SSM 세션이 시작되었습니다.", Colors.SUCCESS))

        elif service_type == 'rds':
            rds = manager.session.client('rds', region_name=region)
            dbs = rds.describe_db_instances(DBInstanceIdentifier=instance_id).get('DBInstances', [])
            if not dbs:
                print(colored_text(f"❌ RDS 인스턴스 {instance_id}를 찾을 수 없습니다.", Colors.ERROR))
                return
            db = dbs[0]
            db_user, db_password = get_db_credentials()
            if not db_user or not db_password:
                return
            tgt = choose_jump_host(manager, region)
            if not tgt:
                return
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
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            time.sleep(Config.WAIT_PORT_READY)
            db_tool = Config.DB_TOOL_PATH
            if db_tool and Path(db_tool).exists():
                network_type_map = {
                    'postgres': 'postgresql', 'mysql': 'mysql',
                    'mariadb': 'mariadb', 'sqlserver': 'mssql',
                }
                network_type = next((v for k, v in network_type_map.items() if k in db['Engine']), 'mysql')
                command = [
                    db_tool, f"--description={db['DBInstanceIdentifier']}", f"-n={network_type}",
                    "-h=localhost", f"-P={local_port}", f"-u={db_user}", f"-p={db_password}",
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
            ec_client = manager.session.client('elasticache', region_name=region)
            clusters = ec_client.describe_cache_clusters(
                CacheClusterId=instance_id, ShowCacheNodeInfo=True
            ).get('CacheClusters', [])
            if not clusters:
                print(colored_text(f"❌ ElastiCache 클러스터 {instance_id}를 찾을 수 없습니다.", Colors.ERROR))
                return
            cluster = clusters[0]
            ep = cluster.get('ConfigurationEndpoint') or (
                cluster.get('CacheNodes')[0].get('Endpoint') if cluster.get('CacheNodes') else {}
            )
            tgt = choose_jump_host(manager, region)
            if not tgt:
                return
            local_port = 12000
            print(colored_text(f"🔹 포트 포워딩: [localhost:{local_port}] -> [{cluster['CacheClusterId']}:{ep.get('Port', 0)}]", Colors.INFO))
            params_dict = {
                "host": [ep.get('Address', '')],
                "portNumber": [str(ep.get('Port', 0))],
                "localPortNumber": [str(local_port)]
            }
            params = json.dumps(params_dict)
            proc = subprocess.Popen(
                create_ssm_forward_command(manager.profile, region, tgt, 'AWS-StartPortForwardingSessionToRemoteHost', params),
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            time.sleep(Config.WAIT_PORT_READY)
            print(colored_text("✅ 포트 포워딩이 활성화되었습니다.", Colors.SUCCESS))
            print(f"   Engine: {cluster['Engine']}")
            print(f"   Address: localhost:{local_port}")
            try:
                tool = Config.CACHE_REDIS_CLI if cluster['Engine'].startswith('redis') else Config.CACHE_MEMCACHED_CLI
                args = [tool, '-h', '127.0.0.1', '-p', str(local_port)] if 'redis' in tool else [tool, '127.0.0.1', str(local_port)]
                launch_terminal_session(args)
                print(colored_text("✅ 로컬 클라이언트가 새 터미널 탭에서 실행되었습니다.", Colors.SUCCESS))
            except Exception as e:
                logging.warning(f"캐시 클라이언트 실행 실패: {e}")
            print("(완료되면 이 창에서 Enter 키를 눌러 연결을 종료합니다)")
            input("[Press Enter to terminate connection]...\n")
            proc.terminate()
            print(colored_text("🔌 포트 포워딩 연결을 종료했습니다.", Colors.SUCCESS))

        elif service_type == 'ecs':
            print(colored_text(f"🐳 ECS 컨테이너 {instance_name}에 재접속합니다...", Colors.INFO))
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


def show_main_help() -> None:
    print(colored_text(MENU_HELP['main'], Colors.INFO))


def main() -> None:
    os.system('clear')

    if not IS_MAC:
        print(colored_text("❌ 이 스크립트는 macOS 전용입니다.", Colors.ERROR))
        print(colored_text("   Windows/Linux용 버전을 사용해주세요.", Colors.INFO))
        sys.exit(1)

    parser = argparse.ArgumentParser(
        description='AWS EC2/RDS/ElastiCache/ECS/EKS 연결 도구 v5.5.0 (macOS)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
사용 예시:
  %(prog)s                           # 대화형 모드
  %(prog)s -p myprofile              # 특정 프로파일 사용
  %(prog)s -r ap-northeast-2         # 특정 리전 선택
  %(prog)s -s ec2                    # EC2 메뉴 직접 진입
  %(prog)s --no-cache                # 캐시 비활성화

지원 서비스: EC2, RDS, ElastiCache, ECS, EKS
'''
    )
    parser.add_argument('-p', '--profile', help='AWS 프로파일 이름')
    parser.add_argument('-d', '--debug', action='store_true', help='디버그 모드')
    parser.add_argument('-r', '--region', help='AWS 리전 이름')
    parser.add_argument('-s', '--service',
                        choices=['ec2', 'rds', 'cache', 'ecs', 'eks', 'cloudwatch', 'lambda', 's3'],
                        help='직접 진입할 서비스')
    parser.add_argument('--no-cache', action='store_true', help='캐시 비활성화')
    parser.add_argument('-v', '--version', action='version', version='%(prog)s v5.5.0')
    args = parser.parse_args()

    if args.no_cache:
        Config.CACHE_TTL_SECONDS = 0
        for key in Config.CACHE_TTLS:
            Config.CACHE_TTLS[key] = 0
        print(colored_text("ℹ️ 캐시가 비활성화되었습니다.", Colors.INFO))

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

            if args.service:
                service = args.service
                args.service = None
                if service == 'ec2':
                    ec2_menu(manager, region)
                elif service == 'rds':
                    connect_to_rds(manager, Config.DB_TOOL_PATH, region)
                elif service == 'cache':
                    connect_to_cache(manager, region)
                elif service == 'ecs':
                    ecs_menu(manager, region)
                elif service == 'eks':
                    eks_menu(manager, region)
                elif service == 'cloudwatch':
                    cloudwatch_menu(manager, region)
                elif service == 'lambda':
                    lambda_menu(manager, region)
                elif service == 's3':
                    s3_browser_menu(manager, region)
                continue

            while True:
                region_display = "All Regions" if region == 'multi-region' else region
                menu_items = [
                    "🖥️ EC2 인스턴스 연결 (배치 작업 지원)",
                    "🗄️ RDS 데이터베이스 연결",
                    "⚡ ElastiCache 클러스터 연결",
                    "🐳 ECS 컨테이너 연결",
                    "☸️ EKS 클러스터 관리",
                    "🌐 CloudShell 브라우저에서 열기",
                    "📊 CloudWatch 모니터링",
                    "λ  Lambda 함수 관리",
                    "📦 S3 버킷 브라우저",
                    "📚 최근 연결 기록",
                    "❓ 도움말",
                ]
                if _stored_credentials:
                    menu_items.append("🗑️ 저장된 DB 자격증명 삭제")
                menu_items.append("🔄 리전 재선택")
                menu_items.append("🚪 종료")

                title = f"Main Menu  │  Profile: {profile}  │  Region: {region_display}"
                footer = "↑↓/jk: 이동  Enter: 선택  q: 종료  /: 검색"
                selected = interactive_select(menu_items, title=title, footer=footer)

                has_creds = bool(_stored_credentials)

                if selected == -1 or selected == len(menu_items) - 1:
                    sys.exit(0)
                elif selected == 0:
                    ec2_menu(manager, region)
                elif selected == 1:
                    connect_to_rds(manager, Config.DB_TOOL_PATH, region)
                elif selected == 2:
                    connect_to_cache(manager, region)
                elif selected == 3:
                    ecs_menu(manager, region)
                elif selected == 4:
                    eks_menu(manager, region)
                elif selected == 5:
                    cloudshell_region = region if region != 'multi-region' else 'ap-northeast-2'
                    open_cloudshell_browser(cloudshell_region)
                elif selected == 6:
                    cloudwatch_menu(manager, region)
                elif selected == 7:
                    lambda_menu(manager, region)
                elif selected == 8:
                    s3_browser_menu(manager, region)
                elif selected == 9:
                    recent = show_recent_connections()
                    if recent:
                        temp_manager = AWSManager(recent['profile'])
                        reconnect_to_instance(temp_manager, recent)
                elif selected == 10:
                    show_main_help()
                elif has_creds and selected == 11:
                    clear_stored_credentials()
                elif (has_creds and selected == 12) or (not has_creds and selected == 11):
                    break

    finally:
        _stored_credentials.clear()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print(colored_text("\n\n사용자 요청으로 프로그램을 종료합니다.", Colors.INFO))
        _stored_credentials.clear()
        sys.exit(0)
    except Exception as e:
        logging.error(f"예상치 못한 오류 발생: {e}", exc_info=True)
        _stored_credentials.clear()
        sys.exit(1)
