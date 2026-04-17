"""ECS 클러스터/서비스/태스크/컨테이너 메뉴"""
from __future__ import annotations

import subprocess
import time
from datetime import datetime

from ec2menu.core.colors import Colors, colored_text
from ec2menu.core.config import Config, IS_MAC
from ec2menu.terminal.session import launch_ecs_exec
from ec2menu.ui.history import add_to_history
from ec2menu.ui.menu import interactive_select

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ec2menu.aws.manager import AWSManager


def ecs_menu(manager: AWSManager, region: str) -> None:
    while True:
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
            clusters = manager.list_ecs_clusters(region)
            for c in clusters:
                c['_region'] = region

        if not clusters:
            print(colored_text(f"\n⚠ 리전 {region}에 ECS 클러스터가 없습니다.", Colors.WARNING))
            return

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

        while True:
            services = manager.list_ecs_services(cluster_region, cluster_name)
            if not services:
                print(colored_text(f"\n⚠ 클러스터 {cluster_name}에 ECS 서비스가 없습니다.", Colors.WARNING))
                break

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

            while True:
                tasks = manager.list_ecs_tasks(cluster_region, cluster_name, service_name)
                if not tasks:
                    print(colored_text(f"\n⚠ 서비스 {service_name}에 실행 중인 태스크가 없습니다.", Colors.WARNING))
                    break

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
                            container_items = [f"📦 {c['Name']} ({c['Status']})" for c in containers]
                            container_items.append("🔙 돌아가기")
                            container_sel = interactive_select(container_items, title="접속할 컨테이너 선택", show_index=False)
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
                        log_configs = manager.get_ecs_task_log_config(cluster_region, selected_task['TaskDefinitionArn'])
                        if not log_configs:
                            print(colored_text("❌ 이 태스크에는 CloudWatch Logs 설정이 없습니다.", Colors.ERROR))
                            print(colored_text("   태스크 정의에서 awslogs 로그 드라이버를 설정하세요.", Colors.INFO))
                            input(colored_text("\n[Enter를 눌러 계속]", Colors.PROMPT))
                            continue

                        if len(log_configs) == 1:
                            selected_log_config = log_configs[0]
                        else:
                            log_container_items = [f"{lc['ContainerName']} → {lc['LogGroup']}" for lc in log_configs]
                            log_container_items.append("🔙 돌아가기")
                            lc_sel = interactive_select(log_container_items, title="로그를 조회할 컨테이너 선택")
                            if lc_sel == -1 or lc_sel == len(log_configs):
                                continue
                            selected_log_config = log_configs[lc_sel]

                        log_group = selected_log_config['LogGroup']
                        log_prefix = selected_log_config['LogStreamPrefix']
                        log_region = selected_log_config['Region']
                        container_name = selected_log_config['ContainerName']

                        print(colored_text("\n⏳ 로그 스트림을 검색 중...", Colors.INFO))
                        log_stream_name = f"{log_prefix}/{container_name}/{task_id}"

                        log_mode_items = [
                            "📄 최근 로그 보기 (마지막 100줄)",
                            "📺 실시간 로그 스트리밍 (새 터미널)",
                            "🔙 돌아가기"
                        ]
                        log_mode = interactive_select(log_mode_items, title="로그 조회 방식", show_index=False)

                        if log_mode == -1 or log_mode == 2:
                            continue

                        if log_mode == 0:
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
                            cmd = f"aws logs tail {log_group} --log-stream-names {log_stream_name} --follow --profile {manager.profile} --region {log_region}"
                            print(colored_text("\n📺 실시간 로그 스트리밍을 시작합니다...", Colors.INFO))
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
