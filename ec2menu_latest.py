#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EC2 인스턴스 연결 자동화 스크립트 (WSL 최적화)

[사전 준비사항]
- Windows 10/11 환경에서 WSL2(리눅스) 활성화
- Windows Terminal(wt.exe) 설치 및 PATH 등록 (Microsoft Store 설치 시 기본 등록)
- mstsc.exe(원격 데스크톱) 기본 내장
- AWS CLI v2 및 프로파일 구성 (aws configure)
- Session Manager Plugin 설치 (https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html)
- Python 3.x 환경 (pip install boto3)
- 본 스크립트는 WSL(리눅스) 환경에서 실행 권장
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

# AWS CLI config/credentials 경로 정의
AWS_CONFIG_PATH = Path("~/.aws/config").expanduser()
AWS_CRED_PATH   = Path("~/.aws/credentials").expanduser()
LOG_PATH = Path.home() / "ec2menu.log"

def setup_logger(debug: bool):
    """로깅(로그 파일+콘솔) 설정"""
    level = logging.DEBUG if debug else logging.INFO
    fmt = "%(asctime)s [%(levelname)s] %(message)s"
    handlers = [logging.StreamHandler(sys.stdout), logging.FileHandler(LOG_PATH, encoding="utf-8")]
    logging.basicConfig(level=level, format=fmt, handlers=handlers)

def list_profiles():
    """AWS CLI 프로파일 목록 반환"""
    profiles = set()
    if AWS_CONFIG_PATH.exists():
        cfg = configparser.RawConfigParser()
        cfg.read(AWS_CONFIG_PATH)
        for sec in cfg.sections():
            if sec.startswith("profile "):
                profiles.add(sec.split(" ", 1)[1])
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

def get_session(profile):
    """지정한 프로파일로 boto3 세션 생성"""
    try:
        return boto3.Session(profile_name=profile)
    except ProfileNotFound as e:
        print(f"프로파일 오류: {e}")
        sys.exit(1)

def has_running(region, session):
    """특정 리전에 실행중인 EC2 인스턴스가 있는지 확인 (있으면 리전명 반환)"""
    try:
        ec2r = session.client("ec2", region_name=region)
        resp = ec2r.describe_instances(Filters=[{"Name": "instance-state-name", "Values": ["running"]}])
        return region if any(i for res in resp["Reservations"] for i in res["Instances"]) else None
    except Exception:
        return None

def choose_region(session, profile, account):
    """실행 중인 인스턴스가 존재하는 리전만 사용자에게 표시"""
    ec2g = session.client("ec2")
    all_regions = [r["RegionName"] for r in ec2g.describe_regions()["Regions"]]
    active_regions = []
    print("\n리전별 EC2 조회 중... (수초 소요)")
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        future_to_region = {executor.submit(has_running, reg, session): reg for reg in all_regions}
        for future in concurrent.futures.as_completed(future_to_region):
            reg = future_to_region[future]
            result = future.result()
            if result:
                active_regions.append(result)
    active_regions.sort()
    if not active_regions:
        print("⚠ 실행 중인 EC2 인스턴스가 있는 리전이 없습니다.")
        return None
    while True:
        print(f"\n==> Profile: {profile} | Account: {account}")
        print("#  Region (EC2 존재하는 리전만 표시)")
        for idx, r in enumerate(active_regions, 1):
            print(f" {idx:2d}) {r}")
        sel = input("번호 입력 (b=뒤로 /cancel=Enter): ").strip()
        if not sel:
            return None
        if sel.lower() == 'b':
            return None
        if sel.isdigit() and 1 <= int(sel) <= len(active_regions):
            return active_regions[int(sel)-1]
        print("❌ 올바른 번호를 입력하세요.")

def list_instances(ec2_client):
    """해당 리전에서 실행 중인 인스턴스 상세 목록 반환"""
    resp = ec2_client.describe_instances(Filters=[{"Name":"instance-state-name","Values":["running"]}])
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
    """사용자에게 인스턴스 목록을 테이블로 보여주고 선택 메뉴 표시"""
    header = '#  Name                 InstanceId               AZ              Type           OS             PublicIP        PrivateIP       State'
    print('\n' + header)
    for idx, inst in enumerate(insts, 1):
        print(f"{idx:2d}) {inst['Name']:<20} {inst['InstanceId']:<22} {inst['AZ']:<15} {inst['Type']:<14} {inst['OS']:<15} {inst['PublicIP']:<15} {inst['PrivateIP']:<15} {inst['State']}")
    while True:
        sel = input("번호 입력 (b=뒤로 /cancel=Enter): ").strip()
        if not sel: return None
        if sel.lower() == 'b': return None
        if sel.isdigit() and 1 <= int(sel) <= len(insts):
            return insts[int(sel)-1], int(sel)
        print("❌ 올바른 번호를 입력하세요.")

def ssm_cmd(profile, region, iid):
    """리눅스 인스턴스 접속용 SSM 세션 명령어 구성"""
    cmd = [
        'aws', 'ssm', 'start-session',
        '--region', region,
        '--target', iid,
        '--document-name', 'AWS-StartInteractiveCommand',
        '--parameters', '{\\"command\\":[\\"bash -l\\"]}'
    ]
    if profile:
        cmd[1:1] = ['--profile', profile]
    return cmd

def start_port_forward(profile, region, iid, port):
    """Windows 인스턴스의 RDP 포트포워딩 세션 실행 (백그라운드)"""
    cmd = [
        'aws', 'ssm', 'start-session',
        '--region', region,
        '--target', iid,
        '--document-name', 'AWS-StartPortForwardingSession',
        '--parameters', f'{{\"portNumber\":[\"3389\"],\"localPortNumber\":[\"{port}\"]}}'
    ]
    if profile:
        cmd[1:1] = ['--profile', profile]
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)

def launch_rdp(port):
    """포트포워딩된 RDP 세션을 mstsc.exe로 실행"""
    subprocess.Popen([
        "mstsc.exe", f"/v:localhost:{port}"
    ], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def find_windows_terminal():
    """Windows Terminal(wt.exe) 실행 경로 탐색"""
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

def main():
    """메인 로직: 메뉴 → 프로파일/리전/인스턴스 선택 → 접속"""
    parser = argparse.ArgumentParser()
    parser.add_argument('--profile', '-p')
    parser.add_argument('--region', '-r')
    parser.add_argument('--debug', '-d', action='store_true')
    args = parser.parse_args()

    setup_logger(args.debug)

    while True:
        profile = args.profile or choose_profile()
        session = get_session(profile)
        sts = session.client('sts')
        account = sts.get_caller_identity()['Account']
        base_port = 13300 + int(account[-3:] or 0)
        args.profile = profile

        while True:
            region = args.region or choose_region(session, profile, account)
            args.region = None
            if not region:
                args.profile = None
                break
            print(f"\n==> Profile: {profile} | Account: {account} | Region: {region}\n")

            insts = list_instances(session.client('ec2', region_name=region))
            if not insts:
                print('⚠ 실행 중인 인스턴스가 없습니다. 리전 선택 메뉴로 돌아갑니다.')
                continue

            while True:
                res = choose_instance(insts)
                if res is None:
                    break
                inst, idx = res
                print(f"▶ connecting {inst['Name']} ({inst['InstanceId']}) in {region} [{inst['OS']}]" )
                if inst['OS'].startswith('Windows'):
                    # 윈도우 인스턴스: SSM RDP 포트포워딩 → mstsc.exe 실행
                    port = base_port + idx
                    proc = start_port_forward(profile, region, inst['InstanceId'], port)
                    time.sleep(2)
                    launch_rdp(port)
                    proc.terminate()
                    continue
                else:
                    # 리눅스 인스턴스: Windows Terminal(wt.exe) 새 탭으로 SSM 세션 연결
                    launch_linux_wt(profile, region, inst['InstanceId'])

if __name__ == '__main__':
    main()

