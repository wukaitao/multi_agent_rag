#!/user/bin/env python
"""
Hermes 网关启动脚本
启动后可以接收多平台消息
"""

import uvicorn
from hermes.hermes_integration import get_hermes_multi_agent_bridge

if __name__ == "__main__":
    """主进程执行"""
    print("=" * 60, "Hermes 多智能体网关", "=" * 60)
    print("Webhook 端点:")
    print("- 微信: http://localhost:8001/webhook/wechat")
    print("- 钉钉: http://localhost:8001/webhook/dingtalk")
    print("- 飞书: http://localhost:8001/webhook/feishu")
    print("- Telegram: http://localhost:8001/webhook/telegram")
    print("API端点:")
    print("- POST http://localhost:8001/api/chat")
    print("- GET http://localhost:8001/health")
    
    uvicorn.run(get_hermes_multi_agent_bridge().create_gateway_app(), host="0.0.0.0", port=8001)