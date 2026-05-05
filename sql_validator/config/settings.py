from __future__ import annotations

from functools import lru_cache

from langchain_core.language_models import BaseChatModel
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── LLM ───────────────────────────────────────────────────────────────
    llm_provider: str = Field(
        default="openai",
        description="LLM 提供商: openai | anthropic",
    )
    llm_api_key: str = Field(description="LLM API Key")
    llm_model: str = Field(default="gpt-4o", description="模型名称")
    llm_base_url: str | None = Field(
        default=None,
        description="自定义 API 地址（OpenAI 兼容接口，如 Azure/DeepSeek/Qwen）",
    )
    llm_temperature: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="温度参数，推荐 0.0 保证输出稳定",
    )
    llm_max_retries: int = Field(
        default=3,
        ge=1,
        le=10,
        description="LLM 调用最大重试次数",
    )
    llm_timeout: int = Field(
        default=120,
        ge=10,
        le=600,
        description="单次 LLM 请求超时秒数，防止 API 无响应时进程挂死",
    )

    # ── Database ───────────────────────────────────────────────────────────
    postgres_dsn: str = Field(
        description="PostgreSQL 连接字符串 (postgresql://user:pass@host:5432/db)"
    )

    # ── Runtime ────────────────────────────────────────────────────────────
    max_sql_files: int = Field(
        default=20,
        ge=1,
        le=100,
        description="单次发版最大 SQL 文件数",
    )
    output_dir: str = Field(default="./reports", description="MD 报告输出目录")

    # ── Observability: Langfuse ────────────────────────────────────────────
    langfuse_public_key: str = Field(default="", description="Langfuse Public Key")
    langfuse_secret_key: str = Field(default="", description="Langfuse Secret Key")
    langfuse_host: str = Field(default="http://localhost:3000", description="Langfuse Host URL")

    # ── Validators ─────────────────────────────────────────────────────────

    @field_validator("postgres_dsn")
    @classmethod
    def validate_dsn(cls, v: str) -> str:
        if not v.startswith(("postgresql://", "postgres://")):
            raise ValueError(
                "postgres_dsn 必须以 postgresql:// 或 postgres:// 开头，"
                f"当前值: {v!r}"
            )
        return v

    @field_validator("llm_provider")
    @classmethod
    def validate_provider(cls, v: str) -> str:
        allowed = {"openai", "anthropic"}
        if v not in allowed:
            raise ValueError(f"llm_provider 必须是 {allowed} 之一，当前值: {v!r}")
        return v

    # ── Factory ────────────────────────────────────────────────────────────

    def create_llm(self) -> BaseChatModel:
        """根据配置创建对应的 LangChain ChatModel 实例。"""
        if self.llm_provider == "anthropic":
            from langchain_anthropic import ChatAnthropic  # type: ignore[import-untyped]

            return ChatAnthropic(  # type: ignore[return-value]
                model=self.llm_model,
                api_key=self.llm_api_key,  # type: ignore[arg-type]
                temperature=self.llm_temperature,
                max_retries=self.llm_max_retries,
                timeout=self.llm_timeout,
            )

        # 默认：OpenAI / 任何 OpenAI 兼容接口
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=self.llm_model,
            api_key=self.llm_api_key,  # type: ignore[arg-type]
            base_url=self.llm_base_url,
            temperature=self.llm_temperature,
            max_retries=self.llm_max_retries,
            timeout=self.llm_timeout,
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """返回 Settings 单例（首次调用时从 .env 读取并校验，失败则快速报错）。"""
    return Settings()
