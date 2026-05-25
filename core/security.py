import re
import time
from functools import wraps
from collections import deque
from config import *

# 1. 鉴权
def check_auth(token: str) -> bool:
    return token == SECRET_TOKEN

# 2. 数据脱敏
def data_desensitize(text: str) -> str:
    text = re.sub(r"1[3-9]\d{9}", "1**********", text)
    text = re.sub(r"\d{18}", "******************", text)
    text = re.sub(r"\w+@\w+\.\w+", "***@***.com", text)
    return text

# 3. 并发限流
request_record = deque(maxlen=MAX_REQUEST_PER_MINUTE)
def rate_limit() -> bool:
    now = time.time()
    while request_record and now - request_record[0] > 60:
        request_record.popleft()
    if len(request_record) >= MAX_REQUEST_PER_MINUTE:
        return False
    request_record.append(now)
    return True

# 4. 熔断降级(异常+超时双重熔断)
def circuit_breaker(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time.time()
        try:
            if not rate_limit():
                return "请求过于频繁, 触发限流熔断"
            res = func(*args, **kwargs)
            if time.time() -  start > TIME_OUT:
                return "请求超时, 触发熔断"
            return res
        except Exception as e:
            return "服务异常, 触发容灾降级, 启用简易模型应答"
    return wrapper
