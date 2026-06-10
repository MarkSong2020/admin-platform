"""定时任务 DTO — scheduled_tasks API 的请求 / 响应形状。

**安全（P4c §3）**：create/update **只接受 ``handler_key`` + ``params``**，无 ``call_target`` /
``python_path`` / ``command`` / ``shell`` / ``module`` 等任意调用目标字段——schema 层即封死 RCE 面。
cron / handler_key / params 的语义校验在 service（需 registry + 时区），schema 只做结构与长度。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

TaskStatus = Literal["enabled", "disabled"]
TriggerType = Literal["schedule", "manual"]
LogStatus = Literal["waiting", "running", "success", "failure", "misfire", "skipped"]


class HandlerInfo(BaseModel):
    """registry 中一个可选 handler（供前端下拉，管理员只能从中选）。"""

    key: str
    display_name: str
    allow_manual: bool


class ScheduledTaskCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    handler_key: str = Field(min_length=1, max_length=128)
    params: dict[str, Any] = Field(default_factory=dict)
    cron_expression: str = Field(min_length=1, max_length=128)
    cron_timezone: str = Field(default="Asia/Shanghai", max_length=64)
    status: TaskStatus = "disabled"
    allow_concurrent: bool = False
    # le=86400（H3 对抗审查）：misfire_grace 进 scheduled_tick_at 的 lookback，无上限时 admin 设
    # 超大值 + 每分钟 cron 会让 claim 在行锁内 O(lookback/period) 迭代（秒级 CPU 持锁）→ 特权 DoS。
    misfire_grace_seconds: int = Field(default=300, ge=0, le=86400)
    # M3：timeout 上限 1 天（原无上限）——manual 手动触发的请求事务会跨 handler 全程开着（executor
    # 的 handler 在事务外跑，但外层 manual_run 请求事务仍持连接），无界 timeout → 长任务长持 DB
    # 连接可耗尽池。上限收敛占用窗口；彻底异步化（202 + 轮询）留排期。
    timeout_seconds: int | None = Field(default=None, ge=1, le=86400)
    remark: str | None = Field(default=None, max_length=255)


class ScheduledTaskUpdate(BaseModel):
    """PATCH：全可选。handler_key/params/cron 任一变更都会在 service 重新校验。"""

    name: str | None = Field(default=None, min_length=1, max_length=128)
    handler_key: str | None = Field(default=None, min_length=1, max_length=128)
    params: dict[str, Any] | None = None
    cron_expression: str | None = Field(default=None, min_length=1, max_length=128)
    cron_timezone: str | None = Field(default=None, max_length=64)
    status: TaskStatus | None = None
    allow_concurrent: bool | None = None
    misfire_grace_seconds: int | None = Field(default=None, ge=0, le=86400)
    timeout_seconds: int | None = Field(default=None, ge=1, le=86400)
    remark: str | None = Field(default=None, max_length=255)


class ScheduledTaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    handler_key: str
    params_json: dict[str, Any]
    cron_expression: str
    cron_timezone: str
    status: TaskStatus
    allow_concurrent: bool
    misfire_grace_seconds: int
    timeout_seconds: int | None
    last_run_at: datetime | None
    last_status: str | None
    remark: str | None
    next_run_at: datetime | None = None  # service 按 cron 计算填充（非存储列）
    created_at: datetime
    updated_at: datetime


class ScheduledTaskPage(BaseModel):
    items: list[ScheduledTaskRead]
    page: int
    size: int
    total: int
    total_pages: int


class ScheduledTaskLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int | None
    execution_id: uuid.UUID  # JSON 序列化为字符串
    trigger_type: TriggerType
    scheduled_at: datetime | None
    handler_key: str
    params_json: dict[str, Any]
    status: LogStatus
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None
    error_code: str | None
    error_message: str | None
    result_summary: str | None
    worker_id: str | None
    actor_user_id: int | None
    created_at: datetime


class ScheduledTaskLogPage(BaseModel):
    items: list[ScheduledTaskLogRead]
    page: int
    size: int
    total: int
    total_pages: int
