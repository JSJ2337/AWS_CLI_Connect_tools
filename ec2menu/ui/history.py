"""연결 히스토리 관리"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict

from ec2menu.core.cache import _cache
from ec2menu.core.config import Config


def load_history() -> Dict[str, Any]:
    try:
        if Config.HISTORY_PATH.exists():
            with open(Config.HISTORY_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logging.warning(f"히스토리 로드 실패: {e}")
    return {"ec2": [], "rds": [], "cache": [], "ecs": []}


def save_history(history: Dict[str, Any]) -> None:
    try:
        with open(Config.HISTORY_PATH, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.warning(f"히스토리 저장 실패: {e}")


def add_to_history(service_type: str, profile: str, region: str, instance_id: str, instance_name: str) -> None:
    history = load_history()

    entry = {
        "profile": profile,
        "region": region,
        "instance_id": instance_id,
        "instance_name": instance_name,
        "timestamp": datetime.now().isoformat(),
    }

    history[service_type] = [h for h in history[service_type] if h["instance_id"] != instance_id]
    history[service_type].insert(0, entry)
    history[service_type] = history[service_type][:10]

    save_history(history)


def invalidate_cache_for_service(manager: Any, region: str, service_type: str) -> None:
    """서비스 타입에 따라 캐시 무효화"""
    if region == 'multi-region':
        regions = manager.list_regions()
        for r in regions:
            _cache.invalidate(f"{service_type}_{manager.profile}_{r}")
    else:
        _cache.invalidate(f"{service_type}_{manager.profile}_{region}")
