"""ElastiCache 클러스터 접속 메뉴"""
from __future__ import annotations

import json
import logging
import subprocess
import time

from ec2menu.core.colors import Colors, colored_text
from ec2menu.core.config import Config
from ec2menu.terminal.session import create_ssm_forward_command, launch_terminal_session
from ec2menu.ui.history import add_to_history, invalidate_cache_for_service
from ec2menu.ui.menu import interactive_select

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ec2menu.aws.manager import AWSManager


def connect_to_cache(manager: AWSManager, region: str) -> None:
    while True:
        if region == 'multi-region':
            regions = manager.list_regions()
            clus = manager.list_cache_clusters_multi_region(regions)
            region_display = "All Regions"
        else:
            clus = manager.list_cache_clusters(region)
            region_display = region

        if not clus:
            print(colored_text(f"\n⚠ {region_display}에 ElastiCache 클러스터가 없습니다", Colors.WARNING))
            time.sleep(1)
            break

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

        if sel == -1 or sel == len(clus) + 1:
            break
        if sel == len(clus):
            print(colored_text("🔄 목록을 새로고침합니다...", Colors.INFO))
            invalidate_cache_for_service(manager, region, "elasticache")
            continue

        idx = sel
        c = clus[idx]
        cache_region = c.get('_region', region)
        add_to_history('cache', manager.profile, cache_region, c['Id'], c['Id'])

        from ec2menu.main import choose_jump_host
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
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            time.sleep(Config.WAIT_PORT_READY)
            print(colored_text("\n✅ 포트 포워딩이 활성화되었습니다. 클라이언트에서 아래 주소로 접속하세요.", Colors.SUCCESS))
            print(f"   Engine: {c['Engine']}")
            print(f"   Address: localhost:{local_port}")

            tool_launched = False
            try:
                tool = Config.CACHE_REDIS_CLI if c['Engine'].startswith('redis') else Config.CACHE_MEMCACHED_CLI
                args = [tool, '-h', '127.0.0.1', '-p', str(local_port)] if 'redis' in tool else [tool, '127.0.0.1', str(local_port)]
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
