"""EC2 인스턴스 목록 조회, 접속, 배치/파일 전송 메뉴"""
from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path
from typing import List, Optional

from ec2menu.aws.batch import BatchJobManager
from ec2menu.aws.transfer import FileTransferManager
from ec2menu.core.colors import Colors, colored_text
from ec2menu.core.config import Config
from ec2menu.core.utils import calculate_local_port, normalize_file_path
from ec2menu.terminal.session import launch_linux_wt, launch_rdp, start_port_forward
from ec2menu.ui.history import add_to_history, invalidate_cache_for_service
from ec2menu.ui.menu import interactive_select

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ec2menu.aws.manager import AWSManager

_sort_key: str = 'Name'
_sort_reverse: bool = False


def filter_linux_instances(instances: List[dict], valid_choices: List[int],
                            region: Optional[str] = None) -> List[dict]:
    selected = []
    for choice_idx in valid_choices:
        inst_data = instances[choice_idx - 1]
        inst = inst_data['raw']
        if inst.get('PlatformDetails', 'Linux').lower().startswith('windows'):
            print(colored_text(
                f"⚠️  Windows 인스턴스는 배치 작업/파일 전송을 지원하지 않습니다: {inst_data['Name']}",
                Colors.WARNING
            ))
            continue
        if region and 'Region' not in inst_data:
            inst_data['Region'] = inst.get('_region', region)
        selected.append(inst_data)
    return selected


def sort_instances(instances: List[dict], sort_key: str = 'Name', reverse: bool = False) -> List[dict]:
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


def show_sort_help() -> None:
    print(colored_text("\n📊 정렬 옵션:", Colors.INFO))
    print("  n = 이름순 정렬")
    print("  t = 타입순 정렬")
    print("  r = 리전순 정렬")
    print("  s = 상태순 정렬")
    print("  같은 키를 다시 누르면 역순 정렬")


def ec2_menu(manager: AWSManager, region: str) -> None:
    global _sort_key, _sort_reverse
    procs = []
    batch_manager = BatchJobManager(manager)
    file_transfer_manager = FileTransferManager(manager)

    try:
        while True:
            force_refresh = False
            if region == 'multi-region':
                regions = manager.list_regions()
                insts_raw = manager.list_instances_multi_region(regions, force_refresh)
                if not insts_raw:
                    print(colored_text("\n⚠ 모든 리전에 실행 중인 EC2 인스턴스가 없습니다.", Colors.WARNING))
                    break
                region_display = "All Regions"
            else:
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

            insts = sort_instances(insts_display, _sort_key, _sort_reverse)

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

            menu_items.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            menu_items.append("📋 배치 작업 (여러 인스턴스에 명령 실행)")
            menu_items.append("📁 파일 업로드 (여러 인스턴스에 파일 전송)")
            menu_items.append("🔄 목록 새로고침")
            menu_items.append("🔙 메인 메뉴로 돌아가기")

            title = f"EC2 Instances  │  Profile: {manager.profile}  │  Region: {region_display}  │  Sort: {_sort_key}"
            footer = "↑↓: 이동  Enter: 접속  /: 검색  b: 메인  r: 새로고침"
            selected = interactive_select(menu_items, title=title, footer=footer)

            separator_idx = len(insts)

            if selected == -1 or selected == len(menu_items) - 1:
                break
            elif selected == separator_idx:
                continue
            elif selected == separator_idx + 1:
                sel = 'batch'
            elif selected == separator_idx + 2:
                sel = 'upload'
            elif selected == separator_idx + 3:
                sel = 'r'
            elif 0 <= selected < separator_idx:
                sel = str(selected + 1)
            else:
                continue

            if not sel or sel == 'b':
                break
            elif sel == 'r':
                print(colored_text("🔄 목록을 새로고침합니다...", Colors.INFO))
                invalidate_cache_for_service(manager, region, "instances")
                force_refresh = True
                continue
            elif sel in ['n', 't', 's', 'r']:
                sort_map = {'n': 'Name', 't': 'Type', 's': 'State', 'r': 'Region'}
                new_sort_key = sort_map.get(sel, 'Name')
                if new_sort_key == _sort_key:
                    _sort_reverse = not _sort_reverse
                else:
                    _sort_key = new_sort_key
                    _sort_reverse = False
                continue
            elif sel == 'batch':
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
                    selected_instances = filter_linux_instances(insts, valid_choices, region)
                    if not selected_instances:
                        print(colored_text("❌ 배치 작업할 Linux 인스턴스가 없습니다.", Colors.ERROR))
                        continue
                    print(colored_text(f"\n{len(selected_instances)}개 Linux 인스턴스에서 실행할 명령을 입력하세요:", Colors.INFO))
                    for inst in selected_instances:
                        print(f"  - {inst['Name']} ({inst['raw']['InstanceId']})")
                    batch_command = input(colored_text("\n실행할 명령 (b=뒤로): ", Colors.PROMPT)).strip()
                    if not batch_command:
                        print(colored_text("❌ 명령을 입력해야 합니다.", Colors.ERROR))
                        continue
                    if batch_command.lower() == 'b':
                        continue
                    results = batch_manager.execute_batch_command(selected_instances, batch_command)
                    batch_manager.show_batch_results(results)
                    input(colored_text("\n[Press Enter to continue]...", Colors.PROMPT))
                    continue
                except ValueError:
                    print(colored_text("❌ 숫자와 쉼표만 입력하세요.", Colors.ERROR))
                    continue
            elif sel == 'upload':
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
                    selected_instances = filter_linux_instances(insts, valid_choices, region)
                    if not selected_instances:
                        print(colored_text("❌ 파일 전송 가능한 Linux 인스턴스가 없습니다.", Colors.ERROR))
                        continue
                    print(colored_text(f"\n선택된 인스턴스 ({len(selected_instances)}개):", Colors.INFO))
                    for inst_data in selected_instances:
                        print(f"  - {inst_data['Name']} ({inst_data['raw']['InstanceId']})")
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
                    local_path = normalize_file_path(local_path)
                    local_path_obj = Path(local_path)
                    if not local_path_obj.exists():
                        print(colored_text(f"❌ 파일이 존재하지 않습니다: {local_path}", Colors.ERROR))
                        continue
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
                    print(colored_text("\n📋 전송 정보:", Colors.HEADER))
                    print(f"로컬 파일: {local_path}")
                    print(f"대상 경로: {remote_path}")
                    print(f"대상 인스턴스: {len(selected_instances)}개")
                    confirm = input(colored_text("\n전송을 시작하시겠습니까? (y/n): ", Colors.PROMPT)).strip().lower()
                    if confirm != 'y':
                        continue
                    results = file_transfer_manager.upload_file_to_multiple_instances(
                        local_path, remote_path, selected_instances
                    )
                    success_count = sum(1 for r in results if r.status == 'SUCCESS')
                    print(colored_text(
                        f"\n📊 전송 완료: {success_count}/{len(results)} 성공",
                        Colors.SUCCESS if success_count == len(results) else Colors.WARNING
                    ))
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
                add_to_history('ec2', manager.profile, inst_region, inst['InstanceId'], inst_data['Name'])
                if inst.get('PlatformDetails', 'Linux').lower().startswith('windows'):
                    rdp_started = True
                    local_port = calculate_local_port(inst['InstanceId']) + i
                    print(colored_text(f"\n(info) Windows 인스턴스 RDP 연결을 시작합니다 (localhost:{local_port})...", Colors.INFO))
                    proc = start_port_forward(manager.profile, inst_region, inst['InstanceId'], local_port)
                    procs.append(proc)
                    launch_rdp(local_port)
                else:
                    print(colored_text("\n(info) Linux 인스턴스 SSM 연결을 시작합니다...", Colors.INFO))
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
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    logging.warning(f"프로세스 종료 타임아웃 (PID={proc.pid}), 강제 종료")
                    proc.kill()
                    proc.wait()
            print(colored_text("🔌 모든 RDP 포트 포워딩 연결을 종료했습니다.", Colors.SUCCESS))
