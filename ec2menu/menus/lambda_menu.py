"""Lambda 함수 관리 메뉴"""
from __future__ import annotations

import json
import subprocess
import time
from datetime import datetime

from ec2menu.core.colors import Colors, colored_text
from ec2menu.ui.menu import interactive_select

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ec2menu.aws.manager import AWSManager


def lambda_menu(manager: AWSManager, region: str) -> None:
    while True:
        if region == 'multi-region':
            print(colored_text("⚠ Lambda는 현재 멀티 리전 모드를 지원하지 않습니다.", Colors.WARNING))
            return

        functions = manager.list_lambda_functions(region)
        if not functions:
            print(colored_text(f"\n⚠ 리전 {region}에 Lambda 함수가 없습니다.", Colors.WARNING))
            input(colored_text("계속하려면 Enter를 누르세요...", Colors.PROMPT))
            return

        func_items = []
        for func in functions:
            name = func['FunctionName']
            if len(name) > 35:
                name = name[:32] + '...'
            runtime = func.get('Runtime', 'N/A')
            memory = func.get('MemorySize', 0)
            func_items.append(f"{name:<35} {runtime:<12} {memory}MB")
        func_items.append("🔙 돌아가기")

        title = f"Lambda Functions  │  Region: {region}  │  {len(functions)} functions"
        func_sel = interactive_select(func_items, title=title)

        if func_sel == -1 or func_sel == len(functions):
            return

        selected_func = functions[func_sel]
        lambda_function_menu(manager, region, selected_func['FunctionName'])


def lambda_function_menu(manager: AWSManager, region: str, function_name: str) -> None:
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
            detail = manager.get_lambda_function_detail(region, function_name)
            if detail:
                print(colored_text(f"\n{'─' * 70}", Colors.HEADER))
                print(colored_text("λ Lambda 함수 상세 정보", Colors.INFO))
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
            detail = manager.get_lambda_function_detail(region, function_name)
            if detail:
                env_vars = detail.get('Environment', {})
                print(colored_text(f"\n{'─' * 70}", Colors.HEADER))
                print(colored_text("⚙️ 환경 변수", Colors.INFO))
                print(colored_text(f"{'─' * 70}", Colors.HEADER))
                if env_vars:
                    for key, value in env_vars.items():
                        if any(x in key.upper() for x in ['PASSWORD', 'SECRET', 'KEY', 'TOKEN']):
                            value = '****'
                        print(f"  {key}: {value}")
                else:
                    print("  환경 변수가 없습니다.")
                print(colored_text(f"{'─' * 70}", Colors.HEADER))
            input(colored_text("\n계속하려면 Enter를 누르세요...", Colors.PROMPT))

        elif action_sel == 2:
            lambda_test_invoke(manager, region, function_name)

        elif action_sel == 3:
            lambda_logs_view(manager, region, function_name)

        elif action_sel == 4:
            lambda_versions_aliases(manager, region, function_name)

        elif action_sel == 5:
            url = f"https://{region}.console.aws.amazon.com/lambda/home?region={region}#/functions/{function_name}"
            print(colored_text("\n🌐 Lambda 콘솔을 엽니다...", Colors.INFO))
            subprocess.run(['open', url])
            print(colored_text("✅ 브라우저가 열렸습니다.", Colors.SUCCESS))
            time.sleep(1)


def lambda_test_invoke(manager: AWSManager, region: str, function_name: str) -> None:
    print(colored_text(f"\n▶️ Lambda 함수 테스트 실행: {function_name}", Colors.INFO))
    print(colored_text('JSON 페이로드를 입력하세요 (빈 입력 = 빈 객체 {}): ', Colors.PROMPT))
    print(colored_text('예: {"key": "value"}', Colors.PROMPT))

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
    print(colored_text("▶️ 실행 결과", Colors.INFO))
    print(colored_text(f"{'─' * 70}", Colors.HEADER))

    status_code = result.get('StatusCode', 0)
    if status_code == 200:
        print(colored_text(f"  상태: ✅ 성공 (HTTP {status_code})", Colors.SUCCESS))
    else:
        print(colored_text(f"  상태: ❌ 오류 (HTTP {status_code})", Colors.ERROR))

    if result.get('FunctionError'):
        print(colored_text(f"  에러: {result['FunctionError']}", Colors.ERROR))

    print(f"  실행 버전: {result.get('ExecutedVersion', 'N/A')}")
    print(colored_text("\n📤 응답 페이로드:", Colors.INFO))
    response_payload = result.get('Payload')
    if response_payload:
        try:
            formatted = json.dumps(response_payload, indent=2, ensure_ascii=False)
            if len(formatted) > 1000:
                formatted = formatted[:1000] + '\n... (truncated)'
            print(formatted)
        except (TypeError, ValueError):
            print(str(response_payload)[:1000])
    else:
        print("  (응답 없음)")

    log_result = result.get('LogResult', '')
    if log_result:
        print(colored_text("\n📜 실행 로그:", Colors.INFO))
        for line in log_result.split('\n')[:20]:
            print(f"  {line}")

    print(colored_text(f"{'─' * 70}", Colors.HEADER))
    input(colored_text("\n계속하려면 Enter를 누르세요...", Colors.PROMPT))


def lambda_logs_view(manager: AWSManager, region: str, function_name: str) -> None:
    hours_items = ["최근 1시간", "최근 6시간", "최근 24시간", "🔙 돌아가기"]
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

    for event in logs[-50:]:
        ts = event.get('timestamp', 0)
        ts_str = datetime.fromtimestamp(ts / 1000).strftime('%H:%M:%S.%f')[:-3] if ts else ''
        msg = event.get('message', '').strip()
        if len(msg) > 100:
            msg = msg[:100] + '...'
        if 'ERROR' in msg or 'Error' in msg:
            print(colored_text(f"  [{ts_str}] {msg}", Colors.ERROR))
        elif 'WARN' in msg or 'Warning' in msg:
            print(colored_text(f"  [{ts_str}] {msg}", Colors.WARNING))
        else:
            print(f"  [{ts_str}] {msg}")

    print(colored_text(f"{'─' * 80}", Colors.HEADER))
    input(colored_text("\n계속하려면 Enter를 누르세요...", Colors.PROMPT))


def lambda_versions_aliases(manager: AWSManager, region: str, function_name: str) -> None:
    versions = manager.list_lambda_versions(region, function_name)
    aliases = manager.list_lambda_aliases(region, function_name)

    print(colored_text(f"\n{'─' * 70}", Colors.HEADER))
    print(colored_text(f"🏷️ 버전 및 별칭: {function_name}", Colors.INFO))
    print(colored_text(f"{'─' * 70}", Colors.HEADER))

    print(colored_text("\n📌 버전:", Colors.INFO))
    if versions:
        for ver in versions[:10]:
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
