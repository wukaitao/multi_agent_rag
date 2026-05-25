from llama_index.llms.ollama import Ollama
from config import LLM_MODEL
from core.memory_manager import add_short_memory, get_short_memory, save_long_memory
from core.security import data_desensitize, circuit_breaker

llm = Ollama(model=LLM_MODEL, temperature=0)

@circuit_breaker
def chat_agent_node(state):
    q = state["query"]
    user =  state["user"]
    memory = get_short_memory()

    if state["prompt"]:
        prompt = state["prompt"]
    else:
        prompt = f"历史对话: {memory}\n用户当前问题: {q}"
    print(f"prompt:\n{prompt}")

    ans = llm.complete(prompt).text
    ans = data_desensitize(ans)

    # 添加回答质量评估(可选)
    quality_score = evaluate_response_quality(q,ans)
    print(f"回答质量评分: {quality_score} / 100")

    add_short_memory("用户:"+q+" AI:"+ans)
    save_long_memory(user, q)
    state["response"] = ans
    # state["quality_score"] = quality_score

    return state

def evaluate_response_quality(query: str, response: str) -> int:
    """简单的回答质量评估"""
    score = 100

    # 1. 长度检测: 过短扣分
    if len(response) < 20:
        score -= 20
    
    # 2. 关键词覆盖
    keywords = extract_keywords(query, top_k=3)
    keyword_match = sum(1 for kw in keywords if kw in response)
    if keyword_match < len(keywords) * 0.5:
        score -= 20

    # 3. 不确定性此过多扣分
    uncertainty = ["可能", "也许", "不确定", "不太清楚", "或许", "大概", "估计"]
    for word in uncertainty:
        if word in response:
            score -= 5
            break

def extract_keywords(text: str, top_k=3):
    """简单关键词提取"""
    import re
    words = re.findall(r"[\u4e00-\u9fa5]{2,}", text)
    return list(set(words))[:top_k]