"""DB-free 确定性导出 OpenAPI schema，供前端 codegen 稳定输入。

设计（spec §3.1/§7/§9）：
- 不读本地 .env：用固定 contract profile 覆盖影响 schema 的 APP_*。
- 清空 get_settings 的 lru_cache，避免缓存的本地配置污染。
- 不连 DB / 不起服务：仅调 create_app().openapi()。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from admin_platform.core.config import get_settings
from admin_platform.main import create_app

# 固定 contract profile：只放影响 OpenAPI schema 的键，值是契约规范值（非本地环境）。
_CONTRACT_ENV: dict[str, str] = {
    "APP_NAME": "admin-platform",
    # Environment 是 Literal["local","dev","staging","production"]（core/config.py:21），无 "test"。
    "APP_ENVIRONMENT": "local",
    # 其余影响 OpenAPI 的 APP_*（如 auth_public_paths）保持后端默认，不从 .env 注入。
}


def build_contract_openapi() -> dict[str, Any]:
    """在固定 contract profile 下生成 OpenAPI schema（确定性、DB-free、不读本地 .env）。"""
    # 1. 移除所有 APP_* 环境变量 + 记录原 cwd。
    saved = {k: v for k, v in os.environ.items() if k.startswith("APP_")}
    for k in saved:
        del os.environ[k]
    original_cwd = os.getcwd()
    try:
        # 2. 注入固定 contract profile。
        os.environ.update(_CONTRACT_ENV)
        # 3. chdir 到无 .env 的临时目录——Settings 的 env_file=".env" 是相对 cwd 解析
        #    （core/config.py:57），切走后读不到本地 .env，schema 不被本地配置污染。
        with tempfile.TemporaryDirectory() as tmp:
            os.chdir(tmp)
            get_settings.cache_clear()
            schema = create_app().openapi()
            get_settings.cache_clear()
        return schema
    finally:
        # 4. 还原 cwd 与环境，避免影响同进程其它测试。
        os.chdir(original_cwd)
        for k in list(os.environ):
            if k.startswith("APP_"):
                del os.environ[k]
        os.environ.update(saved)
        get_settings.cache_clear()


def main() -> None:
    parser = argparse.ArgumentParser(description="导出确定性 OpenAPI schema")
    parser.add_argument(
        "--output",
        default="frontend/openapi/admin-platform.json",
        help="输出路径（相对仓库根）",
    )
    args = parser.parse_args()
    schema = build_contract_openapi()
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    sys.stdout.write(
        f"OpenAPI 已导出 → {out}\n"
    )  # 用 stdout.write 而非 print（仓库 ruff 启用 T20）


if __name__ == "__main__":
    main()
