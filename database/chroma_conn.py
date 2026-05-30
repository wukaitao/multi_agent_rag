from llama_index.core import Settings, SimpleDirectoryReader, VectorStoreIndex, StorageContext
from llama_index.vector_stores.chroma import ChromaVectorStore
from llama_index.embeddings.ollama import OllamaEmbedding
from llama_index.core.retrievers import VectorIndexRetriever
from llama_index.core.postprocessor import SentenceTransformerRerank
import chromadb
from config import *
import numpy as np
from difflib import SequenceMatcher

Settings.embed_model = OllamaEmbedding(
    model_name=EMBED_MODEL,
    base_url=LLM_BASE_URL
)
Settings.chunk_size = 500

chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
chroma_collection = chroma_client.get_or_create_collection("ai_knowledage")
vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
storage_context = StorageContext.from_defaults(vector_store=vector_store)

# 初始化重排序器
# reranker = SentenceTransformerRerank(
#     model="cross-encoder/ms-marco-MiniLM-L-6-v2",
#     top_n=5
# )

def upload_file_to_vector(file_path: str):
    doc = SimpleDirectoryReader(input_files=[file_path]).load_data()
    index = VectorStoreIndex.from_documents(doc, storage_context=storage_context)
    return index

def vector_search(query: str, top_k=10) -> list:
    """基础向量检索, 增加召回数量"""
    index = VectorStoreIndex.from_vector_store(vector_store)
    ret = index.as_retriever(similarity_top_k=top_k)
    return ret.retrieve(query)

def vector_search_with_rerank(query: str, results: list, top_n=5) -> list:
    """使用重排序模型优化结果"""
    if not results:
        return []
    try:
        # 使用重排序器
        # reranked = reranker.postprocess_nodes(results, query_str=query)
        # return reranked[:top_n]
        return results[:top_n]
    except Exception as e:
        print(f"重排序失败:{e}")
        # 降级: 使用原始分数排序
        return sorted(results, key=lambda x:getattr(x, "score", 0), reverse=True)[:top_n]
    
def expand_query(query: str) -> list:
    """查询扩展: 生成同义词和补充查询"""
    expansions = []
    # 1. 关键词提取(简单实现)
    words = query.split()
    if len(words) > 3:
        # 生成不含停用词的查询
        stopwords = {"的", "了", "是", "在", "和", "与", "或"}
        keywords = [w for w in words if w not in stopwords]
        expansions.append(" ".join(keywords[:3]))

    # 2. 添加通用补充词
    expansions.append(query + " 介绍")
    expansions.append(query + " 详细信息")

    # 3. 去重
    return list(set(expansions))[:3]

def hybrid_search(query: str, alpha=0.5, top_k=5) -> list:
    """
    混合检索: 向量 + 关键词
    alpha: 向量权重(0=纯关键词, 1=纯向量)
    """
    # 向量检索
    vec_results = vector_search(query, top_k=top_k*2)
    # 关键词匹配(TF_IDF 简化版)
    keyword_scores = []
    for res in vec_results:
        text =  res.text.lower()
        query_words = set(query.lower().split)
        matches = sum(1 for word in query_words if word in text)
        keyword_score = matches / max(len(query_words), 1)
        keyword_scores.append(keyword_score)
    # 融合分数
    for i, res in enumerate(vec_results):
        vec_score = getattr(res, "score", 0.5)
        fused_score = alpha * vec_score + (1 - alpha) * keyword_scores[i]
        res.score = fused_score
    # 排序并返回
    return sorted(vec_results, key=lambda x:x.score, reverse=True)[:top_k]