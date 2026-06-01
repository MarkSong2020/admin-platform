"""模板里程碑版本号漂移守门。

历史：v0.4.16 review 发现 README / AGENTS / CLAUDE / PROJECT_OVERVIEW 都还
写 v0.4.14，但 CHANGELOG 顶部已经是 v0.4.16；没有自动守门，每次发版后人工
同步 4 处文档很容易漏。

设计：CHANGELOG.md 顶部的 ``## [vX.Y.Z]`` 是 single source of truth；其它
4 处文档必须出现同一个版本号。``pyproject.toml [project].version`` 是业务
实例初始版本（克隆后业务自管），与模板里程碑版本不同源，**不**纳入守门。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

_VERSION_HEADER_RE = re.compile(r"^##\s+\[(v\d+\.\d+\.\d+)\]")


def _changelog_top_version() -> str:
    changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    for line in changelog.splitlines():
        match = _VERSION_HEADER_RE.match(line)
        if match:
            return match.group(1)
    raise AssertionError("CHANGELOG.md has no `## [vX.Y.Z]` header")


@pytest.fixture(scope="module")
def expected_version() -> str:
    return _changelog_top_version()


@pytest.mark.parametrize(
    "doc_path",
    [
        "README.md",
        "AGENTS.md",
        "CLAUDE.md",
        "doc/PROJECT_OVERVIEW.md",
    ],
)
def test_doc_mentions_current_template_version(doc_path: str, expected_version: str) -> None:
    text = (REPO_ROOT / doc_path).read_text(encoding="utf-8")
    assert expected_version in text, (
        f"{doc_path} does not mention current template version {expected_version} "
        "(CHANGELOG.md top entry). Sync README / AGENTS / CLAUDE / PROJECT_OVERVIEW "
        "every release."
    )


def test_changelog_top_version_is_well_formed(expected_version: str) -> None:
    assert _VERSION_HEADER_RE.match(f"## [{expected_version}]"), (
        f"CHANGELOG top version {expected_version!r} is not vX.Y.Z"
    )


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
