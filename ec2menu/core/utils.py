"""공통 유틸리티 함수"""
from __future__ import annotations

import atexit
import logging
import sys
import threading
from pathlib import Path
from typing import List

from ec2menu.core.config import Config


_temp_files_to_cleanup: List[Path] = []
_temp_files_lock = threading.Lock()


def normalize_file_path(path_str: str) -> str:
    """파일 경로 정규화 (따옴표 제거, 경로 확장)"""
    if (path_str.startswith('"') and path_str.endswith('"')) or \
       (path_str.startswith("'") and path_str.endswith("'")):
        path_str = path_str[1:-1]
    return str(Path(path_str).expanduser().resolve())


def calculate_local_port(instance_id: str) -> int:
    """인스턴스 ID로부터 고유한 로컬 포트 번호 생성"""
    id_hash = int(instance_id[-3:], 16) % (Config.PORT_RANGE_END - Config.PORT_RANGE_START)
    return Config.PORT_RANGE_START + id_hash


def setup_logger(debug: bool) -> None:
    level = logging.DEBUG if debug else logging.INFO
    fmt = "%(asctime)s [%(levelname)s] %(message)s"
    handlers = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(Config.LOG_PATH, encoding="utf-8"),
    ]
    logging.basicConfig(level=level, format=fmt, handlers=handlers, style='%')


def cleanup_temp_files() -> None:
    with _temp_files_lock:
        for file_path in _temp_files_to_cleanup:
            try:
                if file_path.exists():
                    file_path.unlink()
                    logging.info(f"임시 파일 삭제됨: {file_path}")
            except Exception as e:
                logging.warning(f"임시 파일 삭제 실패: {file_path} - {e}")


atexit.register(cleanup_temp_files)
