#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EC2 메뉴 스크립트 (최종본)

주요 기능:
  - AWS CLI 프로파일 목록 중에서 사용자 선택
  - 실행 중인 인스턴스가 존재하는 리전만 검색하여 사용자 선택
  - 리전 내 실행 중인 인스턴스를 테이블 형식으로 보여주고 선택 가능
  - Windows 인스턴스는 SSM 포트포워딩 + mstsc.exe 실행 (강제로 전면에 띄움, 반복 시도)
  - Linux 인스턴스는 Windows Terminal (wt.exe) 새 탭을 열어 bash 접속 (강제로 전면에 띄움, 반복 시도)

사전 준비 사항:
  • AWS CLI v2 설치 및 프로파일 구성 (`aws configure`)
  • Session Manager Plugin 설치 (https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html)
  • WSL이 설치된 Windows 환경에서 wt.exe 사용 가능하도록 설정
  • mstsc.exe (기본 내장 RDP 클라이언트) 사용 가능해야 함
  • boto3, botocore 파이썬 라이브러리 설치 (`pip install boto3`)
"""

import argparse
import configparser
import concurrent.futures
import logging
import platform
import readline
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional, Tuple

import boto3
from botocore.exceptions import ProfileNotFound, NoCredentialsError

AWS_CONFIG_PATH = Path("~/.aws/config").expanduser()
AWS_CRED_PATH   = Path("~/.aws/credentials").expanduser()
LOG_PATH = Path.home() / "ec2menu.log"

def setup_logger(debug: bool):
    level = logging.DEBUG if debug else logging.INFO
    fmt = "%(asctime)s [%(levelname)s] %(message)s"
    handlers = [logging.StreamHandler(sys.stdout), logging.FileHandler(LOG_PATH, encoding="utf-8")]
    logging.basicConfig(level=level, format=fmt, handlers=handlers)

def list_profiles():
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
    try:
        return boto3.Session(profile_name=profile)
    except ProfileNotFound as e:
        print(f"프로파일 오류: {e}")
        sys.exit(1)

def has_running(region, session):
    try:
        ec2r = session.client("ec2", region_name=region)
        resp = ec2r.describe_instances(Filters=[{"Name": "instance-state-name", "Values": ["running"]}])
        return region if any(i for res in resp["Reservations"] for i in res["Instances"]) else None
    except Exception:
        return None

def choose_region(session, profile, account):
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
    cmd = [
        'aws', 'ssm', 'start-session',
        '--region', region,
        '--target', iid,
        '--document-name', 'AWS-StartPortForwardingSession',
        '--parameters', f'{{\"portNumber\":[\"3389\"],\"localPortNumber\":[\"{port}\"]}}'
    ]
    if profile:
        cmd[1:1] = ['--profile', profile]
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

# -------------------- 창 활성화 반복 시도 코드 --------------------
def activate_window(process_name):
    cmd = [
        'powershell.exe', '-Command',
        f'''Add-Type @'
        using System;
        using System.Runtime.InteropServices;
        public class WinAPI {{
            [DllImport("user32.dll")]
            public static extern bool SetForegroundWindow(IntPtr hWnd);
        }}
        '@;
        $hwnd = (Get-Process -Name {process_name}).MainWindowHandle | Select-Object -First 1;
        if ($hwnd) {{[WinAPI]::SetForegroundWindow($hwnd)}}'''
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def launch_rdp(port):
    subprocess.Popen(["mstsc.exe", f"/v:localhost:{port}"])
    time.sleep(2)
    for _ in range(5):
        activate_window('mstsc')
        time.sleep(0.3)

def find_windows_terminal():
    for name in ('wt.exe', 'wt'):
        path = shutil.which(name)
        if path:
            return path
    return None

def launch_linux_wt(profile, region, iid):
    wt = find_windows_terminal()
    if not wt:
        print('[WARN] Windows Terminal(wt.exe) 경로를 찾을 수 없어 기본 쉘에서 실행합니다.')
        subprocess.run(ssm_cmd(profile, region, iid))
        return
    cmd = [wt, 'new-tab', 'wsl.exe', '--', *ssm_cmd(profile, region, iid)]
    subprocess.Popen(cmd)
    time.sleep(2)
    for _ in range(5):
        activate_window('WindowsTerminal')
        time.sleep(0.3)
# ---------------------------------------------------------------

def main():
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
                    port = base_port + idx
                    proc = start_port_forward(profile, region, inst['InstanceId'], port)
                    time.sleep(2)
                    launch_rdp(port)
                    proc.terminate()
                    continue
                else:
                    launch_linux_wt(profile, region, inst['InstanceId'])

if __name__ == '__main__':
    main()
