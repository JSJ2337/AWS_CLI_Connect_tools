"""S3 버킷 브라우저 메뉴"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from ec2menu.core.colors import Colors, colored_text
from ec2menu.ui.menu import interactive_select

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ec2menu.aws.manager import AWSManager


def format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes}B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f}KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f}MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f}GB"


def s3_browser_menu(manager: AWSManager, region: str) -> None:
    while True:
        buckets = manager.list_s3_buckets()
        if not buckets:
            print(colored_text("\n⚠ S3 버킷이 없습니다.", Colors.WARNING))
            input(colored_text("계속하려면 Enter를 누르세요...", Colors.PROMPT))
            return

        bucket_items = []
        for bucket in buckets:
            name = bucket['Name']
            created = bucket.get('CreationDate')
            created_str = created.strftime('%Y-%m-%d') if created else 'N/A'
            bucket_items.append(f"{name:<50} 생성: {created_str}")
        bucket_items.append("🔙 돌아가기")

        title = f"S3 Buckets  │  {len(buckets)} buckets"
        bucket_sel = interactive_select(bucket_items, title=title)

        if bucket_sel == -1 or bucket_sel == len(buckets):
            return

        selected_bucket = buckets[bucket_sel]
        bucket_name = selected_bucket['Name']
        bucket_region = manager.get_bucket_location(bucket_name)
        print(colored_text(f"📍 버킷 리전: {bucket_region}", Colors.INFO))
        s3_bucket_browser(manager, bucket_name, bucket_region)


def s3_bucket_browser(manager: AWSManager, bucket_name: str, bucket_region: str, prefix: str = "") -> None:
    while True:
        result = manager.list_s3_objects(bucket_name, prefix=prefix, max_keys=100)
        folders = result.get('folders', [])
        files = result.get('files', [])

        items = []
        display_items = []

        if prefix:
            items.append({'type': 'parent', 'Key': '..'})
            display_items.append("📁 ..")

        for folder in folders:
            items.append(folder)
            folder_name = folder['Key'].rstrip('/').split('/')[-1]
            display_items.append(f"📁 {folder_name}/")

        for f in files:
            items.append(f)
            file_name = f['Key'].split('/')[-1]
            size_str = format_size(f.get('Size', 0))
            display_items.append(f"📄 {file_name:<40} {size_str:>10}")

        display_items.append("🔙 돌아가기")

        current_path = prefix if prefix else "/"
        if len(current_path) > 40:
            current_path = '...' + current_path[-37:]

        title = f"📦 {bucket_name}  │  {current_path}"
        sel = interactive_select(display_items, title=title)

        if sel == -1 or sel == len(items):
            return

        selected_item = items[sel]

        if selected_item.get('type') == 'parent':
            parts = prefix.rstrip('/').split('/')
            prefix = '/'.join(parts[:-1]) + '/' if len(parts) > 1 else ""
            continue

        if selected_item.get('Type') == 'folder':
            prefix = selected_item['Key']
            continue

        s3_file_actions(manager, bucket_name, bucket_region, selected_item['Key'])


def s3_file_actions(manager: AWSManager, bucket_name: str, bucket_region: str, file_key: str) -> None:
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
            info = manager.get_s3_object_info(bucket_name, file_key)
            if info:
                print(colored_text(f"\n{'─' * 70}", Colors.HEADER))
                print(colored_text("📄 파일 정보", Colors.INFO))
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
            default_path = str(Path.home() / 'Downloads' / file_name)
            print(colored_text(f"\n다운로드 경로 (Enter = {default_path}):", Colors.PROMPT))
            local_path = input("> ").strip()
            if not local_path:
                local_path = default_path
            local_path = str(Path(local_path).expanduser())

            print(colored_text(f"\n⬇️ 다운로드 중: {file_key}", Colors.INFO))

            def progress_callback(downloaded: int, total: int, percentage: float) -> None:
                bar_length = 30
                filled = int(bar_length * percentage / 100)
                bar = '█' * filled + '░' * (bar_length - filled)
                sys.stdout.write(f"\r  [{bar}] {percentage:.1f}% ({format_size(downloaded)}/{format_size(total)})")
                sys.stdout.flush()

            success = manager.download_s3_object(bucket_name, file_key, local_path, progress_callback)
            print()
            if success:
                print(colored_text(f"✅ 다운로드 완료: {local_path}", Colors.SUCCESS))
            else:
                print(colored_text("❌ 다운로드 실패", Colors.ERROR))
            input(colored_text("\n계속하려면 Enter를 누르세요...", Colors.PROMPT))

        elif action_sel == 2:
            expiry_items = ["1시간", "6시간", "24시간", "7일", "🔙 돌아가기"]
            expiry_sel = interactive_select(expiry_items, title="URL 유효 기간")

            if expiry_sel == -1 or expiry_sel == 4:
                continue

            expiration = [3600, 21600, 86400, 604800][expiry_sel]
            url = manager.generate_presigned_url(bucket_name, file_key, expiration=expiration)

            if url:
                print(colored_text(f"\n🔗 Presigned URL (유효: {expiry_items[expiry_sel]}):", Colors.INFO))
                print(url)
                try:
                    subprocess.run(['pbcopy'], input=url.encode(), check=True)
                    print(colored_text("\n📋 URL이 클립보드에 복사되었습니다.", Colors.SUCCESS))
                except Exception:
                    pass
            else:
                print(colored_text("❌ URL 생성 실패", Colors.ERROR))
            input(colored_text("\n계속하려면 Enter를 누르세요...", Colors.PROMPT))

        elif action_sel == 3:
            print(colored_text(f"\n⚠️ 정말로 '{file_name}'을(를) 삭제하시겠습니까?", Colors.WARNING))
            confirm = input(colored_text("삭제하려면 'DELETE' 입력: ", Colors.PROMPT)).strip()

            if confirm == 'DELETE':
                success = manager.delete_s3_object(bucket_name, file_key)
                if success:
                    print(colored_text("✅ 파일이 삭제되었습니다.", Colors.SUCCESS))
                    input(colored_text("\n계속하려면 Enter를 누르세요...", Colors.PROMPT))
                    return
                else:
                    print(colored_text("❌ 삭제 실패", Colors.ERROR))
            else:
                print(colored_text("삭제가 취소되었습니다.", Colors.INFO))
            input(colored_text("\n계속하려면 Enter를 누르세요...", Colors.PROMPT))
