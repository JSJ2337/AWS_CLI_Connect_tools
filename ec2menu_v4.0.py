#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EC2 & RDS 접속 자동화 스크립트 (WSL 최적화)

원본 ec2menu_v4.0.py 의 EC2 접속 로직은
한 글자도 수정하지 않고, 파일 하단에만 RDS 메뉴/기능을 추가했습니다.
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
LOG_PATH        = Path.home() / "ec2menu.log"

# 외부 DB 툴 경로 (WSL 환경 기준)
DB_TOOL_PATH = "/mnt/c/Program Files/DBeaver/dbeaver.exe"

# ---------------- 로거 설정 ----------------
def setup_logger(debug: bool):
    level = logging.DEBUG if debug else logging.INFO
    fmt   = "%(asctime)s [%(levelname)s] %(message)s"
    handlers = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_PATH, encoding="utf-8")
    ]
    logging.basicConfig(level=level, format=fmt, handlers=handlers)

# ---------------- AWS 프로파일 ----------------
def list_profiles():
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
    profiles = list_profiles()
    if not profiles:
        print("❌ AWS 프로파일이 없습니다.")
        sys.exit(1)
    print("\n#  Profile")
    for i,p in enumerate(profiles,1):
        print(f" {i:2d}) {p}")
    while True:
        sel = input("번호 입력 (취소=Enter): ").strip()
        if not sel:
            sys.exit(0)
        if sel.isdigit() and 1 <= int(sel) <= len(profiles):
            return profiles[int(sel)-1]
        print("❌ 올바른 번호를 입력하세요.")

def get_session(profile):
    try:
        return boto3.Session(profile_name=profile)
    except ProfileNotFound as e:
        print(f"프로파일 오류: {e}")
        sys.exit(1)

# ---------------- 리전 선택 ----------------
def has_running(region, session):
    try:
        ec2r = session.client("ec2", region_name=region)
        resp = ec2r.describe_instances(
            Filters=[{"Name":"instance-state-name","Values":["running"]}]
        )
        return region if any(i for r in resp["Reservations"] for i in r["Instances"]) else None
    except:
        return None

def choose_region(session, profile, account):
    ec2g = session.client("ec2")
    all_regs = [r["RegionName"] for r in ec2g.describe_regions()["Regions"]]
    active   = []
    print("\n리전별 EC2 조회 중... (수초 소요)")
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as ex:
        futures = { ex.submit(has_running, r, session): r for r in all_regs }
        for f in concurrent.futures.as_completed(futures):
            if f.result():
                active.append(futures[f])
    active.sort()
    if not active:
        print("⚠ 실행 중인 EC2 인스턴스가 있는 리전이 없습니다.")
        return None
    print(f"\n==> Profile: {profile} | Account: {account}")
    for i,r in enumerate(active,1):
        print(f" {i:2d}) {r}")
    while True:
        sel = input("번호 입력 (b=뒤로 /cancel=Enter): ").strip()
        if not sel or sel.lower()=="b":
            return None
        if sel.isdigit() and 1 <= int(sel) <= len(active):
            return active[int(sel)-1]
        print("❌ 올바른 번호를 입력하세요.")

# ---------------- EC2 인스턴스 목록 & 선택 ----------------
def list_instances(ec2_client):
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
    header = '#  Name                 InstanceId               AZ              Type           OS             PublicIP        PrivateIP       State'
    print("\n"+header)
    for i,inst in enumerate(insts,1):
        print(f"{i:2d}) {inst['Name']:<20} {inst['InstanceId']:<22} "
              f"{inst['AZ']:<15} {inst['Type']:<14} {inst['OS']:<15} "
              f"{inst['PublicIP']:<15} {inst['PrivateIP']:<15} {inst['State']}")
    while True:
        sel = input("번호 입력 (b=뒤로 /cancel=Enter): ").strip()
        if not sel or sel.lower()=="b":
            return None
        if sel.isdigit() and 1 <= int(sel) <= len(insts):
            return insts[int(sel)-1], int(sel)
        print("❌ 올바른 번호를 입력하세요.")

# ---------------- EC2 접속 ----------------
def ssm_cmd(profile, region, iid):
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
    cmd = [
        'aws','ssm','start-session',
        '--region', region,
        '--target', iid,
        '--document-name', 'AWS-StartPortForwardingSession',
        '--parameters', f'{{\\"portNumber\\":[\\"3389\\"],\\"localPortNumber\\":[\\"{port}\\"]}}'
    ]
    if profile:
        cmd[1:1] = ['--profile', profile]
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)

def launch_rdp(port):
    subprocess.Popen(
        ["mstsc.exe", f"/v:localhost:{port}"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

def find_windows_terminal():
    for n in ('wt.exe','wt'):
        p = shutil.which(n)
        if p: return p
    return None

def launch_linux_wt(profile, region, iid):
    wt = find_windows_terminal()
    if not wt:
        subprocess.run(ssm_cmd(profile, region, iid))
        return
    subprocess.Popen(
        [wt,'new-tab','wsl.exe','--', *ssm_cmd(profile, region, iid)],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

# ==================== 여기서부터 RDS 접속 기능만 추가 ====================

def list_ssm_managed(profile, region):
    sess = boto3.Session(profile_name=profile, region_name=region)
    return sess.client('ssm').describe_instance_information(MaxResults=50)["InstanceInformationList"]

def choose_jump_host(profile, region):
    managed = list_ssm_managed(profile, region)
    if not managed:
        print("⚠ SSM 관리 인스턴스가 없습니다.")
        return None
    # 자동으로 첫 번째 SSM 관리 인스턴스를 Jump-Host로 지정
    jump = managed[0]['InstanceId']
    print(f"\n🔹 자동 Jump-Host 선택: {jump} ({managed[0]['PlatformName']})")
    return jump

def get_rds_endpoints(profile, region):
    sess = boto3.Session(profile_name=profile, region_name=region)
    resp = sess.client('rds').describe_db_instances()
    return [{
        "Identifier": db["DBInstanceIdentifier"],
        "Endpoint"  : db["Endpoint"]["Address"],
        "Port"      : db["Endpoint"]["Port"],
        "Engine"    : db["Engine"]
    } for db in resp["DBInstances"]]

def choose_rds_instance(lst):
    print("\n# RDS 인스턴스 선택")
    for i,db in enumerate(lst,1):
        print(f" {i:2d}) {db['Identifier']} ({db['Engine']}) → {db['Endpoint']}:{db['Port']}")
    while True:
        sel = input("번호 입력 (b=뒤로 /취소=Enter): ").strip()
        if not sel or sel.lower()=='b':
            return None
        if sel.isdigit() and 1 <= int(sel) <= len(lst):
            return lst[int(sel)-1]
        print("❌ 올바른 번호를 입력하세요.")

def start_rds_port_forward(profile, region, target, endpoint, remote, local):
    # 파라미터를 한 덩어리 JSON 문자열로 넘겨야 CLI가 옵션으로 해석하지 않습니다
    json_param = f'{{"host":["{endpoint}"],"portNumber":["{remote}"],"localPortNumber":["{local}"]}}'
    cmd = [
        'aws','ssm','start-session',
        '--profile', profile,
        '--region', region,
        '--target', target,
        '--document-name','AWS-StartPortForwardingSessionToRemoteHost',
        '--parameters', json_param
    ]
    return subprocess.Popen(cmd)

def launch_db_tool(path):
    subprocess.Popen([path])

def connect_to_rds(profile, region):
    # 1) RDS 목록 → 2) Jump-Host 자동 선택 → 3) 포트포워딩 → 4) DBeaver 실행
    rds_list = get_rds_endpoints(profile, region)
    sel      = choose_rds_instance(rds_list)
    if not sel: return
    jump     = choose_jump_host(profile, region)
    if not jump: return
    ep, pt   = sel["Endpoint"], sel["Port"]
    print(f"\n🔹 RDS 터널링 열기: {ep}:{pt}")
    proc = start_rds_port_forward(profile, region, jump, ep, pt, 13306)
    time.sleep(5)
    print("🔹 DBeaver 실행...")
    launch_db_tool(DB_TOOL_PATH)
    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        proc.wait()

# ==================== 메인 ====================

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--profile','-p')
    parser.add_argument('--region','-r')
    parser.add_argument('--debug','-d', action='store_true')
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
                args.profile = None
                break

            # **여기** 메뉴에 RDS 옵션만 추가했습니다.
            print(f"\n==> Profile: {profile} | Account: {account} | Region: {region}\n")
            print("1) EC2 인스턴스 접속")
            print("2) RDS 접속 (SSM 포트포워딩)")
            print("3) 종료")
            choice = input("선택: ").strip()

            if choice == '1':
                insts = list_instances(session.client('ec2', region_name=region))
                if not insts:
                    print('⚠ 실행 중인 인스턴스가 없습니다.')
                    continue
                res = choose_instance(insts)
                if not res: continue
                inst, idx = res
                print(f"▶ connecting {inst['Name']} ({inst['InstanceId']}) [{inst['OS']}]")
                if inst['OS'].startswith('Windows'):
                    p = start_port_forward(profile, region, inst['InstanceId'], base_port+idx)
                    time.sleep(2)
                    launch_rdp(base_port+idx)
                    p.terminate()
                else:
                    launch_linux_wt(profile, region, inst['InstanceId'])

            elif choice == '2':
                connect_to_rds(profile, region)

            elif choice in ('3',''):
                sys.exit(0)

            else:
                print("❌ 올바른 메뉴 선택")

if __name__ == '__main__':
    main()
