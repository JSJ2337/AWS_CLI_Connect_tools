#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EC2, RDS, ElastiCache, ECS, EKS 접속 자동화 스크립트 v5.5.0 (macOS 전용)

v5.5.0 macOS 버전:
- 📊 CloudWatch 통합: 대시보드, 알람 모니터링, 로그 스트리밍
- λ  Lambda 관리: 함수 목록, 테스트 실행, 실시간 로그 조회
- 📦 S3 브라우저: 버킷/객체 탐색, 파일 업로드/다운로드

v5.5.0 macOS 버전:
- 🔒 보안 강화: shlex.quote() 적용으로 커맨드 인젝션 방지
- 🔐 macOS Keychain 연동: DB 패스워드 안전한 저장/조회
- ⚡ 성능 최적화: 리소스별 캐시 TTL 차등 적용
- 📄 페이지네이션: 대량 결과 20개씩 페이지 단위 표시
- 🛠️ 코드 품질: 헬퍼 함수 추출, 배치 에러 추적 개선
- 🖥️ UX 개선: 명령줄 옵션 추가, 메뉴별 도움말 시스템

v5.3.0 macOS 버전:
- ☸️ EKS 클러스터 관리 기능 추가 (클러스터, 노드그룹, Fargate 프로필)
- 📦 kubectl 연동: Pod 목록/로그/exec 접속 (kubectl 설치 시 자동 활성화)
- 🌐 AWS CloudShell 브라우저 열기 기능
- ⚙️ kubeconfig 자동 설정

v5.2.0 macOS 버전:
- 🍎 macOS 네이티브 지원 (pathlib 경로 처리)
- 🖥️ iTerm2/Terminal.app 통합 (새 탭에서 자동 접속)
- 🪟 Windows App을 통한 RDP 접속 (.rdp 파일 자동 생성)
- 🗑️ WSL/Windows 관련 코드 제거

주요 기능:
- 📁 S3 경유 파일 전송: 대용량 파일 (80MB+) 업로드/다운로드
- 🚀 배치 작업: 여러 인스턴스에 동시 명령 실행
- 📊 진행률 표시: 실시간 전송 상태 및 속도
- 🎨 컬러 테마: 상태별 색깔 구분 (running=녹색, stopped=빨강)
- 🗄️ 멀티 리전 통합 뷰 (여러 리전의 인스턴스 한 번에 조회)
- 📜 연결 히스토리 (최근 접속한 인스턴스 기록 및 빠른 재접속)
- 🐳 ECS Fargate 컨테이너 접속 (ECS Exec 활용)
- ☸️ EKS 클러스터 관리 (boto3 + kubectl 연동)
- 🔑 DB 비밀번호 Keychain 저장 (macOS 보안 저장소)
- 🏃 Role=jumphost 태그 기반 점프 호스트 자동 선택
"""
from __future__ import annotations  # Python 3.9 이하 호환성

import argparse
import atexit
import concurrent.futures
import configparser
import getpass
import json
import logging
import os
import platform
import re
import readline
import shlex
import socket
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, Generator, List, Optional, Tuple

import boto3
from botocore.exceptions import ClientError, ProfileNotFound, NoCredentialsError

# 컬러 지원 라이브러리
try:
    from colorama import init, Fore, Back, Style
    init(autoreset=True)  # 색상 자동 리셋
    COLOR_SUPPORT = True
except ImportError:
    print("💡 더 나은 사용자 경험을 위해 colorama를 설치하세요: pip install colorama")
    COLOR_SUPPORT = False
    # colorama가 없을 때 빈 클래스로 대체
    class MockColor:
        def __getattr__(self, name): return ""
    Fore = Back = Style = MockColor()

# 화살표 키 메뉴 라이브러리 (v5.5.0 simple-term-menu로 교체)
try:
    from simple_term_menu import TerminalMenu
    TERM_MENU_SUPPORT = True
except ImportError:
    print("💡 화살표 키 메뉴를 위해 simple-term-menu를 설치하세요: pip install simple-term-menu")
    TERM_MENU_SUPPORT = False

# ----------------------------------------------------------------------------
# 컬러 테마 설정 (v5.0.2 원본)
# ----------------------------------------------------------------------------
class Colors:
    # 서비스별 색깔
    EC2 = Fore.BLUE
    RDS = Fore.YELLOW
    CACHE = Fore.MAGENTA
    ECS = Fore.CYAN
    EKS = Fore.GREEN  # EKS 전용 색상
    
    # 상태별 색깔
    RUNNING = Fore.GREEN
    STOPPED = Fore.RED
    PENDING = Fore.YELLOW
    WARNING = Fore.YELLOW
    ERROR = Fore.RED
    SUCCESS = Fore.GREEN
    INFO = Fore.CYAN
    
    # UI 요소
    HEADER = Style.BRIGHT + Fore.WHITE
    MENU = Fore.WHITE
    PROMPT = Fore.CYAN
    RESET = Style.RESET_ALL

def colored_text(text: str, color: str = "") -> str:
    """색깔 적용된 텍스트 반환"""
    if COLOR_SUPPORT and color:
        return f"{color}{text}{Colors.RESET}"
    return text

def get_status_color(status: str) -> str:
    """상태에 따른 색깔 반환"""
    status_lower = status.lower()
    if status_lower in ['running', 'available', 'active']:
        return Colors.RUNNING
    elif status_lower in ['stopped', 'terminated', 'inactive']:
        return Colors.STOPPED
    elif status_lower in ['pending', 'starting', 'stopping']:
        return Colors.PENDING
    return ""

# ----------------------------------------------------------------------------
# 캐싱 시스템 (v5.1.0 신규)
# ----------------------------------------------------------------------------
@dataclass
class CacheEntry:
    data: Any
    timestamp: datetime
    ttl_seconds: int = 300  # Config.CACHE_TTL_SECONDS로 설정됨

    def is_expired(self) -> bool:
        return datetime.now() - self.timestamp > timedelta(seconds=self.ttl_seconds)

class PerformanceCache:
    def __init__(self):
        self._cache: Dict[str, CacheEntry] = {}
        self._lock = threading.RLock()
        self._background_refresh_active = {}

    def _get_ttl_for_key(self, key: str) -> int:
        """캐시 키에서 리소스 타입을 추출하여 적절한 TTL 반환 (v5.5.0)"""
        # 캐시 키 형식: {resource_type}_{profile}_{region}...
        resource_type = key.split('_')[0].lower() if '_' in key else 'default'
        return Config.CACHE_TTLS.get(resource_type, Config.CACHE_TTLS['default'])

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            entry = self._cache.get(key)
            if entry and not entry.is_expired():
                return entry.data
            return None

    def set(self, key: str, data: Any, ttl_seconds: Optional[int] = None):
        if ttl_seconds is None:
            # 리소스 타입에 따라 자동으로 TTL 결정 (v5.5.0)
            ttl_seconds = self._get_ttl_for_key(key)
        with self._lock:
            self._cache[key] = CacheEntry(data, datetime.now(), ttl_seconds)
    
    def invalidate(self, key: str):
        with self._lock:
            self._cache.pop(key, None)
    
    def clear(self):
        with self._lock:
            self._cache.clear()
    
    def start_background_refresh(self, key: str, refresh_func, *args, **kwargs):
        """백그라운드에서 캐시 새로고침 (스레드 안전)"""
        with self._lock:
            if key in self._background_refresh_active:
                return
            self._background_refresh_active[key] = True

        def refresh_worker():
            try:
                new_data = refresh_func(*args, **kwargs)
                self.set(key, new_data)
            except Exception as e:
                logging.warning(f"백그라운드 새로고침 실패 ({key}): {e}")
            finally:
                with self._lock:
                    self._background_refresh_active.pop(key, None)

        threading.Thread(target=refresh_worker, daemon=True).start()

# 전역 캐시 인스턴스
_cache = PerformanceCache()

# ----------------------------------------------------------------------------
# 플랫폼 감지 함수 (v5.2.0 macOS 버전)
# ----------------------------------------------------------------------------

# 플랫폼 상수 (macOS 전용)
IS_MAC = platform.system() == 'Darwin'

def normalize_file_path(path_str: str) -> str:
    """파일 경로 정규화 (따옴표 제거, 경로 확장)"""
    # 따옴표 제거
    if (path_str.startswith('"') and path_str.endswith('"')) or \
       (path_str.startswith("'") and path_str.endswith("'")):
        path_str = path_str[1:-1]

    # pathlib로 경로 정규화 및 확장
    return str(Path(path_str).expanduser().resolve())

# ----------------------------------------------------------------------------
# 설정 및 기본값 (v5.2.0 macOS 버전)
# ----------------------------------------------------------------------------

class Config:
    """애플리케이션 설정 (매직 넘버 제거 및 중앙 관리)"""
    # 파일 경로
    AWS_CONFIG_PATH = Path("~/.aws/config").expanduser()
    AWS_CRED_PATH = Path("~/.aws/credentials").expanduser()
    LOG_PATH = Path.home() / ".ec2menu.log"
    HISTORY_PATH = Path.home() / ".ec2menu_history.json"
    BATCH_RESULTS_PATH = Path.home() / ".ec2menu_batch_results.json"

    # 성능 설정
    DEFAULT_WORKERS: int = 20
    CACHE_TTL_SECONDS: int = 300  # 5분 (기본값)

    # 리소스별 캐시 TTL (v5.5.0 신규, v5.5.0 확장)
    CACHE_TTLS = {
        'instances': 120,      # EC2 인스턴스: 2분 (자주 변경됨)
        'ssm': 120,            # SSM 관리 인스턴스: 2분
        'rds': 300,            # RDS: 5분
        'elasticache': 300,    # ElastiCache: 5분
        'ecs': 600,            # ECS 클러스터/서비스: 10분
        'eks': 600,            # EKS 클러스터: 10분
        'regions': 3600,       # 리전 목록: 1시간
        # v5.5.0 신규 서비스
        'cloudwatch_dashboards': 600,  # CloudWatch 대시보드: 10분
        'cloudwatch_alarms': 120,      # CloudWatch 알람: 2분 (상태 변경 빈번)
        'cloudwatch_logs': 60,         # CloudWatch 로그: 1분 (실시간성)
        'lambda': 300,                 # Lambda 함수: 5분
        's3_buckets': 600,             # S3 버킷: 10분
        's3_objects': 60,              # S3 객체: 1분
        'default': 300,        # 기본값: 5분
    }

    # 메뉴 페이지네이션 설정 (v5.5.0 신규)
    MENU_PAGE_SIZE = 20  # 메뉴에서 한 번에 표시할 항목 수

    # 배치 작업 설정
    BATCH_MAX_RETRIES = 3  # SSM 명령 전송 재시도 횟수
    BATCH_COMMAND_RETRY = 3  # 명령 실행 실패 시 재시도 횟수 (5 → 3)
    BATCH_RETRY_DELAY = 10  # 재시도 간 기본 대기 시간 (3초 → 10초)
    BATCH_RETRY_MAX_DELAY = 60  # 최대 대기 시간 (초)
    BATCH_TIMEOUT_SECONDS = 600  # 10분
    BATCH_MAX_WAIT_ATTEMPTS = 200
    BATCH_CONCURRENT_JOBS = 5  # 동시 실행 수 (기본 모드)

    # 페이지네이션 설정
    EC2_PAGE_SIZE = 100
    MAX_PAGINATION_PAGES = 100

    # 포트 설정
    PORT_RANGE_START = 10000
    PORT_RANGE_END = 11000
    RDS_PORT_START = 11000

    # 파일 크기 변환
    BYTES_PER_KB = 1024

    # SSM 설정
    SSM_TIMEOUT_SECONDS = 600

    # 히스토리 설정
    HISTORY_MAX_SIZE = 100

    # 입력 재시도 설정
    MAX_INPUT_RETRIES = 5  # 잘못된 입력 최대 5회까지 허용

    # 대기 시간 설정 (초)
    WAIT_PORT_READY = 2  # 포트 포워딩 준비 대기
    WAIT_APP_LAUNCH = 0.8  # 애플리케이션 실행 대기
    WAIT_RDP_READY = 2  # RDP 클라이언트 준비 대기

    # macOS용 도구 경로 (환경변수 우선)
    DB_TOOL_PATH = os.environ.get('DB_TOOL_PATH', "mysql")
    DBEAVER_PATH = os.environ.get('DBEAVER_PATH', '/Applications/DBeaver.app/Contents/MacOS/dbeaver')
    CACHE_REDIS_CLI = os.environ.get('CACHE_REDIS_CLI', "redis-cli")
    CACHE_MEMCACHED_CLI = os.environ.get('CACHE_MEMCACHED_CLI', "telnet")

    # 디버그 모드
    DEBUG_MODE = os.environ.get('EC2MENU_DEBUG', '0') == '1'

# 하위 호환성을 위한 별칭
AWS_CONFIG_PATH = Config.AWS_CONFIG_PATH
AWS_CRED_PATH = Config.AWS_CRED_PATH
LOG_PATH = Config.LOG_PATH
HISTORY_PATH = Config.HISTORY_PATH
BATCH_RESULTS_PATH = Config.BATCH_RESULTS_PATH
DEFAULT_WORKERS = Config.DEFAULT_WORKERS
DEFAULT_DB_TOOL_PATH = Config.DB_TOOL_PATH
DEFAULT_CACHE_REDIS_CLI = Config.CACHE_REDIS_CLI
DEFAULT_CACHE_MEMCACHED_CLI = Config.CACHE_MEMCACHED_CLI

# 전역 변수
_stored_credentials = {}  # 하위 호환성을 위해 유지 (Keychain 우선 사용)
_sort_key = 'Name'  # 기본 정렬 키
_sort_reverse = False  # 기본 오름차순
_temp_files_to_cleanup: list[Path] = []  # 프로그램 종료 시 삭제할 임시 파일
_temp_files_lock = threading.Lock()  # 동시성 보호

# ----------------------------------------------------------------------------
# macOS Keychain 자격 증명 관리 (v5.5.0 신규)
# ----------------------------------------------------------------------------
class KeychainManager:
    """macOS Keychain을 사용한 안전한 자격 증명 관리"""
    SERVICE_PREFIX = "ec2menu-db"
    _session_credentials: Dict[str, str] = {}  # 메모리 캐시 (성능 최적화)

    @staticmethod
    def store(account: str, password: str, use_keychain: bool = True) -> bool:
        """자격 증명을 Keychain에 저장 (옵션에 따라 메모리만 사용 가능)"""
        service = f"{KeychainManager.SERVICE_PREFIX}"
        KeychainManager._session_credentials[account] = password

        if not use_keychain:
            return True

        try:
            # 기존 항목이 있으면 삭제 후 새로 추가 (-U 옵션 대신 명시적 삭제)
            subprocess.run(
                ['security', 'delete-generic-password', '-a', account, '-s', service],
                capture_output=True, check=False  # 없으면 무시
            )
            result = subprocess.run(
                ['security', 'add-generic-password', '-a', account, '-s', service, '-w', password],
                capture_output=True, text=True
            )
            if result.returncode != 0:
                logging.warning(f"Keychain 저장 실패: {result.stderr}")
                return False
            logging.debug(f"Keychain에 자격 증명 저장 완료: {account}")
            return True
        except Exception as e:
            logging.warning(f"Keychain 저장 중 오류: {e}")
            return False

    @staticmethod
    def get(account: str) -> Optional[str]:
        """Keychain에서 자격 증명 조회 (메모리 캐시 우선)"""
        # 메모리 캐시에서 먼저 조회 (성능 최적화)
        if account in KeychainManager._session_credentials:
            return KeychainManager._session_credentials[account]

        service = f"{KeychainManager.SERVICE_PREFIX}"
        try:
            result = subprocess.run(
                ['security', 'find-generic-password', '-a', account, '-s', service, '-w'],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                password = result.stdout.strip()
                KeychainManager._session_credentials[account] = password
                return password
            return None
        except Exception as e:
            logging.warning(f"Keychain 조회 중 오류: {e}")
            return None

    @staticmethod
    def delete(account: str) -> bool:
        """Keychain에서 자격 증명 삭제"""
        service = f"{KeychainManager.SERVICE_PREFIX}"
        KeychainManager._session_credentials.pop(account, None)

        try:
            result = subprocess.run(
                ['security', 'delete-generic-password', '-a', account, '-s', service],
                capture_output=True, text=True
            )
            return result.returncode == 0
        except Exception as e:
            logging.warning(f"Keychain 삭제 중 오류: {e}")
            return False

    @staticmethod
    def clear_session():
        """세션 메모리 캐시만 삭제 (Keychain은 유지)"""
        KeychainManager._session_credentials.clear()

    @staticmethod
    def has_credentials(account: str) -> bool:
        """자격 증명이 있는지 확인"""
        return KeychainManager.get(account) is not None

# ----------------------------------------------------------------------------
# 유틸리티 함수
# ----------------------------------------------------------------------------
def calculate_local_port(instance_id: str) -> int:
    """인스턴스 ID로부터 고유한 로컬 포트 번호 생성"""
    id_hash = int(instance_id[-3:], 16) % (Config.PORT_RANGE_END - Config.PORT_RANGE_START)
    return Config.PORT_RANGE_START + id_hash

# ----------------------------------------------------------------------------
# 화살표 키 네비게이션 메뉴 (v5.5.0 simple-term-menu 기반으로 교체)
# ----------------------------------------------------------------------------
def interactive_select(
    items: List[str],
    title: str = "",
    footer: str = "",
    show_index: bool = True
) -> int:
    """
    simple-term-menu 기반 화살표 키 네비게이션 메뉴

    Args:
        items: 표시할 항목 리스트
        title: 메뉴 제목
        footer: 하단 상태바 (사용되지 않음, 호환성 유지)
        show_index: 인덱스 표시 여부

    Returns:
        선택된 인덱스 (0-based), 취소 시 -1
    """
    if not items:
        return -1

    # simple-term-menu 사용 가능한 경우
    if TERM_MENU_SUPPORT:
        try:
            # 숫자/알파벳 단축키 포함한 항목 생성
            # simple-term-menu는 [X] 형식을 맨 앞에서 자동으로 단축키로 인식
            # 1-9, 0, a-z 순서로 단축키 할당 (최대 36개)
            display_items = []
            for i, item in enumerate(items):
                if i < 9:
                    shortcut = f"[{i+1}]"  # 1-9
                elif i == 9:
                    shortcut = "[0]"  # 0 = 10번째
                elif i < 36:  # 11-36번째: a-z
                    shortcut = f"[{chr(ord('a') + i - 10)}]"  # a, b, c, ...
                else:
                    shortcut = "   "  # 37번째 이후는 단축키 없음
                # 단축키는 맨 앞에, 여백은 단축키 뒤에 추가
                display_items.append(f"{shortcut}   {item}")

            # 제목 스타일링 (더 넓은 구분선, 여백 추가)
            styled_title = None
            if title:
                line = '═' * 70
                styled_title = f"\n{line}\n    {title}\n{line}\n"

            menu = TerminalMenu(
                display_items,
                title=styled_title,
                menu_cursor="  ▶ ",  # 커서
                menu_cursor_style=("fg_cyan", "bold"),
                menu_highlight_style=("standout", "bold"),  # 반전 + 굵게
                search_key="/",
                quit_keys=("escape", "q"),
                clear_screen=False,  # 화면 전체 지우기 비활성화
                shortcut_key_highlight_style=("fg_cyan", "bold"),
                shortcut_brackets_highlight_style=("fg_gray",),
            )
            result = menu.show()
            return result if result is not None else -1
        except Exception as e:
            # simple-term-menu 실패 시 폴백
            print(colored_text(f"\n⚠️ 메뉴 초기화 실패, 번호 입력 모드로 전환: {e}", Colors.WARNING))
            return _fallback_menu(items, title, show_index)
    else:
        # simple-term-menu 없으면 폴백
        return _fallback_menu(items, title, show_index)


def _fallback_menu(items: List[str], title: str = "", show_index: bool = True) -> int:
    """simple-term-menu 없을 때 폴백 메뉴"""
    if title:
        print(colored_text(f"\n{title}", Colors.HEADER))
        print("-" * 40)

    for i, item in enumerate(items):
        if show_index:
            print(f"  {i + 1}) {item}")
        else:
            print(f"  {item}")

    print()
    sel = input(colored_text("선택 (번호, q=취소): ", Colors.PROMPT)).strip()

    if sel.lower() == 'q' or sel.lower() == 'b' or not sel:
        return -1

    if sel.isdigit():
        idx = int(sel) - 1
        if 0 <= idx < len(items):
            return idx

    return -1


# 하위 호환성을 위한 InteractiveMenu 클래스 래퍼
class InteractiveMenu:
    """하위 호환성을 위한 래퍼 클래스 (simple-term-menu 사용)"""

    def __init__(
        self,
        items: List[str],
        title: str = "",
        footer: str = "",
        selected_idx: int = 0,
        show_index: bool = True,
        page_size: int = 0
    ):
        self.items = items
        self.title = title
        self.footer = footer
        self.selected_idx = selected_idx
        self.show_index = show_index
        self.page_size = page_size

    def run(self) -> int:
        """메뉴 실행"""
        return interactive_select(
            self.items,
            title=self.title,
            footer=self.footer,
            show_index=self.show_index
        )


# ----------------------------------------------------------------------------
# 메뉴 입력 검증 헬퍼 (v5.5.0 신규)
# ----------------------------------------------------------------------------
def get_menu_choice(
    prompt: str,
    max_num: int,
    special_keys: Optional[Dict[str, str]] = None,
    allow_empty: bool = True
) -> Tuple[str, Optional[int]]:
    """
    메뉴 선택 입력 처리 헬퍼

    Args:
        prompt: 입력 프롬프트
        max_num: 최대 선택 가능한 숫자
        special_keys: 특수 키 매핑 (예: {'b': 'back', 'r': 'refresh'})
        allow_empty: 빈 입력 허용 여부

    Returns:
        (action, number): action은 'number', 'back', 'refresh', 'empty', 'invalid' 등
                          number는 숫자 선택 시 값 (1-based)
    """
    if special_keys is None:
        special_keys = {'b': 'back', 'r': 'refresh'}

    sel = input(colored_text(prompt, Colors.PROMPT)).strip().lower()

    if not sel:
        return ('empty', None) if allow_empty else ('invalid', None)

    if sel in special_keys:
        return (special_keys[sel], None)

    if sel.isdigit():
        num = int(sel)
        if 1 <= num <= max_num:
            return ('number', num)

    return ('invalid', None)

# ----------------------------------------------------------------------------
# 페이지네이션 헬퍼 (v5.5.0 신규)
# ----------------------------------------------------------------------------
def paginate_display(
    items: List[Any],
    display_func: Callable[[int, Any], str],
    title: str = "",
    page_size: int = 0
) -> Optional[Tuple[int, Any]]:
    """
    리스트를 페이지 단위로 표시하고 사용자 선택을 받음

    Args:
        items: 표시할 항목 리스트
        display_func: 항목을 문자열로 변환하는 함수 (index, item) -> str
        title: 페이지 상단에 표시할 제목
        page_size: 페이지당 항목 수 (0이면 Config.MENU_PAGE_SIZE 사용)

    Returns:
        (index, item): 선택된 항목의 인덱스와 항목, 취소 시 None
    """
    if page_size <= 0:
        page_size = Config.MENU_PAGE_SIZE

    total_items = len(items)
    if total_items == 0:
        return None

    total_pages = (total_items + page_size - 1) // page_size
    current_page = 0

    while True:
        start_idx = current_page * page_size
        end_idx = min(start_idx + page_size, total_items)
        page_items = items[start_idx:end_idx]

        # 제목 표시
        if title:
            print(colored_text(f"\n{title}", Colors.HEADER))

        # 현재 페이지 항목 표시
        for i, item in enumerate(page_items):
            global_idx = start_idx + i + 1
            print(display_func(global_idx, item))

        # 페이지 정보 및 네비게이션
        if total_pages > 1:
            nav_hint = []
            if current_page > 0:
                nav_hint.append("p=이전")
            if current_page < total_pages - 1:
                nav_hint.append("n=다음")
            nav_str = ", ".join(nav_hint)
            print(colored_text(f"\n[Page {current_page + 1}/{total_pages}] {nav_str}, b=뒤로", Colors.INFO))

        # 사용자 입력
        prompt = f"선택 (1-{total_items}, b=뒤로): "
        sel = input(colored_text(prompt, Colors.PROMPT)).strip().lower()

        if not sel or sel == 'b':
            return None
        elif sel == 'n' and current_page < total_pages - 1:
            current_page += 1
        elif sel == 'p' and current_page > 0:
            current_page -= 1
        elif sel.isdigit():
            idx = int(sel)
            if 1 <= idx <= total_items:
                return (idx - 1, items[idx - 1])
            else:
                print(colored_text("❌ 유효한 번호를 입력하세요.", Colors.ERROR))
        else:
            print(colored_text("❌ 유효한 입력이 아닙니다.", Colors.ERROR))

# ----------------------------------------------------------------------------
# 로거 설정 (v4.40 수정)
# ----------------------------------------------------------------------------
def setup_logger(debug: bool) -> None:
    """로깅 설정 초기화"""
    level = logging.DEBUG if debug else logging.INFO
    fmt   = "%(asctime)s [%(levelname)s] %(message)s"
    handlers = [logging.StreamHandler(sys.stdout), logging.FileHandler(LOG_PATH, encoding="utf-8")]
    # style='%'를 명시하여 boto3 내부 로그와의 충돌 방지
    logging.basicConfig(level=level, format=fmt, handlers=handlers, style='%')

def cleanup_temp_files() -> None:
    """프로그램 종료 시 임시 파일 정리"""
    with _temp_files_lock:
        for file_path in _temp_files_to_cleanup:
            try:
                if file_path.exists():
                    file_path.unlink()
                    logging.info(f"임시 파일 삭제됨: {file_path}")
            except Exception as e:
                logging.warning(f"임시 파일 삭제 실패: {file_path} - {e}")

# 프로그램 종료 시 자동 정리 등록
atexit.register(cleanup_temp_files)

# ----------------------------------------------------------------------------
# 파일 전송 관리 (v5.1.3 신규)
# ----------------------------------------------------------------------------
@dataclass
class FileTransferResult:
    """파일 전송 결과"""
    instance_id: str
    instance_name: str
    local_path: str
    remote_path: str
    file_size: int
    status: str  # SUCCESS, FAILED, TIMEOUT
    error_message: str = ""
    transfer_time: float = 0.0
    timestamp: datetime | None = None

class FileTransferManager:
    def __init__(self, manager):
        self.aws_manager = manager
        self.temp_bucket = None
        self.transfer_history: List[FileTransferResult] = []
        # atexit에 버킷 정리 함수 등록
        atexit.register(self.cleanup_temp_bucket)
    
    def get_or_create_temp_bucket(self):
        """임시 S3 버킷 생성 또는 기존 버킷 사용"""
        if self.temp_bucket:
            return self.temp_bucket
            
        try:
            s3 = self.aws_manager.session.client('s3')
            
            # 버킷 이름 생성 (계정 ID + 랜덤)
            account_id = self.aws_manager.session.client('sts').get_caller_identity()['Account']
            bucket_name = f"ec2menu-temp-{account_id}-{uuid.uuid4().hex[:8]}"
            
            # 버킷 생성 (리전에 따른 LocationConstraint 설정)
            region = self.aws_manager.session.region_name or 'us-east-1'
            if region == 'us-east-1':
                s3.create_bucket(Bucket=bucket_name)
            else:
                s3.create_bucket(
                    Bucket=bucket_name,
                    CreateBucketConfiguration={'LocationConstraint': region}
                )
            
            # 공개 접근 차단 설정 (보안 강화)
            s3.put_public_access_block(
                Bucket=bucket_name,
                PublicAccessBlockConfiguration={
                    'BlockPublicAcls': True,
                    'IgnorePublicAcls': True,
                    'BlockPublicPolicy': True,
                    'RestrictPublicBuckets': True
                }
            )

            # 수명 주기 정책 설정 (1일 후 자동 삭제)
            lifecycle_config = {
                'Rules': [{
                    'ID': 'temp-files-cleanup',
                    'Status': 'Enabled',
                    'Expiration': {'Days': 1},
                    'Filter': {'Prefix': 'temp-files/'}
                }]
            }
            s3.put_bucket_lifecycle_configuration(
                Bucket=bucket_name,
                LifecycleConfiguration=lifecycle_config
            )

            self.temp_bucket = bucket_name
            print(colored_text(f"✅ 임시 S3 버킷 생성: {bucket_name}", Colors.SUCCESS))
            return bucket_name
            
        except ClientError as e:
            print(colored_text(f"❌ S3 버킷 생성 실패: {str(e)}", Colors.ERROR))
            return None
    
    def upload_file_to_s3(self, local_path: str, s3_key: str) -> bool:
        """로컬 파일을 S3에 업로드"""
        try:
            s3 = self.aws_manager.session.client('s3')
            bucket_name = self.get_or_create_temp_bucket()
            
            if not bucket_name:
                return False
            
            file_size = os.path.getsize(local_path)
            print(colored_text(f"📤 S3 업로드 시작: {os.path.basename(local_path)} ({self._format_size(file_size)})", Colors.INFO))
            
            start_time = time.time()
            
            # S3 업로드 (진행률 콜백 포함)
            def progress_callback(bytes_transferred):
                progress = (bytes_transferred / file_size) * 100
                elapsed = time.time() - start_time
                speed = bytes_transferred / elapsed if elapsed > 0 else 0
                print(f"\r📊 업로드 진행: {progress:.1f}% ({self._format_size(bytes_transferred)}/{self._format_size(file_size)}) - {self._format_speed(speed)}", end="", flush=True)
            
            s3.upload_file(
                local_path, bucket_name, s3_key,
                Callback=progress_callback
            )
            
            print()  # 새 줄
            elapsed = time.time() - start_time
            print(colored_text(f"✅ S3 업로드 완료 - {elapsed:.1f}초", Colors.SUCCESS))
            return True
            
        except Exception as e:
            print(colored_text(f"❌ S3 업로드 실패: {str(e)}", Colors.ERROR))
            return False
    
    def download_file_from_s3_to_ec2(self, s3_key: str, remote_path: str, instance_id: str, instance_name: str) -> FileTransferResult:
        """S3에서 EC2로 파일 다운로드"""
        start_time = time.time()
        
        try:
            bucket_name = self.temp_bucket
            if not bucket_name:
                return FileTransferResult(
                    instance_id=instance_id,
                    instance_name=instance_name,
                    local_path="",
                    remote_path=remote_path,
                    file_size=0,
                    status="FAILED",
                    error_message="S3 버킷이 준비되지 않음",
                    timestamp=datetime.now()
                )
            
            # S3에서 EC2로 다운로드 명령 (v5.5.0: shlex.quote 적용으로 인젝션 방지)
            safe_s3_key = shlex.quote(s3_key)
            safe_remote_path = shlex.quote(remote_path)

            if Config.DEBUG_MODE:
                # 디버그 모드: 상세 로그 출력
                command = f"""
                echo "=== 파일 전송 시작 ==="
                echo "S3 버킷: {bucket_name}"
                echo "S3 키: {safe_s3_key}"
                echo "대상 경로: {safe_remote_path}"

                # AWS CLI 설치 확인
                echo "=== AWS CLI 확인 ==="
                which aws || echo "AWS CLI not found"
                aws --version 2>/dev/null || echo "AWS CLI version check failed"

                # IAM 역할 확인
                echo "=== IAM 역할 확인 ==="
                aws sts get-caller-identity 2>/dev/null || echo "IAM role check failed"

                # S3 버킷 접근 확인
                echo "=== S3 버킷 접근 확인 ==="
                aws s3 ls s3://{bucket_name}/ 2>/dev/null || echo "S3 bucket access failed"

                # 파일 다운로드
                echo "=== 파일 다운로드 ==="
                aws s3 cp s3://{bucket_name}/{safe_s3_key} {safe_remote_path} --debug 2>&1

                # 결과 확인
                echo "=== 결과 확인 ==="
                if [ -f {safe_remote_path} ]; then
                    echo "TRANSFER_SUCCESS: $(ls -l {safe_remote_path} | awk '{{print $5}}')"
                    echo "File exists: YES"
                else
                    echo "TRANSFER_SUCCESS: 0"
                    echo "File exists: NO"
                fi
                echo "=== 전송 완료 ==="
                """
            else:
                # 프로덕션 모드: 간결한 출력 (v5.5.0: shlex.quote 적용)
                command = f"""
                aws s3 cp s3://{bucket_name}/{safe_s3_key} {safe_remote_path} 2>&1
                if [ -f {safe_remote_path} ]; then
                    echo "TRANSFER_SUCCESS: $(ls -l {safe_remote_path} | awk '{{print $5}}')"
                else
                    echo "TRANSFER_FAILED"
                fi
                """
            
            ssm = self.aws_manager.session.client('ssm')
            response = ssm.send_command(
                InstanceIds=[instance_id],
                DocumentName='AWS-RunShellScript',
                Parameters={'commands': [command]},
                TimeoutSeconds=600  # 10분 타임아웃
            )
            
            command_id = response['Command']['CommandId']
            
            # 명령 완료 대기
            max_wait = 300  # 5분
            waited = 0
            
            while waited < max_wait:
                try:
                    result = ssm.get_command_invocation(
                        CommandId=command_id,
                        InstanceId=instance_id
                    )
                    
                    status = result['Status']
                    if status in ['Success', 'Failed', 'Cancelled', 'TimedOut']:
                        execution_time = time.time() - start_time
                        
                        if status == 'Success':
                            output = result.get('StandardOutputContent', '')
                            error_output = result.get('StandardErrorContent', '')
                            
                            # 디버깅: 전체 출력 표시
                            print(colored_text(f"🔍 SSM 명령 출력:", Colors.INFO))
                            print(colored_text(f"STDOUT:\n{output}", Colors.INFO))
                            if error_output:
                                print(colored_text(f"STDERR:\n{error_output}", Colors.WARNING))
                            
                            # 파일 크기 추출
                            file_size = 0
                            for line in output.split('\n'):
                                if line.startswith('TRANSFER_SUCCESS:'):
                                    try:
                                        file_size = int(line.split(':')[1].strip())
                                    except:
                                        pass
                            
                            return FileTransferResult(
                                instance_id=instance_id,
                                instance_name=instance_name,
                                local_path="",
                                remote_path=remote_path,
                                file_size=file_size,
                                status="SUCCESS",
                                transfer_time=execution_time,
                                timestamp=datetime.now()
                            )
                        else:
                            output = result.get('StandardOutputContent', '')
                            error_msg = result.get('StandardErrorContent', '알 수 없는 오류')
                            
                            # 디버깅: 실패 시에도 전체 출력 표시
                            print(colored_text(f"❌ SSM 명령 실패 ({status}):", Colors.ERROR))
                            print(colored_text(f"STDOUT:\n{output}", Colors.INFO))
                            print(colored_text(f"STDERR:\n{error_msg}", Colors.ERROR))
                            
                            return FileTransferResult(
                                instance_id=instance_id,
                                instance_name=instance_name,
                                local_path="",
                                remote_path=remote_path,
                                file_size=0,
                                status="FAILED",
                                error_message=error_msg,
                                transfer_time=execution_time,
                                timestamp=datetime.now()
                            )
                    
                    time.sleep(3)
                    waited += 3
                    
                except ClientError:
                    time.sleep(Config.WAIT_PORT_READY)
                    waited += 2
                    continue
            
            # 타임아웃
            return FileTransferResult(
                instance_id=instance_id,
                instance_name=instance_name,
                local_path="",
                remote_path=remote_path,
                file_size=0,
                status="TIMEOUT",
                error_message=f"명령 실행 타임아웃 ({max_wait}초)",
                transfer_time=time.time() - start_time,
                timestamp=datetime.now()
            )
            
        except Exception as e:
            return FileTransferResult(
                instance_id=instance_id,
                instance_name=instance_name,
                local_path="",
                remote_path=remote_path,
                file_size=0,
                status="FAILED",
                error_message=str(e),
                transfer_time=time.time() - start_time,
                timestamp=datetime.now()
            )
    
    def upload_file_to_multiple_instances(self, local_path: str, remote_path: str, instances: List[dict]) -> List[FileTransferResult]:
        """여러 인스턴스에 파일 업로드 (macOS용)"""
        # 경로 정규화 (따옴표 제거 및 확장)
        local_path = normalize_file_path(local_path)

        # 파일 존재 확인
        local_path_obj = Path(local_path)
        if not local_path_obj.exists():
            print(colored_text(f"❌ 로컬 파일이 존재하지 않습니다: {local_path}", Colors.ERROR))
            return []
        
        # S3 키 생성
        filename = os.path.basename(local_path)
        s3_key = f"temp-files/{uuid.uuid4().hex}/{filename}"
        
        # S3에 업로드
        if not self.upload_file_to_s3(local_path, s3_key):
            return []
        
        print(colored_text(f"\n🚀 {len(instances)}개 인스턴스에 파일 전송 시작", Colors.INFO))

        results = []

        try:
            # 병렬로 각 인스턴스에 다운로드
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(instances), 5)) as executor:
                future_to_instance = {
                    executor.submit(
                        self.download_file_from_s3_to_ec2,
                        s3_key, remote_path,
                        inst['raw']['InstanceId'],
                        inst['Name']
                    ): inst
                    for inst in instances
                }

                for future in concurrent.futures.as_completed(future_to_instance):
                    try:
                        result = future.result()
                        results.append(result)

                        # 실시간 결과 출력
                        status_color = Colors.SUCCESS if result.status == 'SUCCESS' else Colors.ERROR
                        size_str = self._format_size(result.file_size) if result.file_size > 0 else ""
                        print(f"{colored_text(result.status, status_color)} {result.instance_name} ({result.instance_id}) {size_str} - {result.transfer_time:.1f}s")

                    except Exception as e:
                        instance = future_to_instance[future]
                        print(colored_text(f"ERROR {instance['Name']} ({instance['raw']['InstanceId']}) - {str(e)}", Colors.ERROR))

            # 결과 저장
            self.transfer_history.extend(results)

            return results

        finally:
            # 항상 S3 임시 파일 정리 (예외 발생 여부와 무관)
            self.cleanup_s3_file(s3_key)
    
    def cleanup_s3_file(self, s3_key: str):
        """S3 임시 파일 삭제"""
        try:
            if self.temp_bucket:
                s3 = self.aws_manager.session.client('s3')
                s3.delete_object(Bucket=self.temp_bucket, Key=s3_key)
                print(colored_text("🗑️  S3 임시 파일 정리 완료", Colors.SUCCESS))
        except Exception as e:
            print(colored_text(f"⚠️  S3 파일 정리 실패: {str(e)}", Colors.WARNING))

    def cleanup_temp_bucket(self):
        """프로그램 종료 시 임시 S3 버킷 삭제"""
        if not self.temp_bucket:
            return

        # 세션 유효성 검사 (프로그램 종료 시 세션이 무효화될 수 있음)
        if not hasattr(self, 'aws_manager') or not self.aws_manager:
            logging.warning(f"AWS Manager가 유효하지 않아 임시 S3 버킷 삭제를 건너뜁니다: {self.temp_bucket}")
            return

        try:
            # 세션이 유효한지 확인
            if not hasattr(self.aws_manager, 'session') or not self.aws_manager.session:
                logging.warning(f"AWS 세션이 유효하지 않아 임시 S3 버킷 삭제를 건너뜁니다: {self.temp_bucket}")
                return

            s3 = self.aws_manager.session.client('s3')

            # 버킷 내 모든 객체 삭제
            try:
                objects = s3.list_objects_v2(Bucket=self.temp_bucket)
                if 'Contents' in objects:
                    for obj in objects['Contents']:
                        s3.delete_object(Bucket=self.temp_bucket, Key=obj['Key'])
            except (ClientError, KeyError):
                pass  # 객체가 없거나 이미 삭제됨

            # 버킷 삭제
            s3.delete_bucket(Bucket=self.temp_bucket)
            logging.info(f"임시 S3 버킷 삭제됨: {self.temp_bucket}")
        except Exception as e:
            logging.warning(f"임시 S3 버킷 삭제 실패: {self.temp_bucket} - {e}")

    def _format_size(self, size_bytes: int) -> str:
        """바이트를 읽기 쉬운 형태로 변환"""
        if size_bytes == 0:
            return "0B"
        size_float = float(size_bytes)
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_float < Config.BYTES_PER_KB:
                return f"{size_float:.1f}{unit}"
            size_float /= Config.BYTES_PER_KB
        return f"{size_float:.1f}TB"
    
    def _format_speed(self, bytes_per_sec: float) -> str:
        """전송 속도를 읽기 쉬운 형태로 변환"""
        return f"{self._format_size(int(bytes_per_sec))}/s"

# ----------------------------------------------------------------------------
# 배치 작업 관리 (v5.1.0 신규)
# ----------------------------------------------------------------------------
@dataclass
class BatchJobResult:
    command: str
    instance_id: str
    instance_name: str
    status: str  # SUCCESS, FAILED, TIMEOUT
    output: str
    error: str
    execution_time: float
    timestamp: datetime

class BatchJobManager:
    def __init__(self, manager):
        self.aws_manager = manager
        self.results_history: List[BatchJobResult] = []
    
    def _validate_ssm_instances(self, instances: List[dict]) -> List[dict]:
        """SSM 연결 가능한 인스턴스만 필터링"""
        validated = []
        regions_to_check = {}
        
        # 리전별로 인스턴스 그룹화
        for instance_data in instances:
            region = instance_data.get('Region', 'unknown')
            if region not in regions_to_check:
                regions_to_check[region] = []
            regions_to_check[region].append(instance_data)
        
        # 각 리전별로 SSM 상태 확인
        for region, region_instances in regions_to_check.items():
            try:
                ssm = self.aws_manager.session.client('ssm', region_name=region)
                instance_ids = [inst['raw']['InstanceId'] for inst in region_instances]
                
                # SSM 관리 인스턴스 정보 조회
                response = ssm.describe_instance_information(
                    Filters=[{
                        'Key': 'InstanceIds',
                        'Values': instance_ids
                    }]
                )
                
                # 온라인 상태인 인스턴스만 선택
                online_instances = {
                    info['InstanceId']: info['PingStatus'] 
                    for info in response['InstanceInformationList']
                    if info['PingStatus'] == 'Online'
                }
                
                # 검증된 인스턴스만 추가
                for instance_data in region_instances:
                    instance_id = instance_data['raw']['InstanceId']
                    if instance_id in online_instances:
                        validated.append(instance_data)
                    else:
                        print(colored_text(f"⚠️  {instance_data['Name']} ({instance_id}): SSM 연결 불가", Colors.WARNING))
                        
            except Exception as e:
                print(colored_text(f"❌ 리전 {region} SSM 상태 확인 실패: {str(e)}", Colors.ERROR))
                # 에러 시에는 원본 인스턴스 그대로 사용 (이전 동작 유지)
                validated.extend(region_instances)
        
        return validated
    
    def execute_batch_command(self, instances: List[dict], command: str, timeout_seconds: int = 120) -> List[BatchJobResult]:
        """여러 인스턴스에서 배치 명령 실행 (개선된 안정성)"""
        print(colored_text(f"\n🚀 {len(instances)}개 인스턴스에서 배치 작업을 시작합니다...", Colors.INFO))
        print(colored_text(f"명령: {command}", Colors.INFO))
        
        # SSM 상태 사전 확인
        print(colored_text("📋 SSM 연결 상태를 확인 중...", Colors.INFO))
        validated_instances = self._validate_ssm_instances(instances)
        
        if len(validated_instances) < len(instances):
            print(colored_text(f"⚠️  {len(instances) - len(validated_instances)}개 인스턴스가 SSM 연결 불가능 상태입니다.", Colors.WARNING))
        
        if not validated_instances:
            print(colored_text("❌ 실행 가능한 인스턴스가 없습니다.", Colors.ERROR))
            return []
            
        print(colored_text(f"✅ {len(validated_instances)}개 인스턴스에서 실행합니다.", Colors.SUCCESS))
        results = []
        
        def execute_on_instance(instance_data, retry_count=0):
            instance = instance_data['raw']
            instance_id = instance['InstanceId']
            instance_name = instance_data['Name']
            region = instance_data.get('Region', 'unknown')

            max_retries = Config.BATCH_COMMAND_RETRY  # 3
            ssm = self.aws_manager.session.client('ssm', region_name=region)

            last_result = None

            # 전체 실행을 재시도
            for attempt in range(max_retries + 1):
                start_time = time.time()

                if attempt > 0:
                    # 재시도 대기
                    delay = min(Config.BATCH_RETRY_DELAY * attempt, Config.BATCH_RETRY_MAX_DELAY)
                    print(colored_text(
                        f"🔄 {instance_name} 재시도 {attempt}/{max_retries} (대기: {delay}초)",
                        Colors.WARNING
                    ))
                    print(colored_text(
                        f"   💡 SSM Agent 복구 또는 네트워크 안정화 대기 중...",
                        Colors.INFO
                    ))
                    time.sleep(delay)

                try:
                    # 1. 명령 전송
                    response = ssm.send_command(
                        InstanceIds=[instance_id],
                        DocumentName='AWS-RunShellScript',
                        Parameters={
                            'commands': [command],
                            'executionTimeout': [str(timeout_seconds)]
                        },
                        TimeoutSeconds=timeout_seconds + 30
                    )

                    command_id = response['Command']['CommandId']

                    # 2. 결과 대기 (기존 로직 유지)
                    max_wait = timeout_seconds + 30
                    max_attempts = 200
                    waited = 0
                    attempt_count = 0

                    while waited < max_wait and attempt_count < max_attempts:
                        attempt_count += 1
                        try:
                            result = ssm.get_command_invocation(
                                CommandId=command_id,
                                InstanceId=instance_id
                            )
                            status = result['Status']

                            if status in ['Success', 'Failed', 'Cancelled', 'TimedOut']:
                                execution_time = time.time() - start_time

                                if status == 'Success':
                                    output = result.get('StandardOutputContent', '').strip()
                                    if attempt > 0:
                                        print(colored_text(f"✅ {instance_name} 재시도 성공!", Colors.SUCCESS))
                                    return BatchJobResult(
                                        command=command,
                                        instance_id=instance_id,
                                        instance_name=instance_name,
                                        status='SUCCESS',
                                        output=output,
                                        error='',
                                        execution_time=execution_time,
                                        timestamp=datetime.now()
                                    )
                                else:
                                    # Failed, Cancelled, TimedOut
                                    error = result.get('StandardErrorContent', '') or result.get('StatusDetails', '')

                                    # 재시도 가능한 오류인지 확인
                                    if attempt < max_retries:
                                        print(colored_text(
                                            f"⚠️  {instance_name}: {status} - 재시도 예정",
                                            Colors.WARNING
                                        ))
                                        # 현재 시도 실패, 다음 시도로 break
                                        raise Exception(f"Command {status}: {error}")
                                    else:
                                        # 최종 실패
                                        return BatchJobResult(
                                            command=command,
                                            instance_id=instance_id,
                                            instance_name=instance_name,
                                            status='FAILED',
                                            output='',
                                            error=error,
                                            execution_time=execution_time,
                                            timestamp=datetime.now()
                                        )

                            # 아직 실행 중
                            time.sleep(3)
                            waited += 3

                        except ClientError as e:
                            error_code = e.response.get('Error', {}).get('Code', '')
                            if error_code == 'InvocationDoesNotExist':
                                # 명령이 아직 시작 안됨
                                time.sleep(2)
                                waited += 2
                                continue
                            else:
                                # 다른 에러는 재시도
                                time.sleep(Config.WAIT_PORT_READY)
                                waited += 2
                                continue

                    # 타임아웃 발생 - 재시도 가능
                    if attempt < max_retries:
                        print(colored_text(
                            f"⚠️  {instance_name}: 타임아웃 - 재시도 예정",
                            Colors.WARNING
                        ))
                        # 다음 시도로
                        continue
                    else:
                        # 최종 타임아웃
                        execution_time = time.time() - start_time
                        return BatchJobResult(
                            command=command,
                            instance_id=instance_id,
                            instance_name=instance_name,
                            status='TIMEOUT',
                            output='',
                            error=f'Command timed out after {max_wait} seconds',
                            execution_time=execution_time,
                            timestamp=datetime.now()
                        )

                except ClientError as e:
                    # send_command 실패
                    error_code = e.response.get('Error', {}).get('Code', '')
                    if attempt < max_retries:
                        print(colored_text(
                            f"⚠️  {instance_name}: {error_code} - 재시도 예정",
                            Colors.WARNING
                        ))
                        continue
                    else:
                        execution_time = time.time() - start_time
                        return BatchJobResult(
                            command=command,
                            instance_id=instance_id,
                            instance_name=instance_name,
                            status='FAILED',
                            output='',
                            error=str(e),
                            execution_time=execution_time,
                            timestamp=datetime.now()
                        )
                except Exception as e:
                    # 기타 오류 - 재시도
                    if attempt < max_retries:
                        print(colored_text(
                            f"⚠️  {instance_name}: {str(e)} - 재시도 예정",
                            Colors.WARNING
                        ))
                        continue
                    else:
                        execution_time = time.time() - start_time
                        return BatchJobResult(
                            command=command,
                            instance_id=instance_id,
                            instance_name=instance_name,
                            status='FAILED',
                            output='',
                            error=str(e),
                            execution_time=execution_time,
                            timestamp=datetime.now()
                        )
        
        # 배치 크기 제한으로 안정성 향상 (최대 5개씩 동시 실행)
        max_concurrent = min(len(validated_instances), 5)
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_concurrent) as executor:
            future_to_instance = {executor.submit(execute_on_instance, inst): inst for inst in validated_instances}
            
            for future in concurrent.futures.as_completed(future_to_instance):
                try:
                    result = future.result()
                    results.append(result)

                    # 실시간 결과 출력
                    status_color = Colors.SUCCESS if result.status == 'SUCCESS' else Colors.ERROR
                    print(f"{colored_text(result.status, status_color)} {result.instance_name} ({result.instance_id}) - {result.execution_time:.1f}s")

                except Exception as e:
                    # v5.5.0: 에러 발생 시에도 결과에 추가하여 전체 상태 추적 가능하도록 개선
                    instance = future_to_instance[future]
                    error_result = BatchJobResult(
                        command=command,
                        instance_id=instance['raw']['InstanceId'],
                        instance_name=instance['Name'],
                        status='FAILED',
                        output='',
                        error=f"Executor error: {str(e)}",
                        execution_time=0.0,
                        timestamp=datetime.now()
                    )
                    results.append(error_result)
                    print(colored_text(f"ERROR {instance['Name']} ({instance['raw']['InstanceId']}) - {str(e)}", Colors.ERROR))
        
        # 결과 요약 출력
        success_count = sum(1 for r in results if r.status == 'SUCCESS')
        failed_count = len(results) - success_count

        print(colored_text(f"\n📊 총 {len(results)}개 인스턴스 - 성공: {success_count}, 실패: {failed_count}", Colors.INFO))

        # 실패한 인스턴스 재시도 옵션 제공
        if failed_count > 0:
            failed_instances = [
                next(inst for inst in validated_instances
                     if inst['raw']['InstanceId'] == r.instance_id)
                for r in results if r.status != 'SUCCESS'
            ]

            print(colored_text(f"\n⚠️  {failed_count}개 인스턴스에서 명령 실행이 실패했습니다.", Colors.WARNING))
            retry_choice = input(colored_text("실패한 인스턴스만 다시 시도하시겠습니까? (y/N): ", Colors.PROMPT)).strip().lower()

            if retry_choice == 'y':
                print(colored_text(f"\n🔄 실패한 {failed_count}개 인스턴스를 다시 시도합니다...", Colors.INFO))
                print(colored_text("💡 더 긴 대기 시간으로 재시도합니다.", Colors.INFO))

                # 재시도 결과
                retry_results = self.execute_batch_command(failed_instances, command, timeout_seconds)

                # 원본 결과에서 실패한 것을 재시도 결과로 교체
                for retry_result in retry_results:
                    for i, r in enumerate(results):
                        if r.instance_id == retry_result.instance_id:
                            results[i] = retry_result
                            break

                # 최종 결과 재계산
                success_count = sum(1 for r in results if r.status == 'SUCCESS')
                failed_count = len(results) - success_count
                print(colored_text(f"\n✅ 재시도 완료 - 성공: {success_count}, 실패: {failed_count}", Colors.SUCCESS))

        # 결과 저장
        self.results_history.extend(results)
        self.save_results_history()

        return results
    
    def show_batch_results(self, results: List[BatchJobResult]):
        """배치 작업 결과 상세 표시"""
        print(colored_text(f"\n📊 배치 작업 결과 상세:", Colors.HEADER))
        print("-" * 80)
        
        success_count = sum(1 for r in results if r.status == 'SUCCESS')
        failed_count = len(results) - success_count
        
        print(f"총 {len(results)}개 인스턴스 - {colored_text(f'성공: {success_count}', Colors.SUCCESS)}, {colored_text(f'실패: {failed_count}', Colors.ERROR)}")
        print()
        
        for result in results:
            status_color = Colors.SUCCESS if result.status == 'SUCCESS' else Colors.ERROR
            print(f"{colored_text('■', status_color)} {result.instance_name} ({result.instance_id}) - {result.execution_time:.1f}s")
            
            if result.output.strip():
                print(f"   출력: {result.output.strip()[:100]}{'...' if len(result.output.strip()) > 100 else ''}")
            
            if result.error.strip():
                print(colored_text(f"   오류: {result.error.strip()[:100]}{'...' if len(result.error.strip()) > 100 else ''}", Colors.ERROR))
            print()
    
    def save_results_history(self):
        """배치 작업 결과 히스토리 저장"""
        try:
            # 최근 100개 결과만 보관
            recent_results = self.results_history[-100:]
            
            # JSON 직렬화 가능한 형태로 변환
            serializable_results = []
            for result in recent_results:
                serializable_results.append({
                    'command': result.command,
                    'instance_id': result.instance_id,
                    'instance_name': result.instance_name,
                    'status': result.status,
                    'output': result.output,
                    'error': result.error,
                    'execution_time': result.execution_time,
                    'timestamp': result.timestamp.isoformat()
                })
            
            with open(BATCH_RESULTS_PATH, 'w', encoding='utf-8') as f:
                json.dump(serializable_results, f, ensure_ascii=False, indent=2)
                
        except Exception as e:
            logging.warning(f"배치 결과 히스토리 저장 실패: {e}")

# ----------------------------------------------------------------------------
# 인스턴스 필터링 헬퍼 함수
# ----------------------------------------------------------------------------
def filter_linux_instances(instances: List[dict], valid_choices: List[int], region: Optional[str] = None) -> List[dict]:
    """Linux 인스턴스만 필터링 (Windows 제외)"""
    selected = []
    for choice_idx in valid_choices:
        inst_data = instances[choice_idx - 1]
        inst = inst_data['raw']

        # Windows 인스턴스 제외
        if inst.get('PlatformDetails', 'Linux').lower().startswith('windows'):
            print(colored_text(
                f"⚠️  Windows 인스턴스는 배치 작업/파일 전송을 지원하지 않습니다: {inst_data['Name']}",
                Colors.WARNING
            ))
            continue

        # 리전 정보 추가 (필요 시)
        if region and 'Region' not in inst_data:
            inst_data['Region'] = inst.get('_region', region)

        selected.append(inst_data)

    return selected

# ----------------------------------------------------------------------------
# 정렬 기능 (v5.0.2 원본)
# ----------------------------------------------------------------------------
def sort_instances(instances, sort_key='Name', reverse=False):
    """인스턴스 목록 정렬"""
    try:
        if sort_key == 'Name':
            return sorted(instances, key=lambda x: x.get('Name', ''), reverse=reverse)
        elif sort_key == 'Type':
            return sorted(instances, key=lambda x: x['raw'].get('InstanceType', ''), reverse=reverse)
        elif sort_key == 'Region':
            return sorted(instances, key=lambda x: x.get('Region', ''), reverse=reverse)
        elif sort_key == 'State':
            return sorted(instances, key=lambda x: x['raw']['State']['Name'], reverse=reverse)
        else:
            return instances
    except (KeyError, TypeError):
        return instances

def show_sort_help():
    """정렬 옵션 도움말 표시"""
    print(colored_text("\n📊 정렬 옵션:", Colors.INFO))
    print("  n = 이름순 정렬")
    print("  t = 타입순 정렬") 
    print("  r = 리전순 정렬")
    print("  s = 상태순 정렬")
    print("  같은 키를 다시 누르면 역순 정렬")

# ----------------------------------------------------------------------------
# 히스토리 관리 (v5.0.1 원본)
# ----------------------------------------------------------------------------
def load_history():
    """연결 히스토리를 로드합니다."""
    try:
        if HISTORY_PATH.exists():
            with open(HISTORY_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logging.warning(f"히스토리 로드 실패: {e}")
    return {"ec2": [], "rds": [], "cache": [], "ecs": []}

def save_history(history):
    """연결 히스토리를 저장합니다."""
    try:
        with open(HISTORY_PATH, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.warning(f"히스토리 저장 실패: {e}")

def invalidate_cache_for_service(manager, region, service_type):
    """서비스 타입에 따라 캐시 무효화 (중복 제거용 헬퍼 함수)"""
    if region == 'multi-region':
        regions = manager.list_regions()
        for r in regions:
            _cache.invalidate(f"{service_type}_{manager.profile}_{r}")
    else:
        _cache.invalidate(f"{service_type}_{manager.profile}_{region}")

def add_to_history(service_type, profile, region, instance_id, instance_name):
    """히스토리에 새 항목을 추가합니다."""
    history = load_history()

    entry = {
        "profile": profile,
        "region": region,
        "instance_id": instance_id,
        "instance_name": instance_name,
        "timestamp": datetime.now().isoformat()
    }

    # 중복 제거 (같은 인스턴스 ID)
    history[service_type] = [h for h in history[service_type] if h["instance_id"] != instance_id]

    # 최신 항목을 맨 앞에 추가
    history[service_type].insert(0, entry)
    
    # 최대 10개까지만 유지
    history[service_type] = history[service_type][:10]
    
    save_history(history)

# ----------------------------------------------------------------------------
# DB 자격 증명 관리 (v5.5.0 - Keychain 연동)
# ----------------------------------------------------------------------------
def get_db_credentials(db_user_hint=""):
    """DB 자격 증명을 가져옵니다. Keychain 또는 메모리에서 조회."""
    global _stored_credentials

    # 1. Keychain에서 저장된 자격 증명 확인 (v5.5.0)
    if db_user_hint and KeychainManager.has_credentials(db_user_hint):
        password = KeychainManager.get(db_user_hint)
        print(colored_text(f"\n🔐 Keychain에 저장된 자격 증명을 찾았습니다: {db_user_hint}", Colors.INFO))
        use_stored = input("Keychain 자격 증명을 사용하시겠습니까? (Y/n, b=뒤로): ").strip().lower()
        if use_stored == 'b':
            return None, None
        if use_stored != 'n':
            return db_user_hint, password

    # 2. 메모리에 저장된 자격 증명 확인 (하위 호환성)
    if _stored_credentials:
        print(colored_text("\n💾 메모리에 저장된 DB 자격 증명이 있습니다.", Colors.INFO))
        use_stored = input("저장된 자격 증명을 사용하시겠습니까? (Y/n, b=뒤로): ").strip().lower()
        if use_stored == 'b':
            return None, None
        if use_stored != 'n':
            return _stored_credentials['user'], _stored_credentials['password']

    # 3. 새로운 자격 증명 입력
    print(colored_text("\nℹ️ 데이터베이스에 연결할 사용자 정보를 입력하세요.", Colors.INFO))
    try:
        db_user = input(f"   DB 사용자 이름{f' ({db_user_hint})' if db_user_hint else ''} (b=뒤로): ") or db_user_hint
        if db_user.lower() == 'b':
            return None, None
        db_password = getpass.getpass("   DB 비밀번호 (입력 시 보이지 않음): ")
    except (EOFError, KeyboardInterrupt):
        print(colored_text("\n입력이 중단되었습니다.", Colors.WARNING))
        return None, None

    if not db_user or not db_password:
        print(colored_text("❌ 사용자 이름과 비밀번호를 모두 입력해야 합니다.", Colors.ERROR))
        return None, None

    # 4. 자격 증명 저장 여부 확인 (v5.5.0: Keychain 옵션 추가)
    print(colored_text("\n자격 증명 저장 옵션:", Colors.INFO))
    print("  1) Keychain에 저장 (macOS 보안 저장소, 영구 저장)")
    print("  2) 메모리에만 저장 (스크립트 종료 시 삭제)")
    print("  3) 저장하지 않음")
    save_choice = input("선택 (1/2/3, b=뒤로): ").strip().lower()

    if save_choice == 'b':
        return None, None
    elif save_choice == '1':
        if KeychainManager.store(db_user, db_password, use_keychain=True):
            print(colored_text("✅ 자격 증명이 macOS Keychain에 저장되었습니다.", Colors.SUCCESS))
        else:
            # Keychain 저장 실패 시 메모리에만 저장
            _stored_credentials['user'] = db_user
            _stored_credentials['password'] = db_password
            print(colored_text("⚠️ Keychain 저장 실패. 메모리에만 저장되었습니다.", Colors.WARNING))
    elif save_choice == '2':
        _stored_credentials['user'] = db_user
        _stored_credentials['password'] = db_password
        KeychainManager.store(db_user, db_password, use_keychain=False)  # 메모리 캐시만
        print(colored_text("✅ 자격 증명이 메모리에 저장되었습니다. (스크립트 종료 시 자동 삭제)", Colors.SUCCESS))

    return db_user, db_password

def clear_stored_credentials():
    """저장된 자격 증명을 삭제합니다 (메모리 + Keychain 세션 캐시)."""
    global _stored_credentials
    _stored_credentials.clear()
    KeychainManager.clear_session()
    print(colored_text("🗑️ 저장된 자격 증명을 삭제했습니다.", Colors.SUCCESS))

# ----------------------------------------------------------------------------
# AWS 호출 모듈 (v5.1.0 확장 - 캐싱 및 성능 최적화)
# ----------------------------------------------------------------------------
class AWSManager:
    def __init__(self, profile: str, max_workers: int = DEFAULT_WORKERS):
        try:
            self.session = boto3.Session(profile_name=profile)
        except ProfileNotFound as e:
            print(colored_text(f"❌ AWS 프로파일 오류: {e}", Colors.ERROR))
            sys.exit(1)
        self.profile     = profile
        self.max_workers = max_workers

    def list_regions(self):
        cache_key = f"regions_{self.profile}"
        cached_data = _cache.get(cache_key)
        if cached_data:
            return cached_data

        try:
            # describe_regions는 어느 리전에서나 호출 가능하므로 기본 리전 사용
            # AWS config에 설정된 리전 또는 us-east-1 사용
            default_region = self.session.region_name or 'us-east-1'
            ec2  = self.session.client('ec2', region_name=default_region)
            resp = ec2.describe_regions(AllRegions=False)
            regions = [r['RegionName'] for r in resp.get('Regions', [])]
            _cache.set(cache_key, regions, ttl_seconds=3600)  # 1시간 캐시
            return regions
        except (ClientError, NoCredentialsError) as e:
            print(colored_text(f"❌ AWS 호출 실패 (describe_regions): {e}", Colors.ERROR))
            return []

    def list_instances(self, region: str, force_refresh: bool = False):
        cache_key = f"instances_{self.profile}_{region}"
        if not force_refresh:
            cached_data = _cache.get(cache_key)
            if cached_data:
                # 백그라운드에서 새로고침 시작
                _cache.start_background_refresh(cache_key, self._fetch_instances, region)
                return cached_data
        
        # 캐시에 없거나 강제 새로고침
        instances = self._fetch_instances(region)
        _cache.set(cache_key, instances)  # Config.CACHE_TTL_SECONDS 사용
        return instances
    
    def _fetch_instances(self, region: str):
        """실제 인스턴스 데이터를 AWS에서 가져오기 (페이지네이션 처리)"""
        try:
            ec2 = self.session.client('ec2', region_name=region)
            
            # 모든 running 인스턴스 조회 (페이지네이션 처리, 무한 루프 방지)
            insts = []
            next_token = None
            seen_tokens = set()
            max_pages = 100  # 안전장치: 최대 100페이지 (10,000개 인스턴스)

            page_count = 0
            while page_count < max_pages:
                page_count += 1
                params = {
                    'Filters': [{'Name':'instance-state-name','Values':['running']}],
                    'MaxResults': 100  # EC2 API 최대값
                }
                if next_token:
                    if next_token in seen_tokens:
                        logging.warning(f"페이지네이션 중복 토큰 감지, 종료 (region={region})")
                        break
                    seen_tokens.add(next_token)
                    params['NextToken'] = next_token

                resp = ec2.describe_instances(**params)

                for res in resp.get('Reservations', []):
                    for i in res.get('Instances', []):
                        insts.append(i)

                next_token = resp.get('NextToken')
                if not next_token:
                    break

            if page_count >= max_pages:
                logging.warning(f"페이지네이션 제한 초과 (region={region}, pages={max_pages})")
                    
            return insts
        except ClientError as e:
            logging.error(f"AWS list_instances 실패({region}): {e}")
            return []

    def list_instances_multi_region(self, regions: list, force_refresh: bool = False):
        """여러 리전의 인스턴스를 병렬로 가져옵니다."""
        all_instances = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            future_to_region = {ex.submit(self.list_instances, region, force_refresh): region for region in regions}
            for future in concurrent.futures.as_completed(future_to_region):
                region = future_to_region[future]
                try:
                    instances = future.result()
                    for inst in instances:
                        inst['_region'] = region  # 리전 정보 추가
                        all_instances.append(inst)
                except Exception as e:
                    logging.warning(f"리전 {region} 인스턴스 검색 실패: {e}")
        return all_instances

    def list_ssm_managed(self, region: str, jump_host_tags: dict | None = None):
        cache_key = f"ssm_{self.profile}_{region}_{str(jump_host_tags)}"
        cached_data = _cache.get(cache_key)
        if cached_data:
            return cached_data
        
        try:
            ssm = self.session.client('ssm', region_name=region)

            # 모든 SSM 관리 인스턴스 조회 (페이지네이션 처리)
            info = []
            next_token = None
            max_pages = Config.MAX_PAGINATION_PAGES
            page_count = 0
            seen_tokens = set()

            while page_count < max_pages:
                page_count += 1
                params = {'MaxResults': 50}  # AWS 기본값보다 크게 설정
                if next_token:
                    if next_token in seen_tokens:
                        logging.warning(f"SSM 페이지네이션 중복 토큰 감지")
                        break
                    seen_tokens.add(next_token)
                    params['NextToken'] = next_token

                response = ssm.describe_instance_information(**params)
                info.extend(response.get('InstanceInformationList', []))

                next_token = response.get('NextToken')
                if not next_token:
                    break

            if page_count >= max_pages:
                logging.warning(f"SSM 페이지네이션 제한 초과")
            
            instance_ids = [i['InstanceId'] for i in info]
            if not instance_ids:
                return []

            ec2 = self.session.client('ec2', region_name=region)
            resp = ec2.describe_instances(InstanceIds=instance_ids)
            
            ssm_instances = []
            for res in resp.get('Reservations', []):
                for i in res.get('Instances', []):
                    # 태그 필터링 검사
                    if jump_host_tags:
                        instance_tags = {t['Key']: t['Value'] for t in i.get('Tags', [])}
                        # 모든 필터 태그가 인스턴스에 있고 값이 일치하는지 확인
                        if not all(instance_tags.get(key) == value for key, value in jump_host_tags.items()):
                            continue
                    
                    name = next((t['Value'] for t in i.get('Tags', []) if t['Key'] == 'Name'), '')
                    ssm_instances.append({'Id': i['InstanceId'], 'Name': name})
            
            result = sorted(ssm_instances, key=lambda x: x['Name'])
            _cache.set(cache_key, result, )
            return result
        except ClientError as e:
            print(colored_text(f"❌ AWS 호출 실패 (list_ssm_managed): {e}", Colors.ERROR))
            return []

    def get_rds_endpoints(self, region: str, force_refresh: bool = False):
        cache_key = f"rds_{self.profile}_{region}"
        if not force_refresh:
            cached_data = _cache.get(cache_key)
            if cached_data:
                return cached_data
        
        try:
            rds = self.session.client('rds', region_name=region)
            dbs = rds.describe_db_instances().get('DBInstances', [])
            result = [
                {
                    'Id':       d['DBInstanceIdentifier'],
                    'Engine':   d['Engine'],
                    'Endpoint': d['Endpoint']['Address'],
                    'Port':     d['Endpoint']['Port'],
                    'DBName':   d.get('DBName')
                }
                for d in dbs
            ]
            _cache.set(cache_key, result, )
            return result
        except ClientError as e:
            print(colored_text(f"❌ AWS 호출 실패 (describe_db_instances): {e}", Colors.ERROR))
            return []

    def get_rds_endpoints_multi_region(self, regions: list, force_refresh: bool = False):
        """여러 리전의 RDS를 병렬로 가져옵니다."""
        all_dbs = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            future_to_region = {ex.submit(self.get_rds_endpoints, region, force_refresh): region for region in regions}
            for future in concurrent.futures.as_completed(future_to_region):
                region = future_to_region[future]
                try:
                    dbs = future.result()
                    for db in dbs:
                        db['_region'] = region  # 리전 정보 추가
                        all_dbs.append(db)
                except Exception as e:
                    logging.warning(f"리전 {region} RDS 검색 실패: {e}")
        return all_dbs

    def list_cache_clusters(self, region: str, force_refresh: bool = False):
        cache_key = f"cache_{self.profile}_{region}"
        if not force_refresh:
            cached_data = _cache.get(cache_key)
            if cached_data:
                return cached_data
        
        try:
            ec = self.session.client('elasticache', region_name=region)
            clus = ec.describe_cache_clusters(ShowCacheNodeInfo=True).get('CacheClusters', [])
            result = []
            for c in clus:
                ep = c.get('ConfigurationEndpoint') or (
                    c.get('CacheNodes')[0].get('Endpoint') if c.get('CacheNodes') else {}
                )
                result.append({
                    'Id':      c['CacheClusterId'],
                    'Engine':  c['Engine'],
                    'Address': ep.get('Address',''),
                    'Port':    ep.get('Port',0)
                })
            _cache.set(cache_key, result, )
            return result
        except ClientError as e:
            print(colored_text(f"❌ AWS 호출 실패 (describe_cache_clusters): {e}", Colors.ERROR))
            return []

    def list_cache_clusters_multi_region(self, regions: list, force_refresh: bool = False):
        """여러 리전의 ElastiCache를 병렬로 가져옵니다."""
        all_clusters = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            future_to_region = {ex.submit(self.list_cache_clusters, region, force_refresh): region for region in regions}
            for future in concurrent.futures.as_completed(future_to_region):
                region = future_to_region[future]
                try:
                    clusters = future.result()
                    for cluster in clusters:
                        cluster['_region'] = region  # 리전 정보 추가
                        all_clusters.append(cluster)
                except Exception as e:
                    logging.warning(f"리전 {region} ElastiCache 검색 실패: {e}")
        return all_clusters

    # ECS 관련 메서드 (v5.0.2 원본 + 캐싱)
    def list_ecs_clusters(self, region: str, force_refresh: bool = False):
        """ECS 클러스터 목록을 가져옵니다."""
        cache_key = f"ecs_clusters_{self.profile}_{region}"
        if not force_refresh:
            cached_data = _cache.get(cache_key)
            if cached_data:
                return cached_data
        
        try:
            ecs = self.session.client('ecs', region_name=region)
            clusters = ecs.list_clusters().get('clusterArns', [])
            if not clusters:
                return []
            
            # 클러스터 상세 정보 조회
            cluster_details = ecs.describe_clusters(clusters=clusters).get('clusters', [])
            result = [
                {
                    'Name': c['clusterName'],
                    'Arn': c['clusterArn'], 
                    'Status': c['status'],
                    'RunningTasks': c['runningTasksCount'],
                    'ActiveServices': c['activeServicesCount']
                }
                for c in cluster_details
            ]
            _cache.set(cache_key, result, )
            return result
        except ClientError as e:
            print(colored_text(f"❌ AWS 호출 실패 (list_ecs_clusters): {e}", Colors.ERROR))
            return []

    def list_ecs_services(self, region: str, cluster_name: str, force_refresh: bool = False):
        """ECS 서비스 목록을 가져옵니다."""
        cache_key = f"ecs_services_{self.profile}_{region}_{cluster_name}"
        if not force_refresh:
            cached_data = _cache.get(cache_key)
            if cached_data:
                return cached_data
        
        try:
            ecs = self.session.client('ecs', region_name=region)
            services = ecs.list_services(cluster=cluster_name).get('serviceArns', [])
            if not services:
                return []
            
            # 서비스 상세 정보 조회
            service_details = ecs.describe_services(cluster=cluster_name, services=services).get('services', [])
            result = [
                {
                    'Name': s['serviceName'],
                    'Arn': s['serviceArn'],
                    'Status': s['status'],
                    'RunningCount': s['runningCount'],
                    'DesiredCount': s['desiredCount'],
                    'LaunchType': s.get('launchType', 'EC2'),
                    'PlatformVersion': s.get('platformVersion', 'LATEST')
                }
                for s in service_details
            ]
            _cache.set(cache_key, result, )
            return result
        except ClientError as e:
            print(colored_text(f"❌ AWS 호출 실패 (list_ecs_services): {e}", Colors.ERROR))
            return []

    def list_ecs_tasks(self, region: str, cluster_name: str, service_name: str | None = None, force_refresh: bool = False):
        """ECS 태스크 목록을 가져옵니다."""
        cache_key = f"ecs_tasks_{self.profile}_{region}_{cluster_name}_{service_name or 'all'}"
        if not force_refresh:
            cached_data = _cache.get(cache_key)
            if cached_data:
                return cached_data
        
        try:
            ecs = self.session.client('ecs', region_name=region)
            
            list_params = {'cluster': cluster_name}
            if service_name:
                list_params['serviceName'] = service_name
                
            tasks = ecs.list_tasks(**list_params).get('taskArns', [])
            if not tasks:
                return []
            
            # 태스크 상세 정보 조회
            task_details = ecs.describe_tasks(cluster=cluster_name, tasks=tasks).get('tasks', [])
            
            # 태스크 정의 정보도 함께 조회
            task_definitions = {}
            for task in task_details:
                task_def_arn = task['taskDefinitionArn']
                if task_def_arn not in task_definitions:
                    try:
                        task_def = ecs.describe_task_definition(taskDefinition=task_def_arn)
                        task_definitions[task_def_arn] = task_def['taskDefinition']
                    except ClientError:
                        task_definitions[task_def_arn] = None
            
            result = []
            for task in task_details:
                task_def = task_definitions.get(task['taskDefinitionArn'])
                containers = []
                
                if task_def:
                    containers = [
                        {
                            'Name': container['name'],
                            'Image': container['image'],
                            'Status': next((c['lastStatus'] for c in task.get('containers', []) if c['name'] == container['name']), 'UNKNOWN')
                        }
                        for container in task_def.get('containerDefinitions', [])
                    ]
                
                result.append({
                    'TaskArn': task['taskArn'],
                    'TaskDefinitionArn': task['taskDefinitionArn'],
                    'LastStatus': task['lastStatus'],
                    'DesiredStatus': task['desiredStatus'],
                    'LaunchType': task.get('launchType', 'EC2'),
                    'PlatformVersion': task.get('platformVersion', 'LATEST'),
                    'Containers': containers,
                    'EnableExecuteCommand': task.get('enableExecuteCommand', False)
                })
            
            _cache.set(cache_key, result, ttl_seconds=120)  # 태스크는 짧은 TTL
            return result
        except ClientError as e:
            print(colored_text(f"❌ AWS 호출 실패 (list_ecs_tasks): {e}", Colors.ERROR))
            return []

    # ------------------------------------------------------------------------
    # EKS 관련 메서드 (v5.3.0 신규)
    # ------------------------------------------------------------------------
    def list_eks_clusters(self, region: str, force_refresh: bool = False) -> List[Dict]:
        """EKS 클러스터 목록을 가져옵니다."""
        cache_key = f"eks_clusters_{self.profile}_{region}"
        if not force_refresh:
            cached_data = _cache.get(cache_key)
            if cached_data:
                return cached_data

        try:
            eks = self.session.client('eks', region_name=region)
            cluster_names = eks.list_clusters().get('clusters', [])
            if not cluster_names:
                return []

            result = []
            for name in cluster_names:
                try:
                    detail = eks.describe_cluster(name=name).get('cluster', {})
                    result.append({
                        'Name': detail.get('name', name),
                        'Arn': detail.get('arn', ''),
                        'Status': detail.get('status', 'UNKNOWN'),
                        'Version': detail.get('version', 'N/A'),
                        'Endpoint': detail.get('endpoint', ''),
                        'PlatformVersion': detail.get('platformVersion', 'N/A'),
                        'CreatedAt': detail.get('createdAt', None),
                    })
                except ClientError as e:
                    logging.warning(f"EKS 클러스터 {name} 상세 조회 실패: {e}")
                    result.append({
                        'Name': name,
                        'Status': 'UNKNOWN',
                        'Version': 'N/A',
                    })

            _cache.set(cache_key, result)
            return result
        except ClientError as e:
            print(colored_text(f"❌ AWS 호출 실패 (list_eks_clusters): {e}", Colors.ERROR))
            return []

    def get_eks_cluster_detail(self, region: str, cluster_name: str) -> Optional[Dict]:
        """EKS 클러스터 상세 정보를 가져옵니다."""
        cache_key = f"eks_cluster_detail_{self.profile}_{region}_{cluster_name}"
        cached_data = _cache.get(cache_key)
        if cached_data:
            return cached_data

        try:
            eks = self.session.client('eks', region_name=region)
            detail = eks.describe_cluster(name=cluster_name).get('cluster', {})

            result = {
                'Name': detail.get('name', cluster_name),
                'Arn': detail.get('arn', ''),
                'Status': detail.get('status', 'UNKNOWN'),
                'Version': detail.get('version', 'N/A'),
                'Endpoint': detail.get('endpoint', ''),
                'PlatformVersion': detail.get('platformVersion', 'N/A'),
                'RoleArn': detail.get('roleArn', ''),
                'VpcId': detail.get('resourcesVpcConfig', {}).get('vpcId', ''),
                'SubnetIds': detail.get('resourcesVpcConfig', {}).get('subnetIds', []),
                'SecurityGroupIds': detail.get('resourcesVpcConfig', {}).get('securityGroupIds', []),
                'ClusterSecurityGroupId': detail.get('resourcesVpcConfig', {}).get('clusterSecurityGroupId', ''),
                'EndpointPublicAccess': detail.get('resourcesVpcConfig', {}).get('endpointPublicAccess', False),
                'EndpointPrivateAccess': detail.get('resourcesVpcConfig', {}).get('endpointPrivateAccess', False),
                'CreatedAt': detail.get('createdAt', None),
                'Tags': detail.get('tags', {}),
            }
            _cache.set(cache_key, result, ttl_seconds=300)
            return result
        except ClientError as e:
            print(colored_text(f"❌ AWS 호출 실패 (get_eks_cluster_detail): {e}", Colors.ERROR))
            return None

    def list_eks_nodegroups(self, region: str, cluster_name: str, force_refresh: bool = False) -> List[Dict]:
        """EKS 노드그룹 목록을 가져옵니다."""
        cache_key = f"eks_nodegroups_{self.profile}_{region}_{cluster_name}"
        if not force_refresh:
            cached_data = _cache.get(cache_key)
            if cached_data:
                return cached_data

        try:
            eks = self.session.client('eks', region_name=region)
            nodegroup_names = eks.list_nodegroups(clusterName=cluster_name).get('nodegroups', [])
            if not nodegroup_names:
                return []

            result = []
            for ng_name in nodegroup_names:
                try:
                    detail = eks.describe_nodegroup(clusterName=cluster_name, nodegroupName=ng_name).get('nodegroup', {})
                    scaling = detail.get('scalingConfig', {})
                    result.append({
                        'Name': detail.get('nodegroupName', ng_name),
                        'Status': detail.get('status', 'UNKNOWN'),
                        'InstanceTypes': detail.get('instanceTypes', []),
                        'AmiType': detail.get('amiType', 'N/A'),
                        'CapacityType': detail.get('capacityType', 'ON_DEMAND'),
                        'DesiredSize': scaling.get('desiredSize', 0),
                        'MinSize': scaling.get('minSize', 0),
                        'MaxSize': scaling.get('maxSize', 0),
                        'NodeRole': detail.get('nodeRole', ''),
                    })
                except ClientError as e:
                    logging.warning(f"노드그룹 {ng_name} 상세 조회 실패: {e}")

            _cache.set(cache_key, result)
            return result
        except ClientError as e:
            print(colored_text(f"❌ AWS 호출 실패 (list_eks_nodegroups): {e}", Colors.ERROR))
            return []

    def list_eks_fargate_profiles(self, region: str, cluster_name: str, force_refresh: bool = False) -> List[Dict]:
        """EKS Fargate 프로필 목록을 가져옵니다."""
        cache_key = f"eks_fargate_{self.profile}_{region}_{cluster_name}"
        if not force_refresh:
            cached_data = _cache.get(cache_key)
            if cached_data:
                return cached_data

        try:
            eks = self.session.client('eks', region_name=region)
            profile_names = eks.list_fargate_profiles(clusterName=cluster_name).get('fargateProfileNames', [])
            if not profile_names:
                return []

            result = []
            for fp_name in profile_names:
                try:
                    detail = eks.describe_fargate_profile(clusterName=cluster_name, fargateProfileName=fp_name).get('fargateProfile', {})
                    selectors = detail.get('selectors', [])
                    namespaces = [s.get('namespace', '') for s in selectors]
                    result.append({
                        'Name': detail.get('fargateProfileName', fp_name),
                        'Status': detail.get('status', 'UNKNOWN'),
                        'PodExecutionRoleArn': detail.get('podExecutionRoleArn', ''),
                        'Namespaces': namespaces,
                        'Subnets': detail.get('subnets', []),
                    })
                except ClientError as e:
                    logging.warning(f"Fargate 프로필 {fp_name} 상세 조회 실패: {e}")

            _cache.set(cache_key, result)
            return result
        except ClientError as e:
            print(colored_text(f"❌ AWS 호출 실패 (list_eks_fargate_profiles): {e}", Colors.ERROR))
            return []

    # ------------------------------------------------------------------------
    # ECS 로그 관련 메서드 (v5.3.0 신규)
    # ------------------------------------------------------------------------
    def get_ecs_task_log_config(self, region: str, task_definition_arn: str) -> List[Dict]:
        """ECS 태스크 정의에서 로그 설정을 가져옵니다."""
        try:
            ecs = self.session.client('ecs', region_name=region)
            task_def = ecs.describe_task_definition(taskDefinition=task_definition_arn)
            container_defs = task_def.get('taskDefinition', {}).get('containerDefinitions', [])

            log_configs = []
            for container in container_defs:
                log_config = container.get('logConfiguration', {})
                if log_config.get('logDriver') == 'awslogs':
                    options = log_config.get('options', {})
                    log_configs.append({
                        'ContainerName': container['name'],
                        'LogGroup': options.get('awslogs-group', ''),
                        'LogStreamPrefix': options.get('awslogs-stream-prefix', ''),
                        'Region': options.get('awslogs-region', region),
                    })
            return log_configs
        except ClientError as e:
            logging.warning(f"태스크 정의 로그 설정 조회 실패: {e}")
            return []

    def get_ecs_log_streams(self, region: str, log_group: str, log_stream_prefix: str, task_id: str) -> List[str]:
        """ECS 태스크의 로그 스트림 목록을 가져옵니다."""
        try:
            logs = self.session.client('logs', region_name=region)
            # 로그 스트림 이름 패턴: {prefix}/{container-name}/{task-id}
            prefix = f"{log_stream_prefix}/" if log_stream_prefix else ""

            response = logs.describe_log_streams(
                logGroupName=log_group,
                logStreamNamePrefix=prefix,
                orderBy='LastEventTime',
                descending=True,
                limit=50
            )

            streams = []
            for stream in response.get('logStreams', []):
                stream_name = stream.get('logStreamName', '')
                # 태스크 ID가 포함된 스트림만 필터링
                if task_id in stream_name:
                    streams.append(stream_name)
            return streams
        except ClientError as e:
            logging.warning(f"로그 스트림 조회 실패: {e}")
            return []

    def get_ecs_container_logs(self, region: str, log_group: str, log_stream: str,
                                start_time: Optional[int] = None, limit: int = 100) -> List[Dict]:
        """ECS 컨테이너 로그를 가져옵니다."""
        try:
            logs = self.session.client('logs', region_name=region)
            params = {
                'logGroupName': log_group,
                'logStreamName': log_stream,
                'limit': limit,
                'startFromHead': False
            }
            if start_time:
                params['startTime'] = start_time

            response = logs.get_log_events(**params)
            events = response.get('events', [])

            return [
                {
                    'timestamp': event.get('timestamp', 0),
                    'message': event.get('message', ''),
                    'ingestionTime': event.get('ingestionTime', 0)
                }
                for event in events
            ]
        except ClientError as e:
            logging.warning(f"로그 조회 실패: {e}")
            return []

    # =========================================================================
    # CloudWatch 관련 메서드 (v5.5.0 신규)
    # =========================================================================

    def list_cloudwatch_dashboards(self, region: str, force_refresh: bool = False) -> List[Dict]:
        """CloudWatch 대시보드 목록 조회"""
        cache_key = f"cw_dashboards_{self.profile}_{region}"
        if not force_refresh:
            cached = _cache.get(cache_key)
            if cached:
                return cached

        try:
            cw = self.session.client('cloudwatch', region_name=region)
            dashboards = []
            paginator = cw.get_paginator('list_dashboards')

            for page in paginator.paginate():
                for entry in page.get('DashboardEntries', []):
                    dashboards.append({
                        'DashboardName': entry.get('DashboardName', ''),
                        'DashboardArn': entry.get('DashboardArn', ''),
                        'LastModified': entry.get('LastModified'),
                        'Size': entry.get('Size', 0)
                    })

            _cache.set(cache_key, dashboards)
            return dashboards
        except ClientError as e:
            logging.warning(f"CloudWatch 대시보드 조회 실패: {e}")
            return []

    def list_cloudwatch_alarms(self, region: str, state: Optional[str] = None,
                               force_refresh: bool = False) -> List[Dict]:
        """CloudWatch 알람 목록 조회 (상태 필터: OK/ALARM/INSUFFICIENT_DATA)"""
        cache_key = f"cw_alarms_{self.profile}_{region}_{state or 'all'}"
        if not force_refresh:
            cached = _cache.get(cache_key)
            if cached:
                return cached

        try:
            cw = self.session.client('cloudwatch', region_name=region)
            alarms = []
            paginator = cw.get_paginator('describe_alarms')

            params = {}
            if state:
                params['StateValue'] = state

            for page in paginator.paginate(**params):
                for alarm in page.get('MetricAlarms', []):
                    alarms.append({
                        'AlarmName': alarm.get('AlarmName', ''),
                        'AlarmArn': alarm.get('AlarmArn', ''),
                        'StateValue': alarm.get('StateValue', ''),
                        'StateReason': alarm.get('StateReason', ''),
                        'MetricName': alarm.get('MetricName', ''),
                        'Namespace': alarm.get('Namespace', ''),
                        'Threshold': alarm.get('Threshold', 0),
                        'ComparisonOperator': alarm.get('ComparisonOperator', ''),
                        'EvaluationPeriods': alarm.get('EvaluationPeriods', 0),
                        'StateUpdatedTimestamp': alarm.get('StateUpdatedTimestamp'),
                    })
                for alarm in page.get('CompositeAlarms', []):
                    alarms.append({
                        'AlarmName': alarm.get('AlarmName', ''),
                        'AlarmArn': alarm.get('AlarmArn', ''),
                        'StateValue': alarm.get('StateValue', ''),
                        'StateReason': alarm.get('StateReason', ''),
                        'MetricName': '[Composite]',
                        'Namespace': '',
                        'Threshold': 0,
                        'ComparisonOperator': '',
                        'EvaluationPeriods': 0,
                        'StateUpdatedTimestamp': alarm.get('StateUpdatedTimestamp'),
                    })

            _cache.set(cache_key, alarms)
            return alarms
        except ClientError as e:
            logging.warning(f"CloudWatch 알람 조회 실패: {e}")
            return []

    def get_alarm_history(self, region: str, alarm_name: str, limit: int = 50) -> List[Dict]:
        """알람 히스토리 조회"""
        try:
            cw = self.session.client('cloudwatch', region_name=region)
            response = cw.describe_alarm_history(
                AlarmName=alarm_name,
                HistoryItemType='StateUpdate',
                MaxRecords=limit
            )

            return [
                {
                    'Timestamp': item.get('Timestamp'),
                    'HistorySummary': item.get('HistorySummary', ''),
                    'HistoryItemType': item.get('HistoryItemType', ''),
                    'HistoryData': item.get('HistoryData', ''),
                }
                for item in response.get('AlarmHistoryItems', [])
            ]
        except ClientError as e:
            logging.warning(f"알람 히스토리 조회 실패: {e}")
            return []

    def list_log_groups(self, region: str, prefix: Optional[str] = None,
                        force_refresh: bool = False) -> List[Dict]:
        """CloudWatch Logs 그룹 목록 조회"""
        cache_key = f"cw_log_groups_{self.profile}_{region}_{prefix or 'all'}"
        if not force_refresh:
            cached = _cache.get(cache_key)
            if cached:
                return cached

        try:
            logs = self.session.client('logs', region_name=region)
            log_groups = []
            paginator = logs.get_paginator('describe_log_groups')

            params = {}
            if prefix:
                params['logGroupNamePrefix'] = prefix

            for page in paginator.paginate(**params):
                for lg in page.get('logGroups', []):
                    log_groups.append({
                        'logGroupName': lg.get('logGroupName', ''),
                        'logGroupArn': lg.get('arn', ''),
                        'creationTime': lg.get('creationTime', 0),
                        'storedBytes': lg.get('storedBytes', 0),
                        'retentionInDays': lg.get('retentionInDays'),
                    })

            _cache.set(cache_key, log_groups)
            return log_groups
        except ClientError as e:
            logging.warning(f"로그 그룹 조회 실패: {e}")
            return []

    def get_log_streams(self, region: str, log_group: str, limit: int = 50) -> List[Dict]:
        """로그 스트림 목록 조회"""
        try:
            logs = self.session.client('logs', region_name=region)
            response = logs.describe_log_streams(
                logGroupName=log_group,
                orderBy='LastEventTime',
                descending=True,
                limit=limit
            )

            return [
                {
                    'logStreamName': stream.get('logStreamName', ''),
                    'creationTime': stream.get('creationTime', 0),
                    'lastEventTimestamp': stream.get('lastEventTimestamp', 0),
                    'lastIngestionTime': stream.get('lastIngestionTime', 0),
                    'storedBytes': stream.get('storedBytes', 0),
                }
                for stream in response.get('logStreams', [])
            ]
        except ClientError as e:
            logging.warning(f"로그 스트림 조회 실패: {e}")
            return []

    def filter_log_events(self, region: str, log_group: str, log_stream: Optional[str] = None,
                          filter_pattern: Optional[str] = None, start_time: Optional[int] = None,
                          end_time: Optional[int] = None, limit: int = 100) -> List[Dict]:
        """로그 이벤트 필터 조회 (실시간 스트리밍에도 활용)"""
        try:
            logs = self.session.client('logs', region_name=region)

            params = {
                'logGroupName': log_group,
                'limit': limit,
            }
            if log_stream:
                params['logStreamNames'] = [log_stream]
            if filter_pattern:
                params['filterPattern'] = filter_pattern
            if start_time:
                params['startTime'] = start_time
            if end_time:
                params['endTime'] = end_time

            response = logs.filter_log_events(**params)

            return [
                {
                    'timestamp': event.get('timestamp', 0),
                    'message': event.get('message', ''),
                    'logStreamName': event.get('logStreamName', ''),
                    'ingestionTime': event.get('ingestionTime', 0),
                }
                for event in response.get('events', [])
            ]
        except ClientError as e:
            logging.warning(f"로그 이벤트 필터 조회 실패: {e}")
            return []

    # =========================================================================
    # Lambda 관련 메서드 (v5.5.0 신규)
    # =========================================================================

    def list_lambda_functions(self, region: str, force_refresh: bool = False) -> List[Dict]:
        """Lambda 함수 목록 조회"""
        cache_key = f"lambda_functions_{self.profile}_{region}"
        if not force_refresh:
            cached = _cache.get(cache_key)
            if cached:
                return cached

        try:
            lambda_client = self.session.client('lambda', region_name=region)
            functions = []
            paginator = lambda_client.get_paginator('list_functions')

            for page in paginator.paginate():
                for func in page.get('Functions', []):
                    functions.append({
                        'FunctionName': func.get('FunctionName', ''),
                        'FunctionArn': func.get('FunctionArn', ''),
                        'Runtime': func.get('Runtime', 'N/A'),
                        'Handler': func.get('Handler', ''),
                        'MemorySize': func.get('MemorySize', 0),
                        'Timeout': func.get('Timeout', 0),
                        'CodeSize': func.get('CodeSize', 0),
                        'Description': func.get('Description', ''),
                        'LastModified': func.get('LastModified', ''),
                        'State': func.get('State', 'Active'),
                        'PackageType': func.get('PackageType', 'Zip'),
                    })

            _cache.set(cache_key, functions)
            return functions
        except ClientError as e:
            logging.warning(f"Lambda 함수 목록 조회 실패: {e}")
            return []

    def get_lambda_function_detail(self, region: str, function_name: str) -> Optional[Dict]:
        """Lambda 함수 상세 정보"""
        try:
            lambda_client = self.session.client('lambda', region_name=region)
            response = lambda_client.get_function(FunctionName=function_name)

            config = response.get('Configuration', {})
            code = response.get('Code', {})

            return {
                'FunctionName': config.get('FunctionName', ''),
                'FunctionArn': config.get('FunctionArn', ''),
                'Runtime': config.get('Runtime', 'N/A'),
                'Role': config.get('Role', ''),
                'Handler': config.get('Handler', ''),
                'CodeSize': config.get('CodeSize', 0),
                'Description': config.get('Description', ''),
                'Timeout': config.get('Timeout', 0),
                'MemorySize': config.get('MemorySize', 0),
                'LastModified': config.get('LastModified', ''),
                'Version': config.get('Version', ''),
                'State': config.get('State', ''),
                'StateReason': config.get('StateReason', ''),
                'Environment': config.get('Environment', {}).get('Variables', {}),
                'VpcConfig': config.get('VpcConfig', {}),
                'Layers': [layer.get('Arn', '') for layer in config.get('Layers', [])],
                'CodeLocation': code.get('Location', ''),
                'RepositoryType': code.get('RepositoryType', ''),
            }
        except ClientError as e:
            logging.warning(f"Lambda 함수 상세 조회 실패: {e}")
            return None

    def invoke_lambda_function(self, region: str, function_name: str,
                               payload: Optional[Dict] = None,
                               invocation_type: str = 'RequestResponse') -> Dict:
        """Lambda 함수 실행 (테스트)"""
        try:
            lambda_client = self.session.client('lambda', region_name=region)

            params = {
                'FunctionName': function_name,
                'InvocationType': invocation_type,
                'LogType': 'Tail',  # 로그 포함
            }

            if payload:
                params['Payload'] = json.dumps(payload)
            else:
                params['Payload'] = '{}'

            response = lambda_client.invoke(**params)

            # 응답 페이로드 읽기
            response_payload = response.get('Payload')
            if response_payload:
                payload_str = response_payload.read().decode('utf-8')
                try:
                    response_data = json.loads(payload_str)
                except json.JSONDecodeError:
                    response_data = payload_str
            else:
                response_data = None

            # 로그 디코딩 (Base64)
            log_result = response.get('LogResult', '')
            if log_result:
                import base64
                log_result = base64.b64decode(log_result).decode('utf-8')

            return {
                'StatusCode': response.get('StatusCode', 0),
                'FunctionError': response.get('FunctionError'),
                'ExecutedVersion': response.get('ExecutedVersion', ''),
                'Payload': response_data,
                'LogResult': log_result,
            }
        except ClientError as e:
            logging.warning(f"Lambda 함수 실행 실패: {e}")
            return {
                'StatusCode': 0,
                'FunctionError': str(e),
                'ExecutedVersion': '',
                'Payload': None,
                'LogResult': '',
            }

    def get_lambda_function_logs(self, region: str, function_name: str,
                                 hours: int = 1, limit: int = 100) -> List[Dict]:
        """Lambda 함수 최근 로그 (CloudWatch Logs 연동)"""
        log_group = f"/aws/lambda/{function_name}"
        start_time = int((time.time() - hours * 3600) * 1000)

        return self.filter_log_events(
            region=region,
            log_group=log_group,
            start_time=start_time,
            limit=limit
        )

    def list_lambda_versions(self, region: str, function_name: str) -> List[Dict]:
        """Lambda 함수 버전 목록"""
        try:
            lambda_client = self.session.client('lambda', region_name=region)
            response = lambda_client.list_versions_by_function(FunctionName=function_name)

            return [
                {
                    'Version': ver.get('Version', ''),
                    'Description': ver.get('Description', ''),
                    'FunctionArn': ver.get('FunctionArn', ''),
                    'LastModified': ver.get('LastModified', ''),
                }
                for ver in response.get('Versions', [])
            ]
        except ClientError as e:
            logging.warning(f"Lambda 버전 조회 실패: {e}")
            return []

    def list_lambda_aliases(self, region: str, function_name: str) -> List[Dict]:
        """Lambda 함수 별칭 목록"""
        try:
            lambda_client = self.session.client('lambda', region_name=region)
            response = lambda_client.list_aliases(FunctionName=function_name)

            return [
                {
                    'Name': alias.get('Name', ''),
                    'FunctionVersion': alias.get('FunctionVersion', ''),
                    'Description': alias.get('Description', ''),
                    'AliasArn': alias.get('AliasArn', ''),
                }
                for alias in response.get('Aliases', [])
            ]
        except ClientError as e:
            logging.warning(f"Lambda 별칭 조회 실패: {e}")
            return []

    # =========================================================================
    # S3 관련 메서드 (v5.5.0 신규)
    # =========================================================================

    def list_s3_buckets(self, force_refresh: bool = False) -> List[Dict]:
        """S3 버킷 목록 조회 (글로벌)"""
        cache_key = f"s3_buckets_{self.profile}"
        if not force_refresh:
            cached = _cache.get(cache_key)
            if cached:
                return cached

        try:
            s3 = self.session.client('s3')
            response = s3.list_buckets()

            buckets = [
                {
                    'Name': bucket.get('Name', ''),
                    'CreationDate': bucket.get('CreationDate'),
                }
                for bucket in response.get('Buckets', [])
            ]

            _cache.set(cache_key, buckets)
            return buckets
        except ClientError as e:
            logging.warning(f"S3 버킷 목록 조회 실패: {e}")
            return []

    def get_bucket_location(self, bucket_name: str) -> str:
        """버킷 리전 조회"""
        try:
            s3 = self.session.client('s3')
            response = s3.get_bucket_location(Bucket=bucket_name)
            # None은 us-east-1을 의미
            location = response.get('LocationConstraint')
            return location if location else 'us-east-1'
        except ClientError as e:
            logging.warning(f"버킷 리전 조회 실패: {e}")
            return 'unknown'

    def list_s3_objects(self, bucket_name: str, prefix: str = "",
                        delimiter: str = "/", max_keys: int = 100) -> Dict:
        """S3 객체 목록 조회 (폴더 구조 지원)"""
        try:
            s3 = self.session.client('s3')

            params = {
                'Bucket': bucket_name,
                'Prefix': prefix,
                'Delimiter': delimiter,
                'MaxKeys': max_keys,
            }

            response = s3.list_objects_v2(**params)

            # 폴더 (CommonPrefixes)
            folders = [
                {
                    'Key': cp.get('Prefix', ''),
                    'Type': 'folder',
                    'Size': 0,
                    'LastModified': None,
                }
                for cp in response.get('CommonPrefixes', [])
            ]

            # 파일 (Contents)
            files = [
                {
                    'Key': obj.get('Key', ''),
                    'Type': 'file',
                    'Size': obj.get('Size', 0),
                    'LastModified': obj.get('LastModified'),
                    'StorageClass': obj.get('StorageClass', 'STANDARD'),
                }
                for obj in response.get('Contents', [])
                if obj.get('Key') != prefix  # 현재 prefix 자체 제외
            ]

            return {
                'folders': folders,
                'files': files,
                'IsTruncated': response.get('IsTruncated', False),
                'NextContinuationToken': response.get('NextContinuationToken'),
            }
        except ClientError as e:
            logging.warning(f"S3 객체 목록 조회 실패: {e}")
            return {'folders': [], 'files': [], 'IsTruncated': False, 'NextContinuationToken': None}

    def get_s3_object_info(self, bucket_name: str, key: str) -> Optional[Dict]:
        """S3 객체 상세 정보"""
        try:
            s3 = self.session.client('s3')
            response = s3.head_object(Bucket=bucket_name, Key=key)

            return {
                'Key': key,
                'ContentLength': response.get('ContentLength', 0),
                'ContentType': response.get('ContentType', ''),
                'LastModified': response.get('LastModified'),
                'ETag': response.get('ETag', ''),
                'StorageClass': response.get('StorageClass', 'STANDARD'),
                'Metadata': response.get('Metadata', {}),
            }
        except ClientError as e:
            logging.warning(f"S3 객체 정보 조회 실패: {e}")
            return None

    def download_s3_object(self, bucket_name: str, key: str, local_path: str,
                           progress_callback: Optional[Callable] = None) -> bool:
        """S3 객체 다운로드"""
        try:
            s3 = self.session.client('s3')

            # 진행률 콜백 설정
            callback = None
            if progress_callback:
                class ProgressPercentage:
                    def __init__(self, client, bucket, key, callback_func):
                        self._size = client.head_object(Bucket=bucket, Key=key)['ContentLength']
                        self._seen_so_far = 0
                        self._callback = callback_func

                    def __call__(self, bytes_amount):
                        self._seen_so_far += bytes_amount
                        percentage = (self._seen_so_far / self._size) * 100
                        self._callback(self._seen_so_far, self._size, percentage)

                callback = ProgressPercentage(s3, bucket_name, key, progress_callback)

            s3.download_file(bucket_name, key, local_path, Callback=callback)
            return True
        except ClientError as e:
            logging.warning(f"S3 다운로드 실패: {e}")
            return False
        except Exception as e:
            logging.warning(f"S3 다운로드 오류: {e}")
            return False

    def upload_s3_object(self, local_path: str, bucket_name: str, key: str,
                         progress_callback: Optional[Callable] = None) -> bool:
        """S3 객체 업로드"""
        try:
            s3 = self.session.client('s3')

            # 진행률 콜백 설정
            callback = None
            if progress_callback:
                file_size = os.path.getsize(local_path)

                class ProgressPercentage:
                    def __init__(self, size, callback_func):
                        self._size = size
                        self._seen_so_far = 0
                        self._callback = callback_func

                    def __call__(self, bytes_amount):
                        self._seen_so_far += bytes_amount
                        percentage = (self._seen_so_far / self._size) * 100
                        self._callback(self._seen_so_far, self._size, percentage)

                callback = ProgressPercentage(file_size, progress_callback)

            s3.upload_file(local_path, bucket_name, key, Callback=callback)
            return True
        except ClientError as e:
            logging.warning(f"S3 업로드 실패: {e}")
            return False
        except Exception as e:
            logging.warning(f"S3 업로드 오류: {e}")
            return False

    def generate_presigned_url(self, bucket_name: str, key: str,
                               expiration: int = 3600) -> Optional[str]:
        """Presigned URL 생성"""
        try:
            s3 = self.session.client('s3')
            url = s3.generate_presigned_url(
                'get_object',
                Params={'Bucket': bucket_name, 'Key': key},
                ExpiresIn=expiration
            )
            return url
        except ClientError as e:
            logging.warning(f"Presigned URL 생성 실패: {e}")
            return None

    def delete_s3_object(self, bucket_name: str, key: str) -> bool:
        """S3 객체 삭제"""
        try:
            s3 = self.session.client('s3')
            s3.delete_object(Bucket=bucket_name, Key=key)
            return True
        except ClientError as e:
            logging.warning(f"S3 객체 삭제 실패: {e}")
            return False


# ----------------------------------------------------------------------------
# 공통 선택 기능 (v5.1.0 확장)
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

def choose_profile() -> str:
    """AWS 프로파일 선택 (항상 str 반환 또는 sys.exit)"""
    lst = list_profiles()
    if not lst:
        print(colored_text("❌ AWS 프로파일이 없습니다. ~/.aws/config 또는 ~/.aws/credentials 파일을 확인하세요.", Colors.ERROR))
        sys.exit(1)

    print(colored_text("\n--- [ AWS Profiles ] ---", Colors.HEADER))
    for i, p in enumerate(lst, 1):
        print(f" {i:2d}) {p}")
    print("------------------------\n")

    retry_count = 0
    while retry_count < Config.MAX_INPUT_RETRIES:
        sel = input(colored_text("사용할 프로파일 번호 입력 (b=뒤로, Enter=종료): ", Colors.PROMPT))
        if not sel:
            sys.exit(0)
        if sel.lower() == 'b':
            sys.exit(0)  # 프로파일 선택이 첫 단계이므로 종료
        if sel.isdigit() and 1 <= int(sel) <= len(lst):
            return lst[int(sel) - 1]
        retry_count += 1
        remaining = Config.MAX_INPUT_RETRIES - retry_count
        if remaining > 0:
            print(colored_text(f"❌ 올바른 번호를 입력하세요. (남은 시도: {remaining}회)", Colors.ERROR))

    # 최대 재시도 횟수 초과
    print(colored_text("❌ 최대 재시도 횟수 초과. 프로그램을 종료합니다.", Colors.ERROR))
    sys.exit(1)

def _check_region_resources(manager: AWSManager, region: str) -> Dict[str, bool]:
    """리전에 EC2/ECS/EKS/RDS/ElastiCache 리소스가 있는지 확인합니다. (v5.5.0 확장)"""
    result = {'ec2': False, 'ecs': False, 'eks': False, 'rds': False, 'cache': False}
    try:
        # EC2 인스턴스 확인
        if manager.list_instances(region):
            result['ec2'] = True
    except Exception:
        pass
    try:
        # ECS 클러스터 확인
        if manager.list_ecs_clusters(region):
            result['ecs'] = True
    except Exception:
        pass
    try:
        # EKS 클러스터 확인
        if manager.list_eks_clusters(region):
            result['eks'] = True
    except Exception:
        pass
    try:
        # RDS 인스턴스 확인 (v5.5.0)
        if manager.get_rds_endpoints(region):
            result['rds'] = True
    except Exception:
        pass
    try:
        # ElastiCache 클러스터 확인 (v5.5.0)
        if manager.list_cache_clusters(region):
            result['cache'] = True
    except Exception:
        pass
    return result

def choose_region(manager: AWSManager) -> Optional[str]:
    """AWS 리전 선택 (str 또는 None 반환) - AWS 리소스가 있는 리전 검색 (v5.5.0 확장)"""
    regs = manager.list_regions()
    valid_regions: Dict[str, Dict[str, bool]] = {}
    print(colored_text("\n⏳ AWS 리소스가 있는 리전을 검색 중입니다. 잠시만 기다려주세요...", Colors.INFO))
    with concurrent.futures.ThreadPoolExecutor(max_workers=manager.max_workers) as ex:
        future = {ex.submit(_check_region_resources, manager, r): r for r in regs}
        for f in concurrent.futures.as_completed(future):
            r = future[f]
            try:
                resources = f.result()
                if any(resources.values()):
                    valid_regions[r] = resources
            except Exception as e:
                logging.warning(f"리전 {r} 검색 중 오류 발생: {e}")

    if not valid_regions:
        print(colored_text("\n⚠ AWS 리소스가 있는 리전이 없습니다.", Colors.WARNING))
        return None

    valid_sorted = sorted(valid_regions.keys())

    # 화살표 메뉴용 항목 생성 (v5.5.0: RDS, Cache 추가)
    region_items = []
    for r in valid_sorted:
        resources = valid_regions[r]
        tags = []
        if resources.get('ec2'):
            tags.append('EC2')
        if resources.get('ecs'):
            tags.append('ECS')
        if resources.get('eks'):
            tags.append('EKS')
        if resources.get('rds'):
            tags.append('RDS')
        if resources.get('cache'):
            tags.append('Cache')
        tags_str = ', '.join(tags) if tags else ''
        item = f"{r:<20} [{tags_str}]"
        region_items.append(item)
    region_items.append("🌏 모든 리전 통합 뷰")
    region_items.append("🔙 돌아가기")

    title = "AWS Regions with Resources"
    sel = interactive_select(region_items, title=title)

    if sel == -1 or sel == len(valid_sorted) + 1:  # 돌아가기
        return None
    if sel == len(valid_sorted):  # 모든 리전 통합 뷰
        return 'multi-region'
    return valid_sorted[sel]

def choose_jump_host(manager: AWSManager, region: str) -> Optional[str]:
    """사용자에게 SSM 관리 인스턴스(Jump Host)를 선택하게 합니다. Role=jumphost 태그가 있는 EC2만 표시합니다."""
    # Role=jumphost 태그가 있는 SSM 인스턴스만 가져오기
    jump_host_tags = {"Role": "jumphost"}
    ssm_targets = manager.list_ssm_managed(region, jump_host_tags)

    if not ssm_targets:
        print(colored_text("⚠ Role=jumphost 태그가 있는 SSM 관리 인스턴스가 없습니다.", Colors.WARNING))
        print("   점프 호스트로 사용할 EC2에 'Role=jumphost' 태그를 추가해주세요.")
        return None

    if len(ssm_targets) == 1:
        print(colored_text(f"\n(info) 유일한 Jump Host '{ssm_targets[0]['Name']} ({ssm_targets[0]['Id']})'를 사용합니다.", Colors.INFO))
        return ssm_targets[0]['Id']

    # 화살표 메뉴용 항목 생성
    jump_items = []
    for target in ssm_targets:
        item = f"{target['Name']:<30} ({target['Id']})"
        jump_items.append(item)
    jump_items.append("🔙 돌아가기")

    title = f"Select Jump Host (Role=jumphost)  │  Region: {region}"
    sel = interactive_select(jump_items, title=title)

    if sel == -1 or sel == len(ssm_targets):  # 돌아가기
        return None
    return ssm_targets[sel]['Id']

def show_recent_connections():
    """최근 연결 목록을 표시하고 선택할 수 있게 합니다."""
    history = load_history()

    all_recent = []
    for service_type, entries in history.items():
        for entry in entries:
            entry['service_type'] = service_type
            all_recent.append(entry)

    # 시간순 정렬
    all_recent.sort(key=lambda x: x['timestamp'], reverse=True)

    if not all_recent:
        print(colored_text("\n⚠ 최근 연결 기록이 없습니다.", Colors.WARNING))
        return None

    # 최대 10개
    recent_10 = all_recent[:10]

    # 화살표 메뉴용 항목 생성
    recent_items = []
    service_icons = {"ec2": "🖥️", "rds": "🗄️", "cache": "⚡", "ecs": "🐳"}
    for entry in recent_10:
        service_icon = service_icons.get(entry['service_type'], "📦")
        timestamp = datetime.fromisoformat(entry['timestamp']).strftime('%m-%d %H:%M')
        item = f"{service_icon} {entry['instance_name']:<25} [{entry['region']}] {timestamp}"
        recent_items.append(item)
    recent_items.append("🔙 돌아가기")

    title = "Recent Connections"
    sel = interactive_select(recent_items, title=title, show_index=False)

    if sel == -1 or sel == len(recent_10):  # 돌아가기
        return None
    return recent_10[sel]

def reconnect_to_instance(manager: AWSManager, entry: dict):
    """히스토리 항목에 따라 직접 인스턴스에 재접속합니다."""
    service_type = entry['service_type']
    region = entry['region']
    instance_id = entry['instance_id']
    instance_name = entry['instance_name']
    
    print(colored_text(f"\n🔄 {instance_name}({instance_id})에 재접속을 시도합니다...", Colors.INFO))
    
    try:
        if service_type == 'ec2':
            # EC2 재접속
            ec2 = manager.session.client('ec2', region_name=region)
            resp = ec2.describe_instances(InstanceIds=[instance_id])
            
            if not resp.get('Reservations'):
                print(colored_text(f"❌ 인스턴스 {instance_id}를 찾을 수 없습니다.", Colors.ERROR))
                return
            
            instance = resp['Reservations'][0]['Instances'][0]
            
            if instance['State']['Name'] != 'running':
                print(colored_text(f"❌ 인스턴스가 실행 중이 아닙니다. 상태: {instance['State']['Name']}", Colors.ERROR))
                return
            
            # Windows/Linux 판단하여 접속
            if instance.get('PlatformDetails', 'Linux').lower().startswith('windows'):
                # Windows RDP 접속
                local_port = calculate_local_port(instance_id)
                print(colored_text(f"(info) Windows 인스턴스 RDP 연결을 시작합니다 (localhost:{local_port})...", Colors.INFO))

                proc = start_port_forward(manager.profile, region, instance_id, local_port)
                launch_rdp(local_port)
                
                print("(info) RDP 창을 닫은 후, 이 터미널로 돌아와 Enter를 누르면 RDP 연결이 종료됩니다.")
                input("\n[Press Enter to terminate RDP connection]...\n")
                proc.terminate()
                print(colored_text("🔌 RDP 포트 포워딩 연결을 종료했습니다.", Colors.SUCCESS))
            else:
                # Linux SSH 접속
                print(colored_text("(info) Linux 인스턴스 SSM 연결을 시작합니다...", Colors.INFO))
                launch_linux_wt(manager.profile, region, instance_id)
                print(colored_text("✅ 새 터미널에서 SSM 세션이 시작되었습니다.", Colors.SUCCESS))
        
        elif service_type == 'rds':
            # RDS 재접속 (기존 코드와 동일)
            rds = manager.session.client('rds', region_name=region)
            dbs = rds.describe_db_instances(DBInstanceIdentifier=instance_id).get('DBInstances', [])
            
            if not dbs:
                print(colored_text(f"❌ RDS 인스턴스 {instance_id}를 찾을 수 없습니다.", Colors.ERROR))
                return
            
            db = dbs[0]
            
            # DB 자격 증명 가져오기
            db_user, db_password = get_db_credentials()
            if not db_user or not db_password:
                return
            
            # 점프 호스트 선택
            tgt = choose_jump_host(manager, region)
            if not tgt:
                return
            
            # 포트 포워딩 및 DB 클라이언트 실행
            local_port = 11000
            print(colored_text(f"🔹 포트 포워딩: [localhost:{local_port}] -> [{db['DBInstanceIdentifier']}:{db['Endpoint']['Port']}]", Colors.INFO))

            params_dict = {
                "host": [db["Endpoint"]["Address"]],
                "portNumber": [str(db["Endpoint"]["Port"])],
                "localPortNumber": [str(local_port)]
            }
            params = json.dumps(params_dict)
            proc = subprocess.Popen(
                create_ssm_forward_command(manager.profile, region, tgt, 'AWS-StartPortForwardingSessionToRemoteHost', params),
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            time.sleep(Config.WAIT_PORT_READY)

            # DB 클라이언트 실행 (mysql, DBeaver 등)
            if DEFAULT_DB_TOOL_PATH and Path(DEFAULT_DB_TOOL_PATH).exists():
                network_type_map = {
                    'postgres': 'postgresql', 'mysql': 'mysql',
                    'mariadb': 'mariadb', 'sqlserver': 'mssql',
                }
                network_type = next((v for k, v in network_type_map.items() if k in db['Engine']), 'mysql')

                command = [
                    DEFAULT_DB_TOOL_PATH, f"--description={db['DBInstanceIdentifier']}", f"-n={network_type}",
                    f"-h=localhost", f"-P={local_port}", f"-u={db_user}", f"-p={db_password}",
                ]
                if db.get('DBName'):
                    command.append(f"-d={db['DBName']}")

                subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                print(colored_text("✅ DB 클라이언트가 실행되었습니다.", Colors.SUCCESS))
            
            print("(완료되면 이 창에서 Enter 키를 눌러 연결을 종료합니다)")
            input("[Press Enter to terminate connection]...\n")
            proc.terminate()
            print(colored_text("🔌 포트 포워딩 연결을 종료했습니다.", Colors.SUCCESS))
        
        elif service_type == 'cache':
            # ElastiCache 재접속 (기존 코드와 동일)
            ec = manager.session.client('elasticache', region_name=region)
            clusters = ec.describe_cache_clusters(CacheClusterId=instance_id, ShowCacheNodeInfo=True).get('CacheClusters', [])
            
            if not clusters:
                print(colored_text(f"❌ ElastiCache 클러스터 {instance_id}를 찾을 수 없습니다.", Colors.ERROR))
                return
            
            cluster = clusters[0]
            ep = cluster.get('ConfigurationEndpoint') or (
                cluster.get('CacheNodes')[0].get('Endpoint') if cluster.get('CacheNodes') else {}
            )
            
            # 점프 호스트 선택
            tgt = choose_jump_host(manager, region)
            if not tgt:
                return
            
            # 포트 포워딩
            local_port = 12000
            print(colored_text(f"🔹 포트 포워딩: [localhost:{local_port}] -> [{cluster['CacheClusterId']}:{ep.get('Port',0)}]", Colors.INFO))
            
            params_dict = {
                "host": [ep.get('Address','')],
                "portNumber": [str(ep.get('Port',0))],
                "localPortNumber": [str(local_port)]
            }
            params = json.dumps(params_dict)
            proc = subprocess.Popen(
                create_ssm_forward_command(manager.profile, region, tgt, 'AWS-StartPortForwardingSessionToRemoteHost', params),
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            time.sleep(Config.WAIT_PORT_READY)
            
            print(colored_text(f"✅ 포트 포워딩이 활성화되었습니다.", Colors.SUCCESS))
            print(f"   Engine: {cluster['Engine']}")
            print(f"   Address: localhost:{local_port}")
            
            # 클라이언트 실행 시도
            try:
                tool = DEFAULT_CACHE_REDIS_CLI if cluster['Engine'].startswith('redis') else DEFAULT_CACHE_MEMCACHED_CLI
                args = [tool, '-h', '127.0.0.1', '-p', str(local_port)] if 'redis' in tool else [tool, '127.0.0.1', str(local_port)]
                # macOS에서 새 터미널 탭으로 실행
                launch_terminal_session(args)
                print(colored_text("✅ 로컬 클라이언트가 새 터미널 탭에서 실행되었습니다.", Colors.SUCCESS))
            except Exception as e:
                logging.warning(f"캐시 클라이언트 실행 실패: {e}")
            
            print("(완료되면 이 창에서 Enter 키를 눌러 연결을 종료합니다)")
            input("[Press Enter to terminate connection]...\n")
            proc.terminate()
            print(colored_text("🔌 포트 포워딩 연결을 종료했습니다.", Colors.SUCCESS))
        
        elif service_type == 'ecs':
            # ECS 재접속 (v5.0.2 원본)
            print(colored_text(f"🐳 ECS 컨테이너 {instance_name}에 재접속합니다...", Colors.INFO))
            # instance_id는 "cluster:service:task:container" 형식으로 저장됨
            parts = instance_id.split(':')
            if len(parts) >= 4:
                cluster_name, service_name, task_arn, container_name = parts[0], parts[1], parts[2], parts[3]
                launch_ecs_exec(manager.profile, region, cluster_name, task_arn, container_name)
            else:
                print(colored_text("❌ ECS 접속 정보가 올바르지 않습니다.", Colors.ERROR))
    
    except ClientError as e:
        print(colored_text(f"❌ AWS 호출 실패: {e}", Colors.ERROR))
    except Exception as e:
        print(colored_text(f"❌ 재접속 실패: {e}", Colors.ERROR))
        logging.error(f"재접속 실패: {e}", exc_info=True)

# ----------------------------------------------------------------------------
# SSM 호출 함수 (v4.41 수정)
# ----------------------------------------------------------------------------
def ssm_cmd(profile, region, iid):
    """리눅스 인스턴스 접속용 SSM 세션 명령어 구성"""
    cmd = [
        'aws', 'ssm', 'start-session',
        '--region', region,
        '--target', iid,
        '--document-name', 'AWS-StartInteractiveCommand',
        '--parameters', '{"command":["bash -l"]}'
    ]
    if profile != 'default':
        cmd[1:1] = ['--profile', profile]
    return cmd

def create_ssm_forward_command(profile, region, target, document, parameters):
    """SSM 포트 포워딩 세션 명령어를 생성합니다."""
    cmd = [
        'aws', 'ssm', 'start-session',
        '--region', region,
        '--target', target,
        '--document-name', document,
        '--parameters', parameters
    ]
    if profile != 'default':
        cmd[1:1] = ['--profile', profile]
    return cmd

def start_port_forward(profile, region, iid, port):
    cmd = [
        'aws', 'ssm', 'start-session',
        '--region', region,
        '--target', iid,
        '--document-name', 'AWS-StartPortForwardingSession',
        '--parameters', f'{{"portNumber":["3389"],"localPortNumber":["{port}"]}}'
    ]
    if profile != 'default':
        cmd[1:1] = ['--profile', profile]
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)

def wait_for_port(port, timeout=30):
    """포트가 LISTEN 상태가 될 때까지 대기"""
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex(('localhost', port))
            sock.close()
            if result == 0:
                return True
        except (socket.error, socket.timeout, OSError) as e:
            logging.debug(f"포트 {port} 대기 중 예외: {e}")
        time.sleep(0.5)
    return False

def launch_rdp(port):
    """macOS에서 RDP 접속 - Windows App 사용"""
    # 포트가 준비될 때까지 대기
    print(colored_text(f'⏳ 포트 {port}가 준비될 때까지 대기 중...', Colors.INFO))
    if not wait_for_port(port):
        print(colored_text(f'\n❌ 포트 {port}가 준비되지 않았습니다.', Colors.ERROR))
        return

    print(colored_text('✅ 포트가 준비되었습니다.', Colors.SUCCESS))

    print(colored_text(f'\n📊 RDP 연결 정보:', Colors.HEADER))
    print(colored_text(f'   호스트: localhost:{port}', Colors.INFO))
    print(colored_text(f'   사용자: Administrator', Colors.INFO))
    print(colored_text(f'   (비밀번호는 별도로 확인하세요)', Colors.WARNING))

    # .rdp 파일 생성 (pathlib 사용)
    import tempfile
    rdp_file = Path(tempfile.gettempdir()) / f'ec2menu_{port}.rdp'
    rdp_content = f"""screen mode id:i:2
desktopwidth:i:1920
desktopheight:i:1080
session bpp:i:32
compression:i:1
keyboardhook:i:2
displayconnectionbar:i:1
disable wallpaper:i:1
disable full window drag:i:1
disable menu anims:i:1
disable themes:i:0
disable cursor setting:i:0
bitmapcachepersistenable:i:1
full address:s:localhost:{port}
audiomode:i:0
redirectprinters:i:0
redirectcomports:i:0
redirectsmartcards:i:0
redirectclipboard:i:1
redirectposdevices:i:0
autoreconnection enabled:i:1
authentication level:i:0
prompt for credentials:i:0
negotiate security layer:i:1
remoteapplicationmode:i:0
username:s:Administrator
"""

    with open(rdp_file, 'w') as f:
        f.write(rdp_content)

    # 파일 권한을 600으로 설정 (소유자만 읽기/쓰기)
    os.chmod(rdp_file, 0o600)

    # atexit 정리 목록에 추가 (thread-safe)
    global _temp_files_to_cleanup, _temp_files_lock
    with _temp_files_lock:
        _temp_files_to_cleanup.append(rdp_file)

    print(colored_text(f'\n📄 RDP 연결 파일 생성: {rdp_file}', Colors.INFO))

    try:
        # Windows App 또는 Microsoft Remote Desktop으로 열기
        if Path('/Applications/Windows App.app').exists():
            print(colored_text('✅ Windows App으로 연결합니다...', Colors.SUCCESS))
            subprocess.run(['open', '-a', 'Windows App', str(rdp_file)])
            time.sleep(Config.WAIT_PORT_READY)  # 앱이 파일을 읽을 시간 대기
        elif Path('/Applications/Microsoft Remote Desktop.app').exists():
            print(colored_text('✅ Microsoft Remote Desktop으로 연결합니다...', Colors.SUCCESS))
            subprocess.run(['open', '-a', 'Microsoft Remote Desktop', str(rdp_file)])
            time.sleep(Config.WAIT_PORT_READY)  # 앱이 파일을 읽을 시간 대기
        else:
            print(colored_text('\n⚠️ RDP 클라이언트가 설치되지 않았습니다.', Colors.WARNING))
            print(colored_text('\n권장: App Store에서 "Microsoft Remote Desktop" 설치', Colors.INFO))
            print(colored_text(f'\n수동 연결 정보:', Colors.INFO))
            print(colored_text(f'   호스트: localhost:{port}', Colors.INFO))
            print(colored_text(f'   사용자: Administrator', Colors.INFO))
            return
    finally:
        # .rdp 파일 즉시 삭제 시도
        try:
            if rdp_file.exists():
                rdp_file.unlink()
                with _temp_files_lock:
                    _temp_files_to_cleanup.remove(rdp_file)  # 정리 목록에서 제거
                print(colored_text(f'🗑️  임시 RDP 파일 삭제됨', Colors.INFO))
        except Exception as e:
            # 삭제 실패 시 경고 로그 기록 (atexit에서 재시도)
            logging.warning(f"RDP 파일 즉시 삭제 실패 (프로그램 종료 시 재시도): {rdp_file} - {e}")

def check_iterm2():
    """iTerm2 설치 확인"""
    iterm_path = '/Applications/iTerm.app'
    return os.path.exists(iterm_path)

def launch_terminal_session(command_list, use_iterm=True):
    """macOS에서 새 터미널 탭에서 명령 실행 (iTerm2 또는 Terminal.app)"""
    import shlex
    # 명령어 리스트를 쉘 명령어 문자열로 변환
    # shlex.quote()로 공백/특수문자 포함 인자를 적절히 보호
    cmd_str = ' '.join(shlex.quote(arg) for arg in command_list)

    # AppleScript 문자열 리터럴용 이스케이프
    # AppleScript에서 쌍따옴표 문자열 사용 시 내부 쌍따옴표만 이스케이프 필요
    applescript_safe = cmd_str.replace('\\', '\\\\').replace('"', '\\"')

    if use_iterm and check_iterm2():
        # iTerm2가 실행 중인지 확인
        is_running = subprocess.run(
            ['osascript', '-e', 'tell application "System Events" to (name of processes) contains "iTerm2"'],
            capture_output=True, text=True
        ).stdout.strip() == 'true'

        # iTerm2 창 개수 확인
        if is_running:
            window_count_result = subprocess.run(
                ['osascript', '-e', 'tell application "iTerm" to count windows'],
                capture_output=True, text=True
            )
            window_count = int(window_count_result.stdout.strip()) if window_count_result.stdout.strip().isdigit() else 0
        else:
            window_count = 0

        try:
            if not is_running or window_count == 0:
                # iTerm2가 실행 중이 아니거나 창이 없음 → open으로 실행하고 기본 세션에 명령 실행
                subprocess.run(['open', '-a', 'iTerm'], check=True)
                time.sleep(Config.WAIT_APP_LAUNCH)  # iTerm2가 완전히 시작될 때까지 대기
                applescript = f'''
                tell application "iTerm"
                    tell current session of current window
                        write text "{applescript_safe}"
                    end tell
                end tell
                '''
                subprocess.run(['osascript', '-e', applescript], check=True)
            else:
                # iTerm2가 이미 실행 중이고 창이 있음 → 새 탭 추가
                applescript = f'''
                tell application "iTerm"
                    tell current window
                        create tab with default profile
                        tell current session
                            write text "{applescript_safe}"
                        end tell
                    end tell
                end tell
                '''
                subprocess.run(['osascript', '-e', applescript], check=True)
        except subprocess.CalledProcessError as e:
            logging.error(f"iTerm2 AppleScript 실행 실패: {e}")
            print(colored_text(f"❌ iTerm2 실행 중 오류 발생. 수동으로 터미널을 열고 다음 명령을 실행하세요:", Colors.ERROR))
            print(colored_text(f"   {cmd_str}", Colors.INFO))
    else:
        # Terminal.app 사용
        try:
            applescript = f'''
            tell application "Terminal"
                activate
                do script "{applescript_safe}"
            end tell
            '''
            subprocess.run(['osascript', '-e', applescript], check=True)
        except subprocess.CalledProcessError as e:
            logging.error(f"Terminal.app AppleScript 실행 실패: {e}")
            print(colored_text(f"❌ Terminal.app 실행 중 오류 발생. 수동으로 터미널을 열고 다음 명령을 실행하세요:", Colors.ERROR))
            print(colored_text(f"   {cmd_str}", Colors.INFO))

def launch_linux_wt(profile, region, iid):
    """리눅스 인스턴스에 새 터미널 탭으로 접속 (macOS용)"""
    cmd = ssm_cmd(profile, region, iid)
    # iTerm2 사용 (use_iterm=True로 복원)
    launch_terminal_session(cmd, use_iterm=True)

# ----------------------------------------------------------------------------
# ECS 호출 함수 (v5.0.2 원본)
# ----------------------------------------------------------------------------
def ecs_exec_cmd(profile, region, cluster, task_arn, container):
    """ECS Exec 명령어 구성"""
    cmd = [
        'aws', 'ecs', 'execute-command',
        '--region', region,
        '--cluster', cluster,
        '--task', task_arn,
        '--container', container,
        '--interactive',
        '--command', '/bin/bash'
    ]
    if profile != 'default':
        cmd[1:1] = ['--profile', profile]
    return cmd

def launch_ecs_exec(profile, region, cluster, task_arn, container):
    """ECS 컨테이너에 새 터미널로 접속 (macOS용)"""
    cmd = ecs_exec_cmd(profile, region, cluster, task_arn, container)
    launch_terminal_session(cmd)

# ----------------------------------------------------------------------------
# EC2 메뉴 (v5.1.0 확장 - 배치 작업 지원)
# ----------------------------------------------------------------------------
def ec2_menu(manager: AWSManager, region: str):
    global _sort_key, _sort_reverse
    procs = []
    batch_manager = BatchJobManager(manager)
    file_transfer_manager = FileTransferManager(manager)
    
    try:
        while True:
            force_refresh = False
            if region == 'multi-region':
                # 멀티 리전 모드
                regions = manager.list_regions()
                insts_raw = manager.list_instances_multi_region(regions, force_refresh)
                if not insts_raw:
                    print(colored_text("\n⚠ 모든 리전에 실행 중인 EC2 인스턴스가 없습니다.", Colors.WARNING))
                    break
                region_display = "All Regions"
            else:
                # 단일 리전 모드
                insts_raw = manager.list_instances(region, force_refresh)
                if not insts_raw:
                    print(colored_text("\n⚠ 이 리전에는 실행 중인 EC2 인스턴스가 없습니다.", Colors.WARNING))
                    break
                region_display = region

            insts_display = []
            for i in insts_raw:
                name = next((t['Value'] for t in i.get('Tags', []) if t['Key'] == 'Name'), '')
                instance_region = i.get('_region', region)
                insts_display.append({
                    'raw': i, 'Name': name,
                    'PublicIp': i.get('PublicIpAddress', '-'),
                    'PrivateIp': i.get('PrivateIpAddress', '-'),
                    'Region': instance_region
                })
            
            # 정렬 적용
            insts = sort_instances(insts_display, _sort_key, _sort_reverse)

            # 화살표 메뉴용 항목 생성
            menu_items = []
            for i_data in insts:
                i = i_data['raw']
                state = i['State']['Name']
                platform = i.get('PlatformDetails', 'Linux/UNIX')
                os_short = "Win" if platform.lower().startswith('windows') else "Linux"

                if region == 'multi-region':
                    item = f"{i_data['Name']:<22} {i['InstanceId']:<20} {i_data['Region']:<14} {state:<10} {os_short:<6} {i_data['PrivateIp']}"
                else:
                    item = f"{i_data['Name']:<22} {i['InstanceId']:<20} {state:<10} {os_short:<6} {i_data['PrivateIp']}"
                menu_items.append(item)

            # 특수 옵션 추가
            menu_items.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            menu_items.append("📋 배치 작업 (여러 인스턴스에 명령 실행)")
            menu_items.append("📁 파일 업로드 (여러 인스턴스에 파일 전송)")
            menu_items.append("🔄 목록 새로고침")
            menu_items.append("🔙 메인 메뉴로 돌아가기")

            title = f"EC2 Instances  │  Profile: {manager.profile}  │  Region: {region_display}  │  Sort: {_sort_key}"
            footer = "↑↓: 이동  Enter: 접속  /: 검색  b: 메인  r: 새로고침"

            selected = interactive_select(menu_items, title=title, footer=footer)

            # 구분선 인덱스
            separator_idx = len(insts)

            if selected == -1 or selected == len(menu_items) - 1:  # 취소 또는 돌아가기
                break
            elif selected == separator_idx:  # 구분선 선택 시 무시
                continue
            elif selected == separator_idx + 1:  # 배치 작업
                sel = 'batch'
            elif selected == separator_idx + 2:  # 파일 업로드
                sel = 'upload'
            elif selected == separator_idx + 3:  # 새로고침
                sel = 'r'
            elif 0 <= selected < separator_idx:  # 인스턴스 선택
                sel = str(selected + 1)
            else:
                continue
            
            if not sel or sel == 'b':
                break
            elif sel == 'r':
                print(colored_text("🔄 목록을 새로고침합니다...", Colors.INFO))
                # 캐시 무효화 후 다음 루프에서 새로고침
                invalidate_cache_for_service(manager, region, "instances")
                force_refresh = True
                continue
            elif sel in ['n', 't', 's', 'r']:
                # 정렬 처리
                sort_map = {'n': 'Name', 't': 'Type', 's': 'State', 'r': 'Region'}
                new_sort_key = sort_map.get(sel, 'Name')
                if new_sort_key == _sort_key:
                    _sort_reverse = not _sort_reverse  # 같은 키면 역순 토글
                else:
                    _sort_key = new_sort_key
                    _sort_reverse = False
                continue
            elif sel == 'batch':
                # 배치 작업 모드
                print(colored_text("\n📋 배치 작업 모드", Colors.HEADER))
                batch_sel = input(colored_text("배치 작업할 인스턴스 번호들 입력 (b=뒤로, 예: 1,2,3,5): ", Colors.PROMPT)).strip()
                
                if not batch_sel:
                    continue
                if batch_sel.lower() == 'b':
                    continue
                
                try:
                    choices = [int(x.strip()) for x in batch_sel.split(',') if x.strip().isdigit()]
                    valid_choices = [c for c in choices if 1 <= c <= len(insts)]
                    if not valid_choices:
                        print(colored_text("❌ 유효한 번호를 입력하세요.", Colors.ERROR))
                        continue
                        
                    # Linux 인스턴스만 필터링
                    selected_instances = filter_linux_instances(insts, valid_choices, region)

                    if not selected_instances:
                        print(colored_text("❌ 배치 작업할 Linux 인스턴스가 없습니다.", Colors.ERROR))
                        continue
                    
                    # 배치 명령 입력
                    print(colored_text(f"\n{len(selected_instances)}개 Linux 인스턴스에서 실행할 명령을 입력하세요:", Colors.INFO))
                    for inst in selected_instances:
                        print(f"  - {inst['Name']} ({inst['raw']['InstanceId']})")
                    
                    batch_command = input(colored_text("\n실행할 명령 (b=뒤로): ", Colors.PROMPT)).strip()
                    if not batch_command:
                        print(colored_text("❌ 명령을 입력해야 합니다.", Colors.ERROR))
                        continue
                    if batch_command.lower() == 'b':
                        continue
                    
                    # 배치 작업 실행
                    results = batch_manager.execute_batch_command(selected_instances, batch_command)
                    
                    # 결과 표시
                    batch_manager.show_batch_results(results)
                    
                    input(colored_text("\n[Press Enter to continue]...", Colors.PROMPT))
                    continue
                    
                except ValueError:
                    print(colored_text("❌ 숫자와 쉼표만 입력하세요.", Colors.ERROR))
                    continue
            elif sel == 'upload':
                # 파일 전송 모드
                print(colored_text("\n📁 파일 전송 모드", Colors.HEADER))
                upload_sel = input(colored_text("파일 전송할 인스턴스 번호들 입력 (b=뒤로, 예: 1,2,3,5): ", Colors.PROMPT)).strip()
                
                if not upload_sel:
                    continue
                if upload_sel.lower() == 'b':
                    continue
                
                try:
                    choices = [int(x.strip()) for x in upload_sel.split(',') if x.strip().isdigit()]
                    valid_choices = [c for c in choices if 1 <= c <= len(insts)]
                    if not valid_choices:
                        print(colored_text("❌ 유효한 번호를 입력하세요.", Colors.ERROR))
                        continue
                        
                    # Linux 인스턴스만 필터링
                    selected_instances = filter_linux_instances(insts, valid_choices, region)

                    if not selected_instances:
                        print(colored_text("❌ 파일 전송 가능한 Linux 인스턴스가 없습니다.", Colors.ERROR))
                        continue
                    
                    print(colored_text(f"\n선택된 인스턴스 ({len(selected_instances)}개):", Colors.INFO))
                    for inst_data in selected_instances:
                        print(f"  - {inst_data['Name']} ({inst_data['raw']['InstanceId']})")
                    
                    # 파일 경로 입력
                    print(colored_text("\n📁 파일 선택 방법:", Colors.INFO))
                    print("  1) 직접 입력: /Users/username/Documents/file.txt")
                    print("  2) 드래그 앤 드롭: 파일을 이 창으로 끌어오기")
                    print("  3) 복사 붙여넣기: Finder에서 Option+Cmd+C로 경로 복사 후 Cmd+V")
                    
                    local_path = input(colored_text("\n업로드할 로컬 파일 경로 (b=뒤로): ", Colors.PROMPT)).strip()
                    if not local_path:
                        print(colored_text("❌ 파일 경로를 입력해야 합니다.", Colors.ERROR))
                        continue
                    if local_path.lower() == 'b':
                        continue
                    
                    # 경로 정규화 (macOS용)
                    local_path = normalize_file_path(local_path)

                    # 파일 존재 확인 및 크기 확인
                    local_path_obj = Path(local_path)
                    if not local_path_obj.exists():
                        print(colored_text(f"❌ 파일이 존재하지 않습니다: {local_path}", Colors.ERROR))
                        continue

                    # 파일 크기 확인 (TOCTOU 개선)
                    try:
                        file_size = local_path_obj.stat().st_size
                    except OSError as e:
                        print(colored_text(f"❌ 파일 접근 실패: {local_path} - {e}", Colors.ERROR))
                        continue
                    print(colored_text(f"📊 파일 크기: {file_transfer_manager._format_size(file_size)}", Colors.INFO))
                    
                    remote_path = input(colored_text("대상 EC2 경로 (b=뒤로): ", Colors.PROMPT)).strip()
                    if not remote_path:
                        print(colored_text("❌ 대상 경로를 입력해야 합니다.", Colors.ERROR))
                        continue
                    if remote_path.lower() == 'b':
                        continue
                    
                    # 확인
                    print(colored_text(f"\n📋 전송 정보:", Colors.HEADER))
                    print(f"로컬 파일: {local_path}")
                    print(f"대상 경로: {remote_path}")
                    print(f"대상 인스턴스: {len(selected_instances)}개")
                    
                    confirm = input(colored_text("\n전송을 시작하시겠습니까? (y/n): ", Colors.PROMPT)).strip().lower()
                    if confirm != 'y':
                        continue
                    
                    # 파일 전송 실행
                    results = file_transfer_manager.upload_file_to_multiple_instances(
                        local_path, remote_path, selected_instances
                    )
                    
                    # 결과 요약
                    success_count = sum(1 for r in results if r.status == 'SUCCESS')
                    print(colored_text(f"\n📊 전송 완료: {success_count}/{len(results)} 성공", Colors.SUCCESS if success_count == len(results) else Colors.WARNING))
                    
                    input(colored_text("\n[Press Enter to continue]...", Colors.PROMPT))
                    continue
                    
                except ValueError:
                    print(colored_text("❌ 숫자와 쉼표만 입력하세요.", Colors.ERROR))
                    continue

            try:
                choices = [int(x.strip()) for x in sel.split(',') if x.strip().isdigit()]
                valid_choices = [c for c in choices if 1 <= c <= len(insts)]
                if not valid_choices:
                    print(colored_text("❌ 유효한 번호를 입력하세요.", Colors.ERROR))
                    continue
            except ValueError:
                print(colored_text("❌ 숫자와 쉼표만 입력하세요.", Colors.ERROR))
                continue

            rdp_started = False
            for i, choice_idx in enumerate(valid_choices):
                inst_data = insts[choice_idx - 1]
                inst = inst_data['raw']
                inst_region = inst_data['Region']
                
                # 히스토리에 추가
                add_to_history('ec2', manager.profile, inst_region, inst['InstanceId'], inst_data['Name'])
                
                if inst.get('PlatformDetails', 'Linux').lower().startswith('windows'):
                    rdp_started = True
                    local_port = calculate_local_port(inst['InstanceId']) + i
                    print(colored_text(f"\n(info) Windows 인스턴스 RDP 연결을 시작합니다 (localhost:{local_port})...", Colors.INFO))

                    proc = start_port_forward(manager.profile, inst_region, inst['InstanceId'], local_port)
                    procs.append(proc)
                    launch_rdp(local_port)
                else:
                    print(colored_text(f"\n(info) Linux 인스턴스 SSM 연결을 시작합니다...", Colors.INFO))
                    launch_linux_wt(manager.profile, inst_region, inst['InstanceId'])
                    print(colored_text("(info) 새 터미널에서 SSM 세션이 시작되었습니다. 이 창에서는 다른 작업을 계속할 수 있습니다.", Colors.SUCCESS))
            
            if rdp_started:
                print("\n(info) RDP 창을 닫은 후, 이 터미널로 돌아와 Enter를 누르면 모든 RDP 연결이 종료됩니다.")
                input("\n[Press Enter to terminate all RDP connection processes]...\n")
                break 
            else:
                time.sleep(Config.WAIT_PORT_READY)

    finally:
        if procs:
            for proc in procs:
                proc.terminate()
                try:
                    proc.wait(timeout=5)  # 5초 대기
                except subprocess.TimeoutExpired:
                    logging.warning(f"프로세스 종료 타임아웃 (PID={proc.pid}), 강제 종료")
                    proc.kill()
                    proc.wait()  # 좀비 프로세스 방지
            print(colored_text("🔌 모든 RDP 포트 포워딩 연결을 종료했습니다.", Colors.SUCCESS))

# ----------------------------------------------------------------------------
# EKS 관련 유틸리티 함수 (v5.3.0 신규)
# ----------------------------------------------------------------------------
def check_kubectl_installed() -> bool:
    """kubectl 설치 여부를 확인합니다."""
    try:
        result = subprocess.run(
            ['kubectl', 'version', '--client', '--output=json'],
            capture_output=True, text=True, timeout=5
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False

def check_kubeconfig_exists(cluster_name: str) -> bool:
    """특정 클러스터에 대한 kubeconfig 컨텍스트가 있는지 확인합니다."""
    try:
        result = subprocess.run(
            ['kubectl', 'config', 'get-contexts', '-o', 'name'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            contexts = result.stdout.strip().split('\n')
            return any(cluster_name in ctx for ctx in contexts)
        return False
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False

def update_kubeconfig(profile: str, region: str, cluster_name: str) -> bool:
    """aws eks update-kubeconfig 명령을 실행하여 kubeconfig를 업데이트합니다."""
    try:
        cmd = [
            'aws', 'eks', 'update-kubeconfig',
            '--region', region,
            '--name', cluster_name,
            '--profile', profile
        ]
        print(colored_text(f"\n⏳ kubeconfig 업데이트 중...", Colors.INFO))
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            print(colored_text(f"✅ kubeconfig 업데이트 완료", Colors.SUCCESS))
            return True
        else:
            print(colored_text(f"❌ kubeconfig 업데이트 실패: {result.stderr}", Colors.ERROR))
            return False
    except subprocess.TimeoutExpired:
        print(colored_text("❌ kubeconfig 업데이트 시간 초과", Colors.ERROR))
        return False
    except FileNotFoundError:
        print(colored_text("❌ AWS CLI가 설치되어 있지 않습니다.", Colors.ERROR))
        return False

def get_kubectl_pods(namespace: str = 'default', debug: bool = False) -> List[Dict]:
    """kubectl을 통해 Pod 목록을 가져옵니다."""
    try:
        result = subprocess.run(
            ['kubectl', 'get', 'pods', '-n', namespace, '-o', 'json'],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            pods = []
            for item in data.get('items', []):
                metadata = item.get('metadata', {})
                status = item.get('status', {})
                container_statuses = status.get('containerStatuses', [])

                pods.append({
                    'Name': metadata.get('name', 'N/A'),
                    'Namespace': metadata.get('namespace', 'default'),
                    'Status': status.get('phase', 'Unknown'),
                    'Ready': f"{sum(1 for c in container_statuses if c.get('ready', False))}/{len(container_statuses)}",
                    'Restarts': sum(c.get('restartCount', 0) for c in container_statuses),
                    'Age': metadata.get('creationTimestamp', 'N/A'),
                    'Containers': [c.get('name', '') for c in container_statuses],
                })
            return pods
        else:
            if debug or result.stderr:
                print(colored_text(f"⚠ kubectl get pods 실패: {result.stderr.strip()}", Colors.WARNING))
            return []
    except subprocess.TimeoutExpired:
        print(colored_text("⚠ kubectl get pods 시간 초과 (30초)", Colors.WARNING))
        return []
    except FileNotFoundError:
        print(colored_text("⚠ kubectl이 설치되어 있지 않습니다.", Colors.WARNING))
        return []
    except json.JSONDecodeError as e:
        print(colored_text(f"⚠ kubectl 출력 파싱 실패: {e}", Colors.WARNING))
        return []

def get_kubectl_namespaces(debug: bool = False) -> List[str]:
    """kubectl을 통해 네임스페이스 목록을 가져옵니다."""
    try:
        result = subprocess.run(
            ['kubectl', 'get', 'namespaces', '-o', 'json'],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return [item.get('metadata', {}).get('name', '') for item in data.get('items', [])]
        else:
            if debug or result.stderr:
                print(colored_text(f"⚠ kubectl get namespaces 실패: {result.stderr.strip()}", Colors.WARNING))
            return []
    except subprocess.TimeoutExpired:
        print(colored_text("⚠ kubectl get namespaces 시간 초과 (30초)", Colors.WARNING))
        return []
    except FileNotFoundError:
        print(colored_text("⚠ kubectl이 설치되어 있지 않습니다.", Colors.WARNING))
        return []
    except json.JSONDecodeError as e:
        print(colored_text(f"⚠ kubectl 출력 파싱 실패: {e}", Colors.WARNING))
        return []

def launch_kubectl_exec(pod_name: str, namespace: str, container: Optional[str] = None):
    """새 터미널에서 kubectl exec 세션을 시작합니다. (iTerm2 우선 사용)"""
    cmd_parts = ['kubectl', 'exec', '-it', pod_name, '-n', namespace]
    if container:
        cmd_parts.extend(['-c', container])
    cmd_parts.extend(['--', '/bin/sh', '-c', 'if command -v bash > /dev/null; then exec bash; else exec sh; fi'])

    if IS_MAC:
        launch_terminal_session(cmd_parts, use_iterm=True)

def launch_kubectl_logs(pod_name: str, namespace: str, container: Optional[str] = None, follow: bool = True):
    """새 터미널에서 kubectl logs 세션을 시작합니다. (iTerm2 우선 사용)"""
    cmd_parts = ['kubectl', 'logs', pod_name, '-n', namespace]
    if container:
        cmd_parts.extend(['-c', container])
    if follow:
        cmd_parts.append('-f')

    if IS_MAC:
        launch_terminal_session(cmd_parts, use_iterm=True)

def open_cloudshell_browser(region: str):
    """CloudShell 콘솔 페이지를 브라우저에서 엽니다."""
    import webbrowser
    url = f'https://{region}.console.aws.amazon.com/cloudshell/home?region={region}'
    print(colored_text(f"\n🌐 CloudShell 페이지를 브라우저에서 엽니다...", Colors.INFO))
    print(colored_text(f"   URL: {url}", Colors.INFO))
    webbrowser.open(url)
    print(colored_text("✅ 브라우저에서 CloudShell에 로그인하세요.", Colors.SUCCESS))

# ----------------------------------------------------------------------------
# EKS 메뉴 (v5.3.0 신규)
# ----------------------------------------------------------------------------
def eks_menu(manager: AWSManager, region: str):
    """EKS 클러스터 관리 메뉴"""
    kubectl_available = check_kubectl_installed()

    while True:
        # 멀티 리전 모드 지원 (v5.5.0)
        if region == 'multi-region':
            regions = manager.list_regions()
            all_clusters = []
            print(colored_text("⏳ 모든 리전에서 EKS 클러스터 검색 중...", Colors.INFO))
            for r in regions:
                try:
                    clusters_in_region = manager.list_eks_clusters(r)
                    for c in clusters_in_region:
                        c['_region'] = r
                    all_clusters.extend(clusters_in_region)
                except Exception:
                    pass
            clusters = all_clusters
        else:
            # 1. EKS 클러스터 목록
            clusters = manager.list_eks_clusters(region)
            for c in clusters:
                c['_region'] = region
        if not clusters:
            print(colored_text(f"\n⚠ 리전 {region}에 EKS 클러스터가 없습니다.", Colors.WARNING))
            return

        # kubectl 미설치 알림
        if not kubectl_available:
            print(colored_text("\n⚠ kubectl 미설치 - Pod 관련 기능 비활성화", Colors.WARNING))

        # 화살표 메뉴용 항목 생성
        cluster_items = []
        for cluster in clusters:
            version = cluster.get('Version', 'N/A')
            cluster_region = cluster.get('_region', region)
            if region == 'multi-region':
                item = f"{cluster['Name']:<30} {cluster['Status']:<10} K8s: {version:<8} [{cluster_region}]"
            else:
                item = f"{cluster['Name']:<30} {cluster['Status']:<10} K8s: {version}"
            cluster_items.append(item)
        cluster_items.append("🔙 돌아가기")

        region_display = "All Regions" if region == 'multi-region' else region
        title = f"EKS Clusters  │  Region: {region_display}  │  {len(clusters)} clusters"
        cluster_sel = interactive_select(cluster_items, title=title)

        if cluster_sel == -1 or cluster_sel == len(clusters):
            return

        selected_cluster = clusters[cluster_sel]
        cluster_name = selected_cluster['Name']
        cluster_region = selected_cluster.get('_region', region)

        # 2. 클러스터 상세 메뉴
        while True:
            # 화살표 메뉴용 항목 생성
            sub_items = [
                "📊 클러스터 상세 정보",
                "🖥️ 노드그룹 목록",
                "🚀 Fargate 프로필",
                "⚙️ kubeconfig 설정",
            ]

            if kubectl_available:
                sub_items.extend([
                    "📦 Pod 목록 조회",
                    "📋 Pod 로그 조회",
                    "🔗 Pod exec 접속",
                ])
            else:
                sub_items.extend([
                    "📦 Pod 목록 조회 (kubectl 필요)",
                    "📋 Pod 로그 조회 (kubectl 필요)",
                    "🔗 Pod exec 접속 (kubectl 필요)",
                ])
            sub_items.append("🔙 돌아가기")

            title = f"EKS: {cluster_name}  │  Region: {cluster_region}"
            sub_sel = interactive_select(sub_items, title=title, show_index=False)

            if sub_sel == -1 or sub_sel == len(sub_items) - 1:
                break

            if sub_sel == 0:
                # 클러스터 상세 정보
                detail = manager.get_eks_cluster_detail(cluster_region, cluster_name)
                if detail:
                    print(colored_text(f"\n--- [ Cluster Detail: {cluster_name} ] ---", Colors.HEADER))
                    print(f"  Name:            {detail['Name']}")
                    print(f"  Status:          {colored_text(detail['Status'], get_status_color(detail['Status']))}")
                    print(f"  Version:         {detail['Version']}")
                    print(f"  Platform:        {detail['PlatformVersion']}")
                    print(f"  Endpoint:        {detail['Endpoint'][:60]}..." if len(detail.get('Endpoint', '')) > 60 else f"  Endpoint:        {detail.get('Endpoint', 'N/A')}")
                    print(f"  VPC:             {detail['VpcId']}")
                    print(f"  Public Access:   {'Yes' if detail['EndpointPublicAccess'] else 'No'}")
                    print(f"  Private Access:  {'Yes' if detail['EndpointPrivateAccess'] else 'No'}")
                    if detail.get('CreatedAt'):
                        print(f"  Created:         {detail['CreatedAt']}")
                    print("------------------------------------------\n")
                    input(colored_text("계속하려면 Enter를 누르세요...", Colors.PROMPT))

            elif sub_sel == 1:
                # 노드그룹 목록
                nodegroups = manager.list_eks_nodegroups(cluster_region, cluster_name)
                if not nodegroups:
                    print(colored_text(f"\n⚠ 클러스터 {cluster_name}에 노드그룹이 없습니다.", Colors.WARNING))
                else:
                    print(colored_text(f"\n--- [ Node Groups in {cluster_name} ] ---", Colors.HEADER))
                    for idx, ng in enumerate(nodegroups, 1):
                        status_color = get_status_color(ng['Status'])
                        status_colored = colored_text(ng['Status'], status_color)
                        instance_types = ', '.join(ng.get('InstanceTypes', ['N/A']))
                        scaling = f"{ng['DesiredSize']}/{ng['MinSize']}-{ng['MaxSize']}"
                        capacity = ng.get('CapacityType', 'ON_DEMAND')
                        print(f" {idx:2d}) {ng['Name']} ({status_colored})")
                        print(f"      Types: {instance_types} | Scaling: {scaling} | {capacity}")
                    print("------------------------------------------\n")
                input(colored_text("계속하려면 Enter를 누르세요...", Colors.PROMPT))

            elif sub_sel == 2:
                # Fargate 프로필
                profiles = manager.list_eks_fargate_profiles(cluster_region, cluster_name)
                if not profiles:
                    print(colored_text(f"\n⚠ 클러스터 {cluster_name}에 Fargate 프로필이 없습니다.", Colors.WARNING))
                else:
                    print(colored_text(f"\n--- [ Fargate Profiles in {cluster_name} ] ---", Colors.HEADER))
                    for idx, fp in enumerate(profiles, 1):
                        status_color = get_status_color(fp['Status'])
                        status_colored = colored_text(fp['Status'], status_color)
                        namespaces = ', '.join(fp.get('Namespaces', ['N/A']))
                        print(f" {idx:2d}) {fp['Name']} ({status_colored})")
                        print(f"      Namespaces: {namespaces}")
                    print("------------------------------------------\n")
                input(colored_text("계속하려면 Enter를 누르세요...", Colors.PROMPT))

            elif sub_sel == 3:
                # kubeconfig 설정
                update_kubeconfig(manager.profile, cluster_region, cluster_name)
                input(colored_text("계속하려면 Enter를 누르세요...", Colors.PROMPT))

            elif sub_sel == 4:
                # Pod 목록 조회
                if not kubectl_available:
                    print(colored_text("❌ kubectl이 설치되어 있지 않습니다.", Colors.ERROR))
                    print(colored_text("   설치 방법: brew install kubectl", Colors.INFO))
                    continue

                # kubeconfig 확인 및 업데이트
                if not check_kubeconfig_exists(cluster_name):
                    print(colored_text(f"⚠ 클러스터 {cluster_name}의 kubeconfig가 없습니다.", Colors.WARNING))
                    update_sel = input(colored_text("kubeconfig를 설정하시겠습니까? (y/N): ", Colors.PROMPT)).strip().lower()
                    if update_sel == 'y':
                        if not update_kubeconfig(manager.profile, cluster_region, cluster_name):
                            continue
                    else:
                        continue

                # 네임스페이스 선택 (화살표 메뉴)
                namespaces = get_kubectl_namespaces()
                if not namespaces:
                    print(colored_text("❌ 네임스페이스 목록을 가져올 수 없습니다.", Colors.ERROR))
                    continue

                ns_items = namespaces + ["🔙 돌아가기"]
                ns_sel = interactive_select(ns_items, title="Namespace 선택")

                if ns_sel == -1 or ns_sel == len(namespaces):
                    continue
                selected_ns = namespaces[ns_sel]

                # Pod 목록 조회 (화살표 메뉴)
                pods = get_kubectl_pods(selected_ns)
                if not pods:
                    print(colored_text(f"⚠ 네임스페이스 {selected_ns}에 Pod가 없습니다.", Colors.WARNING))
                    input(colored_text("계속하려면 Enter를 누르세요...", Colors.PROMPT))
                    continue

                # Pod 정보를 화살표 메뉴로 표시
                pod_items = []
                for pod in pods:
                    status = pod['Status']
                    ready = pod['Ready']
                    restarts = pod['Restarts']
                    pod_items.append(f"{pod['Name']:<45} {status:<12} Ready:{ready:<6} Restarts:{restarts}")
                pod_items.append("🔙 돌아가기")

                pod_sel = interactive_select(pod_items, title=f"Pods in {selected_ns}")

                if pod_sel == -1 or pod_sel == len(pods):
                    continue

                # 선택된 Pod 상세 정보
                selected_pod = pods[pod_sel]
                print(colored_text(f"\n--- [ Pod 상세: {selected_pod['Name']} ] ---", Colors.HEADER))
                print(f"  Name:      {selected_pod['Name']}")
                print(f"  Namespace: {selected_ns}")
                print(f"  Status:    {selected_pod['Status']}")
                print(f"  Ready:     {selected_pod['Ready']}")
                print(f"  Restarts:  {selected_pod['Restarts']}")
                print(f"  Age:       {selected_pod.get('Age', 'N/A')}")
                if selected_pod.get('Containers'):
                    print(f"  Containers: {', '.join(selected_pod['Containers'])}")
                print("----------------------------------------------")
                input(colored_text("계속하려면 Enter를 누르세요...", Colors.PROMPT))

            elif sub_sel == 5:
                # Pod 로그 조회
                if not kubectl_available:
                    print(colored_text("❌ kubectl이 설치되어 있지 않습니다.", Colors.ERROR))
                    input(colored_text("계속하려면 Enter를 누르세요...", Colors.PROMPT))
                    continue

                if not check_kubeconfig_exists(cluster_name):
                    print(colored_text(f"⚠ 먼저 kubeconfig를 설정하세요.", Colors.WARNING))
                    input(colored_text("계속하려면 Enter를 누르세요...", Colors.PROMPT))
                    continue

                namespaces = get_kubectl_namespaces()
                if not namespaces:
                    continue

                # 화살표 메뉴로 네임스페이스 선택
                ns_items = namespaces + ["🔙 돌아가기"]
                title = "Namespace 선택"
                ns_sel = interactive_select(ns_items, title=title)

                if ns_sel == -1 or ns_sel == len(namespaces):
                    continue
                selected_ns = namespaces[ns_sel]

                pods = get_kubectl_pods(selected_ns)
                if not pods:
                    print(colored_text(f"⚠ 네임스페이스 {selected_ns}에 Pod가 없습니다.", Colors.WARNING))
                    input(colored_text("계속하려면 Enter를 누르세요...", Colors.PROMPT))
                    continue

                # 화살표 메뉴로 Pod 선택
                pod_items = []
                for pod in pods:
                    item = f"{pod['Name']:<40} {pod['Status']:<10}"
                    pod_items.append(item)
                pod_items.append("🔙 돌아가기")

                title = f"Pods in {selected_ns}"
                pod_sel = interactive_select(pod_items, title=title)

                if pod_sel == -1 or pod_sel == len(pods):
                    continue
                selected_pod = pods[pod_sel]

                # 컨테이너 선택 (여러 개인 경우)
                containers = selected_pod.get('Containers', [])
                selected_container = None
                if len(containers) > 1:
                    container_items = containers + ["🔙 돌아가기"]
                    title = "Container 선택"
                    c_sel = interactive_select(container_items, title=title)
                    if c_sel == -1 or c_sel == len(containers):
                        continue
                    selected_container = containers[c_sel]
                elif containers:
                    selected_container = containers[0]

                print(colored_text(f"\n📋 Pod '{selected_pod['Name']}' 로그를 새 터미널에서 엽니다...", Colors.INFO))
                launch_kubectl_logs(selected_pod['Name'], selected_ns, selected_container)
                print(colored_text("✅ 새 터미널에서 로그 스트리밍이 시작되었습니다.", Colors.SUCCESS))
                time.sleep(1)

            elif sub_sel == 6:
                # Pod exec 접속
                if not kubectl_available:
                    print(colored_text("❌ kubectl이 설치되어 있지 않습니다.", Colors.ERROR))
                    input(colored_text("계속하려면 Enter를 누르세요...", Colors.PROMPT))
                    continue

                if not check_kubeconfig_exists(cluster_name):
                    print(colored_text(f"⚠ 먼저 kubeconfig를 설정하세요.", Colors.WARNING))
                    input(colored_text("계속하려면 Enter를 누르세요...", Colors.PROMPT))
                    continue

                namespaces = get_kubectl_namespaces()
                if not namespaces:
                    continue

                # 화살표 메뉴로 네임스페이스 선택
                ns_items = namespaces + ["🔙 돌아가기"]
                title = "Namespace 선택"
                ns_sel = interactive_select(ns_items, title=title)

                if ns_sel == -1 or ns_sel == len(namespaces):
                    continue
                selected_ns = namespaces[ns_sel]

                pods = get_kubectl_pods(selected_ns)
                if not pods:
                    print(colored_text(f"⚠ 네임스페이스 {selected_ns}에 Pod가 없습니다.", Colors.WARNING))
                    input(colored_text("계속하려면 Enter를 누르세요...", Colors.PROMPT))
                    continue

                # 화살표 메뉴로 Pod 선택
                pod_items = []
                for pod in pods:
                    item = f"{pod['Name']:<40} {pod['Status']:<10}"
                    pod_items.append(item)
                pod_items.append("🔙 돌아가기")

                title = f"Pods in {selected_ns}"
                pod_sel = interactive_select(pod_items, title=title)

                if pod_sel == -1 or pod_sel == len(pods):
                    continue
                selected_pod = pods[pod_sel]

                # 컨테이너 선택
                containers = selected_pod.get('Containers', [])
                selected_container = None
                if len(containers) > 1:
                    container_items = containers + ["🔙 돌아가기"]
                    title = "Container 선택"
                    c_sel = interactive_select(container_items, title=title)
                    if c_sel == -1 or c_sel == len(containers):
                        continue
                    selected_container = containers[c_sel]
                elif containers:
                    selected_container = containers[0]

                print(colored_text(f"\n🔗 Pod '{selected_pod['Name']}'에 접속합니다...", Colors.INFO))
                launch_kubectl_exec(selected_pod['Name'], selected_ns, selected_container)
                print(colored_text("✅ 새 터미널에서 exec 세션이 시작되었습니다.", Colors.SUCCESS))
                time.sleep(1)

# ----------------------------------------------------------------------------
# ECS 메뉴 (v5.0.2 원본 + 캐싱)
# ----------------------------------------------------------------------------
def ecs_menu(manager: AWSManager, region: str):
    """ECS 클러스터/서비스/태스크/컨테이너 메뉴"""
    while True:
        # 멀티 리전 모드 지원 (v5.5.0)
        if region == 'multi-region':
            regions = manager.list_regions()
            all_clusters = []
            print(colored_text("⏳ 모든 리전에서 ECS 클러스터 검색 중...", Colors.INFO))
            for r in regions:
                try:
                    clusters_in_region = manager.list_ecs_clusters(r)
                    for c in clusters_in_region:
                        c['_region'] = r
                    all_clusters.extend(clusters_in_region)
                except Exception:
                    pass
            clusters = all_clusters
        else:
            # 1. ECS 클러스터 목록
            clusters = manager.list_ecs_clusters(region)
            for c in clusters:
                c['_region'] = region

        if not clusters:
            print(colored_text(f"\n⚠ 리전 {region}에 ECS 클러스터가 없습니다.", Colors.WARNING))
            return

        # 화살표 메뉴용 항목 생성
        cluster_items = []
        for cluster in clusters:
            cluster_region = cluster.get('_region', region)
            if region == 'multi-region':
                item = f"{cluster['Name']:<30} {cluster['Status']:<10} Tasks: {cluster['RunningTasks']}, Services: {cluster['ActiveServices']} [{cluster_region}]"
            else:
                item = f"{cluster['Name']:<30} {cluster['Status']:<10} Tasks: {cluster['RunningTasks']}, Services: {cluster['ActiveServices']}"
            cluster_items.append(item)
        cluster_items.append("🔙 돌아가기")

        region_display = "All Regions" if region == 'multi-region' else region
        title = f"ECS Clusters  │  Region: {region_display}  │  {len(clusters)} clusters"
        cluster_sel = interactive_select(cluster_items, title=title)

        if cluster_sel == -1 or cluster_sel == len(clusters):
            return

        selected_cluster = clusters[cluster_sel]
        cluster_name = selected_cluster['Name']
        cluster_region = selected_cluster.get('_region', region)

        # 2. ECS 서비스 목록
        while True:
            services = manager.list_ecs_services(cluster_region, cluster_name)
            if not services:
                print(colored_text(f"\n⚠ 클러스터 {cluster_name}에 ECS 서비스가 없습니다.", Colors.WARNING))
                break

            # 화살표 메뉴용 항목 생성
            service_items = []
            for service in services:
                item = f"{service['Name']:<30} {service['Status']:<10} {service['LaunchType']:<10} Running: {service['RunningCount']}/{service['DesiredCount']}"
                service_items.append(item)
            service_items.append("🔙 돌아가기")

            title = f"ECS Services  │  Cluster: {cluster_name}"
            service_sel = interactive_select(service_items, title=title)

            if service_sel == -1 or service_sel == len(services):
                break

            selected_service = services[service_sel]
            service_name = selected_service['Name']

            # 3. ECS 태스크 목록
            while True:
                tasks = manager.list_ecs_tasks(cluster_region, cluster_name, service_name)
                if not tasks:
                    print(colored_text(f"\n⚠ 서비스 {service_name}에 실행 중인 태스크가 없습니다.", Colors.WARNING))
                    break

                # 화살표 메뉴용 항목 생성
                task_items = []
                for task in tasks:
                    task_id_short = task['TaskArn'].split('/')[-1]
                    exec_icon = "✅" if task['EnableExecuteCommand'] else "❌"
                    containers_str = ", ".join([c['Name'] for c in task['Containers']])
                    item = f"{task_id_short[:20]:<22} {task['LastStatus']:<10} Exec: {exec_icon}  [{containers_str}]"
                    task_items.append(item)
                task_items.append("🔙 돌아가기")

                title = f"ECS Tasks  │  Service: {service_name}"
                task_sel = interactive_select(task_items, title=title)

                if task_sel == -1 or task_sel == len(tasks):
                    break

                selected_task = tasks[task_sel]
                task_id = selected_task['TaskArn'].split('/')[-1]
                containers = selected_task['Containers']

                # 4. 태스크 작업 선택 (접속 또는 로그)
                while True:
                    exec_icon = "✅" if selected_task['EnableExecuteCommand'] else "❌"
                    action_items = [
                        f"🔗 컨테이너 접속 (Exec: {exec_icon})",
                        "📋 컨테이너 로그 조회",
                        "🔙 돌아가기"
                    ]

                    title = f"Task: {task_id[:20]}..."
                    action_sel = interactive_select(action_items, title=title, show_index=False)

                    if action_sel == -1 or action_sel == 2:
                        break

                    if action_sel == 0:
                        # 컨테이너 접속
                        if not selected_task['EnableExecuteCommand']:
                            print(colored_text("❌ 이 태스크는 ECS Exec이 활성화되지 않았습니다.", Colors.ERROR))
                            print("서비스 설정에서 enableExecuteCommand를 true로 설정하세요.")
                            input(colored_text("\n[Enter를 눌러 계속]", Colors.PROMPT))
                            continue

                        if len(containers) == 1:
                            container = containers[0]
                            print(colored_text(f"\n🐳 컨테이너 '{container['Name']}'에 접속합니다...", Colors.INFO))
                            history_id = f"{cluster_name}:{service_name}:{task_id}:{container['Name']}"
                            add_to_history('ecs', manager.profile, cluster_region, history_id, f"{service_name}/{container['Name']}")
                            launch_ecs_exec(manager.profile, cluster_region, cluster_name, selected_task['TaskArn'], container['Name'])
                            print(colored_text("✅ 새 터미널에서 ECS Exec 세션이 시작되었습니다.", Colors.SUCCESS))
                            time.sleep(Config.WAIT_PORT_READY)
                        else:
                            # 화살표 메뉴로 컨테이너 선택
                            container_items = []
                            for container in containers:
                                item = f"📦 {container['Name']} ({container['Status']})"
                                container_items.append(item)
                            container_items.append("🔙 돌아가기")

                            title = "접속할 컨테이너 선택"
                            container_sel = interactive_select(container_items, title=title, show_index=False)

                            if container_sel == -1 or container_sel == len(containers):
                                continue

                            selected_container = containers[container_sel]
                            print(colored_text(f"\n🐳 컨테이너 '{selected_container['Name']}'에 접속합니다...", Colors.INFO))
                            history_id = f"{cluster_name}:{service_name}:{task_id}:{selected_container['Name']}"
                            add_to_history('ecs', manager.profile, cluster_region, history_id, f"{service_name}/{selected_container['Name']}")
                            launch_ecs_exec(manager.profile, cluster_region, cluster_name, selected_task['TaskArn'], selected_container['Name'])
                            print(colored_text("✅ 새 터미널에서 ECS Exec 세션이 시작되었습니다.", Colors.SUCCESS))
                            time.sleep(Config.WAIT_PORT_READY)

                    elif action_sel == 1:
                        # 로그 조회
                        log_configs = manager.get_ecs_task_log_config(cluster_region, selected_task['TaskDefinitionArn'])
                        if not log_configs:
                            print(colored_text("❌ 이 태스크에는 CloudWatch Logs 설정이 없습니다.", Colors.ERROR))
                            print(colored_text("   태스크 정의에서 awslogs 로그 드라이버를 설정하세요.", Colors.INFO))
                            input(colored_text("\n[Enter를 눌러 계속]", Colors.PROMPT))
                            continue

                        # 컨테이너 선택 (로그 설정이 있는 컨테이너만)
                        if len(log_configs) == 1:
                            selected_log_config = log_configs[0]
                        else:
                            # 화살표 메뉴로 로그 컨테이너 선택
                            log_container_items = []
                            for lc in log_configs:
                                item = f"{lc['ContainerName']} → {lc['LogGroup']}"
                                log_container_items.append(item)
                            log_container_items.append("🔙 돌아가기")

                            title = "로그를 조회할 컨테이너 선택"
                            lc_sel = interactive_select(log_container_items, title=title)

                            if lc_sel == -1 or lc_sel == len(log_configs):
                                continue
                            selected_log_config = log_configs[lc_sel]

                        # 로그 스트림 찾기
                        log_group = selected_log_config['LogGroup']
                        log_prefix = selected_log_config['LogStreamPrefix']
                        log_region = selected_log_config['Region']
                        container_name = selected_log_config['ContainerName']

                        print(colored_text(f"\n⏳ 로그 스트림을 검색 중...", Colors.INFO))

                        # 로그 스트림 이름 패턴: {prefix}/{container-name}/{task-id}
                        log_stream_name = f"{log_prefix}/{container_name}/{task_id}"

                        # 화살표 메뉴로 로그 조회 방식 선택
                        log_mode_items = [
                            "📄 최근 로그 보기 (마지막 100줄)",
                            "📺 실시간 로그 스트리밍 (새 터미널)",
                            "🔙 돌아가기"
                        ]
                        title = "로그 조회 방식"
                        log_mode = interactive_select(log_mode_items, title=title, show_index=False)

                        if log_mode == -1 or log_mode == 2:
                            continue

                        if log_mode == 0:
                            # 최근 로그 조회
                            print(colored_text(f"\n📋 로그 조회 중... ({container_name})", Colors.INFO))
                            logs = manager.get_ecs_container_logs(log_region, log_group, log_stream_name, limit=100)

                            if not logs:
                                print(colored_text("⚠ 로그가 없거나 로그 스트림을 찾을 수 없습니다.", Colors.WARNING))
                                print(colored_text(f"   Log Group: {log_group}", Colors.INFO))
                                print(colored_text(f"   Log Stream: {log_stream_name}", Colors.INFO))
                            else:
                                print(colored_text(f"\n--- [ Logs: {container_name} ({len(logs)} lines) ] ---", Colors.HEADER))
                                for log in logs:
                                    ts = datetime.fromtimestamp(log['timestamp'] / 1000).strftime('%Y-%m-%d %H:%M:%S')
                                    msg = log['message'].rstrip()
                                    print(f"{colored_text(ts, Colors.INFO)} | {msg}")
                                print("------------------------------------------\n")
                            input(colored_text("계속하려면 Enter를 누르세요...", Colors.PROMPT))

                        elif log_mode == 1:
                            # 실시간 로그 스트리밍 (새 터미널에서 AWS CLI 사용)
                            cmd = f"aws logs tail {log_group} --log-stream-names {log_stream_name} --follow --profile {manager.profile} --region {log_region}"
                            print(colored_text(f"\n📺 실시간 로그 스트리밍을 시작합니다...", Colors.INFO))

                            if IS_MAC:
                                script = f'''
                                tell application "Terminal"
                                    activate
                                    do script "{cmd}"
                                end tell
                                '''
                                subprocess.Popen(['osascript', '-e', script])
                            print(colored_text("✅ 새 터미널에서 로그 스트리밍이 시작되었습니다.", Colors.SUCCESS))
                            time.sleep(1)

# ----------------------------------------------------------------------------
# RDS 접속 (v5.0.2 원본 + 캐싱)
# ----------------------------------------------------------------------------
def connect_to_rds(manager: AWSManager, tool_path: str, region: str):
    while True:
        if region == 'multi-region':
            # 멀티 리전 모드
            regions = manager.list_regions()
            dbs = manager.get_rds_endpoints_multi_region(regions)
            region_display = "All Regions"
        else:
            # 단일 리전 모드
            dbs = manager.get_rds_endpoints(region)
            region_display = region
            
        if not dbs:
            print(colored_text(f"\n⚠ {region_display}에 RDS 인스턴스가 없습니다", Colors.WARNING))
            return

        # 화살표 메뉴용 항목 생성
        db_items = []
        for db in dbs:
            engine_display = db['Engine']
            if 'aurora-mysql' in engine_display:
                engine_display = 'aurora (mysql)'
            elif 'aurora-postgresql' in engine_display:
                engine_display = 'aurora (postgres)'

            if region == 'multi-region':
                item = f"{db['Id']:<40} {engine_display:<20} [{db['_region']}]"
            else:
                item = f"{db['Id']:<40} {engine_display:<20}"
            db_items.append(item)
        db_items.append("🔄 목록 새로고침")
        db_items.append("🔙 돌아가기")

        title = f"RDS Instances  │  Region: {region_display}"
        sel = interactive_select(db_items, title=title)

        if sel == -1 or sel == len(dbs) + 1:  # 돌아가기
            return
        if sel == len(dbs):  # 새로고침
            print(colored_text("🔄 목록을 새로고침합니다...", Colors.INFO))
            invalidate_cache_for_service(manager, region, "rds")
            continue

        valid_choices = [sel + 1]  # 선택된 DB (1-based)

        # DB 자격 증명 가져오기
        db_user, db_password = get_db_credentials()
        if not db_user or not db_password:
            continue

        # 첫 번째 선택된 DB의 리전에서 점프 호스트 선택 (멀티 리전의 경우)
        target_region = dbs[valid_choices[0] - 1].get('_region', region)
        if region == 'multi-region':
            print(colored_text(f"\n📍 리전 {target_region}에서 점프 호스트를 선택합니다.", Colors.INFO))
        
        tgt = choose_jump_host(manager, target_region)
        if not tgt:
            continue

        print(colored_text(f"\n(info) SSM 인스턴스 '{tgt}'를 통해 포트 포워딩을 시작합니다.", Colors.INFO))

        procs = []
        try:
            for i, choice_idx in enumerate(valid_choices):
                db = dbs[choice_idx - 1]
                db_region = db.get('_region', region)
                local_port = 11000 + i
                print(colored_text(f"🔹 포트 포워딩: [localhost:{local_port}] -> [{db['Id']}:{db['Port']}] ({db_region})", Colors.INFO))
                
                # 히스토리에 추가
                add_to_history('rds', manager.profile, db_region, db['Id'], db['Id'])
                
                params_dict = {
                    "host": [db["Endpoint"]],
                    "portNumber": [str(db["Port"])],
                    "localPortNumber": [str(local_port)]
                }
                params = json.dumps(params_dict)
                proc = subprocess.Popen(
                    create_ssm_forward_command(manager.profile, target_region, tgt, 'AWS-StartPortForwardingSessionToRemoteHost', params),
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                procs.append(proc)
            
            time.sleep(Config.WAIT_PORT_READY)

            print(colored_text("\n✅ 모든 포트 포워딩 활성화. DBeaver로 자동 연결합니다...", Colors.SUCCESS))

            # DBeaver 자동 연결 (환경변수 지원)
            dbeaver_path = os.environ.get('DBEAVER_PATH', '/Applications/DBeaver.app/Contents/MacOS/dbeaver')
            if Path(dbeaver_path).exists():
                for i, choice_idx in enumerate(valid_choices):
                    db = dbs[choice_idx - 1]
                    local_port = 11000 + i

                    # 엔진 타입에 따른 드라이버 매핑
                    driver_map = {
                        'postgres': 'postgresql',
                        'mysql': 'mysql8',
                        'mariadb': 'mariaDB',
                        'aurora-mysql': 'mysql8',
                        'aurora-postgresql': 'postgresql',
                    }
                    driver = 'mysql8'
                    for key, val in driver_map.items():
                        if key in db['Engine'].lower():
                            driver = val
                            break

                    # DBeaver 연결 스펙 생성
                    db_name = db.get('DBName', '')
                    # 데이터베이스 이름이 있을 때만 database 파라미터 포함
                    if db_name:
                        conn_spec = f"driver={driver}|host=localhost|port={local_port}|database={db_name}|user={db_user}|password={db_password}|name={db['Id']}"
                    else:
                        conn_spec = f"driver={driver}|host=localhost|port={local_port}|user={db_user}|password={db_password}|name={db['Id']}"

                    # DBeaver 실행
                    subprocess.Popen(
                        [dbeaver_path, '-nosplash', '-con', conn_spec],
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )
                    print(colored_text(f"✅ DBeaver 연결 시작: {db['Id']} (localhost:{local_port})", Colors.SUCCESS))

                # DBeaver 창을 포그라운드로 활성화
                time.sleep(1)  # DBeaver가 시작될 시간 대기
                try:
                    subprocess.run(['osascript', '-e', 'tell application "DBeaver" to activate'],
                                   check=False, timeout=5)
                except (subprocess.TimeoutExpired, FileNotFoundError) as e:
                    logging.warning(f"DBeaver 활성화 실패: {e}")
            elif tool_path and Path(tool_path).exists():
                # mysql CLI 같은 도구가 있으면 실행
                for i, choice_idx in enumerate(valid_choices):
                    db = dbs[choice_idx - 1]
                    local_port = 11000 + i
                    command = [
                        tool_path, '-h', 'localhost', '-P', str(local_port),
                        '-u', db_user, f'-p{db_password}'
                    ]
                    if db.get('DBName'):
                        command.append(db['DBName'])
                    subprocess.Popen(command)
                    print(colored_text(f"✅ {tool_path} 연결 시작: {db['Id']}", Colors.SUCCESS))
            else:
                # DB 도구 없음: 연결 정보만 표시
                print(colored_text("\n📊 데이터베이스 연결 정보:", Colors.HEADER))
                for i, choice_idx in enumerate(valid_choices):
                    db = dbs[choice_idx - 1]
                    local_port = 11000 + i
                    print(colored_text(f"\n  [{i+1}] {db['Id']}", Colors.INFO))
                    print(colored_text(f"      호스트: localhost", Colors.INFO))
                    print(colored_text(f"      포트: {local_port}", Colors.INFO))
                    print(colored_text(f"      사용자: {db_user}", Colors.INFO))
                    print(colored_text(f"      비밀번호: {'*' * 8}", Colors.INFO))  # 보안: 비밀번호 마스킹
                    if db.get('DBName'):
                        print(colored_text(f"      데이터베이스: {db['DBName']}", Colors.INFO))
                print(colored_text(f"\n💡 DBeaver를 설치하면 자동 연결이 가능합니다.", Colors.INFO))

            print("\n(완료되면 이 창에서 Enter 키를 눌러 연결을 모두 종료합니다)")
            input("[Press Enter to terminate all connections]...\n")
            break

        finally:
            if procs:
                for proc in procs:
                    proc.terminate()
                print(colored_text("🔌 모든 포트 포워딩 연결을 종료했습니다.", Colors.SUCCESS))

# ----------------------------------------------------------------------------
# ElastiCache 접속 (v5.0.2 원본 + 캐싱)
# ----------------------------------------------------------------------------
def connect_to_cache(manager: AWSManager, region: str):
    while True:
        if region == 'multi-region':
            # 멀티 리전 모드
            regions = manager.list_regions()
            clus = manager.list_cache_clusters_multi_region(regions)
            region_display = "All Regions"
        else:
            # 단일 리전 모드
            clus = manager.list_cache_clusters(region)
            region_display = region
            
        if not clus:
            print(colored_text(f"\n⚠ {region_display}에 ElastiCache 클러스터가 없습니다", Colors.WARNING))
            time.sleep(1)
            break

        # 화살표 메뉴용 항목 생성
        cache_items = []
        for c in clus:
            if region == 'multi-region':
                item = f"{c['Id']:<40} {c['Engine']:<15} [{c['_region']}]"
            else:
                item = f"{c['Id']:<40} {c['Engine']:<15}"
            cache_items.append(item)
        cache_items.append("🔄 목록 새로고침")
        cache_items.append("🔙 돌아가기")

        title = f"ElastiCache Clusters  │  Region: {region_display}"
        sel = interactive_select(cache_items, title=title)

        if sel == -1 or sel == len(clus) + 1:  # 돌아가기
            break
        if sel == len(clus):  # 새로고침
            print(colored_text("🔄 목록을 새로고침합니다...", Colors.INFO))
            invalidate_cache_for_service(manager, region, "cache")
            continue

        idx = sel
        c = clus[idx]
        cache_region = c.get('_region', region)
        
        # 히스토리에 추가
        add_to_history('cache', manager.profile, cache_region, c['Id'], c['Id'])

        tgt = choose_jump_host(manager, cache_region)
        if not tgt:
            break

        local_port = 12000 + idx
        
        print(colored_text(f"\n(info) SSM 인스턴스 '{tgt}'를 통해 포트 포워딩을 시작합니다.", Colors.INFO))
        print(colored_text(f"🔹 포트 포워딩: [localhost:{local_port}] -> [{c['Id']}:{c['Port']}] ({cache_region})", Colors.INFO))

        proc = None
        try:
            params_dict = {
                "host": [c["Address"]],
                "portNumber": [str(c["Port"])],
                "localPortNumber": [str(local_port)]
            }
            params = json.dumps(params_dict)
            proc = subprocess.Popen(
                create_ssm_forward_command(manager.profile, cache_region, tgt, 'AWS-StartPortForwardingSessionToRemoteHost', params),
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(Config.WAIT_PORT_READY)
            
            print(colored_text("\n✅ 포트 포워딩이 활성화되었습니다. 클라이언트에서 아래 주소로 접속하세요.", Colors.SUCCESS))
            print(f"   Engine: {c['Engine']}")
            print(f"   Address: localhost:{local_port}")
            
            tool_launched = False
            try:
                tool = DEFAULT_CACHE_REDIS_CLI if c['Engine'].startswith('redis') else DEFAULT_CACHE_MEMCACHED_CLI
                args = [tool, '-h', '127.0.0.1', '-p', str(local_port)] if 'redis' in tool else [tool, '127.0.0.1', str(local_port)]
                # macOS에서 새 터미널 탭으로 실행
                launch_terminal_session(args)
                tool_launched = True
            except Exception as e:
                logging.warning(f"캐시 클라이언트 실행 실패: {e}")

            if tool_launched:
                print(colored_text("   (로컬 클라이언트가 새 터미널 탭에서 실행되었습니다)", Colors.SUCCESS))
                
            print("   (완료되면 이 창에서 Enter 키를 눌러 연결을 종료합니다)")
            input("\n[Press Enter to terminate the connection]...\n")
            break

        finally:
            if proc:
                proc.terminate()
            print(colored_text("🔌 포트 포워딩 연결을 종료했습니다.", Colors.SUCCESS))
            time.sleep(1)

# ----------------------------------------------------------------------------
# CloudWatch 메뉴 (v5.5.0 신규)
# ----------------------------------------------------------------------------
def cloudwatch_menu(manager: AWSManager, region: str):
    """CloudWatch 통합 메뉴 (대시보드, 알람, 로그)"""
    while True:
        if region == 'multi-region':
            print(colored_text("⚠ CloudWatch는 현재 멀티 리전 모드를 지원하지 않습니다.", Colors.WARNING))
            return

        sub_menu_items = [
            "📊 대시보드 목록",
            "🔔 알람 모니터링",
            "📋 로그 그룹 탐색",
            "🔙 돌아가기"
        ]

        title = f"CloudWatch  │  Region: {region}"
        sub_sel = interactive_select(sub_menu_items, title=title)

        if sub_sel == -1 or sub_sel == 3:
            return

        if sub_sel == 0:
            # 대시보드 목록
            cloudwatch_dashboards_menu(manager, region)

        elif sub_sel == 1:
            # 알람 모니터링
            cloudwatch_alarms_menu(manager, region)

        elif sub_sel == 2:
            # 로그 그룹 탐색
            cloudwatch_logs_menu(manager, region)


def cloudwatch_dashboards_menu(manager: AWSManager, region: str):
    """CloudWatch 대시보드 메뉴"""
    while True:
        dashboards = manager.list_cloudwatch_dashboards(region)
        if not dashboards:
            print(colored_text(f"\n⚠ 리전 {region}에 CloudWatch 대시보드가 없습니다.", Colors.WARNING))
            input(colored_text("계속하려면 Enter를 누르세요...", Colors.PROMPT))
            return

        # 화살표 메뉴용 항목 생성
        dashboard_items = []
        for db in dashboards:
            last_mod = db.get('LastModified')
            if last_mod:
                last_mod_str = last_mod.strftime('%Y-%m-%d %H:%M')
            else:
                last_mod_str = 'N/A'
            size_kb = db.get('Size', 0) / 1024
            item = f"{db['DashboardName']:<40} {size_kb:.1f}KB  수정: {last_mod_str}"
            dashboard_items.append(item)
        dashboard_items.append("🔙 돌아가기")

        title = f"CloudWatch Dashboards  │  Region: {region}"
        sel = interactive_select(dashboard_items, title=title)

        if sel == -1 or sel == len(dashboards):
            return

        selected_db = dashboards[sel]
        dashboard_name = selected_db['DashboardName']

        # 대시보드 액션 메뉴
        action_items = [
            "🌐 브라우저에서 열기",
            "📋 대시보드 정보",
            "🔙 돌아가기"
        ]

        action_sel = interactive_select(action_items, title=f"대시보드: {dashboard_name}")

        if action_sel == 0:
            # 브라우저에서 열기
            url = f"https://{region}.console.aws.amazon.com/cloudwatch/home?region={region}#dashboards:name={dashboard_name}"
            print(colored_text(f"\n🌐 대시보드를 브라우저에서 엽니다...", Colors.INFO))
            subprocess.run(['open', url])
            print(colored_text("✅ 브라우저가 열렸습니다.", Colors.SUCCESS))
            time.sleep(1)

        elif action_sel == 1:
            # 대시보드 정보 출력
            print(colored_text(f"\n{'─' * 60}", Colors.HEADER))
            print(colored_text(f"📊 대시보드 정보", Colors.INFO))
            print(colored_text(f"{'─' * 60}", Colors.HEADER))
            print(f"  이름: {selected_db['DashboardName']}")
            print(f"  ARN: {selected_db.get('DashboardArn', 'N/A')}")
            print(f"  크기: {selected_db.get('Size', 0)} bytes")
            if selected_db.get('LastModified'):
                print(f"  수정일: {selected_db['LastModified'].strftime('%Y-%m-%d %H:%M:%S')}")
            print(colored_text(f"{'─' * 60}", Colors.HEADER))
            input(colored_text("\n계속하려면 Enter를 누르세요...", Colors.PROMPT))


def cloudwatch_alarms_menu(manager: AWSManager, region: str):
    """CloudWatch 알람 모니터링 메뉴"""
    while True:
        filter_items = [
            "📋 모든 알람",
            "🔴 ALARM 상태만",
            "🟢 OK 상태만",
            "🟡 INSUFFICIENT_DATA 상태만",
            "🔙 돌아가기"
        ]

        title = f"CloudWatch Alarms Filter  │  Region: {region}"
        filter_sel = interactive_select(filter_items, title=title)

        if filter_sel == -1 or filter_sel == 4:
            return

        state_filter = None
        if filter_sel == 1:
            state_filter = 'ALARM'
        elif filter_sel == 2:
            state_filter = 'OK'
        elif filter_sel == 3:
            state_filter = 'INSUFFICIENT_DATA'

        alarms = manager.list_cloudwatch_alarms(region, state=state_filter)
        if not alarms:
            msg = f"⚠ 리전 {region}에 "
            msg += f"{state_filter} 상태의 " if state_filter else ""
            msg += "알람이 없습니다."
            print(colored_text(msg, Colors.WARNING))
            input(colored_text("계속하려면 Enter를 누르세요...", Colors.PROMPT))
            continue

        # 알람 목록 표시
        alarm_items = []
        for alarm in alarms:
            state = alarm['StateValue']
            state_icon = '🔴' if state == 'ALARM' else ('🟢' if state == 'OK' else '🟡')
            name = alarm['AlarmName'][:35]
            metric = alarm['MetricName'][:20] if alarm['MetricName'] else ''
            item = f"{state_icon} {name:<35} {metric:<20} {state}"
            alarm_items.append(item)
        alarm_items.append("🔙 돌아가기")

        state_str = state_filter if state_filter else "All"
        title = f"CloudWatch Alarms ({state_str})  │  {len(alarms)} alarms"
        alarm_sel = interactive_select(alarm_items, title=title)

        if alarm_sel == -1 or alarm_sel == len(alarms):
            continue

        selected_alarm = alarms[alarm_sel]
        alarm_name = selected_alarm['AlarmName']

        # 알람 상세 정보
        print(colored_text(f"\n{'─' * 70}", Colors.HEADER))
        print(colored_text(f"🔔 알람 상세 정보", Colors.INFO))
        print(colored_text(f"{'─' * 70}", Colors.HEADER))
        print(f"  이름: {selected_alarm['AlarmName']}")
        print(f"  상태: {selected_alarm['StateValue']}")
        print(f"  메트릭: {selected_alarm.get('Namespace', '')} / {selected_alarm.get('MetricName', '')}")
        print(f"  임계값: {selected_alarm.get('ComparisonOperator', '')} {selected_alarm.get('Threshold', '')}")
        print(f"  평가 기간: {selected_alarm.get('EvaluationPeriods', '')} periods")
        if selected_alarm.get('StateUpdatedTimestamp'):
            print(f"  상태 변경: {selected_alarm['StateUpdatedTimestamp'].strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"\n  상태 사유:")
        print(f"    {selected_alarm.get('StateReason', 'N/A')[:100]}")
        print(colored_text(f"{'─' * 70}", Colors.HEADER))

        # 알람 히스토리 조회
        print(colored_text("\n📜 최근 상태 변경 히스토리:", Colors.INFO))
        history = manager.get_alarm_history(region, alarm_name, limit=10)
        if history:
            for h in history[:5]:
                ts = h.get('Timestamp')
                ts_str = ts.strftime('%Y-%m-%d %H:%M:%S') if ts else 'N/A'
                summary = h.get('HistorySummary', '')[:60]
                print(f"  {ts_str}: {summary}")
        else:
            print("  히스토리가 없습니다.")

        input(colored_text("\n계속하려면 Enter를 누르세요...", Colors.PROMPT))


def cloudwatch_logs_menu(manager: AWSManager, region: str):
    """CloudWatch 로그 그룹 메뉴"""
    prefix_filter = None

    while True:
        # 필터 옵션
        filter_items = [
            "📋 전체 로그 그룹",
            "🔍 /aws/lambda/ 로그",
            "🔍 /aws/ecs/ 로그",
            "🔍 /aws/eks/ 로그",
            "✏️  직접 입력",
            "🔙 돌아가기"
        ]

        title = f"CloudWatch Logs Filter  │  Region: {region}"
        filter_sel = interactive_select(filter_items, title=title)

        if filter_sel == -1 or filter_sel == 5:
            return

        if filter_sel == 0:
            prefix_filter = None
        elif filter_sel == 1:
            prefix_filter = '/aws/lambda/'
        elif filter_sel == 2:
            prefix_filter = '/aws/ecs/'
        elif filter_sel == 3:
            prefix_filter = '/aws/eks/'
        elif filter_sel == 4:
            prefix_filter = input(colored_text("로그 그룹 prefix 입력: ", Colors.PROMPT)).strip()
            if not prefix_filter:
                prefix_filter = None

        log_groups = manager.list_log_groups(region, prefix=prefix_filter)
        if not log_groups:
            msg = f"⚠ 리전 {region}에 "
            msg += f"'{prefix_filter}' prefix의 " if prefix_filter else ""
            msg += "로그 그룹이 없습니다."
            print(colored_text(msg, Colors.WARNING))
            input(colored_text("계속하려면 Enter를 누르세요...", Colors.PROMPT))
            continue

        # 로그 그룹 목록 표시
        while True:
            lg_items = []
            for lg in log_groups:
                name = lg['logGroupName']
                size_mb = lg.get('storedBytes', 0) / (1024 * 1024)
                retention = lg.get('retentionInDays')
                retention_str = f"{retention}d" if retention else "∞"
                item = f"{name:<50} {size_mb:>8.2f}MB  보관: {retention_str}"
                lg_items.append(item)
            lg_items.append("🔙 돌아가기")

            title = f"Log Groups  │  {len(log_groups)} groups"
            lg_sel = interactive_select(lg_items, title=title)

            if lg_sel == -1 or lg_sel == len(log_groups):
                break

            selected_lg = log_groups[lg_sel]
            log_group_name = selected_lg['logGroupName']

            # 로그 스트림 목록
            cloudwatch_log_streams_menu(manager, region, log_group_name)


def cloudwatch_log_streams_menu(manager: AWSManager, region: str, log_group_name: str):
    """로그 스트림 메뉴"""
    while True:
        streams = manager.get_log_streams(region, log_group_name, limit=50)
        if not streams:
            print(colored_text(f"⚠ 로그 그룹에 스트림이 없습니다.", Colors.WARNING))
            input(colored_text("계속하려면 Enter를 누르세요...", Colors.PROMPT))
            return

        stream_items = []
        for stream in streams:
            name = stream['logStreamName']
            if len(name) > 45:
                name = name[:42] + '...'
            last_event = stream.get('lastEventTimestamp', 0)
            if last_event:
                last_event_str = datetime.fromtimestamp(last_event / 1000).strftime('%Y-%m-%d %H:%M')
            else:
                last_event_str = 'N/A'
            item = f"{name:<45} 최근: {last_event_str}"
            stream_items.append(item)
        stream_items.append("🔙 돌아가기")

        # 로그 그룹 이름 축약
        display_name = log_group_name
        if len(display_name) > 40:
            display_name = '...' + display_name[-37:]

        title = f"Log Streams  │  {display_name}"
        stream_sel = interactive_select(stream_items, title=title)

        if stream_sel == -1 or stream_sel == len(streams):
            return

        selected_stream = streams[stream_sel]
        stream_name = selected_stream['logStreamName']

        # 로그 이벤트 조회
        action_items = [
            "📋 최근 로그 (100개)",
            "🔍 로그 검색 (필터)",
            "🌐 브라우저에서 열기",
            "🔙 돌아가기"
        ]

        action_sel = interactive_select(action_items, title=f"스트림: {stream_name[:40]}")

        if action_sel == 0:
            # 최근 로그 조회
            events = manager.filter_log_events(
                region, log_group_name, log_stream=stream_name, limit=100
            )
            if events:
                print(colored_text(f"\n{'─' * 80}", Colors.HEADER))
                print(colored_text(f"📋 최근 로그 ({len(events)}개)", Colors.INFO))
                print(colored_text(f"{'─' * 80}", Colors.HEADER))
                for event in events[-30:]:  # 최근 30개만 출력
                    ts = event.get('timestamp', 0)
                    ts_str = datetime.fromtimestamp(ts / 1000).strftime('%H:%M:%S') if ts else ''
                    msg = event.get('message', '').strip()
                    if len(msg) > 100:
                        msg = msg[:100] + '...'
                    print(f"  [{ts_str}] {msg}")
                print(colored_text(f"{'─' * 80}", Colors.HEADER))
            else:
                print(colored_text("⚠ 로그 이벤트가 없습니다.", Colors.WARNING))
            input(colored_text("\n계속하려면 Enter를 누르세요...", Colors.PROMPT))

        elif action_sel == 1:
            # 필터 검색
            filter_pattern = input(colored_text("검색 패턴 입력 (예: ERROR, Exception): ", Colors.PROMPT)).strip()
            events = manager.filter_log_events(
                region, log_group_name, log_stream=stream_name,
                filter_pattern=filter_pattern, limit=100
            )
            if events:
                print(colored_text(f"\n{'─' * 80}", Colors.HEADER))
                print(colored_text(f"🔍 검색 결과: '{filter_pattern}' ({len(events)}개)", Colors.INFO))
                print(colored_text(f"{'─' * 80}", Colors.HEADER))
                for event in events[-20:]:
                    ts = event.get('timestamp', 0)
                    ts_str = datetime.fromtimestamp(ts / 1000).strftime('%H:%M:%S') if ts else ''
                    msg = event.get('message', '').strip()
                    if len(msg) > 100:
                        msg = msg[:100] + '...'
                    print(f"  [{ts_str}] {msg}")
                print(colored_text(f"{'─' * 80}", Colors.HEADER))
            else:
                print(colored_text(f"⚠ '{filter_pattern}'에 해당하는 로그가 없습니다.", Colors.WARNING))
            input(colored_text("\n계속하려면 Enter를 누르세요...", Colors.PROMPT))

        elif action_sel == 2:
            # 브라우저에서 열기
            import urllib.parse
            encoded_group = urllib.parse.quote(log_group_name, safe='')
            encoded_stream = urllib.parse.quote(stream_name, safe='')
            url = f"https://{region}.console.aws.amazon.com/cloudwatch/home?region={region}#logsV2:log-groups/log-group/{encoded_group}/log-events/{encoded_stream}"
            print(colored_text(f"\n🌐 로그 스트림을 브라우저에서 엽니다...", Colors.INFO))
            subprocess.run(['open', url])
            print(colored_text("✅ 브라우저가 열렸습니다.", Colors.SUCCESS))
            time.sleep(1)


# ----------------------------------------------------------------------------
# Lambda 메뉴 (v5.5.0 신규)
# ----------------------------------------------------------------------------
def lambda_menu(manager: AWSManager, region: str):
    """Lambda 함수 관리 메뉴"""
    while True:
        if region == 'multi-region':
            print(colored_text("⚠ Lambda는 현재 멀티 리전 모드를 지원하지 않습니다.", Colors.WARNING))
            return

        functions = manager.list_lambda_functions(region)
        if not functions:
            print(colored_text(f"\n⚠ 리전 {region}에 Lambda 함수가 없습니다.", Colors.WARNING))
            input(colored_text("계속하려면 Enter를 누르세요...", Colors.PROMPT))
            return

        # 화살표 메뉴용 항목 생성
        func_items = []
        for func in functions:
            name = func['FunctionName']
            if len(name) > 35:
                name = name[:32] + '...'
            runtime = func.get('Runtime', 'N/A')
            memory = func.get('MemorySize', 0)
            item = f"{name:<35} {runtime:<12} {memory}MB"
            func_items.append(item)
        func_items.append("🔙 돌아가기")

        title = f"Lambda Functions  │  Region: {region}  │  {len(functions)} functions"
        func_sel = interactive_select(func_items, title=title)

        if func_sel == -1 or func_sel == len(functions):
            return

        selected_func = functions[func_sel]
        function_name = selected_func['FunctionName']

        # 함수 상세 메뉴
        lambda_function_menu(manager, region, function_name)


def lambda_function_menu(manager: AWSManager, region: str, function_name: str):
    """Lambda 함수 상세 메뉴"""
    while True:
        action_items = [
            "📋 함수 상세 정보",
            "⚙️ 함수 설정 (환경변수)",
            "▶️ 테스트 실행",
            "📜 최근 로그 조회",
            "🏷️ 버전 및 별칭",
            "🌐 콘솔에서 열기",
            "🔙 돌아가기"
        ]

        title = f"Lambda: {function_name}"
        action_sel = interactive_select(action_items, title=title)

        if action_sel == -1 or action_sel == 6:
            return

        if action_sel == 0:
            # 함수 상세 정보
            detail = manager.get_lambda_function_detail(region, function_name)
            if detail:
                print(colored_text(f"\n{'─' * 70}", Colors.HEADER))
                print(colored_text(f"λ Lambda 함수 상세 정보", Colors.INFO))
                print(colored_text(f"{'─' * 70}", Colors.HEADER))
                print(f"  함수명: {detail['FunctionName']}")
                print(f"  ARN: {detail['FunctionArn']}")
                print(f"  런타임: {detail['Runtime']}")
                print(f"  핸들러: {detail['Handler']}")
                print(f"  메모리: {detail['MemorySize']}MB")
                print(f"  타임아웃: {detail['Timeout']}초")
                print(f"  코드 크기: {detail['CodeSize'] / 1024:.1f}KB")
                print(f"  상태: {detail.get('State', 'N/A')}")
                print(f"  버전: {detail.get('Version', 'N/A')}")
                print(f"  수정일: {detail.get('LastModified', 'N/A')}")
                print(f"  Role: {detail.get('Role', 'N/A')}")
                if detail.get('Description'):
                    print(f"  설명: {detail['Description']}")
                if detail.get('Layers'):
                    print(f"  Layers: {len(detail['Layers'])}개")
                print(colored_text(f"{'─' * 70}", Colors.HEADER))
            else:
                print(colored_text("❌ 함수 정보를 조회할 수 없습니다.", Colors.ERROR))
            input(colored_text("\n계속하려면 Enter를 누르세요...", Colors.PROMPT))

        elif action_sel == 1:
            # 환경변수 조회
            detail = manager.get_lambda_function_detail(region, function_name)
            if detail:
                env_vars = detail.get('Environment', {})
                print(colored_text(f"\n{'─' * 70}", Colors.HEADER))
                print(colored_text(f"⚙️ 환경 변수", Colors.INFO))
                print(colored_text(f"{'─' * 70}", Colors.HEADER))
                if env_vars:
                    for key, value in env_vars.items():
                        # 민감 정보 마스킹
                        if any(x in key.upper() for x in ['PASSWORD', 'SECRET', 'KEY', 'TOKEN']):
                            value = '****'
                        print(f"  {key}: {value}")
                else:
                    print("  환경 변수가 없습니다.")
                print(colored_text(f"{'─' * 70}", Colors.HEADER))
            input(colored_text("\n계속하려면 Enter를 누르세요...", Colors.PROMPT))

        elif action_sel == 2:
            # 테스트 실행
            lambda_test_invoke(manager, region, function_name)

        elif action_sel == 3:
            # 로그 조회
            lambda_logs_view(manager, region, function_name)

        elif action_sel == 4:
            # 버전 및 별칭
            lambda_versions_aliases(manager, region, function_name)

        elif action_sel == 5:
            # 콘솔에서 열기
            url = f"https://{region}.console.aws.amazon.com/lambda/home?region={region}#/functions/{function_name}"
            print(colored_text(f"\n🌐 Lambda 콘솔을 엽니다...", Colors.INFO))
            subprocess.run(['open', url])
            print(colored_text("✅ 브라우저가 열렸습니다.", Colors.SUCCESS))
            time.sleep(1)


def lambda_test_invoke(manager: AWSManager, region: str, function_name: str):
    """Lambda 테스트 실행"""
    print(colored_text(f"\n▶️ Lambda 함수 테스트 실행: {function_name}", Colors.INFO))
    print(colored_text("JSON 페이로드를 입력하세요 (빈 입력 = 빈 객체 {}):", Colors.PROMPT))
    print(colored_text("예: {\"key\": \"value\"}", Colors.PROMPT))

    payload_str = input("> ").strip()

    payload = None
    if payload_str:
        try:
            payload = json.loads(payload_str)
        except json.JSONDecodeError as e:
            print(colored_text(f"❌ JSON 파싱 오류: {e}", Colors.ERROR))
            input(colored_text("계속하려면 Enter를 누르세요...", Colors.PROMPT))
            return

    print(colored_text("\n⏳ 함수 실행 중...", Colors.INFO))
    result = manager.invoke_lambda_function(region, function_name, payload=payload)

    print(colored_text(f"\n{'─' * 70}", Colors.HEADER))
    print(colored_text(f"▶️ 실행 결과", Colors.INFO))
    print(colored_text(f"{'─' * 70}", Colors.HEADER))

    status_code = result.get('StatusCode', 0)
    if status_code == 200:
        print(colored_text(f"  상태: ✅ 성공 (HTTP {status_code})", Colors.SUCCESS))
    else:
        print(colored_text(f"  상태: ❌ 오류 (HTTP {status_code})", Colors.ERROR))

    if result.get('FunctionError'):
        print(colored_text(f"  에러: {result['FunctionError']}", Colors.ERROR))

    print(f"  실행 버전: {result.get('ExecutedVersion', 'N/A')}")

    print(colored_text(f"\n📤 응답 페이로드:", Colors.INFO))
    response_payload = result.get('Payload')
    if response_payload:
        try:
            formatted = json.dumps(response_payload, indent=2, ensure_ascii=False)
            # 긴 응답 잘라내기
            if len(formatted) > 1000:
                formatted = formatted[:1000] + '\n... (truncated)'
            print(formatted)
        except (TypeError, ValueError):
            print(str(response_payload)[:1000])
    else:
        print("  (응답 없음)")

    # 실행 로그
    log_result = result.get('LogResult', '')
    if log_result:
        print(colored_text(f"\n📜 실행 로그:", Colors.INFO))
        for line in log_result.split('\n')[:20]:
            print(f"  {line}")

    print(colored_text(f"{'─' * 70}", Colors.HEADER))
    input(colored_text("\n계속하려면 Enter를 누르세요...", Colors.PROMPT))


def lambda_logs_view(manager: AWSManager, region: str, function_name: str):
    """Lambda 로그 조회"""
    hours_items = [
        "최근 1시간",
        "최근 6시간",
        "최근 24시간",
        "🔙 돌아가기"
    ]

    hours_sel = interactive_select(hours_items, title="로그 조회 범위")

    if hours_sel == -1 or hours_sel == 3:
        return

    hours = [1, 6, 24][hours_sel]

    print(colored_text(f"\n⏳ 최근 {hours}시간 로그를 조회합니다...", Colors.INFO))
    logs = manager.get_lambda_function_logs(region, function_name, hours=hours, limit=100)

    if not logs:
        print(colored_text(f"⚠ 최근 {hours}시간 내 로그가 없습니다.", Colors.WARNING))
        input(colored_text("계속하려면 Enter를 누르세요...", Colors.PROMPT))
        return

    print(colored_text(f"\n{'─' * 80}", Colors.HEADER))
    print(colored_text(f"📜 Lambda 로그 ({len(logs)}개)", Colors.INFO))
    print(colored_text(f"{'─' * 80}", Colors.HEADER))

    for event in logs[-50:]:  # 최근 50개만 출력
        ts = event.get('timestamp', 0)
        ts_str = datetime.fromtimestamp(ts / 1000).strftime('%H:%M:%S.%f')[:-3] if ts else ''
        msg = event.get('message', '').strip()
        if len(msg) > 100:
            msg = msg[:100] + '...'

        # 로그 레벨에 따른 색상
        if 'ERROR' in msg or 'Error' in msg:
            print(colored_text(f"  [{ts_str}] {msg}", Colors.ERROR))
        elif 'WARN' in msg or 'Warning' in msg:
            print(colored_text(f"  [{ts_str}] {msg}", Colors.WARNING))
        else:
            print(f"  [{ts_str}] {msg}")

    print(colored_text(f"{'─' * 80}", Colors.HEADER))
    input(colored_text("\n계속하려면 Enter를 누르세요...", Colors.PROMPT))


def lambda_versions_aliases(manager: AWSManager, region: str, function_name: str):
    """Lambda 버전 및 별칭 조회"""
    versions = manager.list_lambda_versions(region, function_name)
    aliases = manager.list_lambda_aliases(region, function_name)

    print(colored_text(f"\n{'─' * 70}", Colors.HEADER))
    print(colored_text(f"🏷️ 버전 및 별칭: {function_name}", Colors.INFO))
    print(colored_text(f"{'─' * 70}", Colors.HEADER))

    print(colored_text("\n📌 버전:", Colors.INFO))
    if versions:
        for ver in versions[:10]:  # 최근 10개
            version = ver.get('Version', '')
            desc = ver.get('Description', '')[:30]
            modified = ver.get('LastModified', '')[:19]
            print(f"  {version:<10} {desc:<30} {modified}")
    else:
        print("  버전이 없습니다.")

    print(colored_text("\n🔗 별칭:", Colors.INFO))
    if aliases:
        for alias in aliases:
            name = alias.get('Name', '')
            ver = alias.get('FunctionVersion', '')
            desc = alias.get('Description', '')[:30]
            print(f"  {name:<20} → v{ver:<10} {desc}")
    else:
        print("  별칭이 없습니다.")

    print(colored_text(f"{'─' * 70}", Colors.HEADER))
    input(colored_text("\n계속하려면 Enter를 누르세요...", Colors.PROMPT))


# ----------------------------------------------------------------------------
# S3 브라우저 메뉴 (v5.5.0 신규)
# ----------------------------------------------------------------------------
def s3_browser_menu(manager: AWSManager, region: str):
    """S3 버킷 브라우저 메뉴"""
    while True:
        buckets = manager.list_s3_buckets()
        if not buckets:
            print(colored_text("\n⚠ S3 버킷이 없습니다.", Colors.WARNING))
            input(colored_text("계속하려면 Enter를 누르세요...", Colors.PROMPT))
            return

        # 버킷 목록
        bucket_items = []
        for bucket in buckets:
            name = bucket['Name']
            created = bucket.get('CreationDate')
            created_str = created.strftime('%Y-%m-%d') if created else 'N/A'
            item = f"{name:<50} 생성: {created_str}"
            bucket_items.append(item)
        bucket_items.append("🔙 돌아가기")

        title = f"S3 Buckets  │  {len(buckets)} buckets"
        bucket_sel = interactive_select(bucket_items, title=title)

        if bucket_sel == -1 or bucket_sel == len(buckets):
            return

        selected_bucket = buckets[bucket_sel]
        bucket_name = selected_bucket['Name']

        # 버킷 리전 확인
        bucket_region = manager.get_bucket_location(bucket_name)
        print(colored_text(f"📍 버킷 리전: {bucket_region}", Colors.INFO))

        # 버킷 브라우저
        s3_bucket_browser(manager, bucket_name, bucket_region)


def s3_bucket_browser(manager: AWSManager, bucket_name: str, bucket_region: str, prefix: str = ""):
    """S3 버킷 내 객체 브라우저"""
    while True:
        result = manager.list_s3_objects(bucket_name, prefix=prefix, max_keys=100)
        folders = result.get('folders', [])
        files = result.get('files', [])

        # 목록 생성
        items = []
        display_items = []

        # 상위 폴더 이동 (루트가 아닌 경우)
        if prefix:
            items.append({'type': 'parent', 'Key': '..'})
            display_items.append("📁 ..")

        # 폴더
        for folder in folders:
            items.append(folder)
            folder_name = folder['Key'].rstrip('/').split('/')[-1]
            display_items.append(f"📁 {folder_name}/")

        # 파일
        for f in files:
            items.append(f)
            file_name = f['Key'].split('/')[-1]
            size = f.get('Size', 0)
            size_str = format_size(size)
            display_items.append(f"📄 {file_name:<40} {size_str:>10}")

        display_items.append("🔙 돌아가기")

        # 현재 경로 표시
        current_path = prefix if prefix else "/"
        if len(current_path) > 40:
            current_path = '...' + current_path[-37:]

        title = f"📦 {bucket_name}  │  {current_path}"
        sel = interactive_select(display_items, title=title)

        if sel == -1 or sel == len(items):
            return

        selected_item = items[sel]

        # 상위 폴더
        if selected_item.get('type') == 'parent':
            # 상위 폴더로 이동
            parts = prefix.rstrip('/').split('/')
            if len(parts) > 1:
                prefix = '/'.join(parts[:-1]) + '/'
            else:
                prefix = ""
            continue

        # 폴더 진입
        if selected_item.get('Type') == 'folder':
            prefix = selected_item['Key']
            continue

        # 파일 선택
        file_key = selected_item['Key']
        s3_file_actions(manager, bucket_name, bucket_region, file_key)


def s3_file_actions(manager: AWSManager, bucket_name: str, bucket_region: str, file_key: str):
    """S3 파일 액션 메뉴"""
    file_name = file_key.split('/')[-1]

    while True:
        action_items = [
            "📋 파일 정보",
            "⬇️ 다운로드",
            "🔗 Presigned URL 생성",
            "🗑️ 삭제",
            "🔙 돌아가기"
        ]

        title = f"파일: {file_name}"
        action_sel = interactive_select(action_items, title=title)

        if action_sel == -1 or action_sel == 4:
            return

        if action_sel == 0:
            # 파일 정보
            info = manager.get_s3_object_info(bucket_name, file_key)
            if info:
                print(colored_text(f"\n{'─' * 70}", Colors.HEADER))
                print(colored_text(f"📄 파일 정보", Colors.INFO))
                print(colored_text(f"{'─' * 70}", Colors.HEADER))
                print(f"  키: {info['Key']}")
                print(f"  크기: {format_size(info['ContentLength'])}")
                print(f"  타입: {info.get('ContentType', 'N/A')}")
                print(f"  ETag: {info.get('ETag', 'N/A')}")
                print(f"  스토리지: {info.get('StorageClass', 'STANDARD')}")
                if info.get('LastModified'):
                    print(f"  수정일: {info['LastModified'].strftime('%Y-%m-%d %H:%M:%S')}")
                if info.get('Metadata'):
                    print(f"  메타데이터: {info['Metadata']}")
                print(colored_text(f"{'─' * 70}", Colors.HEADER))
            else:
                print(colored_text("❌ 파일 정보를 조회할 수 없습니다.", Colors.ERROR))
            input(colored_text("\n계속하려면 Enter를 누르세요...", Colors.PROMPT))

        elif action_sel == 1:
            # 다운로드
            default_path = str(Path.home() / 'Downloads' / file_name)
            print(colored_text(f"\n다운로드 경로 (Enter = {default_path}):", Colors.PROMPT))
            local_path = input("> ").strip()
            if not local_path:
                local_path = default_path

            # 경로 확장
            local_path = str(Path(local_path).expanduser())

            print(colored_text(f"\n⬇️ 다운로드 중: {file_key}", Colors.INFO))

            def progress_callback(downloaded, total, percentage):
                bar_length = 30
                filled = int(bar_length * percentage / 100)
                bar = '█' * filled + '░' * (bar_length - filled)
                sys.stdout.write(f"\r  [{bar}] {percentage:.1f}% ({format_size(downloaded)}/{format_size(total)})")
                sys.stdout.flush()

            success = manager.download_s3_object(bucket_name, file_key, local_path, progress_callback)

            print()  # 줄바꿈
            if success:
                print(colored_text(f"✅ 다운로드 완료: {local_path}", Colors.SUCCESS))
            else:
                print(colored_text("❌ 다운로드 실패", Colors.ERROR))
            input(colored_text("\n계속하려면 Enter를 누르세요...", Colors.PROMPT))

        elif action_sel == 2:
            # Presigned URL 생성
            expiry_items = [
                "1시간",
                "6시간",
                "24시간",
                "7일",
                "🔙 돌아가기"
            ]

            expiry_sel = interactive_select(expiry_items, title="URL 유효 기간")

            if expiry_sel == -1 or expiry_sel == 4:
                continue

            expiration = [3600, 21600, 86400, 604800][expiry_sel]
            url = manager.generate_presigned_url(bucket_name, file_key, expiration=expiration)

            if url:
                print(colored_text(f"\n🔗 Presigned URL (유효: {expiry_items[expiry_sel]}):", Colors.INFO))
                print(url)

                # 클립보드에 복사 (macOS)
                try:
                    subprocess.run(['pbcopy'], input=url.encode(), check=True)
                    print(colored_text("\n📋 URL이 클립보드에 복사되었습니다.", Colors.SUCCESS))
                except Exception:
                    pass
            else:
                print(colored_text("❌ URL 생성 실패", Colors.ERROR))
            input(colored_text("\n계속하려면 Enter를 누르세요...", Colors.PROMPT))

        elif action_sel == 3:
            # 삭제
            print(colored_text(f"\n⚠️ 정말로 '{file_name}'을(를) 삭제하시겠습니까?", Colors.WARNING))
            confirm = input(colored_text("삭제하려면 'DELETE' 입력: ", Colors.PROMPT)).strip()

            if confirm == 'DELETE':
                success = manager.delete_s3_object(bucket_name, file_key)
                if success:
                    print(colored_text("✅ 파일이 삭제되었습니다.", Colors.SUCCESS))
                    input(colored_text("\n계속하려면 Enter를 누르세요...", Colors.PROMPT))
                    return  # 파일 목록으로 돌아가기
                else:
                    print(colored_text("❌ 삭제 실패", Colors.ERROR))
            else:
                print(colored_text("삭제가 취소되었습니다.", Colors.INFO))
            input(colored_text("\n계속하려면 Enter를 누르세요...", Colors.PROMPT))


def format_size(size_bytes: int) -> str:
    """바이트 크기를 읽기 쉬운 형식으로 변환"""
    if size_bytes < 1024:
        return f"{size_bytes}B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f}KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f}MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f}GB"


# ----------------------------------------------------------------------------
# 도움말 시스템 (v5.5.0 신규)
# ----------------------------------------------------------------------------
MENU_HELP = {
    'main': """
╔══════════════════════════════════════════════════════════════════════════════╗
║                         EC2 Menu v5.5.0 도움말                                ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ 메인 메뉴 명령어                                                               ║
║   1-6    각 서비스 메뉴 진입                                                    ║
║   h      최근 연결 기록 조회                                                    ║
║   c      저장된 DB 자격증명 삭제                                                 ║
║   b      리전 재선택                                                           ║
║   Enter  프로그램 종료                                                         ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ 명령줄 옵션                                                                    ║
║   -p, --profile    AWS 프로파일 지정                                           ║
║   -r, --region     AWS 리전 지정                                               ║
║   -s, --service    서비스 직접 진입 (ec2/rds/cache/ecs/eks/cloudwatch/lambda/s3)║
║   --no-cache       캐시 비활성화                                               ║
║   -d, --debug      디버그 모드                                                 ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ v5.5.0 주요 변경사항                                                          ║
║   - CloudWatch 통합 (대시보드, 알람, 로그 조회)                                   ║
║   - Lambda 관리 (함수 목록, 테스트 실행, 로그 조회)                               ║
║   - S3 브라우저 (버킷/객체 탐색, 업로드/다운로드, Presigned URL)                   ║
║   - v5.4.0 기능 포함 (Keychain, 캐시 TTL, 페이지네이션)                          ║
╚══════════════════════════════════════════════════════════════════════════════╝
""",
    'ec2': """
╔══════════════════════════════════════════════════════════════════════════════╗
║                         EC2 메뉴 도움말                                        ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ 기본 명령어                                                                    ║
║   [번호]     인스턴스 선택 (SSM 터미널/RDP 접속)                                ║
║   batch      배치 명령 실행 모드 진입                                           ║
║   upload     파일 업로드 (S3 경유)                                              ║
║   download   파일 다운로드 (S3 경유)                                            ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ 정렬 명령어                                                                    ║
║   n          이름순 정렬                                                       ║
║   t          인스턴스 타입순 정렬                                               ║
║   s          상태순 정렬                                                       ║
║   r (목록)   리전순 정렬 (멀티 리전 모드)                                        ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ 네비게이션                                                                     ║
║   r (새로고침) 목록 새로고침                                                    ║
║   b          뒤로가기                                                          ║
║   h/?        이 도움말 표시                                                    ║
╚══════════════════════════════════════════════════════════════════════════════╝
""",
    'ecs': """
╔══════════════════════════════════════════════════════════════════════════════╗
║                         ECS 메뉴 도움말                                        ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ 네비게이션                                                                     ║
║   [번호]     클러스터/서비스/태스크/컨테이너 선택                                 ║
║   logs       CloudWatch 로그 조회                                              ║
║   b          뒤로가기                                                          ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ ECS Exec 접속                                                                  ║
║   컨테이너 선택 후 자동으로 ECS Exec 세션 시작                                   ║
║   /bin/sh 또는 /bin/bash 셸 사용                                               ║
╚══════════════════════════════════════════════════════════════════════════════╝
""",
    'eks': """
╔══════════════════════════════════════════════════════════════════════════════╗
║                         EKS 메뉴 도움말                                        ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ 클러스터 관리                                                                  ║
║   [번호]     클러스터 선택                                                     ║
║   b          뒤로가기                                                          ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ 클러스터 상세                                                                  ║
║   1          노드 그룹 목록                                                    ║
║   2          Fargate 프로필 목록                                               ║
║   3          Pod 목록 (kubectl)                                                ║
║   4          kubeconfig 설정                                                   ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ Pod 작업 (kubectl 필요)                                                        ║
║   exec       Pod에 셸 접속                                                     ║
║   logs       Pod 로그 조회                                                     ║
╚══════════════════════════════════════════════════════════════════════════════╝
""",
    'cloudwatch': """
╔══════════════════════════════════════════════════════════════════════════════╗
║                       CloudWatch 메뉴 도움말                                   ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ 대시보드                                                                       ║
║   [번호]     대시보드 선택 → 브라우저에서 열기                                    ║
║   b          뒤로가기                                                          ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ 알람                                                                           ║
║   [번호]     알람 선택 → 히스토리 조회                                           ║
║   1/2/3/4    상태 필터 (전체/ALARM/OK/INSUFFICIENT_DATA)                        ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ 로그                                                                           ║
║   [번호]     로그 그룹 선택 → 스트림 목록                                        ║
║   스트림에서 [번호] 선택 → 최근 로그 이벤트 조회                                   ║
╚══════════════════════════════════════════════════════════════════════════════╝
""",
    'lambda': """
╔══════════════════════════════════════════════════════════════════════════════╗
║                         Lambda 메뉴 도움말                                     ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ 함수 목록                                                                      ║
║   [번호]     함수 선택 → 상세 메뉴 진입                                          ║
║   b          뒤로가기                                                          ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ 함수 상세 메뉴                                                                  ║
║   1          함수 상세 정보 조회 (런타임, 메모리, 타임아웃)                         ║
║   2          테스트 실행 (JSON 페이로드 입력)                                    ║
║   3          최근 로그 조회 (CloudWatch Logs 연동)                               ║
║   4          버전 및 별칭 관리                                                   ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ 테스트 실행                                                                     ║
║   빈 입력: 빈 페이로드 ({})로 실행                                               ║
║   JSON 입력: {"key": "value"} 형식으로 페이로드 전달                             ║
╚══════════════════════════════════════════════════════════════════════════════╝
""",
    's3': """
╔══════════════════════════════════════════════════════════════════════════════╗
║                          S3 브라우저 도움말                                     ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ 버킷 목록                                                                      ║
║   [번호]     버킷 선택 → 객체 브라우저 진입                                       ║
║   b          뒤로가기                                                          ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ 객체 브라우저 (폴더 탐색)                                                        ║
║   [번호]     폴더 진입 또는 파일 선택                                            ║
║   ..         상위 폴더로 이동                                                   ║
║   b          뒤로가기 (버킷 목록으로)                                            ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ 파일 작업                                                                       ║
║   d          다운로드 (로컬 경로 입력)                                           ║
║   u          업로드 (로컬 파일 경로 입력)                                         ║
║   l          Presigned URL 생성 (1시간 유효)                                    ║
║   x          파일 삭제                                                          ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""
}

def show_main_help():
    """메인 메뉴 도움말 표시"""
    print(colored_text(MENU_HELP['main'], Colors.INFO))

def show_menu_help(menu_type: str):
    """특정 메뉴 도움말 표시"""
    help_text = MENU_HELP.get(menu_type, MENU_HELP['main'])
    print(colored_text(help_text, Colors.INFO))

# ----------------------------------------------------------------------------
# Main 흐름 (v5.1.0 확장)
# ----------------------------------------------------------------------------
def main():
    global _stored_credentials

    # 시작 시 화면 클리어
    os.system('clear')

    # macOS 플랫폼 체크
    if not IS_MAC:
        print(colored_text("❌ 이 스크립트는 macOS 전용입니다.", Colors.ERROR))
        print(colored_text("   Windows/Linux용 버전을 사용해주세요.", Colors.INFO))
        sys.exit(1)

    parser = argparse.ArgumentParser(
        description='AWS EC2/RDS/ElastiCache/ECS/EKS 연결 도구 v5.5.0 (macOS)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
사용 예시:
  %(prog)s                           # 대화형 모드
  %(prog)s -p myprofile              # 특정 프로파일 사용
  %(prog)s -r ap-northeast-2         # 특정 리전 선택
  %(prog)s -s ec2                    # EC2 메뉴 직접 진입
  %(prog)s --no-cache                # 캐시 비활성화

지원 서비스: EC2, RDS, ElastiCache, ECS, EKS
'''
    )
    parser.add_argument('-p', '--profile', help='AWS 프로파일 이름')
    parser.add_argument('-d', '--debug', action='store_true', help='디버그 모드')
    parser.add_argument('-r', '--region', help='AWS 리전 이름')
    parser.add_argument('-s', '--service',
                        choices=['ec2', 'rds', 'cache', 'ecs', 'eks', 'cloudwatch', 'lambda', 's3'],
                        help='직접 진입할 서비스 (v5.5.0: cloudwatch, lambda, s3 추가)')
    parser.add_argument('--no-cache', action='store_true', help='캐시 비활성화 (v5.5.0)')
    parser.add_argument('-v', '--version', action='version', version='%(prog)s v5.5.0')
    args = parser.parse_args()

    # 캐시 비활성화 옵션 처리 (v5.5.0)
    if args.no_cache:
        Config.CACHE_TTL_SECONDS = 0
        for key in Config.CACHE_TTLS:
            Config.CACHE_TTLS[key] = 0
        print(colored_text("ℹ️ 캐시가 비활성화되었습니다.", Colors.INFO))

    setup_logger(args.debug)

    try:
        profile = args.profile or choose_profile()
        manager = AWSManager(profile)

        while True:
            region = args.region or choose_region(manager)
            args.region = None
            if not region:
                sel = input(colored_text("프로파일을 다시 선택하시겠습니까? (y/N): ", Colors.PROMPT)).strip().lower()
                if sel == 'y':
                    profile = choose_profile()
                    manager = AWSManager(profile)
                    continue
                else:
                    sys.exit(0)

            # v5.5.0: 서비스 직접 진입 옵션 처리
            if args.service:
                service = args.service
                args.service = None  # 한 번만 처리
                if service == 'ec2':
                    ec2_menu(manager, region)
                elif service == 'rds':
                    connect_to_rds(manager, DEFAULT_DB_TOOL_PATH, region)
                elif service == 'cache':
                    connect_to_cache(manager, region)
                elif service == 'ecs':
                    ecs_menu(manager, region)
                elif service == 'eks':
                    eks_menu(manager, region)
                elif service == 'cloudwatch':
                    cloudwatch_menu(manager, region)
                elif service == 'lambda':
                    lambda_menu(manager, region)
                elif service == 's3':
                    s3_browser_menu(manager, region)
                continue

            while True:
                region_display = "All Regions" if region == 'multi-region' else region

                # 메인 메뉴 항목 구성 (v5.5.0: CloudWatch, Lambda, S3 추가)
                menu_items = [
                    "🖥️ EC2 인스턴스 연결 (배치 작업 지원)",
                    "🗄️ RDS 데이터베이스 연결",
                    "⚡ ElastiCache 클러스터 연결",
                    "🐳 ECS 컨테이너 연결",
                    "☸️ EKS 클러스터 관리",
                    "🌐 CloudShell 브라우저에서 열기",
                    "📊 CloudWatch 모니터링",       # v5.5.0 신규
                    "λ  Lambda 함수 관리",          # v5.5.0 신규
                    "📦 S3 버킷 브라우저",           # v5.5.0 신규
                    "📚 최근 연결 기록",
                    "❓ 도움말",
                ]
                if _stored_credentials:
                    menu_items.append("🗑️ 저장된 DB 자격증명 삭제")
                menu_items.append("🔄 리전 재선택")
                menu_items.append("🚪 종료")

                title = f"Main Menu  │  Profile: {profile}  │  Region: {region_display}"
                footer = "↑↓/jk: 이동  Enter: 선택  q: 종료  /: 검색"

                selected = interactive_select(menu_items, title=title, footer=footer)

                # 저장된 자격증명 유무에 따라 인덱스 매핑 조정
                has_creds = bool(_stored_credentials)

                if selected == -1 or selected == len(menu_items) - 1:  # 취소 또는 종료
                    sys.exit(0)
                elif selected == 0:  # EC2
                    ec2_menu(manager, region)
                elif selected == 1:  # RDS
                    connect_to_rds(manager, DEFAULT_DB_TOOL_PATH, region)
                elif selected == 2:  # ElastiCache
                    connect_to_cache(manager, region)
                elif selected == 3:  # ECS
                    ecs_menu(manager, region)
                elif selected == 4:  # EKS
                    eks_menu(manager, region)
                elif selected == 5:  # CloudShell
                    cloudshell_region = region if region != 'multi-region' else 'ap-northeast-2'
                    open_cloudshell_browser(cloudshell_region)
                elif selected == 6:  # CloudWatch (v5.5.0 신규)
                    cloudwatch_menu(manager, region)
                elif selected == 7:  # Lambda (v5.5.0 신규)
                    lambda_menu(manager, region)
                elif selected == 8:  # S3 (v5.5.0 신규)
                    s3_browser_menu(manager, region)
                elif selected == 9:  # 최근 연결 기록
                    recent = show_recent_connections()
                    if recent:
                        temp_manager = AWSManager(recent['profile'])
                        reconnect_to_instance(temp_manager, recent)
                elif selected == 10:  # 도움말
                    show_main_help()
                elif has_creds and selected == 11:  # 자격증명 삭제 (자격증명 있을 때)
                    clear_stored_credentials()
                elif (has_creds and selected == 12) or (not has_creds and selected == 11):  # 리전 재선택
                    break
    
    finally:
        # 프로그램 종료 시 저장된 자격 증명 삭제
        _stored_credentials.clear()

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print(colored_text("\n\n사용자 요청으로 프로그램을 종료합니다.", Colors.INFO))
        # 프로그램 종료 시 저장된 자격 증명 삭제
        _stored_credentials.clear()
        sys.exit(0)
    except Exception as e:
        logging.error(f"예상치 못한 오류 발생: {e}", exc_info=True)
        # 프로그램 종료 시 저장된 자격 증명 삭제
        _stored_credentials.clear()
        sys.exit(1)