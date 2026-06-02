"""
微信插件 ClawBot 集成: 将 Langraph 多智能体系统接入 wechat, 实现类似微信好友聊天的交互体验
- getUpdates[ilink/bot/getupdates]: 长轮询拉取新消息
- sendMessage[ilink/bot/sendmessage]: 发送消息给用户
- getUploadUrl[ilink/bot/getuploadurl]: 获取媒体文件上传地址
- getConfig[ilink/bot/getconfig]: 获取账号配置
- sendTyping[ilink/bot/sendtyping]: 发送[正在输入]状态

# 实现流程: 本地windows内网穿透(ngrok http 8001) -> 通过扫描二维码获取 bot_token -> [getConfig 获取账号配置 ->] getUpdates -> 处理消息(调用 Langgraph Agent) [-> getUploadUrl 上传文件到微信服务器]  -> sendMessage 回复消息给用户 -> sendTyping 控制输入状态
"""
import requests
import asyncio
import httpx
import os
import json
from io import BytesIO
from datetime import datetime
from PIL import Image
from typing import Optional, Dict, Any
from main_graph import graph
from config import BOT_BASE_URL, BOT_TYPE, BOT_QRCODE_URL, ANGET_API_URL, ANGET_REPLY_API_URL, TOKEN_PATH

# ========== ClawBot 微信插件集成 ==========

# ========== 1. getUpdates 长轮询获取消息 ==========
async def get_updates(bot_token: str, get_updates_buf: str = ""):
    """"
    长轮询获取新消息
    Args:
        get_updates_buf: ""    # 上次拉取的未知标识, 首次为空

    Returns:
        get_updates_buf: "new_buf_value_12345"    # 新的未知标识
        msgs: [
            {
                "msg_id": "123456",
                "from_user_id": "user_abc",
                "to_user_id": "bot_xyz",
                "msg_type": "text",
                "content": "用户发的消息内容",
                "timestamp": 1234567890
            }
        ]
    """
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{BOT_BASE_URL}/ilink/bot/getupdates",
                json={"get_updates_buf": get_updates_buf},
                headers=build_headers(bot_token),
                timeout=60
            )
            data = response.json()
            get_updates_buf = data.get("get_updates_buf", "")
            msgs = data.get("msgs", [])
            return msgs, get_updates_buf
        except httpx.RequestError as e:
            # 长轮询超时是正常的
            return [], get_updates_buf
        except Exception as e:
            print(f"get_updates 异常: {str(e)}")
            return None, get_updates_buf

# ========== 2. sendMessage 发送消息给用户 ==========
async def send_message(bot_token, to_user_id, text, context_token, type: Optional[str] = "text"):
    """
    发送消息给用户
    type: 消息类型(text/image/voice/video/file)
    """
    item_list = []
    if type == "text":
        item_list = [{
            "type": "TEXT",
            "text_item": {"text": text}
        }]
    elif type == "image":
        media_id = await upload_media(text, file_type="image")
        if not media_id:
            item_list = [{
                "type": "TEXT",
                "text_item": {"text": "图片上传失败, 请稍后重试."}
            }]
        else:
            item_list = [{
                "type": "IMAGE",
                "image_item": {"media_id": media_id}
            }]
    elif type == "voice":
        media_id = await upload_media(text, file_type="voice")
        if not media_id:
            item_list = [{
                "type": "TEXT",
                "text_item": {"text": "语音上传失败, 请稍后重试."}
            }]
        else:
            item_list = [{
                "type": "VOICE",
                "voice_item": {"media_id": media_id}
            }]
    elif type == "video":
        media_id = await upload_media(text, file_type="video")
        if not media_id:
            item_list = [{
                "type": "TEXT",
                "text_item": {"text": "视频上传失败, 请稍后重试."}
            }]
        else:
            item_list = [{
                "type": "VIDEO",
                "video_item": {"media_id": media_id}
            }]
    elif type =="file":
        media_id = await upload_media(text, file_type="file")
        if not media_id:
            item_list = [{
                "type": "TEXT",
                "text_item": {"text": "文件上传失败, 请稍后重试."}
            }]
        else:
            item_list = [{
                "type": "FILE",
                "file_item": {"media_id": media_id}
            }]
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BOT_BASE_URL}/ilink/bot/sendmessage",
            json={
                "msg": {
                    "to_user_id": to_user_id,
                    "message_type": "BOT",
                    "item_list": item_list,
                    "context_token": context_token
                }
            },
            headers=build_headers(bot_token)
        )
        return response.status_code == 200

# ========== 3. getUploadUrl 获取媒体文件上传地址 ==========
async def get_upload_url(bot_token: str,file_type: str = "image", file_size: int = 0) -> Optional[Dict[str, Any]]:
    """
    获取媒体文件上传地址
    Args:
        file_type: 文件类型(image/voice/video/file)
        file_size: 文件大小(字节)
    Returns:
        {
            "upload_url": "https://...",
            "media_id": "generated_media_id",
            "expire_time": "2026-12-31T23:59:59Z"
        }
    """
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BOT_BASE_URL}/inlink/bot/getuploadurl",
            json={
                "file_type": file_type,
                "file_size": file_size
            },
            headers=build_headers(bot_token),
            timeout=60
        )
        if response.status_code == 200:
            data = response.json()
            if data.get("errcode") == 0:
                return {
                    "upload_url": data.get("upload_url"),
                    "media_id": data.get("media_id"),
                    "expire_time": data.get("expire_time")
                }
            else:
                print(f"获取上传地址失败: {data.get('errmsg')}")
                return None

# ========== 4. getConfig 获取账号配置 ==========
async def get_config(bot_token: str) -> Optional[Dict[str, Any]]:
    """
    获取账号配置信息
    Returns:
        {
            "bot_name": "机器人名称",
            "bot_avatar": "头像URL",
            "max_friends": 5000,       # 最大好友数
            "message_rate_limit": 20,  # 每分钟消息限制
            "supported_message_types": ["text", "image", "voice", "video", "file"]
        }
    """
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BOT_BASE_URL}/ilink/bot/getconfig",
            json={},
            headers=build_headers(bot_token),
            timeout=60
        )
        if response.status_code == 200:
            data = response.json()
            if data.get("errcode") == 0:
                return {
                    "bot_name": data.get("bot_name", "AI助手"),
                    "bot_avatar": data.get("bot_avatar", ""),
                    "max_friends": data.get("max_friends", 5000),
                    "message_rate_limit": data.get("message_rate_limit", 20),
                    "supported_message_types": data.get("supported_message_types", ["text", "image", "voice", "video", "file"])
                }
            else:
                print(f"获取配置失败: {data.get('errmsg')}")
                return None
        else:
            print(f"HTTP错误: {response.status_code}")
            return None

# ========== 5. sendTyping 发送[正在输入]状态 ==========
async def send_typing(bot_token: str, to_user_id: str, typing: bool = True):
    """
    发送[正在输入]状态
    Args:
        bot_token: 机器人令牌
        to_user_id: 接收方用户ID
        typing: True=正在输入, False=取消正在输入
    """
    async with httpx.AsyncClient() as client:
        await client.post(
            f"{BOT_BASE_URL}/ilink/bot/sendtyping",
            json={
                "to_user_id": to_user_id,
                "typing": typing
            },
            headers=build_headers(bot_token),
            timeout=60
        )

# ========== 辅助函数 ==========

async def handle_message(bot_token: str, msg: Dict[str, Any]):
    """处理消息: 调用你的 Langgraph Agent"""
    user_id = msg["from_user_id"]
    context_token = msg.get("context_token")
    msg_type = msg.get("msg_type")
    user_text = extract_text(msg)

    if not user_text:
        await send_message(bot_token, user_id, "暂时仅支持文字对话, 请发送文字消息", context_token)
        return
    
    # 发送[正在输入]状态
    await send_typing(bot_token, user_id, typing=True)

    try:
        # 调用 LangGraph Agent
        result = requests.post(
            ANGET_API_URL,
            json={
                "user": f"wechat_{user_id}",
                "query": user_text,
                "thread_id": "wechat_default_thread",
                "from_skill": None
            },
            headers={
                "Authorization": f"Bearer {bot_token}"
            },
            timeout=180
        )
        response_text = result.get("response", "抱歉, 我无法回答这个问题.")
        response_image = result.get("image", "")
        # 回复支持类型: 文本(text)/图片(image)/语音(voice)/视频(video)/文件(file)  # 判断 response_text 回复
        # 存储消息队列
        await send_reply(bot_token, user_id, response_text, msg_type, context_token)
        # 发送回复
        await send_message(bot_token, user_id, response_text, context_token)

        # 取消[正在输入]状态
        await send_typing(bot_token, user_id, typing=False)
    except Exception as e:
        # 取消[正在输入]状态
        await send_typing(bot_token, user_id, typing=False)
        await send_reply(bot_token, user_id, f"处理失败: {str(e)}", msg_type, context_token)
        await send_message(bot_token, user_id, f"处理失败: {str(e)}", context_token)

async def send_reply(bot_token: str, user_id: str, reply: str, msg_type: str, context_token: str):
    """
    把待发送给微信服务器的消息存储在消息队列, 等待微信服务器通过 get_updates 接口来获取
    """
    async with httpx.AsyncClient() as client:
        try:
            # 调用消息存储队列接口
            result = requests.post(
                ANGET_REPLY_API_URL,
                json={
                    "to_user_id": user_id,
                    "msg_type": "text",
                    "content": reply,
                    "context_token": context_token
                },
                headers={
                    "Authorization": f"Bearer {bot_token}"
                },
                timeout=180
            )
            if result.status == "ok":
                print(f"消息存储成功")
            
            return result
        except Exception as e:
            print(f"消息存储异常: {str(e)}")
            return {
                "status": "error"
            }

async def run_bot(bot_token: str):
    """运行机器人主循环"""
    print(f"机器人已启动, 开始监听消息...")
    print(f"提示: 在微信中向「微信 ClawBot」发送消息测试")

    get_updates_buf = ""

    while True:
        try:
            print(f"========== start get_updates ==========")
            messages, new_buf = await get_updates(bot_token, get_updates_buf)
            print(f"========== messages, new_buf: {messages} {new_buf} ==========")

            if messages is None:
                # 连接错误, 等待后重试
                await asyncio.sleep(5)
                continue

            if new_buf != get_updates_buf:
                get_updates_buf = new_buf

            for msg in messages:
                await handle_message(bot_token, msg)
        except Exception as e:
            print(f"主循环异常: {str(e)}")
            await asyncio.sleep(5)

def build_headers(token):
    """构建请求头"""
    return {
        "Content-Type": "application/json",
        "AuthorizationType": "ilink_to_token",
        "Authorization": f"Bearer {token}"
    }
def extract_text(msg) -> str:
    """从消息中提取文本内容"""
    result = extract_message_content(msg)
    return result["content"] if result["type"] == "text" else ""

def extract_message_content(msg) -> dict:
    """
    提取消息完整内容(支持文本、图片、语音等)
    返回格式:
    {
        "type": "text",        # 消息类型: text/image/voice/video/file
        "content": "文本消息",  # 文本内容或文件URL/ID
        "raw": {...}           # 原始数据
    }
    """
    result = {"type": "unknown", "content": "", "raw": msg}

    # 1. 从item_list中提取解析
    if "item_list" in msg:
        for item in msg["item_list"]:
            msg_type = item.get("type", "")

            if msg_type == "TEXT":
                text_item = item.get("text_item", {})
                result["type"] = "text"
                result["content"] = text_item.get("text", "")
            elif msg_type == "IMAGE":
                image_item = item.get("image_item", {})
                result["type"] = "image"
                result["content"] = image_item.get("url", "")
                result["media_id"] = image_item.get("media_id", "")
            elif msg_type == "VOICE":
                voice_item = item.get("voice_item", {})
                result["type"] = "voice"
                result["content"] = voice_item.get("url", "")
                result["media_id"] = voice_item.get("media_id", "")
            elif msg_type == "VIDEO":
                video_item = item.get("video_item", {})
                result["type"] = "video"
                result["content"] = video_item.get("url", "")
                result["media_id"] = video_item.get("media_id", "")
            elif msg_type == "FILE":
                file_item = item.get("file_item", {})
                result["type"] = "file"
                result["content"] = file_item.get("url", "")
                result["file_name"] = file_item.get("file_name", "")
            
    # 2. 兼容直接字段格式
    elif "msg_type" in msg:
        if msg["msg_type"] == "text":
            result["type"] = "text"
            result["content"] = msg.get("content", "")

    # 3. 简单文本回退
    elif "content" in msg:
        result["type"] = "text"
        result["content"] = msg.get("content", "")

    elif "text" in msg:
        result["type"] = "text"
        result["content"] = msg.get("text", "")

    return result

async def upload_media(bot_token: str, file_path: str, file_type: str = "image") -> Optional[str]:
    """
    上传媒体文件到微信服务器
    Args:
        bot_token: 机器人令牌
        file_path: 本地文件路径
        file_type: 文件类型(image/voice/video/file)
    Returns:
        media_id: 微信服务器返回的媒体ID, 可用于发送消息
    """
    import os
    from pathlib import Path

    # 1. 获取文件信息
    file_size = os.path.getsize(file_path)

    # 2. 获取上传地址
    upload_info = await get_upload_url(bot_token, file_type, file_size)
    if not upload_info:
        return None
    
    upload_url = upload_info["upload_url"]

    # 3. 上传文件
    async with httpx.AsyncClient() as client:
        with open(file_path, "rb") as f:
            files = {"file": (Path(file_path).name, f, "application/octet-stream")}
            response = await client.post(
                upload_url,
                files=files,
                timeout=60
            )
            if response.status_code == 200:
                result = response.json()
                if result.get("errcode") == 0:
                    return upload_info["media_id"]
                else:
                    print(f"上传失败: {result.get('errmsg')}")
                    return None
            else:
                print(f"上传HTTP错误: {response.status_code}")
                return None

# ========== 凭证管理 ==========

def save_token(token:str):
    """将 bot_token 保存到本地文件"""
    # 确保文件存在
    os.makedirs(os.path.dirname(TOKEN_PATH), exist_ok=True)
    data = {
        "bot_token": token,
        "saved_at": datetime.now().isoformat()
    }
    with open(TOKEN_PATH, "w") as f:
        json.dump(data, f, indent=2)
    print(f"bot_token 已保存到 {TOKEN_PATH}")

def load_token() -> Optional[str]:
    """从本地文件加载 bot_token"""
    if os.path.exists(TOKEN_PATH):
        with open(TOKEN_PATH, "r") as f:
            data = json.load(f)
            token = data.get("bot_token")
            if token:
                print(f"bot_token 已从 {TOKEN_PATH} 加载")
                return token
    print(f"未找到有效的 bot_token 文件")
    return None


# ========== 扫码获取登录凭证 ==========

async def get_qrcode():
    """获取登录二维码"""
    url = f"{BOT_BASE_URL}/ilink/bot/get_bot_qrcode?bot_type={BOT_TYPE}"
    print(f"======================= url: {url} ===========================")
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        result = response.json()
        if result.get("ret") != 0:
            print(f"获取二维码失败: {result.get('err_msg')}")
        
        # 直接调用主函数启动轮询登录状态
        print(f"======================= 调用主函数: 获取二维码状态 - 账号配置 - 接收用户消息 - 处理信息[ - 上传资料] - 发送回复[正在输入] ===========================")
        # qrcode = result.get("qrcode", "")
        # asyncio.create_task(main(qrcode))

        return result
    
async def get_qrcode_status(qrcode: str) -> dict:
    """查询二维码状态"""
    url = f"{BOT_BASE_URL}/ilink/bot/get_qrcode_status?qrcode={qrcode}"
    print(f"======================= 查询二维码状态 url: {url} ===========================")
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, timeout=60)
            print(f"================ 666666666666666: {response} ===================")
            if response.status_code != 200:
                print(f"查询二维码状态 HTTP错误: {response.status_code}")
                return {
                    "status": "error",
                    "err_msg": f"HTTP {response.status_code}"
                }
            return response.json()
    
        except Exception as e:
            # 捕获所有异常，打印错误信息并返回
            print(f"查询二维码状态 异常: {str(e)}")
            return {
                "status": "error",
                "err_msg": f"Exception: {str(e)}"
            }

async def poll_login_status(qrcode: str):
    """
    轮询扫码状态
    wait:       等待扫码           ->   继续轮询
    scanned:    已扫码, 等待确认    ->   继续轮询
    confirmed:  已确认, 返回 token ->   保存凭证, 退出
    expired:    二维码已过期       ->   刷新二维码
    """
    print(f"================ 777777777777777777 ===================")
    while True:
        result = await get_qrcode_status(qrcode)
        status = result.get("status")
        if status == "wait":
            print("等待扫码...")
        elif status == "scanned":
            print("扫码已完成, 请在手机上点击确认...")
        elif status == "confirmed":
            # 获取 bot_token 并保存
            bot_token = result.get("bot_token", "")
            print(f"登录成功, bot_token: {bot_token}")
            return bot_token
        elif status == "expired":
            print(f"二维码已过期, 请重新生成二维码")
            return None
        else:
            print(f"未知状态: {status}, 信息: {result}")
        await asyncio.sleep(2)

# ========== 主函数 ==========

async def main(qrcode: str):
    """
    主函数: 登录 + 启动机器人
    如果提供了 qrcode, 则直接使用它轮询登录状态
    """
    # 1. 检查是否有保存的 bot_token
    bot_token = load_token()

    if bot_token:
        # 验证 bot_token 是否有效
        config = await get_config(bot_token)
        if config:
            print(f"使用已保存的 bot_token: {bot_token}, 机器人名称: {config['bot_name']}")
            await run_bot(bot_token)
            return
        
    # 2. 如果没有 token 或 token 无效, 需要扫码登录
    if not qrcode:
        print("没有有效的 bot_token, 需要扫码登录")
        return
    
    # 3. 轮询等待扫码确认
    bot_token = await poll_login_status(qrcode)

    if not bot_token:
        print(f"登录失败, 无法获取 bot_token")
        return
    
    # 4. 保存 bot_token 到本地
    save_token(bot_token)

    # 5. 获取配置并启动机器人
    config = await get_config(bot_token)
    if config:
        print(f"登录成功, 机器人名称: {config['bot_name']}")

    await run_bot(bot_token)