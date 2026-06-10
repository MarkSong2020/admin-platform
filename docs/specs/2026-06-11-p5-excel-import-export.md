# P5 系统工具 — Excel 导入导出 spec

> 2026-06-11 立。P5 第二件（文件管理见 `2026-06-11-p5-file-management.md`）。
> Codex PK（medium）+ Explore agent 两来源印证 + 一处 push back 收敛。已授权依赖 **openpyxl**（不引 xlsxwriter/pandas/polars）。

## 0. 决策收敛（两来源印证 + push back）

| 决策 | 结论 | 来源 |
|---|---|---|
| 通用机制放哪 | **`admin_platform/excel/` 顶层叶子模块**（不碰 core 红线）+ import-linter **C10**（excel 禁 import fastapi/sqlalchemy/domains/core，纯 stdlib/openpyxl/pydantic） | Codex + Explore 一致 |
| 第一版实体 | **post**（name/code/sort_order/status + code 唯一；避开 user 密码/scope、dict FK/单默认复杂度） | Codex + Explore 一致 |
| 机制形态 | **无状态**：不返回 StreamingResponse / 不拿 AsyncSession / 不抛 HTTPException | Codex |
| **导入语义** | **一步全有全无 + 全量错误报告**（⚠️ push back Codex 的两步暂存） | Claude 裁决 |
| 导入策略 | 只新增（code 已存在报错，非 upsert） | Codex |
| 导出范围 | 筛选后全量 + 最大行数上限（超限 422，后台任务排期） | Codex |
| 类型漂移防御 | canonical 文本化（"001" 不被读成 1；空串 vs null；导出 code 列文本格式） | Codex 风险4 |

**push back 导入语义的理由**（不采纳 Codex 的两步 preview→commit + import_token 暂存）：
1. 一步全有全无**同样避免部分写入**（Codex 反 RuoYi「部分成功」的核心关切）+ **同样全量错误报告**。
2. 两步的暂存基建（import_token / TTL / SHA256 / 越权 / 重复提交 / 磁盘）是显著复杂度——Codex 自己列为风险 3。
3. 第一版「最小可用」；两步预览确认是体验优化，**排期**。
4. 导入语义非不可逆架构（可后续从一步加两步），可自裁不升级。

## 1. 目标与非目标

**目标（v1）**：post 岗位的 `.xlsx` 导入（一步全有全无）+ 导出（全量+上限）。通用 `excel/` 机制 schema 驱动，可复用到其它实体。往返一致（导出再导入 canonical row 相等）。

**非目标（排期）**：
- 两步预览确认（preview→commit + 暂存）—— 体验优化
- upsert（按 code 覆盖）—— 引入覆盖审计/回滚成本
- user / dict 扩展 —— 复杂度递增（密码/scope / FK/单默认）
- CSV 路径 / 大文件后台任务 / xlsxwriter 写优化
- 模板下载端点（应预设文本格式列防前导零漂移）

**对抗审查（Codex 二审 + adversarial agent 两来源印证）排期项**（v1 已修 **P0** formula injection / import size 上限 + 非法 xlsx 捕获，**P1** 审计计数标注 / sort_order 越界约束）：
- **zip bomb 深度防御**：v1 限上传 size + 行数，但 openpyxl 无内建「解压总量/单 cell 长度」上限，小压缩比文件仍可放大（PostCreate max_length=64 在已读入内存后才 reject）。需 reader 累计解压字节阈值。
- **canonical 前导零漂移**：数字格式 code 列 `007`→`7` 不可逆（openpyxl 先按格式读类型）。需导入模板预设文本格式列 + 可选「文本列拒绝 numeric cell」。
- 通用 `ExcelExporter` 列级 opt-out formula 转义（当前默认全开）。

**R2–R5 多轮对抗审查 loop 已修**（2026-06-11，全程绿：make check 630 单测 + integration 208 + check-db 无漂移）：
- **R5 存储型控制字符 DoS**（adversarial agent 实跑复现）：`PostCreate.name/code` 无字符集约束，含 openpyxl 非法控制字符（0x00-08/0b-0c/0e-1f）的岗位进库后让 `GET /posts/export` 整表导出抛 `IllegalCharacterError` → 对全体永久 500（低权限「岗位新增」用户投毒一行即可）。修：`excel/writer._canonical` 剥除（结构性兜底，让导出不可能因非法字符失败）+ `PostCreate/Update` L1 `CleanText` 拒绝，defense-in-depth 两层。
- **R5 skeptic 扩面 U+FFFE/U+FFFF 非字符**：能过控制字符正则但生成损坏 .xlsx（XML 1.0 Char 上限 U+FFFD）/ 让 import 对上传者 500。修：writer 剥除（codepoint 表）+ L1 拒绝同源闭合。
- **R5 reader 迭代期异常兜底**：`except` 此前只包 `load_workbook`，`iter_rows` 期间 ParseError（如含 U+FFFE 的文件）漏成 500，与 docstring 声称不符。修：扩 `except` 到行迭代（抽 `_parse_rows` helper 降 PLR0912 复杂度），转 INVALID_FILE。
- **R4 reader 回退守护测试**：valid-zip-non-xlsx（openpyxl 抛 KeyError 非 BadZipFile）测试锁住宽 `except` 不被收窄回退而退化 500。
- **R2 formula `\n` + export 审计**：formula 触发集补 `\n` 开头；导出补 `audited_write`（数据外泄取证点）+ 集成 caplog 断言 import/export 各 emit 一条成功审计。

## 2. 通用机制 `admin_platform/excel/`（无状态，零 domain 知识）

```
excel/schemas.py:
  ExcelColumn(field, header, required=True)        # 列定义（Pydantic 字段↔Excel 列头）
  ImportError(row, column, code, message)          # 行级错误（row=1-based 含表头）
  ImportResult[T](rows: list[T], errors: list[ImportError])
excel/reader.py:
  ExcelImporter(schema: type[BaseModel], columns, *, max_rows):
    parse(content: bytes) -> ImportResult     # openpyxl read-only 流式 → 表头映射 →
      # 逐行 canonical 文本化（cell→str，None→""）→ Pydantic 校验 → 坏行不阻断全量收集错误
excel/writer.py:
  ExcelExporter(columns):
    write(rows: Iterable[Mapping]) -> bytes   # openpyxl write-only 流式 → 表头 + 行
```

**C10 契约**（`.importlinter`）：`admin_platform.excel` 禁 import `fastapi` / `sqlalchemy` / `admin_platform.domains` / `admin_platform.core` —— 纯叶子机制（类似 authz 的 C8）。

## 3. post 适配（`domains/post/excel.py`）

```
POST_COLUMNS = [
  ExcelColumn("name", "岗位名称"), ExcelColumn("code", "岗位编码"),
  ExcelColumn("sort_order", "显示顺序", required=False),
  ExcelColumn("status", "状态", required=False),
]
PostExcelRow(BaseModel):  # 导入行 schema（canonical str 输入，Pydantic coerce）
  name: str (1..64); code: str (1..64)
  sort_order: int = 0; status: Literal["active","disabled"] = "active"
```

## 4. 端点（`/api/v1/posts`）+ 权限

| 方法 | 路径 | 权限 | 审计 | 语义 |
|---|---|---|---|---|
| POST | `/posts/import` | system:post:import | ✓ | multipart xlsx（≤`excel_max_upload_size` 流式校验，超限 413）；**一步全有全无**：全量校验通过→单事务批量写入；行级错误→imported=0 + **不写任何行**，**200** + `PostImportSummary{imported, errors}`（业务结果，errors 始终可见，不走 ProblemDetail 脱敏）。**例外**（对抗审查）：并发撞 `uq_posts_code` 竞态→409 `post.CODE_DUPLICATE`（非 200，DB 兜底防部分写）；非法 xlsx→`INVALID_FILE`（200 errors）；超大→413 |
| GET | `/posts/export` | system:post:export | ✓（R2 补） | 全量（上限 file_excel_max_rows）→ xlsx 流；超限 422。导出是数据外泄取证点，`audited_write` 记「谁导出多少字节」 |

新增权限点 `system:post:{import,export}`（authz/permissions.py + seed post 菜单按钮 + 三集一致测试）。

## 5. 校验（全量聚合，写入前）

导入校验顺序（全量收集，不短路）：
1. **Pydantic 逐行**（必填/长度/status 枚举/sort_order 整数）→ ImportError
2. **文件内 code 重复**（跨行）→ DUPLICATE_IN_FILE
3. **库内 code 重复**（`repo.list_existing_codes`）→ DB_DUPLICATE
4. 全部通过 → `repo.bulk_create` 单事务；否则 imported=0 + errors 全量（**200 + PostImportSummary**，非 422——导入校验错误是业务结果，errors 不受 ProblemDetail debug 脱敏，生产可见）

**类型漂移防御**：reader canonical 把 cell.value 一律 `str` 化（去首尾空白），空 cell→""（让 Pydantic 必填校验捕获，非静默 null）。导出时 code 列写文本（防 Excel 数字格式丢前导零）。

## 6. 实现顺序（分阶段）

1. **excel/ 通用机制**：schemas + reader + writer + 单测（解析/坏行/全量错误/往返）+ .importlinter C10
2. **post 适配**：excel.py（列+row schema）+ service import_posts/export_posts + repository list_existing_codes/bulk_create + 单测
3. **api**：import/export 端点 + permissions + seed 菜单 + api 测
4. **集成 + 门禁**：往返集成测 + doc 同步 + make check
5. **对抗审查 loop** → commit/PR/CI/merge

**红线**：无新迁移（复用 posts 表）。openpyxl 已授权。
