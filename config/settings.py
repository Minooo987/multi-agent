from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import Optional


class Settings(BaseSettings):
    """应用配置"""

    # 模型配置 (Anthropic 兼容协议)
    model_base_url: str = "https://api.siliconflow.cn/v1"
    model_name: str = "Pro/zai-org/GLM-5.1"
    model_api_key: str = ""

    # Oracle 数据库配置
    oracle_host: str = ""
    oracle_port: int = 1521
    oracle_service_name: str = ""
    oracle_user: str = ""
    oracle_password: str = ""
    oracle_pool_min: int = 1
    oracle_pool_max: int = 5

    # Redis 配置
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0

    # PostgreSQL 配置
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "langgraph"
    postgres_password: str = "langgraph"
    postgres_db: str = "checkpoints"

    # 应用配置
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_debug: bool = False

    # LangSmith
    langchain_api_key: Optional[str] = None
    langchain_tracing_v2: bool = False
    langchain_project: str = "data-analysis-team"

    # 日志
    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    """获取配置单例"""
    return Settings()


settings = get_settings()
