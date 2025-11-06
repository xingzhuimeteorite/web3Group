#!/usr/bin/env python3
"""
测试手机端优化格式的飞书推送
展示优化前后的对比效果
"""

from feishu_notifier import FeishuNotifier
from config_loader import load_config

def test_mobile_optimized_format():
    """测试手机端优化格式"""
    print("📱 测试手机端优化格式的巨鲸警报...")
    
    # 加载配置
    config = load_config()
    notifier = FeishuNotifier(config.feishu.webhook_url)
    
    # 模拟真实的巨鲸数据 - 包含多个仓位
    whale_name = "千万级大户2"
    address = "0xcac1f7aa03f7ecda6a6a940e6477a5f72b975086"
    total_value = 85600000.0
    total_pnl = -125000.0
    
    positions = [
        {
            'coin': 'ETH',
            'side': '空头',
            'size': 15000.0000,
            'entry_price': 4152.08,
            'mark_price': 4158.30,
            'liquidation_price': 6682.35,
            'leverage': 2.5,
            'position_value': 62372500.0,
            'unrealized_pnl': -93450.0,
            'pnl_percentage': -0.15
        },
        {
            'coin': 'BTC',
            'side': '多头',
            'size': 250.5000,
            'entry_price': 67800.00,
            'mark_price': 67650.00,
            'liquidation_price': 45200.00,
            'leverage': 3.2,
            'position_value': 16948250.0,
            'unrealized_pnl': -37575.0,
            'pnl_percentage': -0.22
        },
        {
            'coin': 'SOL',
            'side': '多头',
            'size': 25000.0000,
            'entry_price': 245.60,
            'mark_price': 246.80,
            'liquidation_price': 180.50,
            'leverage': 4.0,
            'position_value': 6170000.0,
            'unrealized_pnl': 30000.0,
            'pnl_percentage': 0.49
        }
    ]
    
    alerts = [
        "ETH 空头仓位 $62,372,500",
        "PnL -$125,000",
        "新增大额仓位"
    ]
    
    print("\n📊 发送的消息格式预览:")
    print("=" * 40)
    print(f"🐋 {whale_name}")
    print(f"📍 {address[:10]}...")
    print(f"💰 ${total_value:,.0f}")
    print(f"📉 ${total_pnl:,.0f}")
    print()
    print("🚨 警报")
    for alert in alerts[:2]:
        simplified_alert = alert.replace("大额单仓: ", "").replace("大额PnL: ", "PnL ")
        print(f"• {simplified_alert}")
    print()
    print("📊 主要仓位:")
    
    for pos in positions[:3]:
        side_emoji = "🟢" if pos['side'] == "多头" else "🔴"
        pnl_emoji = "📈" if pos['unrealized_pnl'] >= 0 else "📉"
        
        print(f"{side_emoji} {pos['side']} {pos['coin']} {pos['leverage']:.1f}x")
        print(f"💰 ${pos['position_value']:,.0f}")
        print(f"{pnl_emoji} ${pos['unrealized_pnl']:,.0f} ({pos['pnl_percentage']:+.1f}%)")
        print(f"📊 开仓: ${pos['entry_price']:.2f}")
        print(f"📍 当前: ${pos['mark_price']:.2f}")
        
        # 计算爆仓距离
        liquidation_distance = 0
        if pos['mark_price'] > 0 and pos['liquidation_price'] > 0:
            if pos['side'] == "多头":
                liquidation_distance = ((pos['liquidation_price'] - pos['mark_price']) / pos['mark_price']) * 100
            else:
                liquidation_distance = ((pos['mark_price'] - pos['liquidation_price']) / pos['mark_price']) * 100
        
        print(f"💥 爆仓: ${pos['liquidation_price']:.2f} ({abs(liquidation_distance):.1f}%)")
        if pos != positions[:3][-1]:
            print()
    
    print(f"\n⏰ {__import__('datetime').datetime.now().strftime('%H:%M:%S')}")
    print("=" * 40)
    
    # 发送实际消息
    result = notifier.send_whale_alert(
        whale_name, address, total_value, total_pnl, positions, alerts
    )
    
    print(f"\n飞书推送结果: {'✅ 成功' if result else '❌ 失败'}")
    
    if result:
        print("\n📱 手机端优化特点:")
        print("✅ 每行信息独立显示，避免水平滚动")
        print("✅ 使用简洁的表情符号和文本")
        print("✅ 重要信息突出显示")
        print("✅ 时间戳只显示时分秒")
        print("✅ 警报信息简化表达")
    
    return result

if __name__ == "__main__":
    test_mobile_optimized_format()