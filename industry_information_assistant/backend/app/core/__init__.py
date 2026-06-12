# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

from .database import get_db, SessionLocal, engine, Base

__all__ = [
    "get_db",
    "SessionLocal",
    "engine",
    "Base",
    "verify_password",
    "get_password_hash",
    "create_access_token",
    "decode_token",
    "Token",
    "TokenData",
    "cache",
    "get_redis_client",
    "RedisCache",
]


def __getattr__(name: str):
    if name in {
        "verify_password",
        "get_password_hash",
        "create_access_token",
        "decode_token",
        "Token",
        "TokenData",
    }:
        from . import security

        return getattr(security, name)
    if name in {"cache", "get_redis_client", "RedisCache"}:
        from . import redis_client

        return getattr(redis_client, name)
    raise AttributeError(f"module 'core' has no attribute {name!r}")
