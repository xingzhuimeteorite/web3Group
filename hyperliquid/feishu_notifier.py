#!/usr/bin/env python3
"""
飞书群机器人推送模块
支持向飞书群发送各种类型的消息通知
"""

import json
import requests
import time
from typing import Dict, List, Any, Optional
from datetime import datetime
from dataclasses import dataclass


@dataclass
class FeishuConfig:
    """飞书配置"""
    webhook_url: str
    timeout: int = 10
    retry_times: int = 3
    retry_delay: float = 1.0


class FeishuNotifier:
    """飞书群机器人推送器"""
    
    def __init__(self, webhook_url: str, timeout: int = 10):
        """
        初始化飞书推送器
        
        Args:
            webhook_url: 飞书群机器人的webhook地址
            timeout: 请求超时时间（秒）
        """
        self.webhook_url = webhook_url
        self.timeout = timeout
        self.session = requests.Session()
        
        # 设置请求头
        self.session.headers.update({
            'Content-Type': 'application/json',
            'User-Agent': 'WhaleMonitor-FeishuBot/1.0'
        })
        
    def _send_request(self, payload: Dict[str, Any], retry_times: int = 3) -> bool:
        """
        发送请求到飞书
        
        Args:
            payload: 消息载荷
            retry_times: 重试次数
            
        Returns:
            是否发送成功
        """
        for attempt in range(retry_times):
            try:
                response = self.session.post(
                    self.webhook_url,
                    json=payload,
                    timeout=self.timeout
                )
                
                if response.status_code == 200:
                    result = response.json()
                    # 检查多种可能的成功状态
                    if (result.get('code') == 0 or 
                        result.get('StatusCode') == 0 or 
                        result.get('StatusMessage') == 'success'):
                        return True
                    else:
                        error_msg = (result.get('msg') or 
                                   result.get('StatusMessage') or 
                                   '未知错误')
                        print(f"❌ 飞书推送失败: {error_msg}")
                        return False
                else:
                    print(f"❌ HTTP请求失败: {response.status_code}")
                    
            except requests.exceptions.RequestException as e:
                print(f"❌ 网络请求异常 (尝试 {attempt + 1}/{retry_times}): {e}")
                if attempt < retry_times - 1:
                    time.sleep(1.0 * (attempt + 1))  # 递增延迟
                    
        return False
        
    def send_text(self, text: str) -> bool:
        """
        发送纯文本消息
        
        Args:
            text: 文本内容
            
        Returns:
            是否发送成功
        """
        payload = {
            "msg_type": "text",
            "content": {
                "text": text
            }
        }
        return self._send_request(payload)
        
    def send_rich_text(self, title: str, content: List[List[Dict]]) -> bool:
        """
        发送富文本消息
        
        Args:
            title: 标题
            content: 富文本内容
            
        Returns:
            是否发送成功
        """
        payload = {
            "msg_type": "post",
            "content": {
                "post": {
                    "zh-CN": {
                        "title": title,
                        "content": content
                    }
                }
            }
        }
        return self._send_request(payload)
        
    def send_whale_alert(self, whale_name: str, address: str, total_value: float, 
                        total_pnl: float, positions: List[Dict], alerts: List[str]) -> bool:
        """
        发送巨鲸警报消息
        
        Args:
            whale_name: 巨鲸名称
            address: 地址
            total_value: 总仓位价值
            total_pnl: 总PnL
            positions: 仓位列表
            alerts: 警报信息
            
        Returns:
            是否发送成功
        """
        # 打印即将发送的飞书消息内容到日志
        print("\n" + "="*80)
        print("📱 准备发送飞书警报")
        print("="*80)
        print(f"🏷️  巨鲸名称: {whale_name}")
        print(f"📍 地址: {address}")
        print(f"💰 总仓位价值: ${total_value:,.2f}")
        print(f"📊 总PnL: ${total_pnl:,.2f}")
        print(f"🚨 警报原因: {', '.join(alerts)}")
        print("\n📊 仓位详情:")
        if positions:
            # 只显示价值最大的一个仓位
            largest_position = max(positions, key=lambda x: abs(x['position_value']))
            side_emoji = "🟢" if largest_position['side'] == "多头" else "🔴"
            pnl_emoji = "📈" if largest_position['unrealized_pnl'] >= 0 else "📉"
            print(f"   {side_emoji} {largest_position['side']} {largest_position['coin']}")
            print(f"      💵 价值: ${largest_position['position_value']:,.0f}")
            print(f"      📏 数量: {largest_position['size']:,.4f}")
            print(f"      🎯 杠杆: {largest_position.get('leverage', 'N/A')}x")
            print(f"      {pnl_emoji} PnL: ${largest_position['unrealized_pnl']:,.0f} ({largest_position['pnl_percentage']:.1f}%)")
            print()
        else:
            print("   ⚪ 暂无活跃仓位")
        print("="*80)
        # 构建富文本内容
        content = []
        
        # 标题行 - 使用更简洁的格式
        content.append([
            {"tag": "text", "text": f"🐋 {whale_name}"}
        ])
        content.append([
            {"tag": "text", "text": f"📍 {address[:10]}..."}
        ])
        
        # 基本信息 - 分行显示更清晰
        pnl_emoji = "📈" if total_pnl >= 0 else "📉"
        pnl_color = "green" if total_pnl >= 0 else "red"
        
        content.append([
            {"tag": "text", "text": f"💰 ${total_value:,.0f}"}
        ])
        
        content.append([
            {"tag": "text", "text": f"{pnl_emoji} ${total_pnl:,.0f}"}
        ])
        
        # 警报信息 - 简化显示
        if alerts:
            content.append([{"tag": "text", "text": ""}])  # 空行
            content.append([{"tag": "text", "text": "🚨 警报"}])
            for alert in alerts[:2]:  # 最多显示2个警报，节省空间
                # 简化警报文本
                simplified_alert = alert.replace("大额单仓: ", "").replace("大额PnL: ", "PnL ")
                content.append([{"tag": "text", "text": f"• {simplified_alert}"}])
        
        # 主要仓位（只显示价值最大的一个仓位）
        if positions:
            content.append([{"tag": "text", "text": ""}])  # 空行
            content.append([{"tag": "text", "text": "📊 主要仓位:"}])
            
            # 只显示价值最大的一个仓位
            largest_position = max(positions, key=lambda x: abs(x['position_value']))
            pos = largest_position
            
            # 计算仓位大小
            position_size = pos.get('size', 0)
            entry_price = pos.get('entry_price', 0)
            mark_price = pos.get('mark_price', 0)
            leverage = pos.get('leverage', 1)
            liquidation_price = pos.get('liquidation_price', 0)
            
            # 计算爆仓距离百分比
            liquidation_distance = 0
            if mark_price > 0 and liquidation_price > 0:
                if pos['side'] == "多头":
                    liquidation_distance = ((liquidation_price - mark_price) / mark_price) * 100
                else:  # 空头
                    liquidation_distance = ((mark_price - liquidation_price) / mark_price) * 100
            
            # PnL百分比
            pnl_percentage = pos.get('pnl_percentage', 0)
            pnl_emoji = "📈" if pos['unrealized_pnl'] >= 0 else "📉"
            
            # 仓位标题行
            side_emoji = "🟢" if pos['side'] == "多头" else "🔴"
            content.append([
                {"tag": "text", "text": f"{side_emoji} {pos['side']} {pos['coin']} {leverage:.1f}x"}
            ])
            
            # 价值和PnL行
            content.append([
                {"tag": "text", "text": f"💰 ${pos['position_value']:,.0f}"}
            ])
            content.append([
                {"tag": "text", "text": f"{pnl_emoji} ${pos['unrealized_pnl']:,.0f} ({pnl_percentage:+.1f}%)"}
            ])
            
            # 价格信息行
            content.append([
                {"tag": "text", "text": f"📊 开仓: ${entry_price:.2f}"}
            ])
            content.append([
                {"tag": "text", "text": f"📍 当前: ${mark_price:.2f}"}
            ])
            
            # 爆仓价格行
            content.append([
                {"tag": "text", "text": f"💥 爆仓: ${liquidation_price:.2f} ({abs(liquidation_distance):.1f}%)"}
            ])
        
        # 时间戳 - 使用更简洁的格式
        content.append([{"tag": "text", "text": ""}])  # 空行
        content.append([
            {"tag": "text", "text": f"⏰ {datetime.now().strftime('%H:%M:%S')}"}
        ])
        
        return self.send_rich_text("🐋 巨鲸监控警报", content)
        
    def send_batch_summary(self, total_addresses: int, active_addresses: int, 
                          total_value: float, total_pnl: float, top_whales: List[Dict]) -> bool:
        """
        发送批量监控汇总消息
        
        Args:
            total_addresses: 总监控地址数
            active_addresses: 活跃地址数
            total_value: 总仓位价值
            total_pnl: 总PnL
            top_whales: 前几名巨鲸
            
        Returns:
            是否发送成功
        """
        content = []
        
        # 标题
        content.append([
            {"tag": "text", "text": "📊 巨鲸监控汇总报告"}
        ])
        
        # 统计信息
        content.append([{"tag": "text", "text": ""}])  # 空行
        content.append([
            {"tag": "text", "text": f"📈 监控地址: {total_addresses} 个 (活跃: {active_addresses} 个)"}
        ])
        
        content.append([
            {"tag": "text", "text": f"💰 总价值: ${total_value:,.2f}"}
        ])
        
        pnl_emoji = "📈" if total_pnl >= 0 else "📉"
        content.append([
            {"tag": "text", "text": f"{pnl_emoji} 总PnL: ${total_pnl:,.2f}"}
        ])
        
        # TOP巨鲸
        if top_whales:
            content.append([{"tag": "text", "text": ""}])  # 空行
            content.append([{"tag": "text", "text": "🏆 TOP巨鲸:"}])
            
            for i, whale in enumerate(top_whales[:5], 1):
                whale_emoji = "🐋" if whale.get('whale_level') == 'mega_whale' else "🐟"
                pnl_emoji = "📈" if whale['total_pnl'] >= 0 else "📉"
                
                content.append([
                    {"tag": "text", "text": f"  {i}. {whale_emoji} {whale['name'][:15]} "},
                    {"tag": "text", "text": f"${whale['total_position_value']:,.0f} "},
                    {"tag": "text", "text": f"{pnl_emoji} ${whale['total_pnl']:,.0f}"}
                ])
        
        # 时间戳
        content.append([{"tag": "text", "text": ""}])  # 空行
        content.append([
            {"tag": "text", "text": f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"}
        ])
        
        return self.send_rich_text("📊 巨鲸监控汇总", content)
        
    def send_error_alert(self, error_type: str, error_message: str, context: str = "") -> bool:
        """
        发送错误警报
        
        Args:
            error_type: 错误类型
            error_message: 错误消息
            context: 上下文信息
            
        Returns:
            是否发送成功
        """
        content = []
        
        content.append([
            {"tag": "text", "text": "❌ 系统错误警报", "style": ["bold"], "color": "red"}
        ])
        
        content.append([{"tag": "text", "text": ""}])  # 空行
        content.append([
            {"tag": "text", "text": f"🔍 错误类型: {error_type}"}
        ])
        
        content.append([
            {"tag": "text", "text": f"📝 错误信息: {error_message}"}
        ])
        
        if context:
            content.append([
                {"tag": "text", "text": f"🔧 上下文: {context}"}
            ])
        
        content.append([{"tag": "text", "text": ""}])  # 空行
        content.append([
            {"tag": "text", "text": f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"}
        ])
        
        return self.send_rich_text("❌ 系统错误", content)
        
    def test_connection(self) -> bool:
        """
        测试连接
        
        Returns:
            是否连接成功
        """
        test_message = f"🧪 飞书推送测试 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        return self.send_text(test_message)


def create_feishu_notifier(webhook_url: str) -> FeishuNotifier:
    """
    创建飞书推送器实例
    
    Args:
        webhook_url: webhook地址
        
    Returns:
        飞书推送器实例
    """
    return FeishuNotifier(webhook_url)


if __name__ == "__main__":
    # 测试代码
    print("🧪 飞书推送模块测试")
    
    # 注意：实际使用时需要替换为真实的webhook地址
    test_webhook = "https://open.feishu.cn/open-apis/bot/v2/hook/your-webhook-here"
    
    notifier = FeishuNotifier(test_webhook)
    
    # 测试连接
    print("测试连接...")
    if notifier.test_connection():
        print("✅ 连接测试成功")
    else:
        print("❌ 连接测试失败")