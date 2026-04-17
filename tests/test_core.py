"""core/ 순수 로직 테스트"""
import time

import pytest

from ec2menu.core.cache import PerformanceCache
from ec2menu.core.utils import calculate_local_port, normalize_file_path


class TestPerformanceCache:
    def test_set_and_get(self) -> None:
        cache = PerformanceCache()
        cache.set('test_key', {'data': 1})
        result = cache.get('test_key')
        assert result == {'data': 1}

    def test_expired_entry_returns_none(self) -> None:
        cache = PerformanceCache()
        cache.set('test_key', 'value', ttl_seconds=1)
        time.sleep(1.1)
        assert cache.get('test_key') is None

    def test_invalidate(self) -> None:
        cache = PerformanceCache()
        cache.set('test_key', 'value')
        cache.invalidate('test_key')
        assert cache.get('test_key') is None

    def test_clear(self) -> None:
        cache = PerformanceCache()
        cache.set('key1', 'v1')
        cache.set('key2', 'v2')
        cache.clear()
        assert cache.get('key1') is None
        assert cache.get('key2') is None


class TestNormalizeFilePath:
    def test_removes_quotes(self) -> None:
        result = normalize_file_path("'/path/to/file'")
        assert result == '/path/to/file'

    def test_removes_double_quotes(self) -> None:
        result = normalize_file_path('"/path/to/file"')
        assert result == '/path/to/file'

    def test_expands_home(self) -> None:
        result = normalize_file_path('~/Downloads/file.txt')
        assert '~' not in result
        assert 'Downloads' in result


class TestCalculateLocalPort:
    def test_returns_int_in_range(self) -> None:
        from ec2menu.core.config import Config
        port = calculate_local_port('i-1234567890abcdef0')
        assert isinstance(port, int)
        assert Config.PORT_RANGE_START <= port < Config.PORT_RANGE_END

    def test_deterministic(self) -> None:
        p1 = calculate_local_port('i-1234567890abcdef0')
        p2 = calculate_local_port('i-1234567890abcdef0')
        assert p1 == p2
