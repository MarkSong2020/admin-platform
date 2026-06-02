"""应用版本号 × 文档一致性守门。

admin-platform 是基于 ``python-web-service-template`` 脚手架派生的**独立应用**，
版本口径以本仓 ``pyproject.toml [project].version`` 为准，**不再绑定**模板
CHANGELOG 的里程碑版本（模板 CHANGELOG 现作为派生 lineage 保留，不是本应用的
发版记录）。

设计：``pyproject.toml [project].version`` 是 single source of truth；README /
AGENTS / CLAUDE / PROJECT_OVERVIEW 必须出现当前应用版本，避免发版后漏同步 4 处文档。
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


def _app_version() -> str:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["version"]


@pytest.fixture(scope="module")
def app_version() -> str:
    return _app_version()


@pytest.mark.parametrize(
    "doc_path",
    [
        "README.md",
        "AGENTS.md",
        "CLAUDE.md",
        "doc/PROJECT_OVERVIEW.md",
    ],
)
def test_doc_mentions_current_app_version(doc_path: str, app_version: str) -> None:
    text = (REPO_ROOT / doc_path).read_text(encoding="utf-8")
    assert app_version in text, (
        f"{doc_path} does not mention current app version {app_version} "
        "(pyproject.toml [project].version). Sync README / AGENTS / CLAUDE / "
        "PROJECT_OVERVIEW every release."
    )


def test_app_version_is_well_formed(app_version: str) -> None:
    assert _SEMVER_RE.match(app_version), f"pyproject app version {app_version!r} is not X.Y.Z"


@pytest.mark.parametrize(
    "doc_path",
    [
        "README.md",
        "doc/operations/LOCAL_SETUP.md",
    ],
)
def test_onboarding_doc_mentions_pre_commit_install(doc_path: str) -> None:
    """守门：onboarding 文档必须显式提示 `pre-commit install`。

    历史：v0.4.17 把 ``pre-commit`` 装进 dev deps，但 LOCAL_SETUP / README
    只写 ``make init`` 不写 ``pre-commit install``——hook 没注册，新人首次
    commit 时 ruff-format 改文件导致 commit fail，误以为环境坏了。

    实测显示这是 v0.4.20 review 抓到的 onboarding 真痛点。守门防止未来
    重写文档时漏掉这一步。"""
    text = (REPO_ROOT / doc_path).read_text(encoding="utf-8")
    assert "pre-commit install" in text, (
        f"{doc_path} must mention `pre-commit install` in the onboarding flow — "
        "without it, new joiners hit a wall on first commit (hook not registered "
        "→ ruff-format changes files → commit fails)."
    )
