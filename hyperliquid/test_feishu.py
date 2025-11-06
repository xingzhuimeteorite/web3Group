#!/usr/bin/env python3
"""
飞书推送测试脚本
用于测试飞书消息格式是否正确
"""

import json
from feishu_notifier import FeishuNotifier
from config_loader import load_config

def test_simple_message():
    """测试简单文本消息"""
    print("🧪 测试简单文本消息...")
    
    # 加载配置
    config = load_config()
    notifier = FeishuNotifier(config.feishu.webhook_url)
    
    # 发送简单消息
    result = notifier.send_text("🧪 飞书推送测试 - 简单文本消息")
    print(f"结果: {'✅ 成功' if result else '❌ 失败'}")
    return result

def test_rich_text_message():
    """测试富文本消息"""
    print("🧪 测试富文本消息...")
    
    # 加载配置
    config = load_config()
    notifier = FeishuNotifier(config.feishu.webhook_url)
    
    # 构建简单的富文本内容（移除style属性）
    content = [
        [{"tag": "text", "text": "🧪 飞书推送测试"}],
        [{"tag": "text", "text": "这是一条测试富文本消息"}],
        [{"tag": "text", "text": "包含多行内容和格式"}]
    ]
    
    result = notifier.send_rich_text("测试富文本", content)
    print(f"结果: {'✅ 成功' if result else '❌ 失败'}")
    return result

def test_whale_alert():
    """测试巨鲸警报消息"""
    print("🧪 测试巨鲸警报消息...")
    
    # 加载配置
    config = load_config()
    notifier = FeishuNotifier(config.feishu.webhook_url)
    
    # 模拟巨鲸数据
    whale_name = "测试巨鲸"
    address = "0x1234567890abcdef"
    total_value = 15000000.0
    total_pnl = -500000.0
    positions = [
        {
            'coin': 'ETH',
            'side': '多头',
            'position_value': 8000000.0,
            'unrealized_pnl': -200000.0
        },
        {
            'coin': 'BTC',
            'side': '空头',
            'position_value': 7000000.0,
            'unrealized_pnl': -300000.0
        }
    ]
    alerts = ["新增大额仓位", "PnL变化超过阈值"]
    
    result = notifier.send_whale_alert(
        whale_name, address, total_value, total_pnl, positions, alerts
    )
    print(f"结果: {'✅ 成功' if result else '❌ 失败'}")
    return result

def main():
    """主测试函数"""
    print("🚀 开始飞书推送测试...")
    print("=" * 50)
    
    # 测试简单消息
    test1 = test_simple_message()
    print()
    
    # 测试富文本消息
    test2 = test_rich_text_message()
    print()
    
    # 测试巨鲸警报
    test3 = test_whale_alert()
    print()
    
    # 汇总结果
    print("=" * 50)
    print("📊 测试结果汇总:")
    print(f"简单文本消息: {'✅ 成功' if test1 else '❌ 失败'}")
    print(f"富文本消息: {'✅ 成功' if test2 else '❌ 失败'}")
    print(f"巨鲸警报消息: {'✅ 成功' if test3 else '❌ 失败'}")
    
    if all([test1, test2, test3]):
        print("🎉 所有测试通过!")
    else:
        print("⚠️ 部分测试失败，请检查配置和网络连接")

if __name__ == "__main__":
    main()