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
    add_short_memory("用户:"+q+" AI:"+ans)
    save_long_memory(user, q)
    state["response"] = ans
    return state