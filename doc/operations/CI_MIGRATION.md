# CI 迁移指南：GitHub Actions reference → 业务团队 CI 平台

> 本仓真实 CI 平台**由各业务团队按 ADR Open Q11 决议**，目前未决。
> `.github/workflows/ci.yml` 是**可直接 fork 跑**的参考资产，业务团队
> 选定平台后照其 Makefile 调用方式抄过去即可（业务 logic 完全 portable）。

## 1. 现状

| 平台 | 用途 | 配置位置 |
|---|---|---|
| GitHub Actions | reference（可直接 fork 跑） | `.github/workflows/ci.yml` |
| 阿里云效 / Jenkins / GitLab CI | 各业务团队按 ADR Q11 自选 | 业务仓自管，**模板不放占位** |

**为什么不放 `.workflow/` / `Jenkinsfile` 占位**：模板里塞空文件会让真接入的
业务团队以为这是"建议的部署方式"，反而比"待建"更误导。reference 选 GitHub
Actions 是因为它的 yaml 表达力够、本地 act 可重放、PR 同仓审阅最方便——
不代表团队 CI 平台必须是它。

## 2. 业务 logic 完全 portable（依赖 Makefile，不依赖 CI 平台语法）

业务 CI 平台只要能跑 `make <target>` 就能用。**安全门必须阻塞**：

### Fast lane（每次 PR 必跑，全部阻塞）

1. checkout 代码
2. 装 uv（建议 pin `0.9.30`）
3. `uv python install 3.14`
4. `uv sync --all-extras --dev --frozen`
5. `make check`（ruff format + ruff check + pyright + pytest -m "not integration"）
6. **`make audit`**（uvx pip-audit `.`；**阻塞**，和本仓 [Makefile](../../Makefile) /
   [.github/workflows/ci.yml](../../.github/workflows/ci.yml) 行为一致；紧急例外见 §4）

### DB lane（主干 / pre-release 跑，全部阻塞）

1. 启 PostgreSQL 16-alpine 服务（端口 5432，DB/user/pass 都是 `app`）
2. 启 Redis 7-alpine 服务（端口 6379，integration 测试需要）
3. 同 fast lane 装 uv + sync
4. `APP_DATABASE_URL=postgresql+asyncpg://app:app@localhost:5432/app`
5. `APP_REDIS_URL=redis://localhost:6379/0`
6. `make migrate`（alembic upgrade head）
7. `make check-db`（alembic check 漂移检测 — Errata #3）
8. `make test-integration`（pytest -m integration）

### Generator lane（改 `scripts/new_module.py` 或模板时跑）

`make smoke-generator`（v0.4.16 新增）— 一键跑 `new-module name=smoke_probe with-model=1`
+ `make check` + cleanup，结构性守住"模板开箱即过 check"承诺。

## 3. 各 CI 平台迁移要点（按需挑一份）

模板**不指定**业务 CI 平台。下面是常见平台的 caveat，业务团队自己挑：

### 阿里云效（Yunxiao）

- **Python 3.14 支持**：✅ 已验证（2026-05-18，用户控制台核实）。runner 镜像 `docker.aliyuncs.com/yunxiao/<image>` 选 ubuntu/debian 系即可
- uv 安装：无官方 setup-uv，需 step 内 `curl -LsSf https://astral.sh/uv/install.sh | sh`
- PostgreSQL services：阿里云效"服务容器"语法与 GitHub Actions `services:` 不同，
  参考[官方文档](https://help.aliyun.com/document_detail/153834.html)
- 缓存：自己的 cache action，需显式 export `~/.cache/uv`
- 触发器：用 `triggers:` 段配置 PR / 主干 / 定时

### Jenkins

- 用 Declarative Pipeline；`agent { docker { image 'python:3.14-slim' } }`
- PostgreSQL / Redis 用 sidecar container 或 docker-compose plugin
- secrets 走 `withCredentials`，**不要**把 audit failure 用 `catchError(buildResult: 'SUCCESS')` 吞掉

### GitLab CI

- 直接抄 `.github/workflows/ci.yml` 改 `services:` 块语义，其它几乎一致

## 4. 紧急通道 — audit 例外

某条 CVE 待上游修而你必须发版时：

```bash
# Makefile audit target 接受额外参数（如需扩展）
uvx pip-audit . --ignore-vuln GHSA-XXXX-XXXX-XXXX --reason "upstream fix in v2.5.0; pinned downgrade"
```

**纪律**：
- `--ignore-vuln` 必须在 PR 描述里写清 owner + 解除时间
- 不允许整体 `continue-on-error` 降级（旧文档里写过这点，已删 — 不阻塞 = 没人看）
- 例外清单每周 review，无 owner / 过期 → 自动升 P0

## 5. 部署 stage（业务团队自管）

模板不展开。建议至少：

1. 拉取 commit hash 对应的镜像（`make docker-build` 后推到内部 registry）
2. 跑预部署冒烟（`/healthz` / `/readyz`）
3. 滚动发布
4. 失败回滚（保留前 N 版镜像，K8s rollout undo）

## 6. 双轨期约束

业务 CI 流水线落地前：

- PR 必须本地跑过 `make check` 才合入
- 团队负责人在合入时手动审查 changelog
- 关键 release 前手动跑 `make compose-up && make migrate && make test-integration && make check-db`

业务 CI 落地后此节由各业务团队删除。

## 7. 历史决策记录

- **v0.4.16** 重写：删除 `.workflow/` / `Jenkinsfile` "待建"占位描述（占位空文件比缺更误导）；
  audit 口径从"continue-on-error 不阻塞"改成"阻塞 + `--ignore-vuln` 紧急通道"，
  和 Makefile / reference CI 一致；加 Redis service 进 DB lane 检查；加 generator
  lane（`make smoke-generator`）。
