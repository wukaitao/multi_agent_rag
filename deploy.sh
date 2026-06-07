#!/bin/bash

set -e

echo "开始部署 Multi_Agent_RAG 系统..."

# 1. 检验环境
command -v docker >/dev/null 2>&1 || { echo "需要 Docker"; exit 1; }
command -v docker-compose >/dev/null 2>&1 || { echo "需要 Docker Componse"; exit 1; }

# 2. 加载环境变量
if [ -f .env.prod ]; then
    export $(cat .env.prod | grep -v '^#' | xargs)
fi

# 3. 构建镜像
echo "构建 Docker 镜像..."
docker build -t multi-agent-rag:latest .

# 4. 编译 Cython 模块(可选)
if [ "$PROTECT_CODE" = "TRUE" ]; then
    echo "编译 Cython 模块..."
    docker run --rm -v $(pwd):/app multi-agent-rag:latest python setup.py build_ext --inplace
fi

# 5. 启动服务
echo "启动所有服务..."
docker-compose -f docker-compose.prod.yml up -d

# 6. 健康检查
echo "等待服务启动..."
sleep 10
curl -f http://localhost:8001/health || echo "健康检查失败"

echo "部署完成!"
echo "Sreamlit: http://localhost:8501"
echo "FastAPI: http://localhost:8000"
echo "Hermes Gateway: http://localhost:8001"