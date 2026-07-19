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


def register_temp_file(path: Path) -> None:
    """atexit에서 정리할 임시 파일을 등록한다."""
    with _temp_files_lock:
        _temp_files_to_cleanup.append(path)


def unregister_temp_file(path: Path) -> None:
    """이미 삭제한 임시 파일을 정리 목록에서 제거한다."""
    with _temp_files_lock:
        if path in _temp_files_to_cleanup:
            _temp_files_to_cleanup.remove(path)


def format_size(size_bytes: int) -> str:
    """바이트 크기를 사람이 읽기 쉬운 단위로 변환 (B/KB/MB/GB/TB)."""
    if size_bytes <= 0:
        return "0B"
    size_float = float(size_bytes)
    for unit in ('B', 'KB', 'MB', 'GB'):
        if size_float < Config.BYTES_PER_KB:
            return f"{size_float:.1f}{unit}"
        size_float /= Config.BYTES_PER_KB
    return f"{size_float:.1f}TB"


def calculate_local_port(instance_id: str) -> int:
    """인스턴스 ID로부터 고유한 로컬 포트 번호 생성.

    instance_id가 'i-xxxxxxx' 형식이 아니거나 꼬리가 hex가 아닐 수 있어 예외를 흡수한다.
    """
    port_span = Config.PORT_RANGE_END - Config.PORT_RANGE_START
    try:
        id_hash = int(instance_id[-3:], 16) % port_span
    except (ValueError, IndexError):
        id_hash = hash(instance_id) % port_span
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
