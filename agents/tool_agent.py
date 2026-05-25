from tools.weather import get_weather
from tools.lyrics import get_lyrics
from tools.football import get_football_info
from tools.code_generator import gen_code
from core.security import circuit_breaker

@circuit_breaker
def tool_agent_node(state):
    print(f"tool_agent_node:")
    q = state["query"]
    if "天气" in q:
        res = get_weather("北京")
    elif "歌词" in q:
        res = get_lyrics("平凡之路")
    elif "足球" in q or "转会" in q:
        res = get_football_info()
    elif "代码" in q:
        res = gen_code(q)
    else:
        res = "暂无匹配工具"
    state["response"] =  res
    return state