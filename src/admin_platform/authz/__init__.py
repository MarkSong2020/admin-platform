"""authz —— RBAC 横切基础设施包（数据权限 / 权限校验的被依赖方）。

本包是 RBAC 机制的横切底座，只提供纯类型与不依赖业务的基础设施，
故**不 import** ``domains`` 或 ``core``，避免循环依赖（见 spec §4 data_scope）。
"""
