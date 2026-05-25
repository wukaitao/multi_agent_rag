import os
import asyncio
from neo4j import GraphDatabase
from neo4j_graphrag.experimental.pipeline.kg_builder import SimpleKGPipeline
# 必须使用 neo4j-graphrag 提供的 Ollama 适配器
from neo4j_graphrag.llm import OllamaLLM
from neo4j_graphrag.embeddings import OllamaEmbeddings
from config import *

async def build_kg_from_document(file_path: str):
    """从文档自动构建知识图谱"""
    print("="*60, "build_kg_from_document", "="*60)

    # 1. 连接 Neo4j
    driver = GraphDatabase.driver(
        NEO4J_URL,
        auth=(NEO4J_USER, NEO4J_PASSWORD)
    )

    # 2. 初始化 LLM 和 Embedding（必须用 neo4j-graphrag 的适配器）
    llm = OllamaLLM(
        model_name=LLM_MODEL
    )
    embedder = OllamaEmbeddings(
        model=EMBED_MODEL
    )

    # 3. 构建知识图谱管道（所有必填参数必须完整）
    kg_builder = SimpleKGPipeline(
        llm=llm,
        driver=driver,
        embedder=embedder,
        from_file=file_path.endswith(".pdf"),
        entities=["Person", "Organization", "Event", "Document"],
        relations=["RELATES_TO", "PARTICIPATES_IN", "RELATED_TO"],
        # document_name=os.path.basename(file_path)
    )

    # 4. 运行构建流程（必须用 run_async）
    result = await kg_builder.run_async(file_path=file_path)
    print(f"构建完成: {result}")
    return result

if __name__ == "__main__":
    asyncio.run(build_kg_from_document("data/倚天屠龙记.pdf"))