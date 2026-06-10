"""File DTO — files API 的响应形状。

上传走 multipart（非 JSON body），故无 FileCreate/FileUpdate：元数据由 service 从
UploadFile + 校验结果构造，不接受客户端直接提交元数据（object_key/sha256 等不可信）。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class FileRead(BaseModel):
    """文件元数据响应。物理内容经 ``/files/{id}/download`` 流式取，不在此返回。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    original_filename: str
    content_type: str
    size_bytes: int
    sha256: str
    uploader_id: int
    status: str
    created_at: datetime


class FilePage(BaseModel):
    """分页 envelope（ADR 0001 §7.5）。"""

    model_config = ConfigDict(from_attributes=True)

    items: list[FileRead]
    page: int
    size: int
    total: int
    total_pages: int
