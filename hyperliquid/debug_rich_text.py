#!/usr/bin/env python3
"""
调试飞书富文本消息格式
"""

import requests
import json
from config_loader import load_config

def test_rich_text_formats():
    """测试不同的富文本格式"""
    config = load_config()
    webhook_url = config.feishu.webhook_url
    
    print("🧪 测试飞书富文本格式...")
    
    # 测试1: 基本富文本（无style）
    print("\n1. 测试基本富文本（无style）...")
    payload1 = {
        "msg_type": "post",
        "content": {
            "post": {
                "zh-CN": {
                    "title": "测试标题1",
                    "content": [
                        [
                            {"tag": "text", "text": "🐋 "},
                            {"tag": "text", "text": "测试巨鲸"},
                            {"tag": "text", "text": " (0x1234567890...)"}
                        ],
                        [
                            {"tag": "text", "text": "💰 总价值: "},
                            {"tag": "text", "text": "$1,000,000.00"}
                        ]
                    ]
                }
            }
        }
    }
    
    response1 = requests.post(webhook_url, json=payload1, timeout=10)
    print(f"响应状态码: {response1.status_code}")
    print(f"响应内容: {response1.text}")
    
    # 测试2: 带style的富文本
    print("\n2. 测试带style的富文本...")
    payload2 = {
        "msg_type": "post",
        "content": {
            "post": {
                "zh-CN": {
                    "title": "测试标题2",
                    "content": [
                        [
                            {"tag": "text", "text": "🐋 "},
                            {"tag": "text", "text": "测试巨鲸", "style": ["bold"]},
                            {"tag": "text", "text": " (0x1234567890...)"}
                        ],
                        [
                            {"tag": "text", "text": "💰 总价值: "},
                            {"tag": "text", "text": "$1,000,000.00", "style": ["bold"]}
                        ]
                    ]
                }
            }
        }
    }
    
    response2 = requests.post(webhook_url, json=payload2, timeout=10)
    print(f"响应状态码: {response2.status_code}")
    print(f"响应内容: {response2.text}")
    
    # 测试3: 简化的富文本格式
    print("\n3. 测试简化的富文本格式...")
    payload3 = {
        "msg_type": "post",
        "content": {
            "post": {
                "zh-CN": {
                    "title": "测试标题3",
                    "content": [
                        [{"tag": "text", "text": "🐋 测试巨鲸 (0x1234567890...)"}],
                        [{"tag": "text", "text": "💰 总价值: $1,000,000.00"}],
                        [{"tag": "text", "text": "📈 PnL: $50,000.00"}]
                    ]
                }
            }
        }
    }
    
    response3 = requests.post(webhook_url, json=payload3, timeout=10)
    print(f"响应状态码: {response3.status_code}")
    print(f"响应内容: {response3.text}")

if __name__ == "__main__":
    test_rich_text_formats()