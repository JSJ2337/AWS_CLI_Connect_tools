"""애플리케이션 설정 중앙 관리"""
from __future__ import annotations

import os
import platform
from pathlib import Path


IS_MAC = platform.system() == 'Darwin'


class Config:
    """애플리케이션 설정 (매직 넘버 제거 및 중앙 관리)"""
    AWS_CONFIG_PATH = Path("~/.aws/config").expanduser()
    AWS_CRED_PATH = Path("~/.aws/credentials").expanduser()
    LOG_PATH = Path.home() / ".ec2menu.log"
    HISTORY_PATH = Path.home() / ".ec2menu_history.json"
    BATCH_RESULTS_PATH = Path.home() / ".ec2menu_batch_results.json"

    DEFAULT_WORKERS: int = 20
    CACHE_TTL_SECONDS: int = 300

    CACHE_TTLS = {
        'instances': 120,
        'ssm': 120,
        'rds': 300,
        'elasticache': 300,
        'ecs': 600,
        'eks': 600,
        'regions': 3600,
        'cloudwatch_dashboards': 600,
        'cloudwatch_alarms': 120,
        'cloudwatch_logs': 60,
        'lambda': 300,
        's3_buckets': 600,
        's3_objects': 60,
        'default': 300,
    }

    MENU_PAGE_SIZE = 20

    BATCH_MAX_RETRIES = 3
    BATCH_COMMAND_RETRY = 3
    BATCH_RETRY_DELAY = 10
    BATCH_RETRY_MAX_DELAY = 60
    BATCH_TIMEOUT_SECONDS = 600
    BATCH_MAX_WAIT_ATTEMPTS = 200
    BATCH_CONCURRENT_JOBS = 5

    EC2_PAGE_SIZE = 100
    MAX_PAGINATION_PAGES = 100

    PORT_RANGE_START = 10000
    PORT_RANGE_END = 11000
    RDS_PORT_START = 11000

    BYTES_PER_KB = 1024

    SSM_TIMEOUT_SECONDS = 600
    HISTORY_MAX_SIZE = 100
    MAX_INPUT_RETRIES = 5

    WAIT_PORT_READY = 2
    WAIT_APP_LAUNCH = 0.8
    WAIT_RDP_READY = 2

    DB_TOOL_PATH = os.environ.get('DB_TOOL_PATH', "mysql")
    DBEAVER_PATH = os.environ.get('DBEAVER_PATH', '/Applications/DBeaver.app/Contents/MacOS/dbeaver')
    CACHE_REDIS_CLI = os.environ.get('CACHE_REDIS_CLI', "redis-cli")
    CACHE_MEMCACHED_CLI = os.environ.get('CACHE_MEMCACHED_CLI', "telnet")

    DEBUG_MODE = os.environ.get('EC2MENU_DEBUG', '0') == '1'


# 하위 호환성 별칭
AWS_CONFIG_PATH = Config.AWS_CONFIG_PATH
AWS_CRED_PATH = Config.AWS_CRED_PATH
LOG_PATH = Config.LOG_PATH
HISTORY_PATH = Config.HISTORY_PATH
BATCH_RESULTS_PATH = Config.BATCH_RESULTS_PATH
DEFAULT_WORKERS = Config.DEFAULT_WORKERS
DEFAULT_DB_TOOL_PATH = Config.DB_TOOL_PATH
DEFAULT_CACHE_REDIS_CLI = Config.CACHE_REDIS_CLI
DEFAULT_CACHE_MEMCACHED_CLI = Config.CACHE_MEMCACHED_CLI
