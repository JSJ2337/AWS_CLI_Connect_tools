#!/usr/bin/env python3
"""
Python 기반 EC2 메뉴 스크립트

주요 기능:
  1) AWS 프로파일 선택 및 세션 관리
  2) EC2 인스턴스가 실행 중인 리전만 병렬 조회하여 빠르게 목록화
  3) Windows: SSM 포트 포워딩 → mstsc/xfreerdp로 RDP 자동 실행
  4) Linux : SSM StartInteractiveCommand → bash -l 로그인 셸 실행
  5) 'b' 입력 시 프로파일 선택 화면으로 복귀
  6) 연결 및 프로그램 종료 시 남은 session-manager-plugin 프로세스 자동 정리
  7) 에러·디버그 로그를 ~/ec2menu.log 에 기록

사전 요구사항:
  • AWS CLI v2 설치 및 `aws sts get-caller-identity` 실행 확인
  • Session Manager Plugin 설치 (`session-manager-plugin`)
  • Windows 환경: mstsc.exe (WSL에서 실행)  
    Linux 환경: xfreerdp 또는 rdesktop 설치
  • IAM 권한: SSM StartSession, DescribeInstances, sts:GetCallerIdentity
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

# ───────────────────────────────────────────────────────────────────────
# 상수 정의
# ───────────────────────────────────────────────────────────────────────
AWS_CONFIG_PATH = Path("~/.aws/config").expanduser()
AWS_CRED_PATH   = Path("~/.aws/credentials").expanduser()
LOG_PATH        = Path("~/ec2menu.log").expanduser()

# ───────────────────────────────────────────────────────────────────────
# 로깅 설정: 콘솔 + 파일 (INFO/DEBUG)
# ───────────────────────────────────────────────────────────────────────
def setup_logger(debug: bool):
    level = logging.DEBUG if debug else logging.INFO
    fmt = "%(asctime)s [%(levelname)s] %(message)s"
    handlers = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
    ]
    logging.basicConfig(level=level, format=fmt, handlers=handlers)
    logging.debug("Logger initialized (debug=%s)", debug)

# ───────────────────────────────────────────────────────────────────────
# 플랫폼 확인
# ───────────────────────────────────────────────────────────────────────
def is_wsl() -> bool:
    return "microsoft" in platform.uname().release.lower()

# ───────────────────────────────────────────────────────────────────────
# 필수 바이너리 확인
# ───────────────────────────────────────────────────────────────────────
def verify_binary(name: str):
    if not shutil.which(name):
        logging.error("필수 바이너리 '%s' 가 없습니다.", name)
        sys.exit(1)

# ───────────────────────────────────────────────────────────────────────
# AWS 프로파일 목록 조회
# ───────────────────────────────────────────────────────────────────────
def list_aws_profiles() -> list[str]:
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

# ───────────────────────────────────────────────────────────────────────
# 프로파일 선택
# ───────────────────────────────────────────────────────────────────────
def choose_profile() -> str:
    profiles = list_aws_profiles()
    if not profiles:
        logging.error("AWS 프로파일이 없습니다.")
        sys.exit(1)
    print("\n#  Profile")
    for i, p in enumerate(profiles, 1):
        print(f" {i:2d}) {p}")
    while True:
        sel = input("번호 입력 (취소=Enter): ").strip()
        if not sel:
            sys.exit(0)
        if sel.isdigit() and 1 <= int(sel) <= len(profiles):
            return profiles[int(sel) - 1]
        print("❌ 올바른 번호를 입력하세요.")

# ───────────────────────────────────────────────────────────────────────
# boto3 세션 생성 (프로파일 검증)
# ───────────────────────────────────────────────────────────────────────
def get_session(profile: Optional[str]):
    try:
        return boto3.Session(profile_name=profile) if profile else boto3.Session()
    except ProfileNotFound as e:
        logging.error("프로파일 오류: %s", e)
        sys.exit(1)

# ───────────────────────────────────────────────────────────────────────
# 기본 포트 계산 (계정 ID 마지막 3자리)
# ───────────────────────────────────────────────────────────────────────
def compute_base_port(account_id: str) -> int:
    return 13300 + int(account_id[-3:])

# ───────────────────────────────────────────────────────────────────────
# 로컬 포트 열림 대기 (SSM 포워딩)
# ───────────────────────────────────────────────────────────────────────
def wait_for_port(port: int, timeout: int = 10) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        with socket.socket() as s:
            try:
                s.settimeout(1)
                s.connect(("localhost", port))
                return True
            except:
                time.sleep(0.5)
    return False

# ───────────────────────────────────────────────────────────────────────
# 리전별 실행 중 EC2 존재 여부 조회 (병렬)
# ───────────────────────────────────────────────────────────────────────
def has_running_ec2(region: str, session) -> Optional[str]:
    try:
        ec2 = session.client("ec2", region_name=region)
        resp = ec2.describe_instances(
            Filters=[{"Name":"instance-state-name","Values":["running"]}],
            MaxResults=5
        )
        if any(i for r in resp["Reservations"] for i in r["Instances"]):
            return region
    except Exception as e:
        logging.debug("리전 %s 조회 실패: %s", region, e)
    return None

# ───────────────────────────────────────────────────────────────────────
# 리전 선택 (실행 중인 인스턴스가 있는 리전만 표시)
# ───────────────────────────────────────────────────────────────────────
def choose_region(session, profile: str, account: str) -> Optional[str]:
    ec2g = session.client("ec2")
    all_regs = [r["RegionName"] for r in ec2g.describe_regions()["Regions"]]
    active: list[str] = []

    print("\n리전별 EC2 조회 중... (수초 소요)")
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as ex:
        futures = {ex.submit(has_running_ec2, r, session): r for r in all_regs}
        for f in concurrent.futures.as_completed(futures):
            if f.result(): active.append(f.result())
    active.sort()

    if not active:
        logging.warning("실행 중인 인스턴스가 없습니다.")
        return None

    while True:
        print(f"\n==> Profile: {profile} | Account: {account}")
        print("#  Region (EC2 존재 리전만)")
        for i, r in enumerate(active, 1):
            print(f" {i:2d}) {r}")
        sel = input("번호 입력 (b=뒤로 /cancel=Enter): ").strip()
        if not sel:        return None
        if sel.lower() == 'b': return None
        if sel.isdigit() and 1 <= int(sel) <= len(active):
            return active[int(sel) - 1]
        print("❌ 올바른 번호를 입력하세요.")

# ───────────────────────────────────────────────────────────────────────
# 인스턴스 목록 조회 (해당 리전)
# ───────────────────────────────────────────────────────────────────────
def list_instances(ec2_client) -> list[dict]:
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
    return sorted(insts, key=lambda x: x["Name"] or x["InstanceId"])

# ───────────────────────────────────────────────────────────────────────
# 인스턴스 선택 메뉴 출력
# ───────────────────────────────────────────────────────────────────────
def choose_instance(insts: list[dict]) -> Optional[Tuple[dict,int]]:
    header = (
        "#  Name                 InstanceId               AZ              "
        "Type           OS             PublicIP        PrivateIP       State"
    )
    print("\n" + header)
    for idx, inst in enumerate(insts, 1):
        print(
            f"{idx:2d}) {inst['Name']:<20} {inst['InstanceId']:<22} "
            f"{inst['AZ']:<15} {inst['Type']:<14} {inst['OS']:<15} "
            f"{inst['PublicIP']:<15} {inst['PrivateIP']:<15} {inst['State']}"
        )
    while True:
        sel = input("번호 입력 (b=뒤로 /cancel=Enter): ").strip()
        if not sel:        return None
        if sel.lower()=='b': return None
        if sel.isdigit() and 1 <= int(sel) <= len(insts):
            return insts[int(sel)-1], int(sel)
        print("❌ 올바른 번호를 입력하세요.")

# ───────────────────────────────────────────────────────────────────────
# Windows SSM 포트포워딩 명령 생성
# ───────────────────────────────────────────────────────────────────────
def port_forward_cmd(profile: str, region: str, iid: str, port: int) -> list[str]:
    params = f'{{"portNumber":["3389"],"localPortNumber":["{port}"]}}'
    cmd = [
        "aws","ssm","start-session","--region",region,
        "--target",iid,
        "--document-name","AWS-StartPortForwardingSession",
        "--parameters",params
    ]
    if profile:
        cmd[1:1] = ["--profile",profile]
    return cmd

# ───────────────────────────────────────────────────────────────────────
# Linux SSM 로그인 쉘(bash -l) 명령 생성
# ───────────────────────────────────────────────────────────────────────
def shell_cmd_bash(profile: str, region: str, iid: str) -> list[str]:
    cmd = [
        "aws","ssm","start-session","--region",region,
        "--target",iid,
        "--document-name","AWS-StartInteractiveCommand",
        "--parameters",'{"command":["bash -l"]}'
    ]
    if profile:
        cmd[1:1] = ["--profile",profile]
    return cmd

# ───────────────────────────────────────────────────────────────────────
# 메인: 프로파일 → 리전 → 인스턴스 선택 및 접속
# ───────────────────────────────────────────────────────────────────────
def main():
    readline.parse_and_bind("set convert-meta off")  # 백스페이스/한글 입력 개선

    parser = argparse.ArgumentParser()
    parser.add_argument("-p","--profile", help="AWS profile")
    parser.add_argument("-r","--region",  help="initial region")
    parser.add_argument("-d","--debug",   action="store_true", help="debug log")
    args = parser.parse_args()

    setup_logger(args.debug)
    verify_binary("session-manager-plugin")

    while True:  # ── 프로파일 루프 ──
        profile = args.profile or choose_profile()
        session = get_session(profile)
        try:
            account = session.client("sts").get_caller_identity()["Account"]
        except NoCredentialsError:
            logging.error("자격 증명 오류 – 로그인 상태 확인하세요.")
            sys.exit(1)
        base_port = compute_base_port(account)
        args.profile = profile

        while True:  # ── 리전 루프 ──
            region = args.region or choose_region(session, profile, account)
            args.region = None
            if region is None:
                # b 입력 시 프로파일 초기화 → 다음 반복에서 프로파일 선택 화면 복귀
                args.profile = None
                break

            ec2 = session.client("ec2", region_name=region)
            insts = list_instances(ec2)
            if not insts:
                print("⚠ 실행 중인 인스턴스가 없습니다.")
                continue

            while True:  # ── 인스턴스 루프 ──
                choice = choose_instance(insts)
                if choice is None:
                    break
                inst, idx = choice
                logging.info("선택: %s (%s)", inst["Name"], inst["InstanceId"])

                try:
                    if inst["OS"].startswith("Windows"):
                        # Windows: 포트포워딩 → RDP 실행 → 프로세스 terminate
                        port = base_port + idx
                        proc = subprocess.Popen(
                            port_forward_cmd(profile, region, inst["InstanceId"], port),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                        )
                        if not wait_for_port(port):
                            logging.error("터널 연결 실패 – 포트 %d", port)
                            proc.terminate()
                            continue
                        if is_wsl():
                            subprocess.run([
                                "powershell.exe","-NoProfile",
                                "-Command",f"mstsc.exe /v:localhost:{port}"
                            ])
                        else:
                            client = shutil.which("xfreerdp") or shutil.which("rdesktop")
                            if client and "xfreerdp" in client:
                                subprocess.run([client, f"/v:localhost:{port}", "/cert-ignore"])
                            elif client:
                                subprocess.run([client, f"localhost:{port}"])
                            else:
                                logging.error("RDP 클라이언트를 찾을 수 없습니다.")
                        proc.terminate()

                    else:
                        # Linux: bash 로그인 셸 실행 → exit/Ctrl+D 후 인스턴스 목록 복귀
                        subprocess.run(shell_cmd_bash(profile, region, inst["InstanceId"]))

                except KeyboardInterrupt:
                    logging.info("사용자 중단 – 세션 종료")
                except Exception as e:
                    logging.exception("세션 오류: %s", e)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logging.info("프로그램 종료")
