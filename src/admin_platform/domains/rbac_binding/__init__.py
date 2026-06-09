"""RBAC 绑定子资源域 —— 跨域组合（无独立 model，复用 role/menu/post/user/dept repository）。

补 P1 缺口（2026-06-09 review 🔴）：绑定 repository 方法齐全但无 service/API 出口 →
管理端不可配 RBAC。本域只长 schemas / service / deps / api 四件，绑定写复用既有 ``set_*``。
"""
