# P5 系统工具 — 文件管理 + Excel 导入导出 spec

> 2026-06-11 立。Codex PK（medium）+ 用户拍板范围（AskUserQuestion 2026-06-11）收敛。
> 对标 RuoYi `sys_oss`（文件/对象存储管理）+ RuoYi Excel 导入导出。

## 0. 范围决策：AI 时代砍掉「代码生成器」

P5「系统工具」原路线含三件：① 代码生成 ② Excel 导入导出 ③ 文件上传。**经用户拍板重新圈定**：

| 项 | 决策 | 理由 |
|---|---|---|
| **RuoYi 在线 codegen**（后台页面选表生成代码） | **砍** | AI 时代过时——coding agent（Claude Code）直接读表生成五层 CRUD + 测试 + 迁移 + doc，比 velocity 模板灵活且带工程纪律。Codex PK 亦反对在线 codegen |
| **introspection 逆向辅助**（读已有表→manifest→生成） | **砍** | 单租户 admin 是绿地项目，表都自建（有 spec + migration），无遗留表逆向场景 |
| **`make new-module` CLI 脚手架** | **保留** | 它**不是** RuoYi codegen，是 agent 生成时的「确定性护栏」（五层结构 / import-linter / schema-doc / column-comment 自动注册）；AI 时代防结构漂移反而更有用。CLAUDE.md「新模块必走 make new-module」规则不变 |
| **文件上传**（本 spec §1-§6） | **做**（第一件，零新依赖） | 运行期系统能力，AI 不替代。local fs + 可插拔 `StorageBackend`，可逆默认 |
| **Excel 导入导出**（本 spec §7） | **做**（第二件，需依赖授权） | 运行期业务能力。需引 `openpyxl`/`xlsxwriter`（codex-pk 新依赖红线，待用户单独授权） |

**洞察**：「对标 RuoYi」要分清**时代产物**（codegen，无 coding agent 时代的减负工具）vs **永恒后台刚需**（RBAC/审计/字典/参数/监控/任务/文件/导入导出/前端）。只有 codegen 是前者。

---

## 1. 文件管理目标与非目标

**目标（v1）**：上传 / 流式下载 / 列表分页 / 元数据查询 / 删除（软删元数据 + 物理删文件）。本地文件系统存储，存储抽象 `StorageBackend` 可插拔（未来接 S3 不改业务层）。

**非目标（排期，不在 v1）**：
- 对象存储（S3/OSS）后端实现 —— 接口先稳定，实现后置
- 公开分享 URL / 签名 URL —— v1 下载一律走鉴权端点
- 大文件分片 / 断点续传 —— v1 单次同步上传，size 上限兜底
- 文件版本管理 / 去重引用计数 —— sha256 仅作完整性校验，不做去重共享 blob
- 图片缩略图 / 转码 —— 业务上层关注，不在文件域
- 病毒扫描 —— 需外部引擎，排期

**对抗审查（Codex 二审 + adversarial agent）确认的排期项**（v1 已修 P1 数据丢失/header 注入/XSS nosniff/孤儿清理；下列高成本或低风险项后置）：
- **Orphan sweeper**：upload 在 `repo.create` flush 后、请求 commit **前**的窗口若 commit 失败，物理文件已写但 DB 无记录 → 孤儿（delete 侧已用 commit 后 BackgroundTasks 规避）。需定期对账 GC（扫 storage root vs files 表）兜底两侧残窗。
- **ASGI body 上限**：multipart 经 `SpooledTemporaryFile` 落 temp 盘**后** service 才校验 size；starlette `max_part_size` 对 file part 豁免、无全局 body limit → 磁盘/inode 耗尽放大面（单租户内部低风险）。需 ASGI body-size 中间件按 Content-Length 提前 413。
- **下载/删除 TOCTOU**：`prepare_download` 的 stat 与惰性 `aiter_chunks` open 间并发 delete → 裸 `FileNotFoundError` 断流（200+headers 已发，罕见竞态）。需 open 前持 fd 或优雅断流。
- **content-type 白名单 + 按扩展名映射安全 MIME**：v1 仅扩展名+魔数双校验，content_type 客户端可控仅落库（下载靠 attachment+nosniff 兜 XSS）。
- **OOXML 深度结构校验**：xlsx/docx 仅认 `PK\x03\x04`，不验 `[Content_Types].xml`。
- **下载审计**：敏感文件「谁下载」取证链（写操作已审计）。

---

## 2. 存储抽象（`domains/file/storage.py`，零新依赖）

```
StoredStat(dataclass): size_bytes: int, sha256: str
StorageBackend(ABC):
    async def write_stream(object_key, chunks: AsyncIterator[bytes], *, max_bytes) -> StoredStat
        # 边写边累计 size + sha256；超 max_bytes 抛 FileSizeExceeded 并清理半成品
    def aiter_chunks(object_key, *, chunk_size) -> AsyncIterator[bytes]   # 流式下载（async）
    async def delete(object_key) -> bool
    async def stat(object_key) -> int | None   # 物理字节数；None=不存在（检测元数据指向丢失）
LocalFileStorage(StorageBackend):
    root: Path（config.file_storage_root，resolve 成绝对）
    # object_key = uuid4().hex；分桶 root/<key[:2]>/<key[2:4]>/<key> 避免单目录爆炸
    # 路径守卫：拼接后 resolve() 必须仍在 root 内（防 ../ 穿越）—— 否则 raise StoragePathError
```

阻塞文件 I/O 用 `anyio.to_thread.run_sync` 包装，不阻塞事件循环（PK 风险4：大文件拖垮 worker）。

---

## 3. 数据模型（`files` 表，migration 0019，gated 本地+CI）

| 列 | 类型 | 说明 |
|---|---|---|
| id | BigInteger PK | IdMixin |
| object_key | String(64) unique | 存储对象键（uuid4 hex），**不含原文件名**（防穿越/覆盖） |
| storage_backend | String(32) | "local"（未来 "s3"） |
| original_filename | String(255) | 原始文件名，仅展示/下载用，**不信任** |
| content_type | String(128) | 声明 MIME（校验后落库） |
| size_bytes | BigInteger | 实际写入字节数（边读边累计，非 Content-Length） |
| sha256 | String(64) | 内容哈希（完整性校验，非去重） |
| uploader_id | BigInteger FK users.id RESTRICT | 上传者 |
| status | String(16) | active / deleted |
| deleted_at | DateTime(tz) NULL | 软删时间（NULL=未删） |
| created_at / updated_at | DateTime(tz) | TimestampMixin |

索引：`uq_files_object_key`(unique) / `ix_files_sha256` / `ix_files_uploader_id` / `ix_files_status_created`(status, created_at)。

**软删语义**：删除 = `status='deleted'` + `deleted_at=now()`，物理删**延后到请求事务 commit 成功后**经 BackgroundTasks 执行（commit 失败 → 不删 → DB 回滚 active 与物理一致，避免「commit 前不可逆 unlink」数据丢失，对抗审查 P1）。元数据保留供审计追溯；物理内容不可恢复（v1 不做回收站）。下载/查询已删 → 404。`object_key` 为内部存储寻址键，**不进 FileRead 响应**（最小暴露，未来接签名 URL 时不外泄实现细节，Codex 二审）。

---

## 4. 端点契约（`/api/v1/files`）

| 方法 | 路径 | 权限点 | 审计 | 说明 |
|---|---|---|---|---|
| POST | `/files` | system:file:upload | ✓ | multipart/form-data，UploadFile；201 → FileRead |
| GET | `/files` | system:file:list | — | 分页，仅 status=active |
| GET | `/files/{id}` | system:file:query | — | 元数据 FileRead |
| GET | `/files/{id}/download` | system:file:download | —（排期） | StreamingResponse + Content-Disposition（RFC 5987，剥 CRLF/引号）+ `X-Content-Type-Options: nosniff` |
| DELETE | `/files/{id}` | system:file:remove | ✓ | 204；软删元数据 + **commit 后** BackgroundTasks 物理删 |

上传**不挂** `@idempotent`（multipart body 哈希对大文件昂贵且为流；RuoYi 上传亦不幂等）。

权限点（authz/permissions.py 声明 + seed 菜单 + 路由使用三处一致）：
`system:file:{list,query,upload,download,remove}`。菜单块手写（非 `_resource_menu` 标准五件，对标 RuoYi OSS 的 upload/download）。

---

## 5. 安全模型（defense-in-depth，PK 风险5/6 收敛）

| 层 | 校验 | 失败 |
|---|---|---|
| **L1 入口** | 原文件名扩展名 ∈ 白名单 | 415 file.EXTENSION_NOT_ALLOWED |
| | ⏳ Content-Length 预检 / content-type 白名单 —— **v1 未实现**（size 仅靠 L2 流式累计兜底；content-type 仅落库不校验），见 §1 非目标 | — |
| **L2 业务** | 边读边累计 size（防伪造 Content-Length）→ 超 max 中止 + 清理半成品 | 413 file.SIZE_EXCEEDED |
| | 魔数头**弱类型校验**（首字节签名匹配扩展名；**非**内容深度扫描——xlsx/docx/zip 共享 `PK\x03\x04` 不区分 OOXML 真伪；txt/csv 纯文本豁免） | 415 file.CONTENT_TYPE_MISMATCH |
| | 空文件拒绝 | 422 file.EMPTY_FILE |
| | object_key = uuid4（不信任原文件名） | — |
| **L3 存储守卫** | 拼接路径 resolve() 必须在 root 内 | 500 StoragePathError（内部不可达，纵深兜底） |
| **L4 审计** | **上传/删除**经 audited_write 记 audit_event（下载审计排期，见 §1） | — |

魔数白名单（标准库，**不引 python-magic**）：PDF `%PDF` / PNG `\x89PNG` / JPEG `\xff\xd8\xff` / GIF `GIF8` / ZIP系(xlsx/docx/zip) `PK\x03\x04`。无签名纯文本类（txt/csv/log）跳过魔数校验，仅扩展名+content-type。

---

## 6. config 新增（core/config.py）

```
file_storage_backend: str = "local"                              # 未来 "s3"
file_storage_root: str = "var/uploads"                           # 相对 CWD，storage resolve 绝对
file_max_upload_size_bytes: int = Field(default=52428800, ge=1024, le=5368709120)  # 50MB / 1KB..5GB
file_allowed_extensions: list[str] = Field(default=[...])        # 白名单（小写无点）
```

---

## 7. Excel 导入导出（第二件，⚠️ 待依赖授权）

**待用户授权新依赖后实现**：`openpyxl`（read-only/write-only 近常量内存流式）+ `xlsxwriter`。**不用** pandas/polars 作核心（PK：后台导入需逐行错误/字段校验/事务批次，openpyxl 更贴 workbook 原语）。

设计要点（PK 风险3「类型漂移」收敛）：
- 仅支持 `.xlsx`（CSV 另开轻量路径，排期）
- 导入：openpyxl read-only → Pydantic 逐行校验 → 全量错误报告（sheet/row/column/code/message）→ 确认后批量写入
- 导出：write-only 流式
- 往返一致验收：canonical row 相等（日期/前导零/空值 vs null/数字精度/布尔枚举一致）
- 单次上限：行数 + 文件大小；超限走后台任务（排期）

---

## 8. 实现顺序（分阶段，每阶段验证）

1. **阶段A 数据层**：permissions + config + models + migration 0019 + seed 菜单 → `make schema-doc` + 列 comment 门禁过
2. **阶段B 存储层**：storage.py（StorageBackend + LocalFileStorage）+ 单测（路径穿越/size 超限/sha256）
3. **阶段C 业务层**：schemas + repository + service（上传校验/下载/列表/软删）+ 单测（各校验分支）
4. **阶段D 接口层**：api（multipart/流式/审计）+ deps + main 挂载 + .importlinter C1 + api 测
5. **阶段E 集成+门禁**：集成测（真 fs+DB 往返）+ doc 同步 + `make check` 全绿
6. **阶段F 对抗审查 loop**：派怀疑论者 agent 逐项 refute → 收敛 → commit per cluster → PR → CI → merge
7. **阶段G Excel**（待依赖授权）

**红线**：migration 0019 仅本地 dev + CI 临时容器跑，生产/共享库迁移 gated（等用户安排）。
