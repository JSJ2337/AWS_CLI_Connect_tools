#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Apache Guacamole 연동 관리자
웹 브라우저에서 직접 RDP 연결을 제공합니다.
"""

import asyncio
import asyncpg
import logging
from typing import Dict, Optional
import uuid
import time

logger = logging.getLogger(__name__)

class GuacamoleManager:
    """Apache Guacamole 연동 관리 클래스"""

    def __init__(self, base_url: str = "http://localhost:8081"):
        self.base_url = base_url.rstrip('/')
        self.db_config = {
            'host': 'guacamole-db',
            'port': 5432,
            'database': 'guacamole_db',
            'user': 'guacamole_user',
            'password': 'guacamole_pass'
        }
        self.connections = {}

    async def get_db_connection(self):
        """데이터베이스 연결을 반환합니다."""
        return await asyncpg.connect(**self.db_config)

    async def authenticate(self) -> bool:
        """데이터베이스 연결 테스트"""
        try:
            conn = await self.get_db_connection()
            await conn.close()
            logger.info("Guacamole 데이터베이스 연결 성공")
            return True
        except Exception as e:
            logger.error(f"Guacamole 데이터베이스 연결 오류: {e}")
            return False

    async def create_rdp_connection(self, host: str, port: int, connection_name: str = None) -> Optional[str]:
        """새로운 RDP 연결을 데이터베이스에 직접 생성합니다."""
        try:
            if not await self.authenticate():
                return None

            # 연결 이름 생성
            if not connection_name:
                connection_name = f"RDP-{host}-{port}-{int(time.time())}"

            conn = await self.get_db_connection()

            try:
                # 연결 생성
                connection_id = await conn.fetchval("""
                    INSERT INTO guacamole_connection (connection_name, protocol)
                    VALUES ($1, 'rdp')
                    RETURNING connection_id
                """, connection_name)

                # 연결 파라미터 추가 - Windows Server 호환성 최적화
                parameters = {
                    'hostname': host,
                    'port': str(port),
                    'username': '',  # 빈 사용자명 - SSM이 이미 인증 처리
                    'password': '',  # 빈 비밀번호 - SSM이 이미 인증 처리
                    'ignore-cert': 'true',
                    'disable-auth': 'true',  # 인증 완전 비활성화
                    'enable-drive': 'false',  # 드라이브 리다이렉션 비활성화 (보안상 이유)
                    'enable-printing': 'false',  # 프린터 리다이렉션 비활성화
                    'enable-wallpaper': 'false',  # 성능 최적화
                    'enable-theming': 'false',  # 성능 최적화
                    'enable-font-smoothing': 'false',  # 성능 최적화
                    'enable-full-window-drag': 'false',  # 성능 최적화
                    'enable-desktop-composition': 'false',  # 성능 최적화
                    'resize-method': 'reconnect',
                    'server-layout': 'ko-kr-qwerty',  # 한국어 키보드 레이아웃
                    'color-depth': '16',  # 16비트 색깔로 성능 향상
                    'dpi': '96'  # 기본 DPI 설정
                }

                for param_name, param_value in parameters.items():
                    await conn.execute("""
                        INSERT INTO guacamole_connection_parameter (connection_id, parameter_name, parameter_value)
                        VALUES ($1, $2, $3)
                    """, connection_id, param_name, param_value)

                # guacadmin 사용자에게 연결 권한 부여
                guacadmin_entity_id = await conn.fetchval("""
                    SELECT entity_id FROM guacamole_entity WHERE name = 'guacadmin' AND type = 'USER'
                """)

                if guacadmin_entity_id:
                    await conn.execute("""
                        INSERT INTO guacamole_connection_permission (entity_id, connection_id, permission)
                        VALUES ($1, $2, 'READ')
                    """, guacadmin_entity_id, connection_id)

                # 연결 정보 저장
                self.connections[str(connection_id)] = {
                    'guacamole_id': connection_id,
                    'host': host,
                    'port': port,
                    'name': connection_name,
                    'created_at': time.time()
                }

                logger.info(f"RDP 연결 생성 성공: {connection_name} ({host}:{port}) - ID: {connection_id}")
                return str(connection_id)

            finally:
                await conn.close()

        except Exception as e:
            logger.error(f"RDP 연결 생성 오류: {e}")
            return None

    def get_connection_url(self, connection_id: str) -> Optional[str]:
        """연결 URL을 반환합니다."""
        if connection_id not in self.connections:
            return None

        connection_info = self.connections[connection_id]
        guac_connection_id = connection_info['guacamole_id']

        # Guacamole 클라이언트 URL 생성 (로그인 필요)
        client_url = f"{self.base_url}/guacamole/"
        return client_url

    async def delete_connection(self, connection_id: str) -> bool:
        """연결을 삭제합니다."""
        try:
            if connection_id not in self.connections:
                return False

            connection_info = self.connections[connection_id]
            guac_connection_id = connection_info['guacamole_id']

            conn = await self.get_db_connection()

            try:
                # 연결 삭제 (CASCADE로 파라미터와 권한도 삭제됨)
                await conn.execute("""
                    DELETE FROM guacamole_connection WHERE connection_id = $1
                """, guac_connection_id)

                # 로컬 캐시에서 제거
                del self.connections[connection_id]
                logger.info(f"RDP 연결 삭제 성공: {connection_info['name']}")
                return True

            finally:
                await conn.close()

        except Exception as e:
            logger.error(f"RDP 연결 삭제 오류: {e}")
            return False

    def list_connections(self) -> Dict:
        """활성 연결 목록을 반환합니다."""
        return {
            conn_id: {
                'host': info['host'],
                'port': info['port'],
                'name': info['name'],
                'url': self.get_connection_url(conn_id),
                'created_at': info['created_at']
            }
            for conn_id, info in self.connections.items()
        }

    async def cleanup_old_connections(self, max_age_hours: int = 2):
        """오래된 연결들을 정리합니다."""
        current_time = time.time()
        max_age_seconds = max_age_hours * 3600

        to_delete = []
        for conn_id, info in self.connections.items():
            if current_time - info['created_at'] > max_age_seconds:
                to_delete.append(conn_id)

        for conn_id in to_delete:
            await self.delete_connection(conn_id)

        if to_delete:
            logger.info(f"오래된 RDP 연결 {len(to_delete)}개 정리 완료")

# 전역 인스턴스
guacamole_manager = GuacamoleManager()