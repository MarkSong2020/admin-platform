"""一次性管理 CLI —— 创建超级管理员（信任根）。

用法::

    ADMIN_BOOTSTRAP_PASSWORD='<强口令>' \\
        uv run python -m admin_platform.cli create-super-admin --username root

安全设计（经 Codex 安全 PK 收紧）：

  * **密码只从 env ``ADMIN_BOOTSTRAP_PASSWORD`` 读**（不进 argv，规避 ``ps`` / shell history 暴露）；
    未设置 / 含首尾空白 / 长度 < 12 / 等于 username → 报错退出，**绝不写默认口令**。
  * **一次性信任根**：只要已存在**任意**超管（``is_super_admin=True``）就拒绝——不只是拒绝同名，
    避免本 CLI 变成可重复铸造最高权限账号的口子（Codex PK）。
  * **并发防御**：建超管在单事务内，靠 ``uq_users_username`` 让一个创建者胜出；中途失败回滚。
  * **不泄密**：stderr / ``CliError`` / 成功输出都不含密码或 hash；非预期异常只打类型名。

> 残留 follow-up（未做）：要在 DB 层硬保证"至多一个超管"，需 partial unique index
> ``WHERE is_super_admin``（迁移）；本任务范围内用应用层检查兜底。P1 RBAC 落地后超管由
> 「超级管理员角色」接管，该检查再评估去留。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from admin_platform.core.security import hash_password
from admin_platform.db.engine import dispose_engine
from admin_platform.db.session import db_session
from admin_platform.domains.user.models import User

_ACTIVE = "active"
_MIN_PASSWORD_LEN = 12
_MAX_USERNAME_LEN = 64
_PASSWORD_ENV = "ADMIN_BOOTSTRAP_PASSWORD"  # noqa: S105


class CliError(Exception):
    """CLI 可预期的失败（消息直接给用户，绝不含密码）。"""


def _validate_username(username: str) -> str:
    if username != username.strip() or not username:
        raise CliError("username 不能为空或含首尾空白")
    if len(username) > _MAX_USERNAME_LEN:
        raise CliError(f"username 超过 {_MAX_USERNAME_LEN} 字符")
    if not username.isprintable() or any(ch.isspace() for ch in username):
        raise CliError("username 含不可打印或空白字符")
    return username


def _read_password(username: str) -> str:
    password = os.environ.get(_PASSWORD_ENV, "")
    if not password or password != password.strip():
        raise CliError(f"{_PASSWORD_ENV} 未设置或含首尾空白；拒绝用默认口令创建超管")
    if len(password) < _MIN_PASSWORD_LEN:
        raise CliError(f"{_PASSWORD_ENV} 长度需 ≥ {_MIN_PASSWORD_LEN}")
    if password == username:
        raise CliError("密码不能与 username 相同")
    return password


async def _create(username: str, password: str) -> int:
    """单事务内：拒绝已有任意超管 → 建超管。返回新 user id。"""
    async with db_session() as session:
        existing_admin = (
            await session.execute(select(User).where(User.is_super_admin.is_(True)).limit(1))
        ).scalar_one_or_none()
        if existing_admin is not None:
            raise CliError("超级管理员已存在，拒绝重复创建（一次性 bootstrap，不覆盖）")

        user = User(
            username=username,
            password_hash=hash_password(password),
            status=_ACTIVE,
            is_super_admin=True,
        )
        session.add(user)
        try:
            await session.flush()
        except IntegrityError as exc:
            # 撞唯一约束（并发竞态）—— 脱敏后抛 CliError，不把含 hash 的裸 traceback 给用户。
            raise CliError("创建超管时撞唯一约束（可能并发），未创建") from exc
        return user.id


async def create_super_admin(username: str) -> int:
    """校验 username/password → 创建超级管理员，返回 user id。可预期失败抛 ``CliError``。"""
    username = _validate_username(username)
    password = _read_password(username)
    return await _create(username, password)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="admin_platform.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)
    create_parser = subparsers.add_parser(
        "create-super-admin", help="创建超级管理员（密码从 ADMIN_BOOTSTRAP_PASSWORD 读）"
    )
    create_parser.add_argument("--username", required=True)
    args = parser.parse_args(argv)

    if args.command == "create-super-admin":
        try:
            user_id = asyncio.run(_run_create(args.username))
        except CliError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        except Exception as exc:
            # 只打异常类型名，不打 str/traceback —— 避免任何含 hash 的细节进 stderr。
            print(f"error: 创建失败（{type(exc).__name__}）", file=sys.stderr)
            return 1
        print(f"created super admin: id={user_id} username={args.username}")
        return 0
    return 2  # 不可达：argparse required=True 已挡住无子命令


async def _run_create(username: str) -> int:
    """main 的 async 包装：创建后释放 engine（CLI 进程一次性使用）。"""
    try:
        return await create_super_admin(username)
    finally:
        await dispose_engine()


if __name__ == "__main__":
    raise SystemExit(main())
