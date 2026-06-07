# syntax=

# 第一阶段: 构建阶段
FROM python:3.13.12-slim AS builder

WORKDIR /app

# 配置 pip 国内镜像源
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

# 复制依赖文件
COPY pyproject.toml poetry.lock ./
# COPY pyproject.toml ./

# 安装 Poetry
RUN pip install --no-cache-dir poetry==2.4.1

# 安装依赖(不安装开发依赖)
RUN poetry config virtualenvs.create false && poetry install --without dev --no-interaction --no-ansi --no-root
# RUN poetry config virtualenvs.create false
# RUN poetry install --without dev --no-interaction --no-ansi --no-root

# 第二阶段: 运行阶段
FROM python:3.13.12-slim

WORKDIR /app

# 安装运行时依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 从构建阶段复制依赖
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# 复制项目代码
COPY . .

# 创建非 root 用户
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8001/health || exit 1

# 暴露端口
EXPOSE 8000 8001 8501

# 启动命令(使用 suppervisor 管理多个服务)
CMD ["supervisord", "-c", "supervisord.conf"]
