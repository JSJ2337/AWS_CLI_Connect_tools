#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EC2 & RDS 접속 자동화 스크립트 (WSL 최적화)

– EC2 접속 로직은 원본 ec2menu_v4.0.py 그대로 유지  
– RDS 접속 기능만 파일 하단에 추가, 멀티 선택 지원, Jump-Host는 자동으로 첫 번째 SSM 관리 인스턴스 사용  
"""

import argparse
import configparser
import concurrent.futures
import logging
import readline
import shutil
import subprocess
import sys
import time
from pathlib import Path

import boto3
from botocore.exceptions import ProfileNotFound, NoCredentialsError

# -----------------------------------------------------------------------------
# 설정: AWS CLI 경로 & 로그 파일, DB 툴 경로
# -----------------------------------------------------------------------------
AWS_CONFIG_PATH = Path("~/.aws/config").expanduser()
AWS_CRED_PATH   = Path("~/.aws/credentials").expanduser()
LOG_PATH        = Path.home() / "ec2menu.log"
DB_TOOL_PATH    = "/mnt/c/Program Files/DBeaver/dbeaver.exe"  # WSL에서 호출할 DBeaver 경로

# -----------------------------------------------------------------------------
# 로거 설정
# -----------------------------------------------------------------------------
def setup_logger(debug: bool):
    """콘솔 및 파일 로깅 설정"""
    level = logging.DEBUG if debug else logging.INFO
    fmt   = "%(asctime)s [%(levelname)s] %(message)s"
    handlers = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_PATH, encoding="utf-8")
    ]
    logging.basicConfig(level=level, format=fmt, handlers=handlers)

# -----------------------------------------------------------------------------
# AWS 프로파일 조회 및 선택
# -----------------------------------------------------------------------------
def list_profiles():
    """~/.aws/config 와 ~/.aws/credentials 에서 profile 목록 반환"""
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
    """사용자가 사용할 AWS 프로파일 선택"""
    profiles = list_profiles()
    if not profiles:
        print("❌ AWS 프로파일이 없습니다.")
        sys.exit(1)
    print("\n#  Profile")
    for i, p in enumerate(profiles, 1):
        print(f" {i:2d}) {p}")
    while True:
        sel = input("번호 입력 (취소=Enter): ").strip()
        if not sel:
            sys.exit(0)
        if sel.isdigit() and 1 <= int(sel) <= len(profiles):
            return profiles[int(sel)-1]
        print("❌ 올바른 번호를 입력하세요.")

def get_session(profile):
    """boto3.Session 생성 (프로파일 검증 포함)"""
    try:
        return boto3.Session(profile_name=profile)
    except ProfileNotFound as e:
        print(f"프로파일 오류: {e}")
        sys.exit(1)

# -----------------------------------------------------------------------------
# 리전 선택
# -----------------------------------------------------------------------------
def has_running(region, session):
    """해당 리전에 실행 중인 EC2 인스턴스가 있으면 region 반환"""
    try:
        ec2r = session.client("ec2", region_name=region)
        resp = ec2r.describe_instances(
            Filters=[{"Name":"instance-state-name","Values":["running"]}]
        )
        return region if any(i for r in resp["Reservations"] for i in r["Instances"]) else None
    except:
        return None

def choose_region(session, profile, account):
    """실행 중인 EC2가 있는 리전만 메뉴에 표시"""
    ec2g = session.client("ec2")
    all_regs = [r["RegionName"] for r in ec2g.describe_regions()["Regions"]]
    active   = []
    print("\n리전별 EC2 조회 중... (수초 소요)")
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as ex:
        futures = {ex.submit(has_running, r, session): r for r in all_regs}
        for f in concurrent.futures.as_completed(futures):
            if f.result():
                active.append(futures[f])
    active.sort()
    if not active:
        print("⚠ 실행 중인 EC2 인스턴스가 있는 리전이 없습니다.")
        return None
    print(f"\n==> Profile: {profile} | Account: {account}")
    for i, r in enumerate(active, 1):
        print(f" {i:2d}) {r}")
    while True:
        sel = input("번호 입력 (b=뒤로 /cancel=Enter): ").strip()
        if not sel or sel.lower() == "b":
            return None
        if sel.isdigit() and 1 <= int(sel) <= len(active):
            return active[int(sel)-1]
        print("❌ 올바른 번호를 입력하세요.")

# -----------------------------------------------------------------------------
# EC2 인스턴스 목록 조회 및 선택
# -----------------------------------------------------------------------------
def list_instances(ec2_client):
    """해당 리전의 실행 중 EC2 인스턴스 정보 리스트 반환"""
    resp = ec2_client.describe_instances(
        Filters=[{"Name":"instance-state-name","Values":["running"]}]
    )
    insts = []
    for res in resp["Reservations"]:
        for i in res["Instances"]:
            insts.append({
                "Name": next((t["Value"] for t in i.get("Tags",[]) if t["Key"]=="Name"), ""),
                "InstanceId": i["InstanceId"],
                "AZ": i["Placement"]["AvailabilityZone"],
                "Type": i["InstanceType"],
                "OS": i.get("PlatformDetails","Linux"),
                "PublicIP": i.get("PublicIpAddress",""),
                "PrivateIP": i.get("PrivateIpAddress",""),
                "State": i["State"]["Name"]
            })
    return sorted(insts, key=lambda x: x["Name"])

def choose_instance(insts):
    """인스턴스 목록을 보여주고 선택"""
    header = '#  Name                 InstanceId               AZ              Type           OS             PublicIP        PrivateIP       State'
    print("\n" + header)
    for i, inst in enumerate(insts, 1):
        print(f"{i:2d}) {inst['Name']:<20} {inst['InstanceId']:<22} "
              f"{inst['AZ']:<15} {inst['Type']:<14} {inst['OS']:<15} "
              f"{inst['PublicIP']:<15} {inst['PrivateIP']:<15} {inst['State']}")
    while True:
        sel = input("번호 입력 (b=뒤로 /cancel=Enter): ").strip()
        if not sel or sel.lower() == "b":
            return None
        if sel.isdigit() and 1 <= int(sel) <= len(insts):
            return insts[int(sel)-1], int(sel)
        print("❌ 올바른 번호를 입력하세요.")

# -----------------------------------------------------------------------------
# EC2 접속 (SSM)
# -----------------------------------------------------------------------------
def ssm_cmd(profile, region, iid):
    """리눅스용 SSM 대화형 쉘 세션 커맨드 생성"""
    cmd = [
        'aws','ssm','start-session',
        '--region', region,
        '--target', iid,
        '--document-name', 'AWS-StartInteractiveCommand',
        '--parameters', '{\\"command\\":[\\"bash -l\\"]}'
    ]
    if profile:
        cmd[1:1] = ['--profile', profile]
    return cmd

def start_port_forward(profile, region, iid, port):
    """Windows RDP용 SSM 포트포워딩 세션 실행"""
    cmd = [
        'aws','ssm','start-session',
        '--region', region,
        '--target', iid,
        '--document-name', 'AWS-StartPortForwardingSession',
        '--parameters', f'{{\"portNumber\":[\"3389\"],\"localPortNumber\":[\"{port}\"]}}'
    ]
    if profile:
        cmd[1:1] = ['--profile', profile]
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
                             
def launch_rdp(port):
    """mstsc.exe를 호출해 RDP 세션 시작"""
    subprocess.Popen(
        ["mstsc.exe", f"/v:localhost:{port}"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def find_windows_terminal():
    """wt.exe 경로 탐색"""
    for n in ('wt.exe','wt'):
        p = shutil.which(n)
        if p:
            return p
    return None

def launch_linux_wt(profile, region, iid):
    """Windows Terminal(wt.exe)으로 SSM 세션 새 탭 실행"""
    wt = find_windows_terminal()
    if not wt:
        subprocess.run(ssm_cmd(profile, region, iid))
        return
    subprocess.Popen(
        [wt,'new-tab','wsl.exe','--', *ssm_cmd(profile, region, iid)],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

# -----------------------------------------------------------------------------
# RDS 접속 기능 (멀티 선택 지원)
# -----------------------------------------------------------------------------
def list_ssm_managed(profile, region):
    """SSM 에이전트가 설치된 관리 대상 인스턴스 정보 조회"""
    sess = boto3.Session(profile_name=profile, region_name=region)
    return sess.client('ssm').describe_instance_information(MaxResults=50)["InstanceInformationList"]

def choose_jump_host(profile, region):
    """SSM 관리 인스턴스 중 자동으로 첫 번째를 Jump-Host로 지정"""
    managed = list_ssm_managed(profile, region)
    if not managed:
        print("⚠ SSM 관리 인스턴스가 없습니다.")
        return None
    jump = managed[0]['InstanceId']
    print(f"\n🔹 자동 Jump-Host 선택: {jump} ({managed[0]['PlatformName']})")
    return jump

def get_rds_endpoints(profile, region):
    """RDS 인스턴스 목록과 엔드포인트 정보 조회"""
    sess = boto3.Session(profile_name=profile, region_name=region)
    resp = sess.client('rds').describe_db_instances()
    return [{
        "Identifier": db["DBInstanceIdentifier"],
        "Endpoint"  : db["Endpoint"]["Address"],
        "Port"      : db["Endpoint"]["Port"],
        "Engine"    : db["Engine"]
    } for db in resp["DBInstances"]]

def choose_rds_instances(lst):
    """복수 선택을 지원하는 RDS 인스턴스 선택 UI"""
    print("\n# RDS 인스턴스 선택 (예: 1,2,4)")
    for i, db in enumerate(lst, 1):
        print(f" {i:2d}) {db['Identifier']} ({db['Engine']}) → {db['Endpoint']}:{db['Port']}")
    while True:
        sel = input("번호 입력 (b=뒤로 /취소=Enter): ").strip()
        if not sel or sel.lower() == 'b':
            return []
        parts = [s.strip() for s in sel.split(',') if s.strip().isdigit()]
        indices = [int(s) for s in parts if 1 <= int(s) <= len(lst)]
        if indices:
            seen = set(); result = []
            for idx in indices:
                if idx not in seen:
                    seen.add(idx); result.append(lst[idx-1])
            return result
        print("❌ 올바른 번호(예: 1,3)를 입력하세요.")

def start_rds_port_forward(profile, region, target, endpoint, remote, local):
    """RDS 터널링을 위한 SSM 포트포워딩 세션 실행"""
    json_param = f'{{"host":["{endpoint}"],"portNumber":["{remote}"],"localPortNumber":["{local}"]}}'
    cmd = [
        'aws','ssm','start-session',
        '--profile', profile,
        '--region', region,
        '--target', target,
        '--document-name', 'AWS-StartPortForwardingSessionToRemoteHost',
        '--parameters', json_param
    ]
    return subprocess.Popen(cmd)

def launch_db_tool(path, port):
    """DBeaver(혹은 지정 툴) 자동 실행 (프로파일에 localhost:port 사용)"""
    subprocess.Popen([path, "-con", f"localhost:{port}"])

def connect_to_rds(profile, region, base_port):
    """
    메뉴 2) RDS 접속:
    1) RDS 목록 → 2) 복수 선택 → 3) Jump-Host 자동 선택 → 
    4) 멀티 포트포워딩 & 툴 실행 → 5) 메뉴 복귀
    """
    rds_list = get_rds_endpoints(profile, region)
    selected = choose_rds_instances(rds_list)
    if not selected:
        return
    jump = choose_jump_host(profile, region)
    if not jump:
        return

    # 여러 RDS 인스턴스에 대해 터널 & 툴 실행
    for i, db in enumerate(selected):
        ep, pt = db["Endpoint"], db["Port"]
        local_port = base_port + i + 1
        print(f"\n🔹 [{db['Identifier']}] RDS 터널링: {ep}:{pt} → localhost:{local_port}")
        start_rds_port_forward(profile, region, jump, ep, pt, local_port)
        time.sleep(2)
        print(f"🔹 [{db['Identifier']}] DBeaver 실행...")
        launch_db_tool(DB_TOOL_PATH, local_port)

# -----------------------------------------------------------------------------
# 메인
# -----------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--profile','-p')
    parser.add_argument('--region','-r')
    parser.add_argument('--debug','-d', action='store_true')
    args = parser.parse_args()

    setup_logger(args.debug)

    while True:  # Profile 루프
        profile = args.profile or choose_profile()
        session = get_session(profile)
        sts     = session.client('sts')
        account = sts.get_caller_identity()['Account']
        base_port = 13300 + int(account[-3:] or 0)
        args.profile = profile

        while True:  # Region 루프
            region = args.region or choose_region(session, profile, account)
            args.region = None
            if not region:
                args.profile = None
                break

            # 메뉴 출력
            print(f"\n==> Profile: {profile} | Account: {account} | Region: {region}\n")
            print("1) EC2 인스턴스 접속")
            print("2) RDS 접속 (SSM 포트포워딩, 멀티)")
            print("3) 종료")
            choice = input("선택: ").strip()

            if choice == '1':
                # EC2 인스턴스 접속: 선택 목록 유지 루프
                insts = list_instances(session.client('ec2', region_name=region))
                if not insts:
                    print('⚠ 실행 중인 인스턴스가 없습니다. 리전 선택 메뉴로 돌아갑니다.')
                    continue
                while True:
                    res = choose_instance(insts)
                    if res is None:
                        break
                    inst, idx = res
                    print(f"▶ connecting {inst['Name']} ({inst['InstanceId']}) in {region} [{inst['OS']}]")
                    if inst['OS'].startswith('Windows'):
                        port = base_port + idx
                        proc = start_port_forward(profile, region, inst['InstanceId'], port)
                        time.sleep(2)
                        launch_rdp(port)
                        proc.terminate()
                        continue
                    else:
                        launch_linux_wt(profile, region, inst['InstanceId'])
                continue

            elif choice == '2':
                connect_to_rds(profile, region, base_port)
                continue

            elif choice in ('3', ''):
                sys.exit(0)

            else:
                print("❌ 올바른 메뉴 선택")

if __name__ == '__main__':
    main()
