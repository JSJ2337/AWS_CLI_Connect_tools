#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EC2, RDS, ElastiCache 접속 자동화 스크립트 v4.3 개선판

- EC2 인스턴스가 있는 리전만 선택하도록 필터링
- ssm_cmd에서 `target` 키워드 지원 및 RDS/Cache 포트 포워딩을 SSM 관리 인스턴스를 통해 수행
- 기존 기능 유지 및 사용성 강화
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
import socket
import time
from pathlib import Path

import boto3
from botocore.exceptions import ClientError, ProfileNotFound, NoCredentialsError

# ----------------------------------------------------------------------------
# 설정 및 기본값
# ----------------------------------------------------------------------------
AWS_CONFIG_PATH = Path("~/.aws/config").expanduser()
AWS_CRED_PATH   = Path("~/.aws/credentials").expanduser()
LOG_PATH        = Path.home() / "ec2menu.log"
DEFAULT_WORKERS = 10

DEFAULT_DB_TOOL_PATH        = os.environ.get('DB_TOOL_PATH', "/mnt/c/Program Files/DBeaver/dbeaver.exe")
DEFAULT_CACHE_REDIS_CLI     = os.environ.get('CACHE_REDIS_CLI', "redis-cli")
DEFAULT_CACHE_MEMCACHED_CLI = os.environ.get('CACHE_MEMCACHED_CLI', "telnet")

# ----------------------------------------------------------------------------
# 로거 설정
# ----------------------------------------------------------------------------
def setup_logger(debug: bool):
    level = logging.DEBUG if debug else logging.INFO
    fmt   = "%(asctime)s [%(levelname)s] %(message)s"
    handlers = [logging.StreamHandler(sys.stdout), logging.FileHandler(LOG_PATH, encoding="utf-8")]
    logging.basicConfig(level=level, format=fmt, handlers=handlers)

# ----------------------------------------------------------------------------
# AWS 호출 모듈
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

    def list_ssm_managed(self, region: str):
        try:
            ssm = self.session.client('ssm', region_name=region)
            info = ssm.describe_instance_information().get('InstanceInformationList', [])
            return [i['InstanceId'] for i in info]
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
                    'Port':     d['Endpoint']['Port']
                }
                for d in dbs
            ]
        except ClientError as e:
            print(f"❌ AWS 호출 실패 (describe_db_instances): {e}")
            return []

    def list_cache_clusters(self, region: str):
        try:
            ec = self.session.client('elasticache', region_name=region)
            clus = ec.describe_cache_clusters(ShowCacheNodeInfo=True).get('CacheClusters', [])
            result = []
            for c in clus:
                ep = c.get('ConfigurationEndpoint') or c.get('Endpoint') or (
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

# ----------------------------------------------------------------------------
# 공통 선택 기능
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
    # EC2 인스턴스가 있는 리전만 필터링
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
    print("--------------------------------\n")

    while True:
        sel = input("사용할 리전 번호 입력 (Enter=뒤로): ").strip()
        if not sel:
            return None
        if sel.isdigit() and 1 <= int(sel) <= len(valid_sorted):
            return valid_sorted[int(sel) - 1]
        print("❌ 올바른 번호를 입력하세요.")

# ----------------------------------------------------------------------------
# SSM 호출 함수 (target 지원)
# ----------------------------------------------------------------------------
def ssm_cmd(profile, region, iid=None, doc='AWS-StartInteractiveCommand', params='{"command":["bash -l"]}', target=None):
    cmd = ['aws', 'ssm', 'start-session', '--region', region]
    if profile:
        cmd += ['--profile', profile]
    
    tgt = target or iid
    if tgt:
        cmd += ['--target', tgt]
    
    cmd += ['--document-name', doc, '--parameters', params]
    return cmd


def start_port_forward(profile, region, instance_id, local_port, remote_port=3389):
    params = f'{{"portNumber":["{remote_port}"],"localPortNumber":["{local_port}"]}}'
    return subprocess.Popen(
        ssm_cmd(profile, region, iid=instance_id, doc='AWS-StartPortForwardingSession', params=params),
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )


def launch_rdp(local_port):
    subprocess.Popen(['mstsc.exe', f'/v:localhost:{local_port}'], stdin=subprocess.DEVNULL)


def launch_linux_wt(profile, region, iid):
    cmd = ssm_cmd(profile, region, iid=iid)
    wt  = shutil.which('wt.exe') or shutil.which('wt')
    if wt:
        subprocess.Popen([wt,'new-tab','wsl.exe','--',*cmd], stdin=subprocess.DEVNULL)
    else:
        subprocess.run(cmd)

# ----------------------------------------------------------------------------
# EC2 메뉴
# ----------------------------------------------------------------------------
def ec2_menu(manager: AWSManager, region: str):
    insts_raw = manager.list_instances(region)
    if not insts_raw:
        print("\n⚠ 이 리전에는 실행 중인 EC2 인스턴스가 없습니다.")
        return

    # 이름, Public IP, Private IP 추출 및 정렬
    insts_display = []
    for i in insts_raw:
        name = next((t['Value'] for t in i.get('Tags', []) if t['Key'] == 'Name'), '')
        insts_display.append({
            'raw': i,
            'Name': name,
            'PublicIp': i.get('PublicIpAddress', '-'),
            'PrivateIp': i.get('PrivateIpAddress', '-'),
        })
    
    insts = sorted(insts_display, key=lambda x: x['Name'])

    print("\n--- [ EC2 Instances ] ---")
    # 헤더 출력
    print(f" {'No':<3} {'Name':<25} {'Instance ID':<20} {'Type':<15} {'State':<10} {'OS':<15} {'Public IP':<16} {'Private IP':<16}")
    print("-" * 130)

    for idx, i_data in enumerate(insts, 1):
        i = i_data['raw']
        instance_type = i.get('InstanceType', '-')
        state = i['State']['Name']
        platform = i.get('PlatformDetails', 'Linux/UNIX')
        print(f" {idx:<3} {i_data['Name']:<25} {i['InstanceId']:<20} {instance_type:<15} {state:<10} {platform:<15} {i_data['PublicIp']:<16} {i_data['PrivateIp']:<16}")
    print("-" * 130)

    sel = input("\n접속할 인스턴스 번호 입력 (b=뒤로): ").strip().lower()
    if not sel or sel == 'b':
        return
    if not sel.isdigit() or not (1 <= int(sel) <= len(insts)):
        print("❌ 올바른 번호를 입력하세요.")
        return

    inst = insts[int(sel) - 1]['raw'] # 정렬된 목록에서 원래 인스턴스 정보 추출
    if inst.get('PlatformDetails', 'Linux').lower().startswith('windows'):
        local_port = 10000 + (int(inst['InstanceId'][-3:], 16) % 1000)
        print(f"\n(info) Windows 인스턴스 RDP 연결을 시작합니다 (localhost:{local_port})...")
        proc = start_port_forward(manager.profile, region, inst['InstanceId'], local_port)
        time.sleep(2)  # 포트가 열릴 때까지 잠시 대기
        launch_rdp(local_port)
        proc.terminate() # RDP 클라이언트 실행 후 바로 종료 (세션 유지 불필요)
    else:
        print(f"\n(info) Linux 인스턴스 SSM 연결을 시작합니다...")
        launch_linux_wt(manager.profile, region, inst['InstanceId'])

# ----------------------------------------------------------------------------
# RDS 접속
# ----------------------------------------------------------------------------
def connect_to_rds(manager: AWSManager, db_path: str, region: str):
    dbs = manager.get_rds_endpoints(region)
    if not dbs:
        print("⚠ RDS 인스턴스가 없습니다")
        return

    print("\n--- [ RDS Instances ] ---")
    for idx, db in enumerate(dbs, 1):
        print(f" {idx:2d}) {db['Id']} ({db['Engine']})")
    print("---------------------------\n")

    sel = input("접속할 DB 번호 입력 (b=뒤로, 예: 1,2): ").strip().lower()
    if not sel or sel == 'b':
        return

    choices = [int(x) for x in sel.split(',') if x.isdigit() and 1 <= int(x) <= len(dbs)]
    if not choices:
        print("❌ 유효한 번호를 입력하세요.")
        return

    ssm_targets = manager.list_ssm_managed(region)
    if not ssm_targets:
        print("⚠ 포트 포워딩에 사용할 SSM 관리 인스턴스가 없습니다.")
        return
    
    # TODO: 사용자에게 SSM 타겟을 선택하도록 기능 개선 가능
    tgt = ssm_targets[0]
    print(f"\n(info) SSM 인스턴스 '{tgt}'를 통해 포트 포워딩을 시작합니다.")

    procs = []
    try:
        for i, choice_idx in enumerate(choices):
            db = dbs[choice_idx - 1]
            local_port = 11000 + i
            
            print(f"🔹 포트 포워딩: [localhost:{local_port}] -> [{db['Id']}:{db['Port']}]")
            
            params = f'{{"host":["{db["Endpoint"]}"],"portNumber":["{db["Port"]}"],"localPortNumber":["{local_port}"]}}'
            proc = subprocess.Popen(
                ssm_cmd(manager.profile, region, target=tgt, doc='AWS-StartPortForwardingSessionToRemoteHost', params=params),
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            procs.append(proc)
            
            # DB 툴 실행 (예: DBeaver)
            if db_path and Path(db_path).exists():
                # 이 부분은 DB 툴의 CLI 옵션에 따라 조정이 필요할 수 있습니다.
                # 지금은 바로 연결을 시도하지 않고, 포트만 열어두는 것에 집중합니다.
                pass

        print("\n✅ 포트 포워딩이 활성화되었습니다. DB 클라이언트에서 아래 주소로 접속하세요.")
        print("   (완료되면 이 창에서 Enter 키를 눌러 연결을 모두 종료합니다)")
        input("\n[Press Enter to terminate all connections]...\n")

    finally:
        for proc in procs:
            proc.terminate()
        print("🔌 모든 포트 포워딩 연결을 종료했습니다.")

# ----------------------------------------------------------------------------
# ElastiCache 접속
# ----------------------------------------------------------------------------
def connect_to_cache(manager: AWSManager, region: str):
    clus = manager.list_cache_clusters(region)
    if not clus:
        print("⚠ ElastiCache 클러스터가 없습니다")
        return

    print("\n--- [ ElastiCache Clusters ] ---")
    for idx, c in enumerate(clus, 1):
        print(f" {idx:2d}) {c['Id']} ({c['Engine']})")
    print("--------------------------------\n")

    sel = input("접속할 클러스터 번호 입력 (b=뒤로): ").strip().lower()
    if not sel or sel == 'b':
        return
    
    if not sel.isdigit() or not (1 <= int(sel) <= len(clus)):
        print("❌ 유효한 번호를 입력하세요.")
        return

    idx = int(sel) - 1
    c = clus[idx]

    ssm_targets = manager.list_ssm_managed(region)
    if not ssm_targets:
        print("⚠ 포트 포워딩에 사용할 SSM 관리 인스턴스가 없습니다.")
        return

    tgt = ssm_targets[0]
    local_port = 12000 + idx
    
    print(f"\n(info) SSM 인스턴스 '{tgt}'를 통해 포트 포워딩을 시작합니다.")
    print(f"🔹 포트 포워딩: [localhost:{local_port}] -> [{c['Id']}:{c['Port']}]")

    params = f'{{"host":["{c["Address"]}"],"portNumber":["{c["Port"]}"],"localPortNumber":["{local_port}"]}}'
    proc = None
    try:
        proc = subprocess.Popen(
            ssm_cmd(manager.profile, region, target=tgt, doc='AWS-StartPortForwardingSessionToRemoteHost', params=params),
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        
        print("\n✅ 포트 포워딩이 활성화되었습니다. 클라이언트에서 아래 주소로 접속하세요.")
        print(f"   Engine: {c['Engine']}")
        print(f"   Address: localhost:{local_port}")
        print("   (완료되면 이 창에서 Enter 키를 눌러 연결을 종료합니다)")
        
        # 로컬 클라이언트 자동 실행 (선택적)
        tool = DEFAULT_CACHE_REDIS_CLI if c['Engine'].startswith('redis') else DEFAULT_CACHE_MEMCACHED_CLI
        args = [tool, '-h', '127.0.0.1', '-p', str(local_port)] if 'redis' in tool else [tool, '127.0.0.1', str(local_port)]
        wt = shutil.which('wt.exe') or shutil.which('wt')
        if wt:
            subprocess.Popen([wt, 'new-tab', 'wsl.exe', '--', *args], stdin=subprocess.DEVNULL)
        else:
            subprocess.Popen(args)

        input("\n[Press Enter to terminate the connection]...\n")

    finally:
        if proc:
            proc.terminate()
        print("🔌 포트 포워딩 연결을 종료했습니다.")

# ----------------------------------------------------------------------------
# Main 흐름
# ----------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description='AWS EC2/RDS/ElastiCache 연결 도구 v4.6')
    parser.add_argument('-p', '--profile', help='AWS 프로파일 이름')
    parser.add_argument('-d', '--debug', action='store_true', help='디버그 모드')
    args = parser.parse_args()

    setup_logger(args.debug)
    profile = args.profile or choose_profile()
    manager = AWSManager(profile)

    while True:
        region = choose_region(manager)
        if not region:
            break
        
        print(f"\n--- [ Main Menu ] ---")
        print(f"Profile: {profile} | Region: {region}")
        print("---------------------")
        print(" 1) EC2 인스턴스 연결")
        print(" 2) RDS 데이터베이스 연결")
        print(" 3) ElastiCache 클러스터 연결")
        print("---------------------")
        sel = input("선택 (b=프로파일/리전 재선택, Enter=종료): ").strip().lower()

        if sel == '1':
            ec2_menu(manager, region)
        elif sel == '2':
            connect_to_rds(manager, DEFAULT_DB_TOOL_PATH, region)
        elif sel == '3':
            connect_to_cache(manager, region)
        elif sel == 'b':
            continue
        else:
            break

if __name__ == '__main__':
    main()