import time
from functools import lru_cache
import re
from typing import List

# 缓存优化
@lru_cache(maxsize=128)
def cache_query(text: str):
    time.sleep(0.01)
    return text

# 文本截断优化(智能截断)
def truncate_text(text: str, max_len=800) -> str:
    """智能截断: 尽量在句子边界截断"""
    if len(text) <= max_len:
        return text
    
    # 在最近句子结束处截断
    truncated = text[:max_len]
    last_period = max(
        truncated.rfind("。"),
        truncated.rfind("！"),
        truncated.rfind("？"),
        truncated.rfind("."),
        truncated.rfind("!"),
        truncated.rfind("?"),
        truncated.rfind("\n")
    )

    if last_period > max_len * 0.7:
        return truncated[:last_period + 1] + "..."
    else:
        return truncated + "..."
    
def expand_query(query: str) -> List[str]:
    """查询扩展: 生成多个变体"""
    expansions = []

    # 1. 同义词替换(简单映射)
    synonym_map = {
        "谁": ["哪位", "什么人", "哪个"],
        "什么": ["哪些", "何种", "什么内容"],
        "介绍": ["说明", "描述", "讲解"],
        "功能": ["作用", "用途", "能力"]
    }
    for word, syns in synonym_map.items():
        if word in query:
            for syn in syns:
                expansions.append(query.replace(word, syn))

    # 2. 去除疑问词变体
    question_words = ["谁", "什么", "哪个", "哪些", "如何", "怎样", "为什么"]
    for qw in question_words:
        if query.startswith(qw):
            expansions.append(query[len(qw):].strip())
            break

    # 3. 添加补充词
    expansions.append(query + " 的信息")
    expansions.append(query + " 详情")

    # 去重并限制数量
    unique_expansions = list(set(expansions))[:3]

    # 过滤掉过短或相同的
    result = [e for e in unique_expansions if len(e) > 3 and e != query]

    return result[:2]

def extract_keywords(text: str, top_k=5) -> List[str]:
    """关键词提取(简化版TF-IDF)"""
    # 分词过滤停用词
    stopwords = {"的", "了", "是", "在", "和", "与", "或", "有", "也", "这", "那"}
    words = re.findall(r"[\u4e00-\u9fa5a-zA-Z]+", text)

    # 统计词频
    word_freq = {}
    for word in words:
        if len(word) > 1 and word not in stopwords:
            word_freq[word] = word_freq.get(word, 0) + 1

    # 按频率排序
    sorted_words = sorted(word_freq.items(), key=lambda x:x[1], reverse=True)

    return [word for word, _ in sorted_words[:top_k]]

def kg_input_format():
    """知识图谱输入格式示例"""
    return {
        "example": f"""
        支持格式：
        - [张无忌]->[父亲]->[张翠山]
        - [张无忌];[师傅];[张三丰]
        - 张无忌->师傅->张三丰
        - 张无忌;师傅;张三丰
        - 张无忌>师傅>张三丰
        - 张无忌,父亲,张翠山
        """,
        "pattern": r"""
            (?:\[?([^\]\[>;,\->]+)\]?)\s*   # 第一个实体，可选方括号
            (?:->|;|>|,)\s*                 # 分隔符
            (?:\[?([^\]\[>;,\->]+)\]?)\s*   # 关系，可选方括号
            (?:->|;|>|,)\s*                 # 分隔符
            (?:\[?([^\]\[>;,\->]+)\]?)      # 第二个实体，可选方括号
        """
    }