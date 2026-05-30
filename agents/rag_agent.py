from database.chroma_conn import vector_search, vector_search_with_rerank
from database.neo4j_conn import kg_search, kg_search_with_context
from core.optimizer import truncate_text, expand_query
from core.security import circuit_breaker
from agents.chat_agent import chat_agent_node
from config import *
import re

@circuit_breaker
def rag_agent_node(state):
    """优化版RAG节点: 多查询融合 + 重排序 + 上下文扩展"""
    print(f"========== RAG 节点 ==========")
    print(f"NEO4J_URL: {NEO4J_URL}\nLLM_BASE_URL: {LLM_BASE_URL}\nMEMORY_DB:{MEMORY_DB}")
    query = state["query"]

    # === 1. 查询优化: 多角度检索向量 ===
    expanded_queries = expand_query(query) # 生成同义词查询
    all_vec_results = []

    # 多查询融合
    for query in [query] + expanded_queries[:2]:    # 限制数量
        vec_res = vector_search(query, top_k=5) # 增加找回数量
        all_vec_results.extend(vec_res)

    # 去重并重排序(基于相关性)
    unique_results = {}
    for res in all_vec_results:
        doc_id = res.id_ if hasattr(res, "id_") else res.text[:100]
        if doc_id not in unique_results or res.score > unique_results[doc_id].score:
            unique_results[doc_id] = res

    # 重排序(使用RRF或余弦相似度)
    reranked_results = vector_search_with_rerank(query, list(unique_results.values()))
    top_results = reranked_results[:5]
    print(f"向量检索: 召回 {len(all_vec_results)} 条, 重排后保留 {len(top_results)} 条")

    # === 2. 知识图谱检索增强 ===
    kg_res = kg_search(query)
    kg_context = kg_search_with_context(query) # 获取邻居节点上下文

    # === 3. 构建结构化上下文 ===
    # 向量检索内容(带分数和来源)
    vec_context = ""
    for i, n in enumerate(top_results):
        score = getattr(n, "score", 0.5)
        relavance = "高相关" if score > 0.8 else "中相关" if score > 0.6 else "低相关"
        vec_context += f"\n[{i+1}] {relavance} (置信度: {score:.2f})\n{truncate_text(n.text, 600)}\n"

    # 知识图谱内容(结构化格式)
    kg_context_str = ""
    if kg_res:
        kg_context_str = f"""
        [精确事实]
        {kg_res}
        [关联上下文]
        {kg_context if kg_context else '无额外上下文'}
        """
    else:
        kg_context_str = "[知识图谱]未检索到精确事实, 请完全基于向量检索回答"

    # === 4. 构建增强版 Prompt ===
    enhanced_prompt = f"""
    你是一个专业的智能问答助手, 请基于以下信息回答用户问题:
    ## 检索结果(按置信度排序)
    {vec_context}

    ## 知识图谱
    {kg_context_str}

    ## 用户问题
    {query}

    ## 回答要求
    1. **优先级**: 知识图谱事实 > 高置信度向量 > 中低置信度向量
    2. **置信度标注**: 对于低置信度信息, 需明确说明"根据检测结果推测"
    3. **信息融合**: 若多源信息冲突, 对比说明并给出最可能正确的答案
    4. **完整性**: 若信息不足, 明确告知缺失部分并提供获取建议
    5. **格式**: 使用简洁清晰的语音, 关键事实可用 **粗体** 标注, 复杂信息可用列表或表格形式展示
    6. **引用**: 对于重要信息, 标注来源类型([知识图谱]或[文档检索])

    ## 回答策略
    - 如果知识图谱有精确信息, 优先使用, 向量检索仅作为补充细节
    - 如果只有向量检索: 综合多条结果, 提取共同点, 标注置信度
    - 如果结果为空: 告知"未找到相关信息", 并提供重新表述问题的建议

    请开始回答:
    """
    reference_str = f"[向量检索片段]\n{vec_context}\n\n[知识图谱事实]\n{kg_context_str}"
    state["prompt"] = enhanced_prompt
    state["reference"] = reference_str
    return state