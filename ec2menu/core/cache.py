"""캐싱 시스템"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from ec2menu.core.config import Config


@dataclass
class CacheEntry:
    data: Any
    timestamp: datetime
    ttl_seconds: int = 300

    def is_expired(self) -> bool:
        return datetime.now() - self.timestamp > timedelta(seconds=self.ttl_seconds)


class PerformanceCache:
    def __init__(self):
        self._cache: Dict[str, CacheEntry] = {}
        self._lock = threading.RLock()
        self._background_refresh_active = {}

    def _get_ttl_for_key(self, key: str) -> int:
        # 복합 접두사(cloudwatch_alarms, s3_buckets 등)를 올바르게 매칭하기 위해
        # 긴 접두사부터 검사하여 최장 일치를 우선한다.
        key_lower = key.lower()
        for ttl_key in sorted(
            (k for k in Config.CACHE_TTLS if k != 'default'),
            key=len,
            reverse=True,
        ):
            if key_lower == ttl_key or key_lower.startswith(ttl_key + '_'):
                return Config.CACHE_TTLS[ttl_key]
        return Config.CACHE_TTLS['default']

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            entry = self._cache.get(key)
            if entry and not entry.is_expired():
                return entry.data
            return None

    def set(self, key: str, data: Any, ttl_seconds: Optional[int] = None):
        if ttl_seconds is None:
            ttl_seconds = self._get_ttl_for_key(key)
        with self._lock:
            self._cache[key] = CacheEntry(data, datetime.now(), ttl_seconds)

    def invalidate(self, key: str):
        with self._lock:
            self._cache.pop(key, None)

    def clear(self):
        with self._lock:
            self._cache.clear()

    def start_background_refresh(self, key: str, refresh_func, *args, **kwargs):
        with self._lock:
            if key in self._background_refresh_active:
                return
            self._background_refresh_active[key] = True

        def refresh_worker():
            try:
                new_data = refresh_func(*args, **kwargs)
                self.set(key, new_data)
            except Exception as e:
                logging.warning(f"백그라운드 새로고침 실패 ({key}): {e}")
            finally:
                with self._lock:
                    self._background_refresh_active.pop(key, None)

        threading.Thread(target=refresh_worker, daemon=True).start()


# 전역 캐시 싱글톤 (public)
cache = PerformanceCache()

# 하위 호환성을 위한 별칭 (기존 `_cache` 참조 코드 유지)
_cache = cache
