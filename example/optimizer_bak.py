import time
from functools import lru_cache

# 缓存优化
@lru_cache(maxsize=32)
def cache_query(text: str):
    time.sleep(0.01)
    return text

# 文本截断优化
def truncate_text(text: str, max_len=800) -> str:
    if len(text) > max_len:
        return text[:max_len] + "..."
    return text