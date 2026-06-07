# config.py - 使用 Pydantic Settings 管理配置
from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional

class Settings(BaseSettings):
    # Neo4j 配置
    neo4j_uri: str = Field(default="bolt://localhost:7687", alias="NEO4J_URI")
    neo4j_user: str = Field(default="neo4j", alias="NEO4J_USER")
    neo4j_password: str = Field(default="", alias="NEO4J_PASSWORD")

    # 安全配置
    secret_token: str = Field(default="", alias="SECRET_TOKEN")
    encryption_key: str = Field(default="", alias="ENCRYPTION_KEY")

    # 调试模式(生产环境必须为 False)
    debug: bool = Field(default=False, alias="DEBUG")

    class Config:
        env_file = ".env"
        evn_file_encoding = "utf-8"
        case_sensitive = False

settings = Settings()