"""터미널 메뉴 UI"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

from ec2menu.core.colors import Colors, colored_text
from ec2menu.core.config import Config

try:
    from simple_term_menu import TerminalMenu
    TERM_MENU_SUPPORT = True
except ImportError:
    print("💡 화살표 키 메뉴를 위해 simple-term-menu를 설치하세요: pip install simple-term-menu")
    TERM_MENU_SUPPORT = False


def interactive_select(
    items: List[str],
    title: str = "",
    footer: str = "",
    show_index: bool = True,
) -> int:
    """simple-term-menu 기반 화살표 키 네비게이션 메뉴. 취소 시 -1 반환."""
    if not items:
        return -1

    if TERM_MENU_SUPPORT:
        try:
            display_items = []
            for i, item in enumerate(items):
                if i < 9:
                    shortcut = f"[{i+1}]"
                elif i == 9:
                    shortcut = "[0]"
                elif i < 36:
                    shortcut = f"[{chr(ord('a') + i - 10)}]"
                else:
                    shortcut = "   "
                display_items.append(f"{shortcut}   {item}")

            styled_title = None
            if title:
                line = '═' * 70
                styled_title = f"\n{line}\n    {title}\n{line}\n"

            menu = TerminalMenu(
                display_items,
                title=styled_title,
                menu_cursor="  ▶ ",
                menu_cursor_style=("fg_cyan", "bold"),
                menu_highlight_style=("standout", "bold"),
                search_key="/",
                quit_keys=("escape", "q"),
                clear_screen=False,
                shortcut_key_highlight_style=("fg_cyan", "bold"),
                shortcut_brackets_highlight_style=("fg_gray",),
            )
            result = menu.show()
            return result if result is not None else -1
        except Exception as e:
            print(colored_text(f"\n⚠️ 메뉴 초기화 실패, 번호 입력 모드로 전환: {e}", Colors.WARNING))
            return _fallback_menu(items, title, show_index)
    else:
        return _fallback_menu(items, title, show_index)


def _fallback_menu(items: List[str], title: str = "", show_index: bool = True) -> int:
    if title:
        print(colored_text(f"\n{title}", Colors.HEADER))
        print("-" * 40)

    for i, item in enumerate(items):
        if show_index:
            print(f"  {i + 1}) {item}")
        else:
            print(f"  {item}")

    print()
    sel = input(colored_text("선택 (번호, q=취소): ", Colors.PROMPT)).strip()

    if sel.lower() in ('q', 'b') or not sel:
        return -1

    if sel.isdigit():
        idx = int(sel) - 1
        if 0 <= idx < len(items):
            return idx

    return -1


class InteractiveMenu:
    """하위 호환성 래퍼 클래스"""

    def __init__(
        self,
        items: List[str],
        title: str = "",
        footer: str = "",
        selected_idx: int = 0,
        show_index: bool = True,
        page_size: int = 0,
    ):
        self.items = items
        self.title = title
        self.footer = footer
        self.selected_idx = selected_idx
        self.show_index = show_index
        self.page_size = page_size

    def run(self) -> int:
        return interactive_select(
            self.items,
            title=self.title,
            footer=self.footer,
            show_index=self.show_index,
        )


def get_menu_choice(
    prompt: str,
    max_num: int,
    special_keys: Optional[Dict[str, str]] = None,
    allow_empty: bool = True,
) -> Tuple[str, Optional[int]]:
    """메뉴 선택 입력 처리 헬퍼. (action, number) 튜플 반환."""
    if special_keys is None:
        special_keys = {'b': 'back', 'r': 'refresh'}

    sel = input(colored_text(prompt, Colors.PROMPT)).strip().lower()

    if not sel:
        return ('empty', None) if allow_empty else ('invalid', None)

    if sel in special_keys:
        return (special_keys[sel], None)

    if sel.isdigit():
        num = int(sel)
        if 1 <= num <= max_num:
            return ('number', num)

    return ('invalid', None)


def paginate_display(
    items: List[Any],
    display_func: Callable[[int, Any], str],
    title: str = "",
    page_size: int = 0,
) -> Optional[Tuple[int, Any]]:
    """리스트를 페이지 단위로 표시하고 사용자 선택을 받음. 취소 시 None 반환."""
    if page_size <= 0:
        page_size = Config.MENU_PAGE_SIZE

    total_items = len(items)
    if total_items == 0:
        return None

    total_pages = (total_items + page_size - 1) // page_size
    current_page = 0

    while True:
        start_idx = current_page * page_size
        end_idx = min(start_idx + page_size, total_items)
        page_items = items[start_idx:end_idx]

        if title:
            print(colored_text(f"\n{title}", Colors.HEADER))

        for i, item in enumerate(page_items):
            global_idx = start_idx + i + 1
            print(display_func(global_idx, item))

        if total_pages > 1:
            nav_hint = []
            if current_page > 0:
                nav_hint.append("p=이전")
            if current_page < total_pages - 1:
                nav_hint.append("n=다음")
            nav_str = ", ".join(nav_hint)
            print(colored_text(f"\n[Page {current_page + 1}/{total_pages}] {nav_str}, b=뒤로", Colors.INFO))

        prompt = f"선택 (1-{total_items}, b=뒤로): "
        sel = input(colored_text(prompt, Colors.PROMPT)).strip().lower()

        if not sel or sel == 'b':
            return None
        elif sel == 'n' and current_page < total_pages - 1:
            current_page += 1
        elif sel == 'p' and current_page > 0:
            current_page -= 1
        elif sel.isdigit():
            idx = int(sel)
            if 1 <= idx <= total_items:
                return (idx - 1, items[idx - 1])
            else:
                print(colored_text("❌ 유효한 번호를 입력하세요.", Colors.ERROR))
        else:
            print(colored_text("❌ 유효한 입력이 아닙니다.", Colors.ERROR))
