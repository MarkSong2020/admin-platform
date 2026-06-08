"""Post repository —— SQLAlchemy 2.x async 数据访问层。返回 ORM 行 / None / 集合，不抛业务异常。

除标准 CRUD 外，承载岗位绑定查询与写（镜像 role 域 ``user_roles``，岗位无 data_scope 故更简单）：
  * ``list_posts_for_user`` —— JOIN ``user_posts`` 取用户的全部岗位。
  * ``set_user_posts`` —— 全量替换绑定（先取 advisory lock 再先删后插，幂等）。
"""

from __future__ import annotations

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from admin_platform.domains.post.models import Post, UserPost
from admin_platform.domains.post.schemas import PostCreate, PostUpdate

# pg_advisory_xact_lock 的稳定 key —— 串行化 user_posts「先删后插」的全量替换（镜像 role 域
# F3 修复）：并发两请求替换同一目标时，避免最终落成两请求的并集 / 撞 uq_user_posts。事务级锁，
# 提交/回滚自动释放。取与 dept(478221) / role(478231-2) / menu(478241-2) 不同的值避免跨域互锁。
_USER_POSTS_LOCK_KEY = 478251  # 串行化 user_posts 替换


class PostRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_paginated(self, page: int, size: int) -> list[Post]:
        offset = (page - 1) * size
        stmt = select(Post).offset(offset).limit(size).order_by(Post.sort_order, Post.id)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def count(self) -> int:
        result = await self._session.execute(select(func.count()).select_from(Post))
        return int(result.scalar_one())

    async def get(self, item_id: int) -> Post | None:
        return await self._session.get(Post, item_id)

    async def find_by_code(self, code: str) -> Post | None:
        """按 code 查找（唯一性预检用）。"""
        result = await self._session.execute(select(Post).where(Post.code == code).limit(1))
        return result.scalar_one_or_none()

    async def create(self, payload: PostCreate) -> Post:
        obj = Post(**payload.model_dump())
        self._session.add(obj)
        await self._session.flush()
        return obj

    async def update(self, item_id: int, payload: PostUpdate) -> Post | None:
        obj = await self._session.get(Post, item_id)
        if obj is None:
            return None
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(obj, key, value)
        await self._session.flush()
        # onupdate=func.now() 让 updated_at 在 UPDATE 后过期；异步 session 下后续序列化
        # （PostRead 含时间戳）访问过期列会触发隐式刷新报错（Errata #7）。显式 refresh 取回新值。
        await self._session.refresh(obj)
        return obj

    async def delete(self, item_id: int) -> bool:
        obj = await self._session.get(Post, item_id)
        if obj is None:
            return False
        await self._session.delete(obj)
        return True

    # ---- 岗位绑定查询 / 写（全量替换，先删后插）-------------------------------

    async def list_posts_for_user(self, user_id: int) -> list[Post]:
        """用户拥有的岗位（JOIN ``user_posts``）。"""
        stmt = (
            select(Post)
            .join(UserPost, UserPost.post_id == Post.id)
            .where(UserPost.user_id == user_id)
            .order_by(Post.id)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def set_user_posts(self, user_id: int, post_ids: list[int]) -> None:
        """全量替换用户的岗位绑定（去重；空列表 = 解绑所有岗位）。

        先取事务级 advisory lock 串行化「先删后插」（镜像 role 域 F3 修复）：并发两请求替换
        同一/不同用户的绑定时，避免最终落成两请求的并集或撞 ``uq_user_posts``。提交/回滚
        自动释放锁。
        """
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(:k)").bindparams(k=_USER_POSTS_LOCK_KEY)
        )
        await self._session.execute(delete(UserPost).where(UserPost.user_id == user_id))
        await self._session.flush()
        for post_id in dict.fromkeys(post_ids):
            self._session.add(UserPost(user_id=user_id, post_id=post_id))
        await self._session.flush()
