"""Pydantic models for rule configuration and validation."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class CleanStep(str, Enum):
    """Ordered cleaning steps available in the pipeline."""

    drop_empty_columns = "drop_empty_columns"
    deduplicate = "deduplicate"
    infer_types = "infer_types"
    wide_to_long = "wide_to_long"


class Rule(BaseModel):
    """A single processing rule bound to a file_type."""

    name: str = Field(..., min_length=1, description="规则名称")
    file_type: str = Field(..., min_length=1, description="文件类型，如日报/周报/月报/明细")
    version: int = Field(default=1, description="规则版本，用于兼容性校验")
    sheet_names: list[str] | None = Field(
        default=None,
        description="Excel 中要导入的 Sheet 名称列表；None 或空列表表示导入所有 Sheet",
    )
    input_columns: list[str] | None = Field(
        default=None,
        description="导入后保留的输入字段白名单；None 表示保留全部",
    )
    clean_steps: list[CleanStep] = Field(
        default_factory=list,
        description="有序清洗步骤",
    )
    field_mapping: dict[str, str] = Field(
        default_factory=dict,
        description="字段映射（旧名 -> 新名）",
    )
    computed_columns: dict[str, str] = Field(
        default_factory=dict,
        description="计算列（列名 -> DuckDB SQL 表达式）",
    )
    split_keys: list[str] = Field(
        ...,
        min_length=1,
        description="机构拆分字段列表，支持多级",
    )
    output_columns: list[str] | None = Field(
        default=None,
        description="最终输出字段白名单；None 表示输出全部",
    )
    output_format: str = Field(
        default="excel",
        description="输出格式",
    )
    output_template: str = Field(
        default="{date}_{file_type}_{last_split_value}",
        description="输出文件名模板",
    )
    output_dir: str = Field(
        default="",
        description="输出根目录；空字符串表示使用 AppConfig 默认值",
    )
    enabled: bool = Field(default=True, description="是否启用")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("output_format")
    @classmethod
    def _validate_output_format(cls, v: str) -> str:
        allowed = {"excel", "csv", "parquet"}
        if v not in allowed:
            raise ValueError(f"output_format 必须是其中之一: {allowed}")
        return v

    @field_validator("split_keys")
    @classmethod
    def _validate_split_keys(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("split_keys 不能为空，至少指定一个拆分字段")
        if len(v) > 4:
            raise ValueError("split_keys 最多支持 4 级拆分")
        return v

    def model_dump_for_toml(self) -> dict[str, Any]:
        """Serialize to a dict suitable for TOML writing.

        Converts Enums to strings and datetimes to ISO format.
        Drops None values since tomli_w does not support them.
        """
        data = self.model_dump()
        data["clean_steps"] = [step.value for step in self.clean_steps]
        data["created_at"] = self.created_at.isoformat()
        data["updated_at"] = self.updated_at.isoformat()
        # tomli_w cannot serialize None values
        data = {k: v for k, v in data.items() if v is not None}
        return data

    @classmethod
    def model_validate_from_toml(cls, data: dict[str, Any]) -> "Rule":
        """Reconstruct a Rule from raw TOML dict.

        Handles string -> Enum conversion for clean_steps.
        """
        raw_steps = data.get("clean_steps", [])
        data["clean_steps"] = [CleanStep(s) for s in raw_steps]
        return cls.model_validate(data)


class ArchiveConfig(BaseModel):
    """Subset of Rule focused on output archiving."""

    output_format: str = Field(default="excel")
    output_template: str = Field(default="{date}_{file_type}_{last_split_value}")
    split_keys: list[str] = Field(default_factory=list, min_length=1)

    @field_validator("output_format")
    @classmethod
    def _validate_output_format(cls, v: str) -> str:
        allowed = {"excel", "csv", "parquet"}
        if v not in allowed:
            raise ValueError(f"output_format 必须是其中之一: {allowed}")
        return v


class AppConfig(BaseModel):
    """Global application configuration."""

    default_output_dir: str = Field(default="output", description="默认输出目录")
    db_path: str = Field(default="mallard_auto.duckdb", description="DuckDB 数据库路径")
    imap_server: str | None = Field(default=None, description="IMAP 服务器地址")
    imap_port: int = Field(default=993, description="IMAP 端口")
    imap_username: str | None = Field(default=None, description="IMAP 用户名")
    imap_password: str | None = Field(default=None, description="IMAP 密码")

