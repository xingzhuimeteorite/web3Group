#!/usr/bin/env python3
"""
飞书推送调试脚本
用于调试飞书消息格式问题
"""

import json
import requests
from config_loader import load_config

def debug_feishu_request():
    """调试飞书请求"""
    print("🔍 开始调试飞书请求...")
    
    # 加载配置
    config = load_config()
    webhook_url = config.feishu.webhook_url
    
    print(f"Webhook URL: {webhook_url}")
    
    # 测试简单文本消息
    print("\n📝 测试简单文本消息...")
    text_payload = {
        "msg_type": "text",
        "content": {
            "text": "🧪 调试测试 - 简单文本消息"
        }
    }
    
    print(f"请求数据: {json.dumps(text_payload, indent=2, ensure_ascii=False)}")
    
    try:
        response = requests.post(
            webhook_url,
            json=text_payload,
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        print(f"响应状态码: {response.status_code}")
        print(f"响应内容: {response.text}")
        print(f"响应JSON: {response.json()}")
    except Exception as e:
        print(f"请求失败: {e}")
    
    # 测试富文本消息
    print("\n📄 测试富文本消息...")
    rich_payload = {
        "msg_type": "post",
        "content": {
            "post": {
                "zh-CN": {
                    "title": "调试测试富文本",
                    "content": [
                        [{"tag": "text", "text": "这是一条测试富文本消息"}],
                        [{"tag": "text", "text": "包含多行内容"}]
                    ]
                }
            }
        }
    }
    
    print(f"请求数据: {json.dumps(rich_payload, indent=2, ensure_ascii=False)}")
    
    try:
        response = requests.post(
            webhook_url,
            json=rich_payload,
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        print(f"响应状态码: {response.status_code}")
        print(f"响应内容: {response.text}")
        print(f"响应JSON: {response.json()}")
    except Exception as e:
        print(f"请求失败: {e}")

if __name__ == "__main__":
    debug_feishu_request()