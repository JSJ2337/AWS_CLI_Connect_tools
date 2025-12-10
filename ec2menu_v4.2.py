#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EC2, RDS, ElastiCache 접속 자동화 스크립트 (WSL 최적화)

– EC2 접속 로직은 latest 버전과 동일하게 유지
– RDS 멀티 선택 지원 추가
– ElastiCache 접속 기능 추가 (SSM 포트포워딩 + redis-cli / telnet)
"""

import argparse
import configparser
import concurrent.futures
import logging
import readline
import shutil
import subprocess
import sys
import socket  # 포트 연결 확인용
import time
from pathlib import Path

import boto3
from botocore.exceptions import ProfileNotFound

# -----------------------------------------------------------------------------
# 설정 경로 및 툴 경로
# -----------------------------------------------------------------------------
AWS_CONFIG_PATH     = Path("~/.aws/config").expanduser()
AWS_CRED_PATH       = Path("~/.aws/credentials").expanduser()
LOG_PATH            = Path.home() / "ec2menu.log"
DB_TOOL_PATH        = "/mnt/c/Program Files/DBeaver/dbeaver.exe"  # WSL에서 실행할 DBeaver 경로
CACHE_REDIS_CLI     = "redis-cli"
CACHE_MEMCACHED_CLI = "telnet"

# -----------------------------------------------------------------------------
# 로깅 설정
# -----------------------------------------------------------------------------
def setup_logger(debug: bool):
    level = logging.DEBUG if debug else logging.INFO
    fmt   = "%(asctime)s [%(levelname)s] %(message)s"
    handlers = [logging.StreamHandler(sys.stdout), logging.FileHandler(LOG_PATH, encoding="utf-8")]
    logging.basicConfig(level=level, format=fmt, handlers=handlers)

# -----------------------------------------------------------------------------
# AWS 프로파일 조회 및 선택
# -----------------------------------------------------------------------------
def list_profiles():
    """AWS CLI 프로파일 목록 반환"""
    profiles = set()
    if AWS_CONFIG_PATH.exists():
        cfg = configparser.RawConfigParser()
        cfg.read(AWS_CONFIG_PATH)
        for sec in cfg.sections():
            if sec.startswith("profile "):
                profiles.add(sec.split(" ",1)[1])
            elif sec == "default":
                profiles.add("default")
    if AWS_CRED_PATH.exists():
        cred = configparser.RawConfigParser()
        cred.read(AWS_CRED_PATH)
        profiles.update(cred.sections())
    return sorted(profiles)


def choose_profile():
    """사용자에게 AWS 프로파일 선택 메뉴 표시"""
    profiles = list_profiles()
    if not profiles:
        print("❌ AWS 프로파일이 없습니다.")
        sys.exit(1)
    print("\n#  Profile")
    for idx, p in enumerate(profiles, 1):
        print(f" {idx:2d}) {p}")
    while True:
        sel = input("번호 입력 (취소=Enter): ").strip()
        if not sel:
            sys.exit(0)
        if sel.isdigit() and 1 <= int(sel) <= len(profiles):
            return profiles[int(sel)-1]
        print("❌ 올바른 번호를 입력하세요.")


def get_session(profile: str):
    """지정한 프로파일로 boto3 세션 생성"""
    try:
        return boto3.Session(profile_name=profile)
    except ProfileNotFound as e:
        print(f"프로파일 오류: {e}")
        sys.exit(1)

# -----------------------------------------------------------------------------
# EC2 접속 로직 (latest 기준 그대로)
# -----------------------------------------------------------------------------

def has_running(region, session):
    try:
        ec2r = session.client('ec2', region_name=region)
        resp = ec2r.describe_instances(
            Filters=[{'Name':'instance-state-name','Values':['running']}]
        )
        return region if any(r.get('Instances') for r in resp.get('Reservations',[])) else None
    except Exception:
        return None


def choose_region(session, profile, account):
    ec2g = session.client('ec2')
    all_regions = [r['RegionName'] for r in ec2g.describe_regions().get('Regions',[])]
    active_regions = []
    print("\n리전별 EC2 조회 중... (수초 소요)")
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        future_to_reg = {executor.submit(has_running, reg, session): reg for reg in all_regions}
        for fut in concurrent.futures.as_completed(future_to_reg):
            reg = future_to_reg[fut]
            if fut.result(): active_regions.append(reg)
    active_regions.sort()
    if not active_regions:
        print("⚠ 실행 중인 EC2 인스턴스가 있는 리전이 없습니다.")
        return None
    print(f"\n==> Profile: {profile} | Account: {account}")
    print("#  Region (EC2 존재하는 리전만 표시)")
    for idx, r in enumerate(active_regions, 1):
        print(f" {idx:2d}) {r}")
    while True:
        sel = input("번호 입력 (b=뒤로 /cancel=Enter): ").strip()
        if not sel or sel.lower() in ('b','cancel'):
            return None
        if sel.isdigit() and 1 <= int(sel) <= len(active_regions):
            return active_regions[int(sel)-1]
        print("❌ 올바른 번호를 입력하세요.")


def list_instances(ec2_client):
    resp = ec2_client.describe_instances(
        Filters=[{'Name':'instance-state-name','Values':['running']}]
    )
    insts = []
    for res in resp.get('Reservations',[]):
        for i in res.get('Instances',[]):
            insts.append({
                'Name':       next((t['Value'] for t in i.get('Tags',[]) if t.get('Key')=='Name'), ''),
                'InstanceId': i.get('InstanceId',''),
                'AZ':         i.get('Placement',{}).get('AvailabilityZone',''),
                'Type':       i.get('InstanceType',''),
                'OS':         i.get('PlatformDetails','Linux'),
                'PublicIP':   i.get('PublicIpAddress',''),
                'PrivateIP':  i.get('PrivateIpAddress',''),
                'State':      i.get('State',{}).get('Name','')
            })
    return sorted(insts, key=lambda x: x['Name'])


def choose_instance(insts):
    header = '#  Name                 InstanceId               AZ              Type           OS             PublicIP        PrivateIP       State'
    print('\n' + header)
    for idx, inst in enumerate(insts, 1):
        print(f"{idx:2d}) {inst['Name']:<20} {inst['InstanceId']:<22} {inst['AZ']:<15} {inst['Type']:<14} {inst['OS']:<15} {inst['PublicIP']:<15} {inst['PrivateIP']:<15} {inst['State']}")
    while True:
        sel = input("번호 입력 (b=뒤로 /cancel=Enter): ").strip()
        if not sel or sel.lower() in ('b','cancel'):
            return None
        if sel.isdigit() and 1 <= int(sel) <= len(insts):
            return insts[int(sel)-1], int(sel)
        print("❌ 올바른 번호를 입력하세요.")


def ssm_cmd(profile, region, iid):
    cmd = [
        'aws','ssm','start-session',
        '--region', region,
        '--target', iid,
        '--document-name','AWS-StartInteractiveCommand',
        '--parameters', '{\\"command\\":[\\"bash -l\\"]}'
    ]
    if profile:
        cmd.insert(1,'--profile'); cmd.insert(2,profile)
    return cmd


def start_port_forward(profile, region, iid, local_port, remote_port=3389):
    cmd = [
        'aws','ssm','start-session',
        '--region', region,
        '--target', iid,
        '--document-name','AWS-StartPortForwardingSession',
        '--parameters', f'{{"portNumber":["{remote_port}"],"localPortNumber":["{local_port}"]}}'
    ]
    if profile:
        cmd.insert(1,'--profile'); cmd.insert(2,profile)
    return subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def launch_rdp(local_port):
    print(f"▶ connecting RDP localhost:{local_port}")
    subprocess.Popen(['mstsc.exe', f'/v:localhost:{local_port}'], stdin=subprocess.DEVNULL)


def find_windows_terminal():
    for name in ('wt.exe','wt'):
        path = shutil.which(name)
        if path:
            return path
    return None


def launch_linux_wt(profile, region, iid):
    cmd = ssm_cmd(profile, region, iid)
    wt  = find_windows_terminal()
    print(f"▶ connecting {iid} Linux session in {region}")
    if wt:
        subprocess.Popen([wt,'new-tab','wsl.exe','--',*cmd], stdin=subprocess.DEVNULL)
    else:
        subprocess.run(cmd)

# -----------------------------------------------------------------------------
# SSM 관리 대상 인스턴스 조회
# -----------------------------------------------------------------------------
def list_ssm_managed(profile, region):
    sess = boto3.Session(profile_name=profile, region_name=region)
    info = sess.client('ssm').describe_instance_information().get('InstanceInformationList',[])
    return [i['InstanceId'] for i in info]

# -----------------------------------------------------------------------------
# RDS 접속 기능
# -----------------------------------------------------------------------------
def get_rds_endpoints(profile, region):
    sess = boto3.Session(profile_name=profile, region_name=region)
    dbs  = sess.client('rds').describe_db_instances().get('DBInstances',[])
    return [{'Id':d['DBInstanceIdentifier'],'Engine':d['Engine'], 'Endpoint':d['Endpoint']['Address'],'Port':d['Endpoint']['Port']} for d in dbs]


def choose_rds_instances(lst):
    print("\n# RDS 인스턴스 선택 (예: 1,2)")
    for idx, db in enumerate(lst,1): print(f" {idx:2d}) {db['Id']} ({db['Engine']}) → {db['Endpoint']}:{db['Port']}")
    while True:
        sel = input("번호 입력 (b=뒤로 /cancel=Enter): ").strip()
        if not sel or sel.lower() in ('b','cancel'): return []
        parts = [s for s in sel.split(',') if s.isdigit()]
        if parts: return [lst[int(p)-1] for p in parts]
        print("❌ 올바른 번호 형식: 1,2")


def start_rds_port_forward(profile, region, endpoint, remote_port, local_port):
    tgt = list_ssm_managed(profile, region)[0]
    cmd = [
        'aws','ssm','start-session',
        '--region', region,
        '--target', tgt,
        '--document-name','AWS-StartPortForwardingSessionToRemoteHost',
        '--parameters', f'{{"host":["{endpoint}"],"portNumber":["{remote_port}"],"localPortNumber":["{local_port}"]}}'
    ]
    if profile:
        cmd.insert(1,'--profile'); cmd.insert(2,profile)
    return subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def launch_db_tool(path, port):
    print(f"▶ connecting DB localhost:{port}")
    subprocess.Popen([path,'--connect',f'localhost:{port}'], stdin=subprocess.DEVNULL)


def connect_to_rds(profile, region, base_port):
    lst    = get_rds_endpoints(profile, region)
    chosen = choose_rds_instances(lst)
    for idx, db in enumerate(chosen,1):
        local = base_port + idx
        print(f"🔹 [{db['Id']}] {db['Endpoint']}:{db['Port']} -> localhost:{local}")
        proc  = start_rds_port_forward(profile, region, db['Endpoint'], db['Port'], local)
        time.sleep(1)
        launch_db_tool(DB_TOOL_PATH, local)
        proc.terminate()

# -----------------------------------------------------------------------------
# ElastiCache 접속 기능
# -----------------------------------------------------------------------------
def list_cache_clusters(profile, region):
    """ElastiCache 클러스터 정보(Engine, Endpoint) 목록 반환"""
    sess     = boto3.Session(profile_name=profile, region_name=region)
    ec       = sess.client('elasticache')
    clusters = ec.describe_cache_clusters(ShowCacheNodeInfo=True).get('CacheClusters', [])
    result   = []
    for c in clusters:
        # Redis cluster mode disabled: 단일 엔드포인트
        if 'ConfigurationEndpoint' in c and c['ConfigurationEndpoint']:
            ep = c['ConfigurationEndpoint']
        elif 'Endpoint' in c and c['Endpoint']:
            ep = c['Endpoint']
        else:
            # Cluster mode enabled 또는 기타: 첫번째 CacheNode의 Endpoint 사용
            nodes = c.get('CacheNodes', [])
            if nodes:
                ep = nodes[0].get('Endpoint', {})
            else:
                ep = {'Address': '', 'Port': 0}
        result.append({
            'Id':      c['CacheClusterId'],
            'Engine':  c['Engine'],
            'Address': ep.get('Address', ''),
            'Port':    ep.get('Port', 0)
        })
    return result


def choose_cache_cluster(clusters):
    print("\n# ElastiCache 클러스터 선택")
    for idx, c in enumerate(clusters,1): print(f" {idx:2d}) {c['Id']} ({c['Engine']}) → {c['Address']}:{c['Port']}")
    while True:
        sel = input("번호 입력 (b=뒤로 /cancel=Enter): ").strip()
        if not sel or sel.lower() in ('b','cancel'): return None
        if sel.isdigit() and 1 <= int(sel) <= len(clusters): return clusters[int(sel)-1]
        print("❌ 올바른 번호를 입력하세요.")


def start_cache_port_forward(profile, region, endpoint, remote_port, local_port):
    tgt = list_ssm_managed(profile, region)[0]
    cmd = [
        'aws','ssm','start-session',
        '--region', region,
        '--target', tgt,
        '--document-name','AWS-StartPortForwardingSessionToRemoteHost',
        '--parameters', f'{{"host":["{endpoint}"],"portNumber":["{remote_port}"],"localPortNumber":["{local_port}"]}}'
    ]
    if profile:
        cmd.insert(1,'--profile'); cmd.insert(2,profile)
    return subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def launch_cache_cli(engine, port):
    """Redis 또는 Memcached 클라이언트를 Windows Terminal 새 탭으로 실행"""
    tool = CACHE_REDIS_CLI if engine.lower().startswith('redis') else CACHE_MEMCACHED_CLI
    # CLI 인자 구성
    if tool == CACHE_REDIS_CLI:
        cli_args = [tool, '-h', '127.0.0.1', '-p', str(port)]
    else:
        cli_args = [tool, '127.0.0.1', str(port)]
    # Windows Terminal 실행 경로 확인
    wt = shutil.which('wt') or shutil.which('wt.exe')
    if wt:
        # WSL 환경에서 새로운 탭으로 실행
        subprocess.Popen([wt, 'new-tab', 'wsl.exe', '--', *cli_args], stdin=subprocess.DEVNULL)
    else:
        # Windows Terminal이 없으면 현재 콘솔에서 실행
        print(f"▶ launching {tool} on localhost:{port}")
        subprocess.Popen(cli_args)

# -----------------------------------------------------------------------------
# 메인
# -----------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-p','--profile')
    parser.add_argument('-r','--region')
    parser.add_argument('-d','--debug', action='store_true')
    args = parser.parse_args()

    setup_logger(args.debug)
    while True:
        profile = args.profile or choose_profile()
        session = get_session(profile)
        sts     = session.client('sts')
        account = sts.get_caller_identity()['Account']
        base_port = 13300 + int(account[-3:] or 0)
        args.profile = profile

        while True:
            region = args.region or choose_region(session, profile, account)
            args.region = None
            if not region:
                break
            print(f"\n==> Profile: {profile} | Account: {account} | Region: {region}\n")
            print("1) EC2 인스턴스 접속")
            print("2) RDS 접속 (멀티 SSM 포워딩)")
            print("3) ElastiCache 접속 (SSM 포워딩)")
            print("4) 종료")
            choice = input("선택: ").strip()

            if choice == '1':
                insts = list_instances(session.client('ec2', region_name=region))
                if not insts:
                    print('⚠ 실행 중인 인스턴스 없음')
                    continue
                while True:
                    sel = choose_instance(insts)
                    if not sel:
                        break
                    inst, idx = sel
                    if inst['OS'].lower().startswith('windows'):
                        local = base_port + idx
                        proc = start_port_forward(profile, region, inst['InstanceId'], local)
                        time.sleep(2)
                        launch_rdp(local)
                        proc.terminate()
                    else:
                        launch_linux_wt(profile, region, inst['InstanceId'])
                continue

            elif choice == '2':
                connect_to_rds(profile, region, base_port)
                continue

            elif choice == '3':
                # ElastiCache 접속
                clusters = list_cache_clusters(profile, region)
                sel = choose_cache_cluster(clusters)
                if sel:
                    local = base_port + 100
                    print(f"🔹 [{sel['Id']}] {sel['Address']}:{sel['Port']} -> localhost:{local}")
                    # SSM 포트 포워딩 세션 시작
                    proc = start_cache_port_forward(profile, region, sel['Address'], sel['Port'], local)
                    # 포트 포워딩이 준비될 때까지 최대 10초 대기
                    for _ in range(10):
                        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                            if s.connect_ex(('127.0.0.1', local)) == 0:
                                break
                        time.sleep(1)
                    else:
                        print(f"❌ 포트 포워딩 실패: localhost:{local}")
                        proc.terminate()
                        continue
                    # 로컬 CLI 실행
                    launch_cache_cli(sel['Engine'], local)
                    proc.terminate()
                continue

            elif choice in ('4',''):
                sys.exit(0)

            else:
                print("❌ 올바른 메뉴 선택")

if __name__ == '__main__':
    main()
