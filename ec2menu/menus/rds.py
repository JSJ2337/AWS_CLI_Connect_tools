"""RDS 데이터베이스 접속 메뉴"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from pathlib import Path

from ec2menu.core.colors import Colors, colored_text
from ec2menu.core.config import Config
from ec2menu.terminal.session import create_ssm_forward_command
from ec2menu.ui.credentials import get_db_credentials
from ec2menu.ui.history import add_to_history, invalidate_cache_for_service
from ec2menu.ui.menu import interactive_select

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ec2menu.aws.manager import AWSManager


def connect_to_rds(manager: AWSManager, tool_path: str, region: str) -> None:
    while True:
        if region == 'multi-region':
            regions = manager.list_regions()
            dbs = manager.get_rds_endpoints_multi_region(regions)
            region_display = "All Regions"
        else:
            dbs = manager.get_rds_endpoints(region)
            region_display = region

        if not dbs:
            print(colored_text(f"\n⚠ {region_display}에 RDS 인스턴스가 없습니다", Colors.WARNING))
            return

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

        if sel == -1 or sel == len(dbs) + 1:
            return
        if sel == len(dbs):
            print(colored_text("🔄 목록을 새로고침합니다...", Colors.INFO))
            invalidate_cache_for_service(manager, region, "rds")
            continue

        valid_choices = [sel + 1]

        db_user, db_password = get_db_credentials()
        if not db_user or not db_password:
            continue

        target_region = dbs[valid_choices[0] - 1].get('_region', region)
        if region == 'multi-region':
            print(colored_text(f"\n📍 리전 {target_region}에서 점프 호스트를 선택합니다.", Colors.INFO))

        from ec2menu.main import choose_jump_host
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
                add_to_history('rds', manager.profile, db_region, db['Id'], db['Id'])
                params_dict = {
                    "host": [db["Endpoint"]],
                    "portNumber": [str(db["Port"])],
                    "localPortNumber": [str(local_port)]
                }
                params = json.dumps(params_dict)
                proc = subprocess.Popen(
                    create_ssm_forward_command(manager.profile, target_region, tgt, 'AWS-StartPortForwardingSessionToRemoteHost', params),
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
                procs.append(proc)

            time.sleep(Config.WAIT_PORT_READY)
            print(colored_text("\n✅ 모든 포트 포워딩 활성화. DBeaver로 자동 연결합니다...", Colors.SUCCESS))

            dbeaver_path = os.environ.get('DBEAVER_PATH', '/Applications/DBeaver.app/Contents/MacOS/dbeaver')
            if Path(dbeaver_path).exists():
                for i, choice_idx in enumerate(valid_choices):
                    db = dbs[choice_idx - 1]
                    local_port = 11000 + i
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
                    db_name = db.get('DBName', '')
                    if db_name:
                        conn_spec = f"driver={driver}|host=localhost|port={local_port}|database={db_name}|user={db_user}|password={db_password}|name={db['Id']}"
                    else:
                        conn_spec = f"driver={driver}|host=localhost|port={local_port}|user={db_user}|password={db_password}|name={db['Id']}"
                    subprocess.Popen(
                        [dbeaver_path, '-nosplash', '-con', conn_spec],
                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                    )
                    print(colored_text(f"✅ DBeaver 연결 시작: {db['Id']} (localhost:{local_port})", Colors.SUCCESS))
                time.sleep(1)
                try:
                    subprocess.run(['osascript', '-e', 'tell application "DBeaver" to activate'],
                                   check=False, timeout=5)
                except (subprocess.TimeoutExpired, FileNotFoundError) as e:
                    logging.warning(f"DBeaver 활성화 실패: {e}")
            elif tool_path and Path(tool_path).exists():
                for i, choice_idx in enumerate(valid_choices):
                    db = dbs[choice_idx - 1]
                    local_port = 11000 + i
                    command = [tool_path, '-h', 'localhost', '-P', str(local_port), '-u', db_user, f'-p{db_password}']
                    if db.get('DBName'):
                        command.append(db['DBName'])
                    subprocess.Popen(command)
                    print(colored_text(f"✅ {tool_path} 연결 시작: {db['Id']}", Colors.SUCCESS))
            else:
                print(colored_text("\n📊 데이터베이스 연결 정보:", Colors.HEADER))
                for i, choice_idx in enumerate(valid_choices):
                    db = dbs[choice_idx - 1]
                    local_port = 11000 + i
                    print(colored_text(f"\n  [{i+1}] {db['Id']}", Colors.INFO))
                    print(colored_text(f"      호스트: localhost", Colors.INFO))
                    print(colored_text(f"      포트: {local_port}", Colors.INFO))
                    print(colored_text(f"      사용자: {db_user}", Colors.INFO))
                    print(colored_text(f"      비밀번호: {'*' * 8}", Colors.INFO))
                    if db.get('DBName'):
                        print(colored_text(f"      데이터베이스: {db['DBName']}", Colors.INFO))
                print(colored_text("\n💡 DBeaver를 설치하면 자동 연결이 가능합니다.", Colors.INFO))

            print("\n(완료되면 이 창에서 Enter 키를 눌러 연결을 모두 종료합니다)")
            input("[Press Enter to terminate all connections]...\n")
            break

        finally:
            if procs:
                for proc in procs:
                    proc.terminate()
                print(colored_text("🔌 모든 포트 포워딩 연결을 종료했습니다.", Colors.SUCCESS))
