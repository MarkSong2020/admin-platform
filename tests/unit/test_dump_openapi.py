"""dump_openapi 确定性契约：环境变量污染不得改变导出的 OpenAPI schema。"""

import json

from scripts.dump_openapi import build_contract_openapi


def test_openapi_is_deterministic_under_env_pollution(monkeypatch):
    """固定 contract profile 下，污染影响 schema 的 APP_* 不改变输出。"""
    clean = build_contract_openapi()

    monkeypatch.setenv("APP_NAME", "polluted-name")
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    monkeypatch.setenv("APP_AUTH_PUBLIC_PATHS", '["/totally/wrong"]')

    polluted = build_contract_openapi()

    assert polluted == clean, "OpenAPI 导出受 env 污染，确定性被破坏"


def test_openapi_has_expected_shape():
    """导出的 schema 含 openapi 版本与 paths，且为可 JSON 序列化的 dict。"""
    schema = build_contract_openapi()
    assert schema["openapi"].startswith("3.")
    assert "/api/v1/auth/login" in schema["paths"]
    json.dumps(schema)  # 不抛即 OK


def test_openapi_ignores_local_dotenv(tmp_path, monkeypatch):
    """cwd 存在污染的 .env 时，schema 仍确定（build 内部 chdir 绕过本地 .env）。"""
    clean = build_contract_openapi()
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text('APP_AUTH_PUBLIC_PATHS=["/polluted"]\n', encoding="utf-8")
    assert build_contract_openapi() == clean, ".env 文件污染了 OpenAPI schema"
