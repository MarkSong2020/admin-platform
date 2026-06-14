"""seed 页面组件跨语言真值源：fixture 必须等于 MENU_TREE 中菜单(C)的 component 全集。

前端 Vitest 只读该 fixture 断言 ⊆ import.meta.glob keys（spec §5）。
后端改 seed 不同步 fixture → 本测试红，防跨语言漂移。
"""

import json
from collections.abc import Iterable
from pathlib import Path

from admin_platform.rbac.seed import MENU_TREE, SeedMenu

FIXTURE = Path("tests/contracts/seed_page_components.json")


def _collect_page_components(nodes: Iterable[SeedMenu]) -> set[str]:
    """递归收集 menu_type == 'C' 且有 component 的页面组件路径。

    MENU_TREE 是 tuple[SeedMenu, ...] frozen dataclass（seed.py:32），用属性访问、非 dict.get()。
    目录(M)的 component 是 Layout/ParentView 壳名、按钮(F)无 component，均排除。
    """
    result: set[str] = set()
    for node in nodes:
        if node.menu_type == "C" and node.component:
            result.add(node.component)
        result |= _collect_page_components(node.children)
    return result


def test_fixture_matches_seed_page_components():
    expected = _collect_page_components(MENU_TREE)
    actual = set(json.loads(FIXTURE.read_text(encoding="utf-8")))
    assert actual == expected, (
        f"seed_page_components.json 与 MENU_TREE 漂移；"
        f"缺 {expected - actual}，多 {actual - expected}"
    )
