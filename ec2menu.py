#!/usr/bin/env python3
"""
Python 기반 EC2 메뉴 스크립트
Usage:
    ./ec2menu.py [--profile <aws-profile>] [--region <initial-region>]

주요 기능:
  • AWS 프로파일 선택 및 세션 생성
  • 프로파일, 계정, 리전 정보 표시
  • 리전별 실행 중 EC2 인스턴스 조회 (EC2가 있는 리전만 표시, 병렬 조회로 빠름)
  • Windows 인스턴스: SSM 포트 포워딩 후 RDP 자동 실행
  • Linux 인스턴스: SSM 대화형 셸
  • 인스턴스 목록에 Public/Private IP 및 상태 표시
  • 터널 포트 오픈 대기 및 자동 재시도 방지

사전 요구:
  • AWS CLI v2,  Session Manager Plugin 설치
  • WSL: mstsc.exe 사용
  • 리눅스 GUI: xfreerdp 또는 rdesktop 설치
  • AWS IAM SSM 권한 및 Access key 발급필요
  • 리눅스 GUI: xfreerdp 또는 rdesktop 설치
"""
import argparse
import configparser
import os
import shutil
import subprocess
import sys
import platform
import boto3
import socket
import time
import readline  # CLI 입력 편집 기능 활성화
import concurrent.futures  # 병렬 처리용
from botocore.exceptions import ProfileNotFound, NoCredentialsError

AWS_CONFIG_PATH = os.path.expanduser('~/.aws/config')
AWS_CRED_PATH   = os.path.expanduser('~/.aws/credentials')

def is_wsl():
    return 'microsoft' in platform.uname().release.lower()

def verify_session_manager_plugin():
    if not shutil.which('session-manager-plugin'):
        print('❌ Session Manager Plugin이 없습니다.')
        sys.exit(1)

def list_aws_profiles():
    profiles = set()
    if os.path.exists(AWS_CONFIG_PATH):
        cfg = configparser.RawConfigParser()
        cfg.read(AWS_CONFIG_PATH)
        for sec in cfg.sections():
            if sec.startswith('profile '):
                profiles.add(sec.split(' ',1)[1])
            elif sec == 'default':
                profiles.add('default')
    if os.path.exists(AWS_CRED_PATH):
        cred = configparser.RawConfigParser()
        cred.read(AWS_CRED_PATH)
        for sec in cred.sections():
            profiles.add(sec)
    return sorted(profiles)

def choose_profile():
    profiles = list_aws_profiles()
    if not profiles:
        print('❌ AWS 프로파일이 없습니다.')
        sys.exit(1)
    print('\n#  Profile')
    for idx, p in enumerate(profiles, 1):
        print(f" {idx:2d}) {p}")
    while True:
        sel = input('번호 입력 (취소=Enter): ')
        if not sel.strip():
            sys.exit(0)
        if sel.isdigit() and 1 <= int(sel) <= len(profiles):
            return profiles[int(sel)-1]
        print('❌ 올바른 번호를 입력하세요.')

def get_session(profile=None):
    try:
        return boto3.Session(profile_name=profile) if profile else boto3.Session()
    except ProfileNotFound as e:
        print(f"프로파일 오류: {e}")
        sys.exit(1)

def compute_base_port(sts_client):
    try:
        acct = sts_client.get_caller_identity()['Account']
    except NoCredentialsError:
        print('❌ 자격 증명을 찾을 수 없습니다.')
        sys.exit(1)
    return 13300 + int(acct[-3:] or 0)

def wait_for_port(port, timeout=10):
    start = time.time()
    while time.time() - start < timeout:
        with socket.socket() as s:
            try:
                s.settimeout(1)
                s.connect(('localhost', port))
                return True
            except Exception:
                time.sleep(0.5)
    return False

def has_running_ec2(region, session):
    try:
        ec2r = session.client('ec2', region_name=region)
        resp = ec2r.describe_instances(Filters=[{'Name': 'instance-state-name', 'Values': ['running']}])
        return region if any(i for res in resp['Reservations'] for i in res['Instances']) else None
    except Exception:
        return None

def choose_region(session, profile, account):
    ec2g = session.client('ec2')
    all_regions = [r['RegionName'] for r in ec2g.describe_regions()['Regions']]
    active_regions = []

    print('\n리전별 EC2 인스턴스 존재여부를 조회 중입니다. (최대 수십초 소요) ...')

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        future_to_region = {executor.submit(has_running_ec2, reg, session): reg for reg in all_regions}
        for future in concurrent.futures.as_completed(future_to_region):
            reg = future_to_region[future]
            result = future.result()
            if result:
                active_regions.append(result)
    active_regions.sort()

    if not active_regions:
        print("⚠ 실행 중인 EC2 인스턴스가 있는 리전이 없습니다. 다시 프로파일을 선택합니다.")
        return None  # 종료가 아니라 메뉴 복귀

    while True:
        print(f"\n==> Profile: {profile} | Account: {account}")
        print('#  Region (EC2 존재하는 리전만 표시)')
        for idx, r in enumerate(active_regions, 1):
            print(f" {idx:2d}) {r}")
        sel = input('번호 입력 (b=뒤로 /cancel=Enter): ')
        if not sel.strip():
            return None
        if sel.lower() == 'b':
            return None
        if sel.isdigit() and 1 <= int(sel) <= len(active_regions):
            return active_regions[int(sel)-1]
        else:
            print('❌ 올바른 번호를 입력하세요.')

def list_instances(ec2_client):
    resp = ec2_client.describe_instances(Filters=[{'Name':'instance-state-name','Values':['running']}])
    insts = []
    for res in resp['Reservations']:
        for i in res['Instances']:
            insts.append({
                'Name': next((t['Value'] for t in i.get('Tags',[]) if t['Key']=='Name'), ''),
                'InstanceId': i['InstanceId'],
                'AZ': i['Placement']['AvailabilityZone'],
                'Type': i['InstanceType'],
                'OS': i.get('PlatformDetails','Linux'),
                'PublicIP': i.get('PublicIpAddress',''),
                'PrivateIP': i.get('PrivateIpAddress',''),
                'State': i['State']['Name']
            })
    return sorted(insts, key=lambda x: x['Name'])

def choose_instance(insts):
    header = '#  Name                 InstanceId               AZ              Type           OS             PublicIP        PrivateIP       State'
    print('\n' + header)
    for idx, inst in enumerate(insts, 1):
        print(f"{idx:2d}) {inst['Name']:<20} {inst['InstanceId']:<22} {inst['AZ']:<15} {inst['Type']:<14} {inst['OS']:<15} {inst['PublicIP']:<15} {inst['PrivateIP']:<15} {inst['State']}")
    while True:
        sel = input('번호 입력 (b=뒤로 /cancel=Enter): ')
        if not sel.strip(): return None
        if sel.lower() == 'b': return None
        if sel.isdigit() and 1 <= int(sel) <= len(insts):
            return insts[int(sel)-1], int(sel)
        print('❌ 올바른 번호를 입력하세요.')

def launch_rdp(port):
    if is_wsl():
        subprocess.run([
            "powershell.exe",
            "-NoProfile",
            "-Command",
            f"mstsc.exe /v:localhost:{port}"
        ])
    else:
        client = shutil.which('xfreerdp') or shutil.which('rdesktop')
        if client and os.path.basename(client)=='xfreerdp':
            subprocess.run([client, f"/v:localhost:{port}", "/cert-ignore"])
        elif client and os.path.basename(client)=='rdesktop':
            subprocess.run([client, f"localhost:{port}"])
        else:
            print('❌ RDP 클라이언트를 찾을 수 없습니다.')

def start_ssm_port_forward(profile, region, iid, port):
    verify_session_manager_plugin()
    params = f'{{"portNumber":["3389"],"localPortNumber":["{port}"]}}'
    cmd = ['aws', 'ssm', 'start-session', '--region', region, '--target', iid,
           '--document-name', 'AWS-StartPortForwardingSession', '--parameters', params]
    if profile: cmd[1:1] = ['--profile', profile]
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def start_ssm_shell(profile, region, iid):
    verify_session_manager_plugin()
    cmd = ['aws', 'ssm', 'start-session', '--region', region, '--target', iid,
           '--document-name', 'AWS-StartInteractiveCommand', '--parameters', 'command=["bash -l"]']
    if profile: cmd[1:1] = ['--profile', profile]
    subprocess.run(cmd)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--profile', '-p', help='AWS profile name')
    parser.add_argument('--region', '-r')
    args = parser.parse_args()

    while True:
        profile = args.profile or choose_profile()
        session = get_session(profile)
        sts = session.client('sts')
        account = sts.get_caller_identity()['Account']
        base_port = compute_base_port(sts)

        while True:
            region = choose_region(session, profile, account)
            if region is None:
                args.profile = None  # 리전이 없으면(취소, 뒤로 등) 프로파일 선택으로 복귀
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
                    proc = start_ssm_port_forward(profile, region, inst['InstanceId'], port)
                    if not wait_for_port(port):
                        print('❌ 터널 연결 실패: 포트가 열리지 않습니다.')
                        proc.kill()
                        continue
                    launch_rdp(port)
                    proc.kill()
                    continue
                else:
                    start_ssm_shell(profile, region, inst['InstanceId'])

if __name__ == '__main__':
    main()

