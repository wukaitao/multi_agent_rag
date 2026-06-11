# syntax=

# 第一阶段: 构建阶段
FROM python:3.13.12-slim AS builder

WORKDIR /app

# 【关键】先声明 ARG，确保作用域覆盖整个 builder 阶段
ARG PROTECT_CODE
ENV FINAL_PROTECT_CODE $PROTECT_CODE

# 配置 pip 国内镜像源
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

# 复制依赖文件
# COPY pyproject.toml poetry.lock ./
COPY pyproject.toml ./

# 安装 Poetry
RUN pip install --no-cache-dir poetry==2.4.1

# 安装依赖(不安装开发依赖)
RUN poetry config virtualenvs.create false && poetry install --without dev --no-interaction --no-ansi --no-root

# 复制项目代码
COPY . .

# 安装 Cython 和 Pyarmor
RUN pip install --no-cache-dir cython==3.2.5 pyarmor==9.2.5

# 关键：加 set -e 防止静默失败，加 echo 调试输出
RUN echo "========== FINAL_PROTECT_CODE: ${FINAL_PROTECT_CODE}; $FINAL_PROTECT_CODE =========="
RUN set -e; \
    echo "===== DEBUG: FINAL_PROTECT_CODE = [${FINAL_PROTECT_CODE}] ====="; \
    if [ "${FINAL_PROTECT_CODE}" = "Pyarmor" ]; then \
        echo "Running Pyarmor encryption..."; \
        pyarmor gen -r -O dist agents core hermes database tools app.py config.py main_graph.py \
            --exclude ".venv" --exclude ".venv_win" --exclude "venv" --exclude "__pycache__" --exclude "dist"; \
        echo "===== DEBUG: dist generated successfully ====="; \
        ls -la /app/dist; \
    elif [ "${FINAL_PROTECT_CODE}" = "Cython" ]; then \
        echo "Running Cython compile..."; \
        python setup.py build_ext --inplace; \
    elif [ "${FINAL_PROTECT_CODE}" = "Hybrid" ]; then \
        echo "Running Hybrid mode..."; \
        python setup.py build_ext --inplace && \
        pyarmor gen -r -O dist agents core hermes database tools app.py config.py main_graph.py \
            --exclude ".venv" --exclude ".venv_win" --exclude "__pycache__" --exclude "dist"; \
    else \
        echo "WARNING: FINAL_PROTECT_CODE not set, copying raw code to dist"; \
        mkdir -p dist && cp -r agents core hermes database tools app.py config.py main_graph.py dist/; \
    fi

# 第二阶段: 运行阶段
FROM python:3.13.12-slim

WORKDIR /app

# 安装运行时依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    supervisor \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 从构建阶段复制依赖
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# 复制 Cython Pyarmor 后的代码
COPY --from=builder /app/dist ./

# 复制 配置文件
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# 创建非 root 用户
RUN useradd -m -u 1000 appuser && mkdir -p /data &&  chown -R appuser:appuser /app /data
USER appuser

# 健康检查
# HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
#     CMD curl -f http://localhost:8001/health || exit 1

# 暴露端口
EXPOSE 8000 8001 8501

# 启动命令(使用 suppervisor 管理多个服务)
CMD ["supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
# 直接前台运行 hermes-gateway 服务
# CMD ["python", "-m", "uvicorn", "app:gateway_app", "--host", "0.0.0.0", "--port", "8001"]