"""DB 자격 증명 관리"""
from __future__ import annotations

import getpass
from typing import Optional, Tuple

from ec2menu.core.colors import Colors, colored_text
from ec2menu.core.keychain import KeychainManager

# 메모리 자격 증명 저장소 (하위 호환성)
_stored_credentials: dict = {}


def get_db_credentials(db_user_hint: str = "") -> Tuple[Optional[str], Optional[str]]:
    """DB 자격 증명 조회. Keychain → 메모리 → 신규 입력 순서로 시도."""
    global _stored_credentials

    # 1. Keychain에서 확인
    if db_user_hint and KeychainManager.has_credentials(db_user_hint):
        password = KeychainManager.get(db_user_hint)
        print(colored_text(f"\n🔐 Keychain에 저장된 자격 증명을 찾았습니다: {db_user_hint}", Colors.INFO))
        use_stored = input("Keychain 자격 증명을 사용하시겠습니까? (Y/n, b=뒤로): ").strip().lower()
        if use_stored == 'b':
            return None, None
        if use_stored != 'n':
            return db_user_hint, password

    # 2. 메모리에서 확인
    if _stored_credentials:
        print(colored_text("\n💾 메모리에 저장된 DB 자격 증명이 있습니다.", Colors.INFO))
        use_stored = input("저장된 자격 증명을 사용하시겠습니까? (Y/n, b=뒤로): ").strip().lower()
        if use_stored == 'b':
            return None, None
        if use_stored != 'n':
            return _stored_credentials['user'], _stored_credentials['password']

    # 3. 신규 입력
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

    # 4. 저장 여부 확인
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
            _stored_credentials['user'] = db_user
            _stored_credentials['password'] = db_password
            print(colored_text("⚠️ Keychain 저장 실패. 메모리에만 저장되었습니다.", Colors.WARNING))
    elif save_choice == '2':
        _stored_credentials['user'] = db_user
        _stored_credentials['password'] = db_password
        KeychainManager.store(db_user, db_password, use_keychain=False)
        print(colored_text("✅ 자격 증명이 메모리에 저장되었습니다. (스크립트 종료 시 자동 삭제)", Colors.SUCCESS))

    return db_user, db_password


def clear_stored_credentials() -> None:
    global _stored_credentials
    _stored_credentials.clear()
    KeychainManager.clear_session()
    print(colored_text("🗑️ 저장된 자격 증명을 삭제했습니다.", Colors.SUCCESS))
