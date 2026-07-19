"""환경 진단 (doctor) — 실행에 필요한 필수 전제조건 점검.

brew/flutter doctor 패턴. 각 점검은 (status, name, detail, hint) 튜플을 돌려주고,
run_doctor 가 이를 모아 출력한 뒤 FAIL 개수를 반환한다(= 프로세스 exit code).
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from typing import List, Optional, Tuple

from ec2menu.core.colors import Colors, colored_text

# 점검 상태
OK = "OK"
WARN = "WARN"
FAIL = "FAIL"

_STATUS_ICON = {OK: "✅", WARN: "⚠️", FAIL: "❌"}
_STATUS_COLOR = {OK: Colors.SUCCESS, WARN: Colors.WARNING, FAIL: Colors.ERROR}

# (status, name, detail, hint)
CheckResult = Tuple[str, str, str, str]


def _run(cmd: List[str], timeout: int = 5) -> Optional[str]:
    """명령을 실행하고 표준출력(없으면 표준에러)을 반환. 미설치/실패/타임아웃 시 None."""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode == 0:
        return (proc.stdout or proc.stderr).strip()
    return None


def check_python_version() -> CheckResult:
    """Python 3.9 이상인지 확인 (from __future__ annotations 등 코드 요구사항)."""
    major, minor, micro = sys.version_info[:3]
    ver = f"{major}.{minor}.{micro}"
    if (major, minor) >= (3, 9):
        return (OK, "Python", ver, "")
    return (FAIL, "Python", ver, "Python 3.9 이상이 필요합니다.")


def check_aws_cli() -> CheckResult:
    """aws CLI 설치 여부 및 버전 확인."""
    if not shutil.which("aws"):
        return (FAIL, "aws CLI", "미설치", "brew install awscli 로 설치하세요.")
    out = _run(["aws", "--version"]) or ""
    # 예: "aws-cli/2.15.30 Python/3.11.8 Darwin/..." → 첫 토큰에서 버전 추출
    ver = out.split()[0].replace("aws-cli/", "") if out else "알 수 없음"
    return (OK, "aws CLI", ver, "")


def check_session_manager_plugin() -> CheckResult:
    """SSM 세션/포트포워딩에 필수인 session-manager-plugin 확인."""
    if not shutil.which("session-manager-plugin"):
        return (
            FAIL, "session-manager-plugin", "미설치",
            "SSM 세션/포트포워딩에 필수. brew install --cask session-manager-plugin",
        )
    out = _run(["session-manager-plugin", "--version"]) or "설치됨"
    return (OK, "session-manager-plugin", out, "")


def check_boto3() -> CheckResult:
    """AWS SDK(boto3) 설치 여부 및 버전 확인."""
    try:
        import boto3
    except ImportError:
        return (FAIL, "boto3", "미설치", "pip install boto3 로 설치하세요.")
    return (OK, "boto3", boto3.__version__, "")


def check_aws_credentials(profile: Optional[str]) -> CheckResult:
    """선택된 프로파일(없으면 기본 자격증명)로 AWS 인증이 유효한지 점검한다.

    sts get-caller-identity 호출의 성공/실패로 판단한다. 실패는 원인에 따라
    자격증명 없음 / 토큰 만료 / 프로파일 없음 / 네트워크 문제로 나뉘며,
    각각에 맞는 해결 힌트를 돌려주는 것이 이 함수의 목표다.
    """
    name = "AWS 자격증명"
    import boto3
    from botocore.exceptions import (
        ClientError,
        EndpointConnectionError,
        NoCredentialsError,
        ProfileNotFound,
    )

    # TODO(human): 위에 import 된 boto3 / botocore 예외를 사용해 아래를 구현.
    #   1) boto3.Session(profile_name=profile) 로 세션 생성 (profile 이 None 이면 기본)
    #   2) session.client("sts").get_caller_identity() 호출
    #   3) 성공 시:  (OK, name, f"{resp['Account']}  {resp['Arn']}", "")
    #   4) 실패 유형별로 (FAIL, name, <짧은 요약>, <해결 힌트>) 반환
    #      - ProfileNotFound        → "~/.aws/config 에 프로파일 없음"
    #      - NoCredentialsError     → "자격증명 미설정 (aws configure)"
    #      - ClientError            → 만료 토큰(ExpiredToken/InvalidClientTokenId)이면 갱신 안내
    #      - EndpointConnectionError→ "네트워크/프록시 확인"
    #   힌트에는 실제 비밀값(키/토큰)을 절대 넣지 말 것.
    return (WARN, name, "미점검", "check_aws_credentials 미구현")


# CLI 인자에 의존하지 않는 순수 점검들 (자격증명은 profile 이 필요해 별도 처리)
_STATELESS_CHECKS = (
    check_python_version,
    check_aws_cli,
    check_session_manager_plugin,
    check_boto3,
)


def run_doctor(profile: Optional[str] = None) -> int:
    """모든 필수 점검을 실행/출력하고 FAIL 개수를 반환한다."""
    print(colored_text("\n🩺 환경 진단 (Doctor)\n", Colors.HEADER))

    results: List[CheckResult] = []
    for check in _STATELESS_CHECKS:
        try:
            results.append(check())
        except Exception as e:  # 개별 점검 오류가 전체 진단을 멈추지 않도록 흡수
            results.append((FAIL, check.__name__, "점검 오류", str(e)))
    try:
        results.append(check_aws_credentials(profile))
    except Exception as e:
        results.append((FAIL, "AWS 자격증명", "점검 오류", str(e)))

    fail_count = 0
    for status, name, detail, hint in results:
        icon = _STATUS_ICON.get(status, "•")
        print(colored_text(f"  {icon} {name:<24} {detail}", _STATUS_COLOR.get(status, "")))
        if hint and status != OK:
            print(colored_text(f"       └─ {hint}", Colors.INFO))
        if status == FAIL:
            fail_count += 1

    print()
    if fail_count == 0:
        print(colored_text("✅ 모든 필수 점검을 통과했습니다.", Colors.SUCCESS))
    else:
        print(colored_text(f"❌ 필수 점검 {fail_count}건 실패 — 위 힌트를 확인하세요.", Colors.ERROR))
    return fail_count
