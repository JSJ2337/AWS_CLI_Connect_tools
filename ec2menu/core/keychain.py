"""macOS Keychain 자격 증명 관리"""
from __future__ import annotations

import logging
import subprocess
from typing import Dict, Optional


class KeychainManager:
    """macOS Keychain을 사용한 안전한 자격 증명 관리"""
    SERVICE_PREFIX = "ec2menu-db"
    _session_credentials: Dict[str, str] = {}

    @staticmethod
    def store(account: str, password: str, use_keychain: bool = True) -> bool:
        service = KeychainManager.SERVICE_PREFIX
        KeychainManager._session_credentials[account] = password

        if not use_keychain:
            return True

        try:
            subprocess.run(
                ['security', 'delete-generic-password', '-a', account, '-s', service],
                capture_output=True, check=False
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
        if account in KeychainManager._session_credentials:
            return KeychainManager._session_credentials[account]

        service = KeychainManager.SERVICE_PREFIX
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
        service = KeychainManager.SERVICE_PREFIX
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
        KeychainManager._session_credentials.clear()

    @staticmethod
    def has_credentials(account: str) -> bool:
        return KeychainManager.get(account) is not None
