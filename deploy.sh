#!/bin/bash

set -e

echo "开始部署 Multi_Agent_RAG 系统..."

# 1. 检验环境
command -v docker >/dev/null 2>&1 || { echo "需要 Docker"; exit 1; }
command -v docker >/dev/null 2>&1 && echo "Docker 已安装"

# 2. 加载环境变量
echo "加载环境变量"
if [ -f .env.prod ]; then
    # 安全加载环境变量
    set -a
    source .env.prod
    set +a
    echo "环境变量已加载"
else
    echo ".env.prod 不存在, 使用默认配置"
fi
echo "PROTECT_CODE = $PROTECT_CODE"

# 3. 构建镜像
echo "构建 Docker 镜像..."
docker build --no-cache --build-arg PROTECT_CODE=$PROTECT_CODE -t multi-agent-rag:latest . # --no-cache

# 5. 启动服务
echo "启动所有服务..."
docker compose -f docker-compose.prod.yml up -d

# 6. 健康检查
echo "等待服务启动..."
sleep 10

# 检查是否正常
curl -f http://localhost:8001/health || echo "健康检查失败"

echo "部署完成!"
echo "服务地址:"
echo "Sreamlit: http://localhost:8501"
echo "FastAPI: http://localhost:8000"
echo "Hermes Gateway: http://localhost:8001"