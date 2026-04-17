"""컬러 테마 설정"""
from __future__ import annotations

try:
    from colorama import init, Fore, Back, Style
    init(autoreset=True)
    COLOR_SUPPORT = True
except ImportError:
    print("💡 더 나은 사용자 경험을 위해 colorama를 설치하세요: pip install colorama")
    COLOR_SUPPORT = False

    class MockColor:
        def __getattr__(self, name): return ""

    Fore = Back = Style = MockColor()


class Colors:
    EC2 = Fore.BLUE
    RDS = Fore.YELLOW
    CACHE = Fore.MAGENTA
    ECS = Fore.CYAN
    EKS = Fore.GREEN

    RUNNING = Fore.GREEN
    STOPPED = Fore.RED
    PENDING = Fore.YELLOW
    WARNING = Fore.YELLOW
    ERROR = Fore.RED
    SUCCESS = Fore.GREEN
    INFO = Fore.CYAN

    HEADER = Style.BRIGHT + Fore.WHITE
    MENU = Fore.WHITE
    PROMPT = Fore.CYAN
    RESET = Style.RESET_ALL


def colored_text(text: str, color: str = "") -> str:
    if COLOR_SUPPORT and color:
        return f"{color}{text}{Colors.RESET}"
    return text


def get_status_color(status: str) -> str:
    status_lower = status.lower()
    if status_lower in ['running', 'available', 'active']:
        return Colors.RUNNING
    elif status_lower in ['stopped', 'terminated', 'inactive']:
        return Colors.STOPPED
    elif status_lower in ['pending', 'starting', 'stopping']:
        return Colors.PENDING
    return ""
