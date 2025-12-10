#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EC2Menu RDP 로컬 헬퍼 프로그램
웹에서 커스텀 URL 스키마를 통해 RDP 연결을 자동으로 실행합니다.

사용법:
  ec2rdp://localhost:3389
  ec2rdp://192.168.1.100:3389
"""

import sys
import subprocess
import urllib.parse
import re
import os
import logging
from pathlib import Path

# 로깅 설정
log_dir = Path.home() / "AppData" / "Local" / "EC2Menu"
log_dir.mkdir(exist_ok=True)
log_file = log_dir / "ec2rdp_helper.log"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def parse_ec2rdp_url(url):
    """ec2rdp:// URL을 파싱하여 호스트와 포트를 추출합니다."""
    try:
        # ec2rdp://localhost:3389 -> localhost:3389
        if url.startswith('ec2rdp://'):
            address = url[9:]  # 'ec2rdp://' 제거

            # IPv6 주소 처리 [::1]:3389
            if address.startswith('['):
                match = re.match(r'\[([^\]]+)\]:(\d+)', address)
                if match:
                    return match.group(1), int(match.group(2))

            # IPv4 주소나 hostname 처리 localhost:3389
            if ':' in address:
                host, port = address.rsplit(':', 1)
                return host, int(port)
            else:
                # 포트가 없으면 기본 RDP 포트 사용
                return address, 3389

    except Exception as e:
        logger.error(f"URL 파싱 오류: {e}")
        return None, None

    return None, None

def launch_mstsc(host, port):
    """mstsc.exe를 실행하여 RDP 연결을 시작합니다."""
    try:
        target = f"{host}:{port}"
        cmd = ["mstsc.exe", f"/v:{target}"]

        logger.info(f"RDP 연결 시작: {target}")
        logger.info(f"실행 명령어: {' '.join(cmd)}")

        # mstsc 실행
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.DETACHED_PROCESS
        )

        logger.info(f"mstsc 실행 완료 (PID: {process.pid})")
        return True

    except FileNotFoundError:
        logger.error("mstsc.exe를 찾을 수 없습니다. Windows RDP 클라이언트가 설치되어 있는지 확인하세요.")
        return False
    except Exception as e:
        logger.error(f"mstsc 실행 오류: {e}")
        return False

def main():
    """메인 함수"""
    if len(sys.argv) != 2:
        logger.error("사용법: ec2rdp_helper.py <ec2rdp://host:port>")
        return 1

    url = sys.argv[1]
    logger.info(f"수신된 URL: {url}")

    # URL 파싱
    host, port = parse_ec2rdp_url(url)
    if not host or not port:
        logger.error(f"잘못된 URL 형식: {url}")
        return 1

    logger.info(f"파싱 결과 - 호스트: {host}, 포트: {port}")

    # mstsc 실행
    success = launch_mstsc(host, port)
    if not success:
        return 1

    return 0

if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except Exception as e:
        logger.error(f"예상치 못한 오류: {e}")
        sys.exit(1)