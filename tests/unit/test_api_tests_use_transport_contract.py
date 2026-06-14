"""AST 契约：api 测试只能经 TestClient/ASGITransport 打端点，禁止直接调用 router endpoint 函数。

**为什么**：直接 ``await list_users(...)`` / ``list_roles(...)`` 调端点函数会**绕过整个 FastAPI 请求
栈**——query/path 参数解析、Pydantic 校验、依赖注入、中间件、异常处理全不走。本仓「列表端点 422」
bug 正是「请求绑定」层的问题，只有真发 HTTP 请求才暴露；裸调端点函数的「假 api 测试」会让这类绑定
反模式悄悄漏过。本契约用 AST 扫 ``tests/api/*.py``，禁止直接调用从各域 ``*.api`` 模块导入的 endpoint
函数（即 ``@router.get/post/...`` 装饰的函数），逼 api 测试一律走 ``TestClient`` / ``ASGITransport``。

**判据（精确，避免误伤）**：只标记「**从某 ``*.api`` 模块 import 进来、且确为 endpoint 函数名**」的
符号被直接调用——同名巧合（如测试里自定义 helper 恰好叫 ``get_role``）不导入自 ``.api`` 故不误判。

不连 DB / 不导入业务代码：纯 ``ast`` 静态解析源码（``ast.parse`` 读文件文本）。
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_API_DIR = _REPO_ROOT / "src" / "admin_platform" / "domains"
_TESTS_API_DIR = _REPO_ROOT / "tests" / "api"

_ROUTER_METHODS = {"get", "post", "put", "patch", "delete"}

# 合理例外（精确粒度，``"<file>.py:<lineno>"`` → 原因）。**不**按整文件豁免——按整文件放行会顺带
# 放行同文件其它裸调（漏报）。key 与违规描述前缀 ``<file>.py:<lineno>`` 对齐：豁免哪一行就只放行那行。
# 当前为空：所有 api 测试都已走 TestClient。若某 case 确需直接调端点函数（极少见，应优先重构为
# HTTP 调用），在此登记 ``"test_xxx.py:123": "原因"`` 并注明理由。
_ALLOWLIST: dict[str, str] = {}


def _endpoint_function_names() -> set[str]:
    """收集所有 ``@router.<method>(...)`` 装饰的 endpoint 函数名（遍历 ``domains/*/api.py``）。"""
    names: set[str] = set()
    for api_file in sorted(_API_DIR.glob("*/api.py")):
        tree = ast.parse(api_file.read_text(encoding="utf-8"), filename=str(api_file))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for decorator in node.decorator_list:
                if (
                    isinstance(decorator, ast.Call)
                    and isinstance(decorator.func, ast.Attribute)
                    and isinstance(decorator.func.value, ast.Name)
                    and decorator.func.value.id == "router"
                    and decorator.func.attr in _ROUTER_METHODS
                ):
                    names.add(node.name)
    return names


def _symbols_imported_from_api(tree: ast.Module) -> dict[str, str]:
    """该测试模块里「从某 ``*.api`` 模块 import 进来」的符号映射：``本地名 → 原始名``（含 ``as`` 别名）。

    ``from x.api import list_users as foo`` 产出 ``{"foo": "list_users"}``——保留**原始 endpoint 名**用于
    与 ``endpoint_names`` 求交集（别名换不掉它指向的真实 endpoint），同时保留**本地名**用于扫调用点。
    若只存本地别名（旧实现），``foo()`` 的 ``foo`` 不在 ``endpoint_names`` 里 → 别名绕过漏报。
    """
    imported: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.endswith(".api"):
            for alias in node.names:
                imported[alias.asname or alias.name] = alias.name
    return imported


def _api_module_aliases(tree: ast.Module) -> set[str]:
    """该模块里「绑定到某 ``*.api`` 模块整体」的本地名集合（用于抓模块属性裸调 ``api.list_users()``）。

    ``from x.api import f`` 把单个符号拿进来，归 ``_symbols_imported_from_api``；本函数管把**整个 api
    模块**拿进来的两种写法（裸调写法 ``api.list_users()`` 的来源）：
      * ``import a.b.api as api``（``ast.Import`` + asname）→ 本地名 ``api``；
      * ``from a.b import api [as alias]``（``ast.ImportFrom``，导入名是 ``api`` 子模块）→ 本地名 ``alias`` 或 ``api``。
    无 asname 的 ``import a.b.api`` 须用全点号链 ``a.b.api.f()`` 访问，属少见写法，登记为已知边界不强求。
    """
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.endswith(".api") and alias.asname:
                    aliases.add(alias.asname)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "api":  # from x.domains.y import api
                    aliases.add(alias.asname or "api")
    return aliases


def _endpoint_call_hit(
    node: ast.Call,
    suspect: dict[str, str],
    module_aliases: set[str],
    endpoint_names: set[str],
) -> str | None:
    """判断一个 ``ast.Call`` 是否命中 endpoint 裸调，命中返回描述串（含原始 endpoint 名），否则 ``None``。

    抓三类形态（间接赋值 ``f = list_users; f()`` 属 AST 静态分析固有盲区，登记为已知边界不强求）：
      1. **直接名调用** ``list_users()`` / ``as`` 别名 ``foo()``——``node.func`` 是 ``ast.Name``；
      2. **模块属性调用** ``api.list_users()``——``node.func`` 是 ``ast.Attribute``（旧实现只看 ``ast.Name`` 故漏）；
      3. **getattr 调用** ``getattr(api, "list_users")()``——动态取属性绕过形态。
    """
    func = node.func
    # 形态 1：直接名调用 list_users() / 别名 foo()
    if isinstance(func, ast.Name) and func.id in suspect:
        original = suspect[func.id]
        via = f"（别名 {func.id} → {original}）" if func.id != original else ""
        return f"{original}(...){via}"
    # 形态 2：模块属性裸调 api.list_users()
    if (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id in module_aliases
        and func.attr in endpoint_names
    ):
        return f"{func.attr}(...)（模块属性裸调 {func.value.id}.{func.attr}）"
    # 形态 3：getattr(api, "list_users")()
    if isinstance(func, ast.Call) and isinstance(func.func, ast.Name) and func.func.id == "getattr":
        args = func.args
        if (
            len(args) >= 2
            and isinstance(args[0], ast.Name)
            and args[0].id in module_aliases
            and isinstance(args[1], ast.Constant)
            and isinstance(args[1].value, str)
            and args[1].value in endpoint_names
        ):
            return f"{args[1].value}(...)（getattr 裸调 {args[0].id}）"
    return None


def _direct_endpoint_calls(test_file: Path, endpoint_names: set[str]) -> list[str]:
    """返回该测试文件里「直接调用 import 自 ``.api`` 的 endpoint 函数」的违规位置描述。

    判据按**原始 endpoint 名**判定（``orig in endpoint_names``）。覆盖直接名调用 / ``as`` 别名 /
    模块属性裸调 ``api.list_users()`` / ``getattr`` 裸调四种形态（见 ``_endpoint_call_hit``）。
    """
    tree = ast.parse(test_file.read_text(encoding="utf-8"), filename=str(test_file))
    mapping = _symbols_imported_from_api(tree)
    # 本地名 → 原始名，仅保留原始名确为 endpoint 函数的项。
    suspect = {local: orig for local, orig in mapping.items() if orig in endpoint_names}
    module_aliases = _api_module_aliases(tree)
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        hit = _endpoint_call_hit(node, suspect, module_aliases, endpoint_names)
        if hit is not None:
            violations.append(f"{test_file.name}:{node.lineno} 直接调用 endpoint 函数 {hit}")
    return violations


def test_api_tests_do_not_call_router_endpoints_directly() -> None:
    """``tests/api/*.py`` 不得直接调用 router endpoint 函数（必须经 TestClient/ASGITransport）。

    临时把任一 api 测试改成 ``await list_xxx(...)`` 直调端点 → 本契约 FAIL 并报出 file:line + 函数名。
    """
    endpoint_names = _endpoint_function_names()
    assert endpoint_names, "未收集到任何 endpoint 函数名——收集逻辑可能失效（防空集恒过）"

    violations: list[str] = []
    for test_file in sorted(_TESTS_API_DIR.glob("test_*.py")):
        for v in _direct_endpoint_calls(test_file, endpoint_names):
            # 违规描述前缀即 ``<file>.py:<lineno>``（与 _ALLOWLIST key 同形）——按精确 file:line 豁免，
            # 不按整文件放行（整文件豁免会顺带放行同文件其它裸调）。
            location = v.split(" ", 1)[0]
            if location not in _ALLOWLIST:
                violations.append(v)
    assert not violations, (
        "api 测试直接调用了 router endpoint 函数（绕过 FastAPI 请求栈/校验/绑定，"
        "请改为经 TestClient/ASGITransport 发真实 HTTP 请求）:\n" + "\n".join(violations)
    )


def test_alias_import_call_is_flagged(tmp_path: Path) -> None:
    """负向探针：``import list_users as call_list_users; call_list_users()`` 必须被标记为违规。

    旧实现只存本地别名、与原始 endpoint 名求交集，故 ``as`` 别名调用漏报（假绿）。本探针喂 synthetic
    源码证明别名绕过已堵；若有人退回「只存本地别名」，这里立刻 FAIL。
    """
    source = (
        "from admin_platform.domains.user.api import list_users as call_list_users\n"
        "call_list_users()\n"
    )
    probe = tmp_path / "test_alias_probe.py"
    probe.write_text(source, encoding="utf-8")

    violations = _direct_endpoint_calls(probe, {"list_users"})
    assert violations, "别名调用 call_list_users() 未被标记——别名绕过仍存在"
    assert "list_users" in violations[0], "违规描述应报出原始 endpoint 名 list_users"
    assert "call_list_users" in violations[0], "违规描述应报出本地别名 call_list_users"


def test_non_endpoint_same_name_helper_is_not_flagged(tmp_path: Path) -> None:
    """负向探针（防误报）：导入自 ``.api`` 但**不是 endpoint** 的同名符号被调用，不应误判违规。

    判据按「原始名确在 ``endpoint_names`` 集里」过滤——非 endpoint 的 helper（即便也从某 ``.api``
    导入）调用不该报。喂一个非 endpoint 名（不在 endpoint_names 里）证明不误伤。
    """
    source = "from admin_platform.domains.user.api import build_user_filter as helper\nhelper()\n"
    probe = tmp_path / "test_helper_probe.py"
    probe.write_text(source, encoding="utf-8")

    # endpoint_names 不含 build_user_filter → 不应被标记。
    violations = _direct_endpoint_calls(probe, {"list_users"})
    assert not violations, f"非 endpoint helper 被误报违规: {violations}"


def test_module_attribute_call_is_flagged(tmp_path: Path) -> None:
    """负向探针：``import x.api as api; api.list_users()``（模块属性裸调）必须被标记为违规。

    旧实现只扫 ``ast.Name`` 调用，``api.list_users()`` 的 ``node.func`` 是 ``ast.Attribute`` 故漏报
    （Codex high + harness 门 meta agent 双源实测确认的假绿路径）。本探针证明已堵。
    """
    source = "import admin_platform.domains.user.api as api\napi.list_users()\n"
    probe = tmp_path / "test_modattr_probe.py"
    probe.write_text(source, encoding="utf-8")

    violations = _direct_endpoint_calls(probe, {"list_users"})
    assert violations, "模块属性裸调 api.list_users() 未被标记——ast.Attribute 形态仍漏"
    assert "list_users" in violations[0]


def test_from_import_module_then_attribute_call_is_flagged(tmp_path: Path) -> None:
    """负向探针：``from x.domains.y import api; api.list_users()`` 必须被标记为违规。

    这是「未来作者最自然的裸调写法」——把 api 子模块整体 import 进来再点调端点函数。
    """
    source = "from admin_platform.domains.user import api\napi.list_users()\n"
    probe = tmp_path / "test_fromimport_modattr_probe.py"
    probe.write_text(source, encoding="utf-8")

    violations = _direct_endpoint_calls(probe, {"list_users"})
    assert violations, "from-import 模块后属性裸调 api.list_users() 未被标记"
    assert "list_users" in violations[0]


def test_getattr_call_is_flagged(tmp_path: Path) -> None:
    """负向探针：``getattr(api, "list_users")()`` 动态取属性裸调必须被标记为违规。"""
    source = 'import admin_platform.domains.user.api as api\ngetattr(api, "list_users")()\n'
    probe = tmp_path / "test_getattr_probe.py"
    probe.write_text(source, encoding="utf-8")

    violations = _direct_endpoint_calls(probe, {"list_users"})
    assert violations, 'getattr(api, "list_users")() 未被标记——getattr 形态仍漏'
    assert "list_users" in violations[0]


def test_module_attribute_call_to_non_endpoint_is_not_flagged(tmp_path: Path) -> None:
    """负向探针（防误报）：``api.<非 endpoint 名>()`` 不应被标记（只有点调真实 endpoint 名才算违规）。"""
    source = "import admin_platform.domains.user.api as api\napi.build_user_filter()\n"
    probe = tmp_path / "test_modattr_helper_probe.py"
    probe.write_text(source, encoding="utf-8")

    # build_user_filter 不在 endpoint_names → 即便经模块属性调用也不应误报。
    violations = _direct_endpoint_calls(probe, {"list_users"})
    assert not violations, f"模块属性调用非 endpoint 被误报: {violations}"
