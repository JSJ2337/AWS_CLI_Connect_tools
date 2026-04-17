"""CloudWatch 대시보드/알람/로그 메뉴"""
from __future__ import annotations

import subprocess
import time
import urllib.parse
from datetime import datetime

from ec2menu.core.colors import Colors, colored_text
from ec2menu.ui.menu import interactive_select

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ec2menu.aws.manager import AWSManager


def cloudwatch_menu(manager: AWSManager, region: str) -> None:
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
            cloudwatch_dashboards_menu(manager, region)
        elif sub_sel == 1:
            cloudwatch_alarms_menu(manager, region)
        elif sub_sel == 2:
            cloudwatch_logs_menu(manager, region)


def cloudwatch_dashboards_menu(manager: AWSManager, region: str) -> None:
    while True:
        dashboards = manager.list_cloudwatch_dashboards(region)
        if not dashboards:
            print(colored_text(f"\n⚠ 리전 {region}에 CloudWatch 대시보드가 없습니다.", Colors.WARNING))
            input(colored_text("계속하려면 Enter를 누르세요...", Colors.PROMPT))
            return

        dashboard_items = []
        for db in dashboards:
            last_mod = db.get('LastModified')
            last_mod_str = last_mod.strftime('%Y-%m-%d %H:%M') if last_mod else 'N/A'
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

        action_items = ["🌐 브라우저에서 열기", "📋 대시보드 정보", "🔙 돌아가기"]
        action_sel = interactive_select(action_items, title=f"대시보드: {dashboard_name}")

        if action_sel == 0:
            url = f"https://{region}.console.aws.amazon.com/cloudwatch/home?region={region}#dashboards:name={dashboard_name}"
            print(colored_text("\n🌐 대시보드를 브라우저에서 엽니다...", Colors.INFO))
            subprocess.run(['open', url])
            print(colored_text("✅ 브라우저가 열렸습니다.", Colors.SUCCESS))
            time.sleep(1)
        elif action_sel == 1:
            print(colored_text(f"\n{'─' * 60}", Colors.HEADER))
            print(colored_text("📊 대시보드 정보", Colors.INFO))
            print(colored_text(f"{'─' * 60}", Colors.HEADER))
            print(f"  이름: {selected_db['DashboardName']}")
            print(f"  ARN: {selected_db.get('DashboardArn', 'N/A')}")
            print(f"  크기: {selected_db.get('Size', 0)} bytes")
            if selected_db.get('LastModified'):
                print(f"  수정일: {selected_db['LastModified'].strftime('%Y-%m-%d %H:%M:%S')}")
            print(colored_text(f"{'─' * 60}", Colors.HEADER))
            input(colored_text("\n계속하려면 Enter를 누르세요...", Colors.PROMPT))


def cloudwatch_alarms_menu(manager: AWSManager, region: str) -> None:
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

        alarm_items = []
        for alarm in alarms:
            state = alarm['StateValue']
            state_icon = '🔴' if state == 'ALARM' else ('🟢' if state == 'OK' else '🟡')
            name = alarm['AlarmName'][:35]
            metric = alarm['MetricName'][:20] if alarm['MetricName'] else ''
            alarm_items.append(f"{state_icon} {name:<35} {metric:<20} {state}")
        alarm_items.append("🔙 돌아가기")

        state_str = state_filter if state_filter else "All"
        title = f"CloudWatch Alarms ({state_str})  │  {len(alarms)} alarms"
        alarm_sel = interactive_select(alarm_items, title=title)

        if alarm_sel == -1 or alarm_sel == len(alarms):
            continue

        selected_alarm = alarms[alarm_sel]
        alarm_name = selected_alarm['AlarmName']

        print(colored_text(f"\n{'─' * 70}", Colors.HEADER))
        print(colored_text("🔔 알람 상세 정보", Colors.INFO))
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


def cloudwatch_logs_menu(manager: AWSManager, region: str) -> None:
    prefix_filter = None

    while True:
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
            prefix_filter = input(colored_text("로그 그룹 prefix 입력: ", Colors.PROMPT)).strip() or None

        log_groups = manager.list_log_groups(region, prefix=prefix_filter)
        if not log_groups:
            msg = f"⚠ 리전 {region}에 "
            msg += f"'{prefix_filter}' prefix의 " if prefix_filter else ""
            msg += "로그 그룹이 없습니다."
            print(colored_text(msg, Colors.WARNING))
            input(colored_text("계속하려면 Enter를 누르세요...", Colors.PROMPT))
            continue

        while True:
            lg_items = []
            for lg in log_groups:
                name = lg['logGroupName']
                size_mb = lg.get('storedBytes', 0) / (1024 * 1024)
                retention = lg.get('retentionInDays')
                retention_str = f"{retention}d" if retention else "∞"
                lg_items.append(f"{name:<50} {size_mb:>8.2f}MB  보관: {retention_str}")
            lg_items.append("🔙 돌아가기")

            title = f"Log Groups  │  {len(log_groups)} groups"
            lg_sel = interactive_select(lg_items, title=title)

            if lg_sel == -1 or lg_sel == len(log_groups):
                break

            selected_lg = log_groups[lg_sel]
            cloudwatch_log_streams_menu(manager, region, selected_lg['logGroupName'])


def cloudwatch_log_streams_menu(manager: AWSManager, region: str, log_group_name: str) -> None:
    while True:
        streams = manager.get_log_streams(region, log_group_name, limit=50)
        if not streams:
            print(colored_text("⚠ 로그 그룹에 스트림이 없습니다.", Colors.WARNING))
            input(colored_text("계속하려면 Enter를 누르세요...", Colors.PROMPT))
            return

        stream_items = []
        for stream in streams:
            name = stream['logStreamName']
            if len(name) > 45:
                name = name[:42] + '...'
            last_event = stream.get('lastEventTimestamp', 0)
            last_event_str = datetime.fromtimestamp(last_event / 1000).strftime('%Y-%m-%d %H:%M') if last_event else 'N/A'
            stream_items.append(f"{name:<45} 최근: {last_event_str}")
        stream_items.append("🔙 돌아가기")

        display_name = log_group_name
        if len(display_name) > 40:
            display_name = '...' + display_name[-37:]

        title = f"Log Streams  │  {display_name}"
        stream_sel = interactive_select(stream_items, title=title)

        if stream_sel == -1 or stream_sel == len(streams):
            return

        selected_stream = streams[stream_sel]
        stream_name = selected_stream['logStreamName']

        action_items = [
            "📋 최근 로그 (100개)",
            "🔍 로그 검색 (필터)",
            "🌐 브라우저에서 열기",
            "🔙 돌아가기"
        ]
        action_sel = interactive_select(action_items, title=f"스트림: {stream_name[:40]}")

        if action_sel == 0:
            events = manager.filter_log_events(region, log_group_name, log_stream=stream_name, limit=100)
            if events:
                print(colored_text(f"\n{'─' * 80}", Colors.HEADER))
                print(colored_text(f"📋 최근 로그 ({len(events)}개)", Colors.INFO))
                print(colored_text(f"{'─' * 80}", Colors.HEADER))
                for event in events[-30:]:
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
            encoded_group = urllib.parse.quote(log_group_name, safe='')
            encoded_stream = urllib.parse.quote(stream_name, safe='')
            url = f"https://{region}.console.aws.amazon.com/cloudwatch/home?region={region}#logsV2:log-groups/log-group/{encoded_group}/log-events/{encoded_stream}"
            print(colored_text("\n🌐 로그 스트림을 브라우저에서 엽니다...", Colors.INFO))
            subprocess.run(['open', url])
            print(colored_text("✅ 브라우저가 열렸습니다.", Colors.SUCCESS))
            time.sleep(1)
