import os
import sys
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 环境判断
def is_wsl():
    """ 判断是否在 WSL2 环境"""
    return sys.platform == "linux" and "microsoft" in os.uname().release.lower()
def is_windows():
    """ 判断是否在 Windows 环境"""
    return sys.platform == "win32"

# LLM 配置
LLM_MODEL = "qwen3:0.6b"
VL_MODEL = "gemma4:e2b"
EMBED_MODEL = "mxbai-embed-large"
LLM_BASE_URL = "http://localhost:11434" if not is_wsl() else "http://host.docker.internal:11434"

# 知识图谱(Neo4j)
NEO4J_URL = "bolt://localhost:7687" if not is_wsl() else "bolt://192.168.18.104:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "12345678"
# 向量数据库(ChromaDB + SQLite3)
CHROMA_PATH = "./chroma_db" if not is_wsl() else "/mnt/e/work/AIAgent/multi_agent_rag/chroma_db"

# 安全配置
SECRET_TOKEN = "admin2026ai"
MAX_REQUEST_PER_MINUTE = 20
TIME_OUT = 120

# 路径
DATA_PATH = "./data"
TEMP_OPATH = "./temp"
GRAPH_FILE_PATH = "./main_graph_flow.png"
# 关系型数据库(SQLite3)
MEMORY_DB = "./memory/memory.db" if not is_wsl() else "/mnt/e/work/AIAgent/multi_agent_rag/memory/memory.db"

# ModelScope 配置
MODELSCOPE_MODEL = "Qwen/Qwen-Image"
MODELSCOPE_API_KEY = "ms-0e90e04f-0ed7-4ec0-a4c1-ce426ef47171"
MODELSCOPE_SUBMIT_URL = "https://api-inference.modelscope.cn/v1/images/generations"
MODELSCOPE_STATUS_URL = "https://api-inference.modelscope.cn/v1/tasks/"
MODELSCOPE_MAX_ATTEMPTS = 50

# RAG 优化配置
RAG = {
    "vector_top_k": 10,                  # 向量检索召回数
    "rerank_top_n": 5,                   # 重排序后保留数
    "query_expansion_count": 2,          # 查询扩展数量
    "max_context_length": 2000,          # 最大上下文长度
    "high_confidence_threshold": 0.8,    # 高置信度阈值
    "low_confidence_threshold": 0.6      # 低置信度阈值
}

# 检索器配置
RETRIEVER_CONFIG = {
    "similarity_top_k": 10,
    "vector_store_query_model": "default",
    "hybrid_search_alpha": 0.7           # 混合检索向量权重
}

# FastAPI
ANGET_API_URL = "http://localhost:8000/api/chat"

# SKILL 配置
SKILL_PATH = "~/.hermes/skills" if False else r"\\wsl.localhost\Ubuntu\home\wukai\.hermes\skills"  # 根据实际环境调整

# KG 增强版 Prompt
UNIVERSAL_HIGH_PRECISION_PROMPT = """你是专业通用知识图谱三元组抽取专家，擅长从任意非结构化文本中精准提取高质量实体与语义关系。
    你必须严格遵守以下所有规则，不允许随意发挥、不允许编造、不允许偷懒：

    【1.抽取范围】
    只从当前给定文本中抽取真实出现的实体和关系，禁止脑补、禁止推测、禁止生成文本不存在的内容。

    【2.实体规范】
    - 实体为文本中真实存在的具体名词、专有名词、核心概念、关键对象
    - 可自动识别：人物、组织、地点、事件、物品、工具、理论、技术、制度、作品、属性、状态、时间等所有合理实体类型
    - 实体名称必须完整、准确、无缩写、无简称、无错别字
    - 禁止生成：Document、Chunk、Text、段落、章节、文本内容、片段等无效占位实体

    【3.关系规范（超高精度）】
    - 关系必须是细粒度、精准、唯一、可解释的语义动词/动词短语
    - 禁止使用模糊万能关系：相关、关联、涉及、包含、属于、有关系
    - 必须区分细微语义：影响、导致、组成、参与、创建、学习、隶属、对立、适配、定义、依据、作用于、来源于、适用于等
    - 一条事实只输出一条最精准关系，禁止重复、禁止同义多条

    【4.过滤规则（极严格）】
    - 不抽取无意义虚词、修饰词、无关描述
    - 不抽取重复三元组
    - 不抽取模糊、不确定、推测性内容
    - 不生成空实体、空关系、空值
    - 不生成语义相同但文字不同的冗余三元组

    【5.输出要求】
    严格输出高质量结构化三元组，保证图谱干净、简洁、逻辑正确、无噪声。

    待抽取文本：
    {text}
"""

os.makedirs(DATA_PATH, exist_ok=True)
os.makedirs(TEMP_OPATH, exist_ok=True)