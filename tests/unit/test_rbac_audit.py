"""audited_write 审计 helper 单测（DB-free）——守 except 两分支（AppError / IntegrityError）。

Round-3 补：Round-2 给 audited_write 新增的 `except IntegrityError → 409/framework.CONFLICT`
分支（并发唯一约束兜底竞态的审计完整性）此前无任何测试覆盖，红线路径不能空守。这里直接喂
会抛对应异常的 coro，断言审计 envelope + re-raise，不依赖 DB 制造真实竞态。
"""

from __future__ import annotations

import logging

import pytest
from sqlalchemy.exc import IntegrityError

from admin_platform.core.auth import CurrentUser
from admin_platform.core.errors import AppError
from admin_platform.core.rbac_audit import audited_write


def _rbac_events(caplog: pytest.LogCaptureFixture) -> list[dict]:
    return [
        e
        for r in caplog.records
        if (e := getattr(r, "audit_event", None)) and e.get("event_type") == "rbac_write"
    ]


async def test_audited_write_audits_integrity_error_as_conflict(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # 并发唯一约束兜底（两请求都过 service 预检、第二个 flush 撞 uq）抛裸 IntegrityError →
    # audited_write 必须补一条 409/framework.CONFLICT 的 rbac_write failure 审计并原样 re-raise。
    async def _boom() -> object:
        raise IntegrityError("INSERT ...", {}, Exception("uq_roles_code"))

    user = CurrentUser(user_id="1", sub="1")
    with (
        caplog.at_level(logging.INFO, logger="admin_platform.audit"),
        pytest.raises(IntegrityError),
    ):
        await audited_write(user, "system:role:add", "role", coro=_boom())
    events = _rbac_events(caplog)
    assert len(events) == 1
    result = events[0]["result"]
    assert result["status"] == "failure"
    assert result["http_status"] == 409
    assert result["error_code"] == "framework.CONFLICT"


async def test_audited_write_audits_app_error_with_precise_code(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # 对照分支：AppError 走精确业务码 + 真实 status_code（证两条 except 分支都守门、不互相吞）。
    async def _boom() -> object:
        raise AppError(code="role.NOT_FOUND", title="x", status_code=404)

    user = CurrentUser(user_id="1", sub="1")
    with (
        caplog.at_level(logging.INFO, logger="admin_platform.audit"),
        pytest.raises(AppError),
    ):
        await audited_write(user, "system:role:edit", "role", coro=_boom(), target_id=9)
    events = _rbac_events(caplog)
    assert len(events) == 1
    assert events[0]["result"]["error_code"] == "role.NOT_FOUND"
    assert events[0]["result"]["http_status"] == 404


async def test_audited_write_success_emits_success_audit(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # 成功路径：emit success + 从返回资源取 id/display。
    class _Created:
        id = 7
        code = "r-new"

    async def _ok() -> _Created:
        return _Created()

    user = CurrentUser(user_id="1", sub="1")
    with caplog.at_level(logging.INFO, logger="admin_platform.audit"):
        result = await audited_write(
            user,
            "system:role:add",
            "role",
            coro=_ok(),
            display=lambda r: r.code,
            success_status=201,
        )
    assert result.id == 7
    events = _rbac_events(caplog)
    assert len(events) == 1
    assert events[0]["result"]["status"] == "success"
    assert events[0]["result"]["http_status"] == 201
    assert events[0]["target"]["id"] == "7"
    assert events[0]["target"]["display"] == "r-new"
