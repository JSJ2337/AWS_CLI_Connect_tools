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
        print("❌ AWS 프로파일이 없습니다.")
        sys.exit(1)
    print("\n# Profile\n")
    for i,p in enumerate(lst,1): print(f" {i:2d}) {p}")
    while True:
        sel = input("번호 입력 (Enter=종료): ").strip()
        if not sel: sys.exit(0)
        if sel.isdigit() and 1 <= int(sel) <= len(lst): return lst[int(sel)-1]
        print("❌ 올바른 번호를 입력하세요.")


def choose_region(manager: AWSManager):
    # EC2 인스턴스가 있는 리전만 필터링
    regs = manager.list_regions()
    valid = []
    print("EC2 인스턴스 유무 확인 중, 잠시만 기다려주세요...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=manager.max_workers) as ex:
        future = {ex.submit(manager.list_instances, r): r for r in regs}
        for f in concurrent.futures.as_completed(future):
            r = future[f]
            try:
                if f.result(): valid.append(r)
            except:
                pass
    if not valid:
        print("⚠ EC2 인스턴스가 있는 리전이 없습니다")
        return None
    print("\n# Region")
    for i,r in enumerate(sorted(valid),1): print(f" {i:2d}) {r}")
    sel = input("번호 입력 (Enter=취소): ").strip()
    if not sel: return None
    if sel.isdigit() and 1 <= int(sel) <= len(valid): return sorted(valid)[int(sel)-1]
    print("❌ 올바른 번호를 입력하세요.")
    return None

# ----------------------------------------------------------------------------
# SSM 호출 함수 (target 지원)
# ----------------------------------------------------------------------------
def ssm_cmd(profile, region, iid=None, doc='AWS-StartInteractiveCommand', params='{"command":["bash -l"]}', target=None):
    cmd = ['aws','ssm','start-session','--region',region]
    if profile: cmd += ['--profile',profile]
    tgt = target or iid
    if tgt: cmd += ['--target',tgt]
    cmd += ['--document-name',doc,'--parameters',params]
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
    insts = manager.list_instances(region)
    if not insts:
        print("⚠ 실행 중인 EC2 인스턴스 없음")
        return
    for idx, i in enumerate(insts,1):
        name = next((t['Value'] for t in i.get('Tags',[]) if t['Key']=='Name'),'')
        print(f" {idx:2d}) {name} {i['InstanceId']} {i['PlatformDetails']} {i['Placement']['AvailabilityZone']}")
    sel = input("번호 입력 (b=뒤로): ").strip().lower()
    if not sel or sel=='b': return
    if not sel.isdigit() or not (1 <= int(sel) <= len(insts)):
        print("❌ 올바른 번호를 입력하세요.")
        return
    inst = insts[int(sel)-1]
    if inst.get('PlatformDetails','Linux').lower().startswith('windows'):
        local = 10000 + (int(inst['InstanceId'][-3:],16) % 1000)
        proc  = start_port_forward(manager.profile, region, inst['InstanceId'], local)
        time.sleep(2); launch_rdp(local); proc.terminate()
    else:
        launch_linux_wt(manager.profile, region, inst['InstanceId'])

# ----------------------------------------------------------------------------
# RDS 접속
# ----------------------------------------------------------------------------
def connect_to_rds(manager: AWSManager, db_path: str, region: str):
    dbs = manager.get_rds_endpoints(region)
    if not dbs:
        print("⚠ RDS 인스턴스가 없습니다")
        return
    for idx, db in enumerate(dbs,1):
        print(f" {idx:2d}) {db['Id']} → {db['Endpoint']}:{db['Port']}")
    sel = input("번호 입력 (b=뒤로,예:1,2): ").strip().lower()
    if not sel or sel=='b': return
    choices = [int(x) for x in sel.split(',') if x.isdigit()]
    ssm_targets = manager.list_ssm_managed(region)
    if not ssm_targets:
        print("⚠ SSM 관리 인스턴스가 없습니다")
        return
    tgt = ssm_targets[0]
    for idx, i in enumerate(choices,1):
        db = dbs[i-1]
        local = 11000 + idx
        print(f"🔹 {db['Id']} -> localhost:{local}")
        params = f'{{"host":["{db["Endpoint"]}"],"portNumber":["{db["Port"]}"],"localPortNumber":["{local}"]}}'
        proc = subprocess.Popen(
            ssm_cmd(manager.profile, region, target=tgt, doc='AWS-StartPortForwardingSessionToRemoteHost', params=params),
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        time.sleep(1)
        subprocess.Popen([db_path, '--connect', f'localhost:{local}'], stdin=subprocess.DEVNULL)
        proc.terminate()

# ----------------------------------------------------------------------------
# ElastiCache 접속
# ----------------------------------------------------------------------------
def connect_to_cache(manager: AWSManager, region: str):
    clus = manager.list_cache_clusters(region)
    if not clus:
        print("⚠ ElastiCache 클러스터가 없습니다")
        return
    for idx, c in enumerate(clus,1):
        print(f" {idx:2d}) {c['Id']} → {c['Address']}:{c['Port']}")
    sel = input("번호 입력 (b=뒤로): ").strip().lower()
    if not sel or sel=='b': return
    idx = int(sel)-1; c = clus[idx]
    ssm_targets = manager.list_ssm_managed(region)
    if not ssm_targets:
        print("⚠ SSM 관리 인스턴스가 없습니다")
        return
    tgt   = ssm_targets[0]
    local = 12000 + idx
    print(f"🔹 {c['Id']} -> localhost:{local}")
    params = f'{{"host":["{c["Address"]}"],"portNumber":["{c["Port"]}"],"localPortNumber":["{local}"]}}'
    proc = subprocess.Popen(
        ssm_cmd(manager.profile, region, target=tgt, doc='AWS-StartPortForwardingSessionToRemoteHost', params=params),
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    time.sleep(1)
    tool = DEFAULT_CACHE_REDIS_CLI if c['Engine'].startswith('redis') else DEFAULT_CACHE_MEMCACHED_CLI
    args = [tool, '-h', '127.0.0.1', '-p', str(local)] if 'redis' in tool else [tool, '127.0.0.1', str(local)]
    wt   = shutil.which('wt.exe') or shutil.which('wt')
    if wt:
        subprocess.Popen([wt,'new-tab','wsl.exe','--',*args], stdin=subprocess.DEVNULL)
    else:
        subprocess.Popen(args)
    proc.terminate()

# ----------------------------------------------------------------------------
# Main 흐름
# ----------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description='AWS EC2/RDS/ElastiCache 연결 도구 v4.3')
    parser.add_argument('-p','--profile', help='AWS 프로파일 이름')
    parser.add_argument('-d','--debug', action='store_true', help='디버그 모드')
    args = parser.parse_args()

    setup_logger(args.debug)
    profile = args.profile or choose_profile()
    manager = AWSManager(profile)

    while True:
        region = choose_region(manager)
        if not region: break
        print(f"\n==> Profile: {profile} | Region: {region} \n")
        print("1) EC2 접속")
        print("2) RDS 접속")
        print("3) ElastiCache 접속")
        sel = input("선택 (Enter=종료): ").strip().lower()
        if sel=='1': ec2_menu(manager, region)
        elif sel=='2': connect_to_rds(manager, DEFAULT_DB_TOOL_PATH, region)
        elif sel=='3': connect_to_cache(manager, region)
        else: break

if __name__ == '__main__':
    main()
