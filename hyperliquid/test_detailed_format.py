#!/usr/bin/env python3
"""
测试详细格式的飞书推送
"""

from feishu_notifier import FeishuNotifier
from config_loader import load_config

def test_detailed_whale_alert():
    """测试详细格式的巨鲸警报"""
    print("🧪 测试详细格式的巨鲸警报...")
    
    # 加载配置
    config = load_config()
    notifier = FeishuNotifier(config.feishu.webhook_url)
    
    # 模拟详细的巨鲸数据
    whale_name = "千万级大户"
    address = "0xcac1f7aa03f7ecda6a6a940e6477a5f72b975086"
    total_value = 41509000.0
    total_pnl = 11800.0
    
    positions = [
        {
            'coin': 'ETH',
            'side': '空头',
            'size': 10000.0000,
            'entry_price': 4152.08,
            'mark_price': 4150.90,
            'liquidation_price': 6682.35,
            'leverage': 2.0,
            'position_value': 41509000.0,
            'unrealized_pnl': 11800.0,
            'pnl_percentage': 0.028
        },
        {
            'coin': 'BTC',
            'side': '多头',
            'size': 150.5000,
            'entry_price': 67500.00,
            'mark_price': 67800.00,
            'liquidation_price': 45200.00,
            'leverage': 3.0,
            'position_value': 10203900.0,
            'unrealized_pnl': 45150.0,
            'pnl_percentage': 0.44
        }
    ]
    
    alerts = ["新增大额仓位", "仓位价值超过阈值"]
    
    result = notifier.send_whale_alert(
        whale_name, address, total_value, total_pnl, positions, alerts
    )
    
    print(f"结果: {'✅ 成功' if result else '❌ 失败'}")
    return result

if __name__ == "__main__":
    test_detailed_whale_alert()