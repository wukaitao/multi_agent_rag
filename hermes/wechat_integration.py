"""
微信插件 ClawBot 集成: 将 Langraph 多智能体系统接入 wechat, 实现类似微信好友聊天的交互体验
- getUpdates[ilink/bot/getupdates]: 长轮询拉取新消息
- sendMessage[ilink/bot/sendmessage]: 发送消息给用户
- getUploadUrl[ilink/bot/getuploadurl]: 获取媒体文件上传地址
- getConfig[ilink/bot/getconfig]: 获取正在输入凭证
- sendTyping[ilink/bot/sendtyping]: 发送[正在输入]状态

# 实现流程: 本地windows内网穿透(ngrok http 8001) -> 通过扫描二维码获取 bot_token -> [getConfig 获取账号配置 ->] getUpdates -> 处理消息(调用 Langgraph Agent) [-> getUploadUrl 上传文件到微信服务器]  -> sendMessage 回复消息给用户 -> sendTyping 控制输入状态
"""
import requests
import asyncio
import httpx
import os
import json
import base64
import random
from io import BytesIO
from datetime import datetime
from PIL import Image
from typing import Optional, Dict, Any
from main_graph import graph
from config import BOT_BASE_URL, BOT_TYPE, BOT_QRCODE_URL, ANGET_API_URL, ANGET_REPLY_API_URL, TOKEN_PATH, QRCODE_STATUS_PATH

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
    print(f"========== get_updates bot_token: {bot_token} ========")
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{BOT_BASE_URL}/ilink/bot/getupdates",
                json={"get_updates_buf": get_updates_buf},
                headers=build_headers(bot_token),
                timeout=10
            )
            print(f"\nheaders:\n{build_headers(bot_token)}\n")
            data = response.json()
            print(f"========== getupdates success ==========")
            print(f"========== getupdates response: {response} ==========")
            print(f"========== data: {data} ==========")
            get_updates_buf = data.get("get_updates_buf", "")
            msgs = data.get("msgs", [])
            return msgs, get_updates_buf
        except httpx.RequestError as e:
            # 长轮询超时是正常的
            print(f"========== getupdates timeout ==========")
            return [], get_updates_buf
        except Exception as e:
            print(f"get_updates 异常: {str(e)}")
            return None, get_updates_buf

# ========== 2. sendMessage 发送消息给用户 ==========
async def send_message(bot_token, to_user_id, text, context_token, client_id: str, type: str, typing_ticket: str):
    """
    发送消息给用户
    type: 消息类型(text/image/voice/video/file)
    message_type: 1 固定值 - 单聊普通业务消息(图文/语音/文件/视频都归在此大类); 2 - 群消息; 3 - 系统通知; 4 - 事件推送（入群/被撤回等)
    """
    print(f"========== send_message bot_token: {bot_token} ========")
    item_list = []
    if type == "text":
        item_list = [{
            "type": 1,
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
    payload = {
        "msg": {
            "to_user_id": to_user_id,
            "context_token": context_token,
            "client_id": client_id,
            "item_list": item_list,
            "message_type": 2,
            "message_state": 2
        }
    }
    print(f"================== payload: {payload} ==================")
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BOT_BASE_URL}/ilink/bot/sendmessage",
            json=payload,
            headers=build_headers(bot_token)
        )
        print(f"========== send_message - response: {response} =========")
        print(f"0000000000000000000000000000000000000000000000000000000000000000000000000000")
        if response.status_code == 200:
            result = response.json()
            print(f"11111========== send_message - result: {result} =========11111")
            print(f"22222========== send_message - ret: {result.get('ret')} =========22222")
            print("成功发送消息..........................................")
            # 关闭[正在输入]状态
            await send_typing(bot_token, to_user_id, typing_ticket, 2)
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
    print(f"========== get_upload_url bot_token: {bot_token} ========")
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BOT_BASE_URL}/ilink/bot/getuploadurl",
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

# ========== 4. getConfig 获取正在输入凭证 ==========
async def get_config(bot_token: str, ilink_user_id: str, context_token: str):
    """
    获取账号配置信息
    Args:
        "ilink_user_id": "wechat",     # iLink 用户ID (微信用户)
        "context_token": "xxxxxx"      # 消息上下文令牌, 来自用户消息体 context_token 字段, 携带可绑定会话上下文
    Returns:
        {
            "typing_ticket": "正在输入凭证",
            "expire_time": "凭证过期时间"
        }
    """
    print(f"========== get_config bot_token: {bot_token} ========")
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BOT_BASE_URL}/ilink/bot/getconfig",
            json={
                "ilink_user_id": ilink_user_id,
                "context_token": context_token
            },
            headers=build_headers(bot_token),
            timeout=60
        )
        print(f"ilink_user_id:\n{ilink_user_id}")
        print(f"context_token:\n{context_token}")
        print(f"\n555555555555555555555 response: {response} 5555555555555555555555555555\n\n")

        if response.status_code == 200:
            print("\nuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuu\n")
            data = response.json()
            print(f"\nuuuuuuuuuuuuuuuuuuuu data: {data} uuuuuuuuuuuuuuuuuuuuuuuuuuuu\n")
            if data.get("ret") == 0:
                print(f"\nkkkkkkkkkkkkkkkkkk data.getdata: {data.get('data')} kkkkkkkkkkkkkkkkkkkkkkkk\n")
                # data.typing_ticket # 正在输入凭证
                # data.expire_time   # 凭证过期时间
                return data
            else:
                print(f"获取正在输入凭证失败: {data.get('ret')}")
                print(f"============= {data} =============")
                return None
        else:
            print("\nrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrr\n")
            print(f"get_config HTTP错误: {response.status_code}")
            return None

# ========== 5. sendTyping [正在输入]状态 ==========
async def send_typing(bot_token: str, ilink_user_id: str, typing_ticket: str, status: int):
    """
    发送[正在输入]状态
    Args:
        "ilink_user_id": "用户 ID, 来自 getupdates 消息体 from_user_id, 格式oxxx@im.wechat"
        "typing_ticket": "getconfig 接口返回的 typing_ticket, 票据过期需重新拉取"
        "status": "1=开启正在输入(聊天框弹窗); 2=关闭正在输入(消失弹窗)"
        "base_info": "网关版本校验, 固定{'channel_version': '1.0.3'}"
    """
    print(f"========== send_typing bot_token: {bot_token} ========")
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BOT_BASE_URL}/ilink/bot/sendtyping",
            json={
                "ilink_user_id": ilink_user_id,
                "typing_ticket": typing_ticket,
                "status": status
            },
            headers=build_headers(bot_token),
            timeout=60
        )
        if response.status_code == 200:
            data = response.json()
            if data.get("ret") == 0:
                print(f"正在输入接口{'开启' if status == 1 else '取消'}成功")
            else:
                print(f"正在输入接口操作失败: {data.get('ret')}")
                print(f"============= {data} =============")
                return None
        else:
            print(f"HTTP错误: {response.status_code}")

# ========== 6. getBotInfo 获取账号配置 ==========
async def get_bot_info(bot_token: str):
    """
    获取账号配置信息
    Args:
    Returns:
        {
            "bot_name": "机器人账号昵称",
            "bot_avatar": "机器人头像远程 URL 地址",
            "max_friends": 5000,       # 机器人最大可添加好友上限(示例 5000)
            "message_rate_limit": 20,  # 每分钟消息发送频次限额(示例 20 条/分钟), 用来做发送限流
            "supported_message_types": # 机器人支持收发的消息类型：文本 / 图片 / 语音 / 视频 / 文件 ["text", "image", "voice", "video", "file"]
        }
    """
    print(f"========== get_bot_info bot_token: {bot_token} ========")
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BOT_BASE_URL}/ilink/bot/getbotinfo",
            json={},
            headers=build_headers(bot_token),
            timeout=60
        )
        print(f"headers:\n{build_headers(bot_token)}")
        if response.status_code == 200:
            data = response.json()
            print(f"============= data: {data} =============")
            if data.get("ret") == 0:
                print(f"============= get_bot_info: {data.get('data')} =============")
                return data.get("data")
                # return {
                #     "bot_name": data.get("bot_name", "AI助手"),
                #     "bot_avatar": data.get("bot_avatar", ""),
                #     "max_friends": data.get("max_friends", 5000),
                #     "message_rate_limit": data.get("message_rate_limit", 20),
                #     "supported_message_types": data.get("supported_message_types", ["text", "image", "voice", "video", "file"])
                # }
            else:
                print(f"获取配置失败: {data.get('errmsg')}")
                return None
        else:
            print(f"get_bot_info HTTP错误: {response.status_code}")
            return None

# ========== 辅助函数 ==========

async def handle_message(bot_token: str, msg: Dict[str, Any]):
    """处理消息: 调用你的 Langgraph Agent"""
    print(f"========== handle_message bot_token: {bot_token} ========")
    # msg["to_user_id"] 机器人自身ID(bot唯一标识)
    user_id = msg["from_user_id"]
    context_token = msg.get("context_token")
    client_id = msg.get("client_id")
    user_text = extract_text(msg)
    config_result = await get_config(bot_token, user_id, context_token)
    typing_ticket = config_result.get("typing_ticket", "") if config_result else ""
    
    # 开启[正在输入]状态
    await send_typing(bot_token, user_id, typing_ticket, 1)

    if not user_text:
        await send_message(bot_token, user_id, "暂时仅支持文字对话, 请发送文字消息", context_token, client_id, "text", typing_ticket)
        return

    async with httpx.AsyncClient() as client:
        try:
            # 调用 LangGraph Agent
            response = await client.post(
                ANGET_API_URL,
                json={
                    "user": user_id,
                    "query": user_text,
                    "thread_id": f"wechat_{user_id}",
                    "from_skill": "rag_query" # ToDo 暂时固定为RAG知识库查询
                },
                headers={
                    "Authorization": f"Bearer {bot_token}"
                },
                timeout=180
            )
            if response.status_code == 200:
                result = response.json()
                print(f"==================== 111111 result: {result} ==================")
                response_text = result.get("response", "抱歉, 我无法回答这个问题.")
                print(f"==================== 2222222222222 response_text: {response_text} ==================")
                response_image = result.get("image", "")
                # 回复支持类型: 文本(text)/图片(image)/语音(voice)/视频(video)/文件(file)  # 判断 response_text 回复
                # 发送回复
                await send_message(bot_token, user_id, response_text, context_token, client_id, "text", typing_ticket)
            else:
                raise Exception(f"接口 HTTP 异常: {response.status_code}")
        except Exception as e:
            print(f"==================== 000000000000000000 ==================")
            await send_message(bot_token, user_id, f"处理失败: {str(e)}", context_token, client_id, "text", typing_ticket)

async def run_bot(bot_token: str):
    """运行机器人主循环"""
    print(f"========== run_bot bot_token: {bot_token} ========")
    print(f"机器人已启动, 开始监听消息...")
    print(f"提示: 在微信中向「微信 ClawBot」发送消息测试")

    get_updates_buf = ""

    while True:
        try:
            print(f"\n========== start get_updates ==========")
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
    print(f"========== build_headers bot_token: {token} ========")
    print(f"========== randomWechatUin: {randomWechatUin()} ========")
    return {
        "Content-Type": "application/json",
        "AuthorizationType": "ilink_bot_token",
        "Authorization": f"Bearer {token}",
        "X-WECHAT-UIN": randomWechatUin()
    }
def extract_text(msg) -> str:
    """从消息中提取文本内容"""
    result = extract_message_content(msg)
    return result["content"] if result["type"] == "text" else ""

def randomWechatUin():
    # 生成 4 字节随机数(对应 crypto.randomBytes(4))
    uint32_bytes = random.getrandbits(32).to_bytes(4, byteorder='big', signed=False)
    # 转为 uint32 十进制字符串
    uint32 = int.from_bytes(uint32_bytes, byteorder='big', signed=False)
    # 转 utf8 字节 → base64 编码
    return base64.b64encode(str(uint32).encode('utf-8')).decode('utf-8')

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
            """
            # 1 text_item - 纯文本消息; 
            # 2 image_item -- 图片消息(原图 + 缩略图 url、aes 密钥); 
            # 3 voice_item - 微信语音消息(silk/m4a); 
            # 4 file_item - 普通文件(txt/m4a / 压缩包等); 
            # 5 video_item - 短视频消息(视频 + 封面缩略图)
            """

            if msg_type == 1:
                text_item = item.get("text_item", {})
                result["type"] = "text"
                result["content"] = text_item.get("text", "")
            elif msg_type == 2:
                image_item = item.get("image_item", {})
                result["type"] = "image"
                result["content"] = image_item.get("media", {}).get("full_url", "")
                result["media_id"] = image_item.get("media", {}).get("aes_key", "")
            elif msg_type == 3:
                voice_item = item.get("voice_item", {})
                result["type"] = "voice"
                result["content"] = voice_item.get("media", {}).get("full_url", "")
                result["media_id"] = voice_item.get("media", {}).get("aes_key", "")
            elif msg_type == 4:
                file_item = item.get("file_item", {})
                result["type"] = "file"
                result["content"] = file_item.get("media", {}).get("full_url", "")
                result["file_name"] = file_item.get("file_name", "")
            elif msg_type == 5:
                video_item = item.get("video_item", {})
                result["type"] = "video"
                result["content"] = video_item.get("media", {}).get("full_url", "")
                result["media_id"] = video_item.get("media", {}).get("aes_key", "")
            
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

def save_qrcode_status(qrcode_status: dict):
    """将 qrcode_status 保存到本地文件"""
    # 确保文件存在
    os.makedirs(os.path.dirname(QRCODE_STATUS_PATH), exist_ok=True)
    data = {
        "baseurl": qrcode_status.get("baseurl", ""),
        "bot_token": qrcode_status.get("bot_token", ""),
        "ilink_bot_id": qrcode_status.get("ilink_bot_id", ""),
        "ilink_user_id": qrcode_status.get("ilink_user_id", ""),
        "saved_at": datetime.now().isoformat()
    }
    with open(QRCODE_STATUS_PATH, "w") as f:
        json.dump(data, f, indent=2)
    print(f"qrcode_status 已保存到 {QRCODE_STATUS_PATH}")

def load_qrcode_status():
    """从本地文件加载 qrcode_status"""
    if os.path.exists(QRCODE_STATUS_PATH):
        with open(QRCODE_STATUS_PATH, "r") as f:
            print(f"qrcode_status 已从 {QRCODE_STATUS_PATH} 加载")
            return json.load(f)
    print(f"未找到有效的 qrcode_status 文件")
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
            # 获取 qrcode_status 并保存
            bot_token = result.get("bot_token", "")
            print(f"================ 8888888888888888 =====================")
            print(f"================ /ilink/bot/get_qrcode_status result: {result} =====================")
            print(f"登录成功, bot_token: {bot_token}")
            return result
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
    # 1. 检查是否有保存的 qrcode_status
    qrcode_status = load_qrcode_status()

    if qrcode_status:
        # 验证 bot_token 是否有效
        config = await get_bot_info(qrcode_status.get("bot_token"))
        if config:
            print(f"使用已保存的 qrcode_status: {qrcode_status}, 机器人名称: {config['bot_name']}")
            await run_bot(qrcode_status.get("bot_token"))
            return
        
    # 2. 如果没有 bot_token 或 bot_token 无效, 需要扫码登录
    if not qrcode:
        print("bot_token 无效, 需要扫码登录")
        return
    
    # 3. 轮询等待扫码确认
    qrcode_status = await poll_login_status(qrcode)

    if not qrcode_status:
        print(f"登录失败, 无法获取 qrcode_status")
        return
    
    # 4. 保存 qrcode_status 到本地
    save_qrcode_status(qrcode_status)

    # 5. 获取配置并启动机器人
    config = await get_bot_info(qrcode_status.get("bot_token"))
    if config:
        print(f"登录成功, 机器人名称: {config['bot_name']}")

    await run_bot(qrcode_status.get("bot_token"))