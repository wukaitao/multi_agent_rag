import whisper
import edge_tts
import asyncio
from llama_index.llms.ollama import Ollama
from config import *
from core.security import circuit_breaker
import os
import requests
import time
from datetime import datetime

asr_model = whisper.load_model("base")
vl_llm = Ollama(
    model=VL_MODEL,
    base_url=LLM_BASE_URL,
    temperature=0
)

# 语音转文字
def audio2text(audio_path):
    return asr_model.transcribe(audio_path)["text"]

# 文字转语音(异步修复)
async def text2audio(text, out_path):
    com = edge_tts.Communicate(text, "zh-CN-XiaoxiaoNeural")
    await com.save(out_path)
    return out_path

# 图片理解
def img2text(img_path):
    return vl_llm.complete("详细描述这张图片:" + img_path).text

# 真实文生图
def text2img(prompt: str, save_path: str = None, is_modal: bool = False):
    if save_path is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_path = f"temp/generated_{timestamp}.png"

    # 调用大模型生成图片
    if is_modal:
        return None
    # 调用在线API生成图片(阿里云的ModelScope)
    else:
        return text2img_modelscope(prompt, save_path)

def text2img_modelscope(prompt: str, save_path: str) -> str:
    """
    使用 ModelScope 异步 API 生成图片(两步法)
    """
    # 请求头: 必须包含异步模式标志
    headers = {
        "Authorization": f"Bearer {MODELSCOPE_API_KEY}",
        "Content-Type": "application/json",
        "X-ModelScope-Async-Mode": "true"
    }
    # 请求体
    payload = {
        "model": MODELSCOPE_MODEL,
        "prompt": prompt
    }
    print(f"prompt:\n{prompt}")
    try:
        # 1. 提交任务, 获取 task_id
        response = requests.post(MODELSCOPE_SUBMIT_URL, headers=headers, json=payload)
        response.raise_for_status() # 检查 HTTP 错误

        submit_result = response.json()
        task_id = submit_result.get("task_id")
        print(f"✅ 任务已提交，task_id: {task_id}")

        if not task_id:
            return None
        
        # 2. 轮询查询任务状态, 获取图片
        status_url = MODELSCOPE_STATUS_URL + task_id
        print(f"status_url:\n{status_url}")
        # 查询任务的请求头
        status_headers = {
            "Authorization": f"Bearer {MODELSCOPE_API_KEY}",
            "X-ModelScope-Task-Type": "image_generation"
        }
        for i in range(MODELSCOPE_MAX_ATTEMPTS):
            status_response = requests.get(status_url, headers=status_headers)
            status_response.raise_for_status()
            status_data = status_response.json()
            task_status = status_data.get("task_status")

            if task_status == "SUCCEED":
                # 成功, 从结果中取出图片 URL
                output_images = status_data.get("output_images", [])
                if output_images:
                    img_url = output_images[0]
                    # 下载并保存
                    img_response = requests.get(img_url)
                    img_response.raise_for_status()
                    with open(save_path, "wb") as f:
                        f.write(img_response.content)
                    return save_path
                else:
                    return None
            elif task_status == "FAILED":
                return None
            else:
                # 任务还在处理中, 等待一段时间后再重试
                print(f"⏳ 处理中，第 {i+1} 次等待...")
                time.sleep(2)
        return None
    except requests.exceptions.RequestException as e:
        print("bbb")
        return None

@circuit_breaker
def multimodal_agent_node(state):
    q = state["query"]
    if "生成图" in q:
        if text2img(q):
            state["image"] = text2img(q)
        else:
            state["response"] = "网络出错或连接超时"
    elif "语音" in q:
        asyncio.run(text2audio("语音合成测试", TEMP_OPATH + "/voice.mp3"))
        state["response"] = "语音合成成功, 已保存为mp3"
    else:
        state["response"] = "多模态模块就绪: 文生图、图片解析、语音互换全部可用"
    return state