#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EC2, RDS, ElastiCache 접속 자동화 스크립트 v5.0.1

새로운 기능:
- DB 비밀번호 세션 중 임시 저장 (메모리에만 저장, 스크립트 종료 시 삭제)
- 멀티 리전 통합 뷰 지원 (여러 리전의 인스턴스를 한 번에 조회)
- 연결 히스토리 기능 (최근 접속한 인스턴스 기록 및 빠른 재접속)

기존 기능 유지:
- v4.40에서 실수로 변경되었던 리눅스 인스턴스 접속 로직(`launch_linux_wt`)
  WSL을 정상적으로 호출하도록 이전 버전(v4.39)으로 복원.
- 로깅 오류 수정 사항은 그대로 유지.
- f-string 문법 오류 수정 (json.dumps 사용)
- RDS/ElastiCache 점프 호스트 선택 시 Role=jumphost 태그가 있는 EC2만 자동으로 표시
  점프 호스트로 사용할 EC2에 'Role=jumphost' 태그를 미리 추가해두세요
"""
import os
import sys
import argparse
import configparser
import concurrent.futures
import logging
import readline
import shutil
import subprocess
import time
from pathlib import Path
import getpass
import json
from datetime import datetime, timedelta

import boto3
from botocore.exceptions import ClientError, ProfileNotFound, NoCredentialsError

# ----------------------------------------------------------------------------
# WSL 환경 감지 및 경로 변환 함수 (v4.22 원본)
# ----------------------------------------------------------------------------
def is_running_in_wsl():
    """스크립트가 WSL 환경에서 실행 중인지 확인합니다."""
    return 'WSL_DISTRO_NAME' in os.environ or (
        os.path.exists('/proc/version') and 'microsoft' in open('/proc/version').read().lower()
    )

def get_platform_specific_path(win_path):
    """WSL 환경일 경우 Windows 경로를 WSL 경로로 변환합니다."""
    if is_running_in_wsl() and win_path and ':' in win_path:
        drive = win_path[0].lower()
        path = win_path[2:].replace('\\', '/')
        return f"/mnt/{drive}{path}"
    return win_path

# ----------------------------------------------------------------------------
# 설정 및 기본값 (v5.0.1 확장)
# ----------------------------------------------------------------------------
AWS_CONFIG_PATH          = Path("~/.aws/config").expanduser()
AWS_CRED_PATH            = Path("~/.aws/credentials").expanduser()
LOG_PATH                 = Path.home() / "ec2menu.log"
HISTORY_PATH             = Path.home() / ".ec2menu_history.json"
DEFAULT_WORKERS          = 10

WIN_HEIDISQL_PATH        = "C:\\Program Files\\HeidiSQL\\heidisql.exe"
DEFAULT_HEIDISQL_PATH    = get_platform_specific_path(os.environ.get('HEIDISQL_PATH', WIN_HEIDISQL_PATH))
DEFAULT_DB_TOOL_PATH     = DEFAULT_HEIDISQL_PATH

DEFAULT_CACHE_REDIS_CLI  = os.environ.get('CACHE_REDIS_CLI', "redis-cli")
DEFAULT_CACHE_MEMCACHED_CLI = os.environ.get('CACHE_MEMCACHED_CLI', "telnet")

# 전역 변수 - DB 비밀번호 임시 저장
_stored_credentials = {}

# ----------------------------------------------------------------------------
# 로거 설정 (v4.40 수정)
# ----------------------------------------------------------------------------
def setup_logger(debug: bool):
    level = logging.DEBUG if debug else logging.INFO
    fmt   = "%(asctime)s [%(levelname)s] %(message)s"
    handlers = [logging.StreamHandler(sys.stdout), logging.FileHandler(LOG_PATH, encoding="utf-8")]
    # style='%'를 명시하여 boto3 내부 로그와의 충돌 방지
    logging.basicConfig(level=level, format=fmt, handlers=handlers, style='%')

# ----------------------------------------------------------------------------
# 히스토리 관리 (v5.0.1 신규)
# ----------------------------------------------------------------------------
def load_history():
    """연결 히스토리를 로드합니다."""
    try:
        if HISTORY_PATH.exists():
            with open(HISTORY_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logging.warning(f"히스토리 로드 실패: {e}")
    return {"ec2": [], "rds": [], "cache": []}

def save_history(history):
    """연결 히스토리를 저장합니다."""
    try:
        with open(HISTORY_PATH, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.warning(f"히스토리 저장 실패: {e}")

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
# DB 자격 증명 관리 (v5.0.1 신규)
# ----------------------------------------------------------------------------
def get_db_credentials(db_user_hint=""):
    """DB 자격 증명을 가져옵니다. 저장된 것이 있으면 재사용 옵션 제공."""
    global _stored_credentials
    
    # 저장된 자격 증명이 있는지 확인
    if _stored_credentials:
        print(f"\n💾 저장된 DB 자격 증명이 있습니다.")
        use_stored = input("저장된 자격 증명을 사용하시겠습니까? (Y/n): ").strip().lower()
        if use_stored != 'n':
            return _stored_credentials['user'], _stored_credentials['password']
    
    print("\nℹ️ 데이터베이스에 연결할 사용자 정보를 입력하세요.")
    try:
        db_user = input(f"   DB 사용자 이름{f' ({db_user_hint})' if db_user_hint else ''}: ") or db_user_hint
        db_password = getpass.getpass("   DB 비밀번호 (입력 시 보이지 않음): ")
    except (EOFError, KeyboardInterrupt):
        print("\n입력이 중단되었습니다.")
        return None, None
        
    if not db_user or not db_password:
        print("❌ 사용자 이름과 비밀번호를 모두 입력해야 합니다.")
        return None, None
    
    # 자격 증명 저장 여부 확인
    save_creds = input("이 세션 동안 자격 증명을 저장하시겠습니까? (Y/n): ").strip().lower()
    if save_creds != 'n':
        _stored_credentials['user'] = db_user
        _stored_credentials['password'] = db_password
        print("✅ 자격 증명이 메모리에 저장되었습니다. (스크립트 종료 시 자동 삭제)")
    
    return db_user, db_password

def clear_stored_credentials():
    """저장된 자격 증명을 삭제합니다."""
    global _stored_credentials
    _stored_credentials.clear()
    print("🗑️ 저장된 자격 증명을 삭제했습니다.")

# ----------------------------------------------------------------------------
# AWS 호출 모듈 (v5.0.1 확장)
# ----------------------------------------------------------------------------
class AWSManager:
    def __init__(self, profile: str, max_workers: int = DEFAULT_WORKERS):
        try:
            self.session = boto3.Session(profile_name=profile)
        except ProfileNotFound as e:
            print(f"❌ AWS 프로파일 오류: {e}")
            sys.exit(1)
        self.profile     = profile
        self.max_workers = max_workers

    def list_regions(self):
        try:
            ec2  = self.session.client('ec2')
            resp = ec2.describe_regions(AllRegions=False)
            return [r['RegionName'] for r in resp.get('Regions', [])]
        except (ClientError, NoCredentialsError) as e:
            print(f"❌ AWS 호출 실패 (describe_regions): {e}")
            return []

    def list_instances(self, region: str):
        try:
            ec2 = self.session.client('ec2', region_name=region)
            resp = ec2.describe_instances(
                Filters=[{'Name':'instance-state-name','Values':['running']}]
            )
            insts = []
            for res in resp.get('Reservations', []):
                for i in res.get('Instances', []):
                    insts.append(i)
            return insts
        except ClientError as e:
            logging.error(f"AWS list_instances 실패({region}): {e}")
            return []

    def list_instances_multi_region(self, regions: list):
        """여러 리전의 인스턴스를 병렬로 가져옵니다."""
        all_instances = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            future_to_region = {ex.submit(self.list_instances, region): region for region in regions}
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

    def list_ssm_managed(self, region: str, jump_host_tags: dict = None):
        try:
            ssm = self.session.client('ssm', region_name=region)
            info = ssm.describe_instance_information().get('InstanceInformationList', [])
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
            
            return sorted(ssm_instances, key=lambda x: x['Name'])
        except ClientError as e:
            print(f"❌ AWS 호출 실패 (list_ssm_managed): {e}")
            return []

    def get_rds_endpoints(self, region: str):
        try:
            rds = self.session.client('rds', region_name=region)
            dbs = rds.describe_db_instances().get('DBInstances', [])
            return [
                {
                    'Id':       d['DBInstanceIdentifier'],
                    'Engine':   d['Engine'],
                    'Endpoint': d['Endpoint']['Address'],
                    'Port':     d['Endpoint']['Port'],
                    'DBName':   d.get('DBName')
                }
                for d in dbs
            ]
        except ClientError as e:
            print(f"❌ AWS 호출 실패 (describe_db_instances): {e}")
            return []

    def get_rds_endpoints_multi_region(self, regions: list):
        """여러 리전의 RDS를 병렬로 가져옵니다."""
        all_dbs = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            future_to_region = {ex.submit(self.get_rds_endpoints, region): region for region in regions}
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

    def list_cache_clusters(self, region: str):
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
            return result
        except ClientError as e:
            print(f"❌ AWS 호출 실패 (describe_cache_clusters): {e}")
            return []

    def list_cache_clusters_multi_region(self, regions: list):
        """여러 리전의 ElastiCache를 병렬로 가져옵니다."""
        all_clusters = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            future_to_region = {ex.submit(self.list_cache_clusters, region): region for region in regions}
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

# ----------------------------------------------------------------------------
# 공통 선택 기능 (v5.0.1 확장)
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

def choose_profile():
    lst = list_profiles()
    if not lst:
        print("❌ AWS 프로파일이 없습니다. ~/.aws/config 또는 ~/.aws/credentials 파일을 확인하세요.")
        sys.exit(1)
    
    print("\n--- [ AWS Profiles ] ---")
    for i, p in enumerate(lst, 1):
        print(f" {i:2d}) {p}")
    print("------------------------\n")

    while True:
        sel = input("사용할 프로파일 번호 입력 (Enter=종료): ").strip()
        if not sel:
            sys.exit(0)
        if sel.isdigit() and 1 <= int(sel) <= len(lst):
            return lst[int(sel) - 1]
        print("❌ 올바른 번호를 입력하세요.")

def choose_region(manager: AWSManager):
    regs = manager.list_regions()
    valid = []
    print("\n⏳ EC2 인스턴스가 있는 리전을 검색 중입니다. 잠시만 기다려주세요...")
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
        print("\n⚠ EC2 인스턴스가 있는 리전이 없습니다. (활성화된 리전이 없거나, 모든 리전에 실행중인 인스턴스가 없습니다)")
        return None

    print("\n--- [ AWS Regions with EC2 ] ---")
    valid_sorted = sorted(valid)
    for i, r in enumerate(valid_sorted, 1):
        print(f" {i:2d}) {r}")
    print(" 99) 🌏 모든 리전 통합 뷰")
    print("--------------------------------\n")

    while True:
        sel = input("사용할 리전 번호 입력 (Enter=뒤로): ").strip()
        if not sel:
            return None
        if sel == '99':
            return 'multi-region'
        if sel.isdigit() and 1 <= int(sel) <= len(valid_sorted):
            return valid_sorted[int(sel) - 1]
        print("❌ 올바른 번호를 입력하세요.")

def choose_jump_host(manager, region):
    """사용자에게 SSM 관리 인스턴스(Jump Host)를 선택하게 합니다. Role=jumphost 태그가 있는 EC2만 표시합니다."""
    # Role=jumphost 태그가 있는 SSM 인스턴스만 가져오기
    jump_host_tags = {"Role": "jumphost"}
    ssm_targets = manager.list_ssm_managed(region, jump_host_tags)
    
    if not ssm_targets:
        print("⚠ Role=jumphost 태그가 있는 SSM 관리 인스턴스가 없습니다.")
        print("   점프 호스트로 사용할 EC2에 'Role=jumphost' 태그를 추가해주세요.")
        return None
    
    if len(ssm_targets) == 1:
        print(f"\n(info) 유일한 Jump Host '{ssm_targets[0]['Name']} ({ssm_targets[0]['Id']})'를 사용합니다.")
        return ssm_targets[0]['Id']

    print("\n--- [ Select Jump Host (Role=jumphost) ] ---")
    for i, target in enumerate(ssm_targets, 1):
        print(f" {i:2d}) {target['Name']} ({target['Id']})")
    print("--------------------------------------------\n")
    
    while True:
        sel = input("사용할 Jump Host 번호 입력: ").strip()
        if sel.isdigit() and 1 <= int(sel) <= len(ssm_targets):
            return ssm_targets[int(sel) - 1]['Id']
        print("❌ 올바른 번호를 입력하세요.")

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
        print("\n⚠ 최근 연결 기록이 없습니다.")
        return None
    
    print("\n--- [ Recent Connections ] ---")
    for i, entry in enumerate(all_recent[:10], 1):  # 최대 10개
        service_icon = {"ec2": "🖥️", "rds": "🗄️", "cache": "⚡"}.get(entry['service_type'], "📦")
        timestamp = datetime.fromisoformat(entry['timestamp']).strftime('%m-%d %H:%M')
        print(f" {i:2d}) {service_icon} {entry['instance_name']} ({entry['instance_id']}) [{entry['region']}] - {timestamp}")
    print("------------------------------\n")
    
    while True:
        sel = input("재접속할 항목 번호 입력 (Enter=뒤로): ").strip()
        if not sel:
            return None
        if sel.isdigit() and 1 <= int(sel) <= len(all_recent[:10]):
            return all_recent[int(sel) - 1]
        print("❌ 올바른 번호를 입력하세요.")

def reconnect_to_instance(manager: AWSManager, entry: dict):
    """히스토리 항목에 따라 직접 인스턴스에 재접속합니다."""
    service_type = entry['service_type']
    region = entry['region']
    instance_id = entry['instance_id']
    instance_name = entry['instance_name']
    
    print(f"\n🔄 {instance_name}({instance_id})에 재접속을 시도합니다...")
    
    try:
        if service_type == 'ec2':
            # EC2 재접속
            ec2 = manager.session.client('ec2', region_name=region)
            resp = ec2.describe_instances(InstanceIds=[instance_id])
            
            if not resp.get('Reservations'):
                print(f"❌ 인스턴스 {instance_id}를 찾을 수 없습니다.")
                return
            
            instance = resp['Reservations'][0]['Instances'][0]
            
            if instance['State']['Name'] != 'running':
                print(f"❌ 인스턴스가 실행 중이 아닙니다. 상태: {instance['State']['Name']}")
                return
            
            # Windows/Linux 판단하여 접속
            if instance.get('PlatformDetails', 'Linux').lower().startswith('windows'):
                # Windows RDP 접속
                local_port = 10000 + (int(instance_id[-3:], 16) % 1000)
                print(f"(info) Windows 인스턴스 RDP 연결을 시작합니다 (localhost:{local_port})...")
                
                proc = start_port_forward(manager.profile, region, instance_id, local_port)
                time.sleep(2)
                launch_rdp(local_port)
                
                print("(info) RDP 창을 닫은 후, 이 터미널로 돌아와 Enter를 누르면 RDP 연결이 종료됩니다.")
                input("\n[Press Enter to terminate RDP connection]...\n")
                proc.terminate()
                print("🔌 RDP 포트 포워딩 연결을 종료했습니다.")
            else:
                # Linux SSH 접속
                print("(info) Linux 인스턴스 SSM 연결을 시작합니다...")
                launch_linux_wt(manager.profile, region, instance_id)
                print("✅ 새 터미널에서 SSM 세션이 시작되었습니다.")
        
        elif service_type == 'rds':
            # RDS 재접속
            rds = manager.session.client('rds', region_name=region)
            dbs = rds.describe_db_instances(DBInstanceIdentifier=instance_id).get('DBInstances', [])
            
            if not dbs:
                print(f"❌ RDS 인스턴스 {instance_id}를 찾을 수 없습니다.")
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
            
            # 포트 포워딩 및 HeidiSQL 실행
            local_port = 11000
            print(f"🔹 포트 포워딩: [localhost:{local_port}] -> [{db['DBInstanceIdentifier']}:{db['Endpoint']['Port']}]")
            
            params_dict = {
                "host": [db["Endpoint"]["Address"]],
                "portNumber": [str(db["Endpoint"]["Port"])],
                "localPortNumber": [str(local_port)]
            }
            params = json.dumps(params_dict)
            proc = subprocess.Popen(
                create_ssm_forward_command(manager.profile, region, tgt, 'AWS-StartPortForwardingSessionToRemoteHost', params),
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            time.sleep(2)
            
            # HeidiSQL 실행
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
                print("✅ HeidiSQL이 실행되었습니다.")
            
            print("(완료되면 이 창에서 Enter 키를 눌러 연결을 종료합니다)")
            input("[Press Enter to terminate connection]...\n")
            proc.terminate()
            print("🔌 포트 포워딩 연결을 종료했습니다.")
        
        elif service_type == 'cache':
            # ElastiCache 재접속
            ec = manager.session.client('elasticache', region_name=region)
            clusters = ec.describe_cache_clusters(CacheClusterId=instance_id, ShowCacheNodeInfo=True).get('CacheClusters', [])
            
            if not clusters:
                print(f"❌ ElastiCache 클러스터 {instance_id}를 찾을 수 없습니다.")
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
            print(f"🔹 포트 포워딩: [localhost:{local_port}] -> [{cluster['CacheClusterId']}:{ep.get('Port',0)}]")
            
            params_dict = {
                "host": [ep.get('Address','')],
                "portNumber": [str(ep.get('Port',0))],
                "localPortNumber": [str(local_port)]
            }
            params = json.dumps(params_dict)
            proc = subprocess.Popen(
                create_ssm_forward_command(manager.profile, region, tgt, 'AWS-StartPortForwardingSessionToRemoteHost', params),
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            time.sleep(2)
            
            print(f"✅ 포트 포워딩이 활성화되었습니다.")
            print(f"   Engine: {cluster['Engine']}")
            print(f"   Address: localhost:{local_port}")
            
            # 클라이언트 실행 시도
            try:
                tool = DEFAULT_CACHE_REDIS_CLI if cluster['Engine'].startswith('redis') else DEFAULT_CACHE_MEMCACHED_CLI
                args = [tool, '-h', '127.0.0.1', '-p', str(local_port)] if 'redis' in tool else [tool, '127.0.0.1', str(local_port)]
                wt = find_windows_terminal()
                if wt:
                    subprocess.Popen([wt, 'new-tab', 'wsl.exe', '--', *args], stdin=subprocess.DEVNULL)
                    print("✅ 로컬 클라이언트가 새 창에서 실행되었습니다.")
                elif shutil.which(tool):
                    subprocess.Popen(args)
                    print("✅ 로컬 클라이언트가 실행되었습니다.")
            except Exception as e:
                logging.warning(f"캐시 클라이언트 실행 실패: {e}")
            
            print("(완료되면 이 창에서 Enter 키를 눌러 연결을 종료합니다)")
            input("[Press Enter to terminate connection]...\n")
            proc.terminate()
            print("🔌 포트 포워딩 연결을 종료했습니다.")
    
    except ClientError as e:
        print(f"❌ AWS 호출 실패: {e}")
    except Exception as e:
        print(f"❌ 재접속 실패: {e}")
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
        '--parameters', '{\\"command\\":[\\"bash -l\\"]}'
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

def launch_rdp(port):
    subprocess.Popen([
        "mstsc.exe", f"/v:localhost:{port}"
    ], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def find_windows_terminal():
    for name in ('wt.exe', 'wt'):
        path = shutil.which(name)
        if path:
            return path
    return None

def launch_linux_wt(profile, region, iid):
    """리눅스 인스턴스에 Windows Terminal 새 탭(wt.exe new-tab)으로 접속"""
    wt = find_windows_terminal()
    if not wt:
        print('[WARN] Windows Terminal(wt.exe) 경로를 찾을 수 없어 기본 쉘에서 실행합니다.')
        subprocess.run(ssm_cmd(profile, region, iid))
        return
    cmd = [wt, 'new-tab', 'wsl.exe', '--', *ssm_cmd(profile, region, iid)]
    subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

# ----------------------------------------------------------------------------
# EC2 메뉴 (v5.0.1 확장)
# ----------------------------------------------------------------------------
def ec2_menu(manager: AWSManager, region: str):
    procs = []
    try:
        while True:
            if region == 'multi-region':
                # 멀티 리전 모드
                regions = manager.list_regions()
                insts_raw = manager.list_instances_multi_region(regions)
                if not insts_raw:
                    print("\n⚠ 모든 리전에 실행 중인 EC2 인스턴스가 없습니다.")
                    break
                region_display = "All Regions"
            else:
                # 단일 리전 모드
                insts_raw = manager.list_instances(region)
                if not insts_raw:
                    print("\n⚠ 이 리전에는 실행 중인 EC2 인스턴스가 없습니다.")
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
            
            insts = sorted(insts_display, key=lambda x: (x['Region'], x['Name']))

            print("\n--- [ EC2 Instances ] ---")
            if region == 'multi-region':
                print(f" {'No':<3} {'Name':<25} {'Instance ID':<20} {'Region':<15} {'Type':<15} {'State':<10} {'OS':<15} {'Private IP':<16} {'Public IP':<16}")
                print("-" * 145)
            else:
                print(f" {'No':<3} {'Name':<25} {'Instance ID':<20} {'Type':<15} {'State':<10} {'OS':<15} {'Private IP':<16} {'Public IP':<16}")
                print("-" * 130)

            for idx, i_data in enumerate(insts, 1):
                i = i_data['raw']
                instance_type = i.get('InstanceType', '-')
                state = i['State']['Name']
                platform = i.get('PlatformDetails', 'Linux/UNIX')
                if region == 'multi-region':
                    print(f" {idx:<3} {i_data['Name']:<25} {i['InstanceId']:<20} {i_data['Region']:<15} {instance_type:<15} {state:<10} {platform:<15} {i_data['PrivateIp']:<16} {i_data['PublicIp']:<16}")
                else:
                    print(f" {idx:<3} {i_data['Name']:<25} {i['InstanceId']:<20} {instance_type:<15} {state:<10} {platform:<15} {i_data['PrivateIp']:<16} {i_data['PublicIp']:<16}")
            
            if region == 'multi-region':
                print("-" * 145)
            else:
                print("-" * 130)
            print(f"Profile: {manager.profile} | Region: {region_display}")

            sel = input("\n접속할 인스턴스 번호 입력 (r=새로고침, b=메인, 예: 1,2,3): ").strip().lower()
            if not sel or sel == 'b':
                break
            if sel == 'r':
                print("🔄 목록을 새로고침합니다...")
                continue

            try:
                choices = [int(x.strip()) for x in sel.split(',') if x.strip().isdigit()]
                valid_choices = [c for c in choices if 1 <= c <= len(insts)]
                if not valid_choices:
                    print("❌ 유효한 번호를 입력하세요.")
                    continue
            except ValueError:
                print("❌ 숫자와 쉼표만 입력하세요.")
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
                    print(f"\n(info) Windows 인스턴스 RDP 연결을 시작합니다 (localhost:{local_port})...")
                    
                    proc = start_port_forward(manager.profile, inst_region, inst['InstanceId'], local_port)
                    procs.append(proc)
                    time.sleep(2)
                    launch_rdp(local_port)
                else:
                    print(f"\n(info) Linux 인스턴스 SSM 연결을 시작합니다...")
                    launch_linux_wt(manager.profile, inst_region, inst['InstanceId'])
                    print("(info) 새 터미널에서 SSM 세션이 시작되었습니다. 이 창에서는 다른 작업을 계속할 수 있습니다.")
            
            if rdp_started:
                print("\n(info) RDP 창을 닫은 후, 이 터미널로 돌아와 Enter를 누르면 모든 RDP 연결이 종료됩니다.")
                input("\n[Press Enter to terminate all RDP connection processes]...\n")
                break 
            else:
                time.sleep(2)

    finally:
        if procs:
            for proc in procs:
                proc.terminate()
            print("🔌 모든 RDP 포트 포워딩 연결을 종료했습니다.")

# ----------------------------------------------------------------------------
# RDS 접속 (v5.0.1 확장)
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
            print(f"\n⚠ {region_display}에 RDS 인스턴스가 없습니다")
            return

        print(f"\n--- [ RDS Instances ({region_display}) ] ---")
        for idx, db in enumerate(dbs, 1):
            engine_display = db['Engine']
            if 'aurora-mysql' in engine_display: engine_display = 'aurora (mysql)'
            elif 'aurora-postgresql' in engine_display: engine_display = 'aurora (postgres)'
            
            if region == 'multi-region':
                print(f" {idx:2d}) {db['Id']} ({engine_display}) [{db['_region']}]")
            else:
                print(f" {idx:2d}) {db['Id']} ({engine_display})")
        print("---------------------------\n")

        sel = input("접속할 DB 번호 입력 (r=새로고침, b=뒤로, 예: 1,2,3): ").strip().lower()
        if not sel or sel == 'b': 
            return
        if sel == 'r':
            print("🔄 목록을 새로고침합니다...")
            continue

        try:
            choices = [int(x.strip()) for x in sel.split(',') if x.strip().isdigit()]
            valid_choices = [c for c in choices if 1 <= c <= len(dbs)]
            if not valid_choices:
                print("❌ 유효한 번호를 입력하세요.")
                continue
        except ValueError:
            print("❌ 숫자와 쉼표만 입력하세요.")
            continue

        # DB 자격 증명 가져오기
        db_user, db_password = get_db_credentials()
        if not db_user or not db_password:
            continue

        # 첫 번째 선택된 DB의 리전에서 점프 호스트 선택 (멀티 리전의 경우)
        target_region = dbs[valid_choices[0] - 1].get('_region', region)
        if region == 'multi-region':
            print(f"\n📍 리전 {target_region}에서 점프 호스트를 선택합니다.")
        
        tgt = choose_jump_host(manager, target_region)
        if not tgt:
            continue

        print(f"\n(info) SSM 인스턴스 '{tgt}'를 통해 포트 포워딩을 시작합니다.")

        procs = []
        try:
            for i, choice_idx in enumerate(valid_choices):
                db = dbs[choice_idx - 1]
                db_region = db.get('_region', region)
                local_port = 11000 + i
                print(f"🔹 포트 포워딩: [localhost:{local_port}] -> [{db['Id']}:{db['Port']}] ({db_region})")
                
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
            
            time.sleep(2)

            print("\n✅ 모든 포트 포워딩 활성화. HeidiSQL에 직접 연결합니다...")
            
            if tool_path and Path(tool_path).exists():
                for i, choice_idx in enumerate(valid_choices):
                    db = dbs[choice_idx - 1]
                    local_port = 11000 + i
                    network_type_map = {
                        'postgres': 'postgresql', 'mysql': 'mysql', 
                        'mariadb': 'mariadb', 'sqlserver': 'mssql',
                    }
                    network_type = next((v for k, v in network_type_map.items() if k in db['Engine']), 'mysql')

                    # 세션 이름을 DB ID로 지정하여 HeidiSQL에 표시
                    command = [
                        tool_path, f"--description={db['Id']}", f"-n={network_type}", f"-h=localhost",
                        f"-P={local_port}", f"-u={db_user}", f"-p={db_password}",
                    ]
                    if db.get('DBName'):
                        command.append(f"-d={db['DBName']}")

                    subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                print(f"❌ DB 도구 경로를 찾을 수 없습니다: {tool_path}")

            print("\n(완료되면 이 창에서 Enter 키를 눌러 연결을 모두 종료합니다)")
            input("[Press Enter to terminate all connections]...\n")
            break

        finally:
            if procs:
                for proc in procs:
                    proc.terminate()
                print("🔌 모든 포트 포워딩 연결을 종료했습니다.")
            
# ----------------------------------------------------------------------------
# ElastiCache 접속 (v5.0.1 확장)
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
            print(f"\n⚠ {region_display}에 ElastiCache 클러스터가 없습니다")
            time.sleep(1)
            break

        print(f"\n--- [ ElastiCache Clusters ({region_display}) ] ---")
        for idx, c in enumerate(clus, 1):
            if region == 'multi-region':
                print(f" {idx:2d}) {c['Id']} ({c['Engine']}) [{c['_region']}]")
            else:
                print(f" {idx:2d}) {c['Id']} ({c['Engine']})")
        print("--------------------------------\n")

        sel = input("접속할 클러스터 번호 입력 (r=새로고침, b=뒤로): ").strip().lower()
        if not sel or sel == 'b': 
            break
        if sel == 'r':
            print("🔄 목록을 새로고침합니다...")
            continue
        
        if not sel.isdigit() or not (1 <= int(sel) <= len(clus)):
            print("❌ 유효한 번호를 입력하세요.")
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
        
        print(f"\n(info) SSM 인스턴스 '{tgt}'를 통해 포트 포워딩을 시작합니다.")
        print(f"🔹 포트 포워딩: [localhost:{local_port}] -> [{c['Id']}:{c['Port']}] ({cache_region})")

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
            time.sleep(2)
            
            print("\n✅ 포트 포워딩이 활성화되었습니다. 클라이언트에서 아래 주소로 접속하세요.")
            print(f"   Engine: {c['Engine']}")
            print(f"   Address: localhost:{local_port}")
            
            tool_launched = False
            try:
                tool = DEFAULT_CACHE_REDIS_CLI if c['Engine'].startswith('redis') else DEFAULT_CACHE_MEMCACHED_CLI
                args = [tool, '-h', '127.0.0.1', '-p', str(local_port)] if 'redis' in tool else [tool, '127.0.0.1', str(local_port)]
                wt = find_windows_terminal()
                if wt:
                    subprocess.Popen([wt, 'new-tab', 'wsl.exe', '--', *args], stdin=subprocess.DEVNULL)
                    tool_launched = True
                elif shutil.which(tool):
                    subprocess.Popen(args)
                    tool_launched = True
            except Exception as e:
                logging.warning(f"캐시 클라이언트 실행 실패: {e}")
                
            if tool_launched:
                print("   (로컬 클라이언트가 새 창에서 실행되었습니다)")
                
            print("   (완료되면 이 창에서 Enter 키를 눌러 연결을 종료합니다)")
            input("\n[Press Enter to terminate the connection]...\n")
            break

        finally:
            if proc:
                proc.terminate()
            print("🔌 포트 포워딩 연결을 종료했습니다.")
            time.sleep(1)

# ----------------------------------------------------------------------------
# Main 흐름 (v5.0.1 확장)
# ----------------------------------------------------------------------------
def main():
    global _stored_credentials
    
    parser = argparse.ArgumentParser(description='AWS EC2/RDS/ElastiCache 연결 도구 v5.0.1')
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
                sel = input("프로파일을 다시 선택하시겠습니까? (y/N): ").strip().lower()
                if sel == 'y':
                    profile = choose_profile()
                    manager = AWSManager(profile)
                    continue
                else:
                    sys.exit(0)

            while True:
                region_display = "All Regions" if region == 'multi-region' else region
                print(f"\n--- [ Main Menu ] ---")
                print(f"Profile: {profile} | Region: {region_display}")
                print("---------------------")
                print(" 1) EC2 인스턴스 연결")
                print(" 2) RDS 데이터베이스 연결")
                print(" 3) ElastiCache 클러스터 연결")
                print(" h) 📚 최근 연결 기록")
                if _stored_credentials:
                    print(" c) 🗑️  저장된 DB 자격증명 삭제")
                print("---------------------")
                sel = input("선택 (b=리전 재선택, Enter=종료): ").strip().lower()

                if sel == '1':
                    ec2_menu(manager, region)
                elif sel == '2':
                    connect_to_rds(manager, DEFAULT_DB_TOOL_PATH, region)
                elif sel == '3':
                    connect_to_cache(manager, region)
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
                    print("❌ 잘못된 선택입니다.")
    
    finally:
        # 프로그램 종료 시 저장된 자격 증명 삭제
        _stored_credentials.clear()

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n사용자 요청으로 프로그램을 종료합니다.")
        # 프로그램 종료 시 저장된 자격 증명 삭제
        _stored_credentials.clear()
        sys.exit(0)
    except Exception as e:
        logging.error(f"예상치 못한 오류 발생: {e}", exc_info=True)
        # 프로그램 종료 시 저장된 자격 증명 삭제
        _stored_credentials.clear()
        sys.exit(1)