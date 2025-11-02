#!/usr/bin/env python3
"""
空投飞书通知模块
专门用于发送空投提醒的飞书消息
"""

import json
import requests
import time
from typing import Dict, List, Any, Optional
from datetime import datetime
from dataclasses import dataclass
from web_catch import AirdropInfo


@dataclass
class FeishuConfig:
    """飞书配置"""
    webhook_url: str
    timeout: int = 10
    retry_times: int = 3
    retry_delay: float = 1.0


class AirdropNotifier:
    """空投飞书通知器"""
    
    def __init__(self, webhook_url: str, timeout: int = 10):
        """
        初始化空投通知器
        
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
            'User-Agent': 'AirdropMonitor-FeishuBot/1.0'
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

    def send_rich_text(self, title: str, content: List[List[Dict[str, Any]]]) -> bool:
        """
        发送富文本消息
        
        Args:
            title: 消息标题
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

    def send_airdrop_reminder(self, airdrop: AirdropInfo, reminder_type: str) -> bool:
        """
        发送空投提醒消息
        
        Args:
            airdrop: 空投信息
            reminder_type: 提醒类型 ("3小时前" 或 "1小时前")
            
        Returns:
            是否发送成功
        """
        # 确定提醒图标和颜色
        if reminder_type == "3小时前":
            reminder_emoji = "⏰"
            urgency_emoji = "🔔"
        else:  # 1小时前
            reminder_emoji = "🚨"
            urgency_emoji = "⚡"
        
        # 确定空投类型图标
        type_emoji = "🎯" if airdrop.type == "tge" else "🎁"
        
        # 构建富文本内容
        content = []
        
        # 标题行
        content.append([
            {"tag": "text", "text": f"{urgency_emoji} 空投提醒 - {reminder_type}"}
        ])
        
        content.append([{"tag": "text", "text": ""}])  # 空行
        
        # 项目信息
        content.append([
            {"tag": "text", "text": f"{type_emoji} 项目: {airdrop.name or '未知项目'}"}
        ])
        
        if airdrop.token:
            content.append([
                {"tag": "text", "text": f"🏷️ 代币: {airdrop.token}"}
            ])
        
        # 时间信息
        content.append([
            {"tag": "text", "text": f"📅 日期: {airdrop.date}"}
        ])
        
        content.append([
            {"tag": "text", "text": f"{reminder_emoji} 时间: {airdrop.time}"}
        ])
        
        # 空投详情
        if airdrop.points and airdrop.points != "-":
            content.append([
                {"tag": "text", "text": f"⭐ 积分: {airdrop.points}"}
            ])
        
        if airdrop.amount and airdrop.amount != "-":
            content.append([
                {"tag": "text", "text": f"💰 数量: {airdrop.amount}"}
            ])
        # 可选显示USD估值或价格
        if getattr(airdrop, 'amount_usd', None) is not None:
            content.append([
                {"tag": "text", "text": f"💵 估值: ${airdrop.amount_usd}"}
            ])
        elif getattr(airdrop, 'price', None) is not None or getattr(airdrop, 'dex_price', None) is not None:
            price_str = f"${getattr(airdrop, 'price'):.4f}" if getattr(airdrop, 'price', None) is not None else ""
            dex_str = f" (DEX ${getattr(airdrop, 'dex_price'):.4f})" if getattr(airdrop, 'dex_price', None) is not None else ""
            content.append([
                {"tag": "text", "text": f"💵 价格: {price_str}{dex_str}"}
            ])
        
        # 状态和类型
        status_emoji = "✅" if airdrop.status == "announced" else "⏳"
        content.append([
            {"tag": "text", "text": f"{status_emoji} 状态: {airdrop.status}"}
        ])
        
        content.append([
            {"tag": "text", "text": f"📋 类型: {airdrop.type}"}
        ])
        
        # 分隔线
        content.append([{"tag": "text", "text": ""}])  # 空行
        content.append([
            {"tag": "text", "text": "━━━━━━━━━━━━━━━━━━━━"}
        ])
        
        # 提醒信息
        if reminder_type == "3小时前":
            content.append([
                {"tag": "text", "text": "💡 距离空投还有3小时，请提前准备！"}
            ])
        else:
            content.append([
                {"tag": "text", "text": "🔥 距离空投还有1小时，请立即准备！"}
            ])
        
        # 时间戳
        content.append([{"tag": "text", "text": ""}])  # 空行
        content.append([
            {"tag": "text", "text": f"⏰ 提醒时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"}
        ])
        
        # 发送消息
        title = f"{urgency_emoji} 空投{reminder_type}提醒"
        return self.send_rich_text(title, content)

    def send_daily_summary(self, today_airdrops: List[AirdropInfo], upcoming_airdrops: List[AirdropInfo]) -> bool:
        """
        发送每日空投汇总
        
        Args:
            today_airdrops: 今日空投列表
            upcoming_airdrops: 即将到来的空投列表
            
        Returns:
            是否发送成功
        """
        content = []
        
        # 标题
        content.append([
            {"tag": "text", "text": "📊 每日空投汇总"}
        ])
        
        content.append([{"tag": "text", "text": ""}])  # 空行
        
        # 今日空投
        content.append([
            {"tag": "text", "text": f"🎯 今日空投 ({len(today_airdrops)}个)"}
        ])
        
        if today_airdrops:
            for airdrop in today_airdrops[:5]:  # 最多显示5个
                type_emoji = "🎯" if airdrop.type == "tge" else "🎁"
                # 价格/估值信息（有则附加）
                price_suffix = ""
                if getattr(airdrop, 'amount_usd', None) is not None:
                    price_suffix = f"  💵 ${airdrop.amount_usd}"
                else:
                    price = getattr(airdrop, 'price', None)
                    dex_price = getattr(airdrop, 'dex_price', None)
                    if price is not None or dex_price is not None:
                        base = f"${price:.4f}" if price is not None else ""
                        dex = f" (DEX ${dex_price:.4f})" if dex_price is not None else ""
                        price_suffix = f"  💵 {base}{dex}"
                content.append([
                    {"tag": "text", "text": f"  {type_emoji} {airdrop.name or airdrop.token} - {airdrop.time}{price_suffix}"}
                ])
        else:
            content.append([
                {"tag": "text", "text": "  暂无今日空投"}
            ])
        
        content.append([{"tag": "text", "text": ""}])  # 空行
        
        # 即将到来的空投
        content.append([
            {"tag": "text", "text": f"⏰ 即将到来 ({len(upcoming_airdrops)}个)"}
        ])
        
        if upcoming_airdrops:
            for airdrop in upcoming_airdrops[:5]:  # 最多显示5个
                type_emoji = "🎯" if airdrop.type == "tge" else "🎁"
                price_suffix = ""
                if getattr(airdrop, 'amount_usd', None) is not None:
                    price_suffix = f"  💵 ${airdrop.amount_usd}"
                else:
                    price = getattr(airdrop, 'price', None)
                    dex_price = getattr(airdrop, 'dex_price', None)
                    if price is not None or dex_price is not None:
                        base = f"${price:.4f}" if price is not None else ""
                        dex = f" (DEX ${dex_price:.4f})" if dex_price is not None else ""
                        price_suffix = f"  💵 {base}{dex}"
                content.append([
                    {"tag": "text", "text": f"  {type_emoji} {airdrop.name or airdrop.token} - {airdrop.date} {airdrop.time}{price_suffix}"}
                ])
        else:
            content.append([
                {"tag": "text", "text": "  暂无即将到来的空投"}
            ])
        
        # 时间戳
        content.append([{"tag": "text", "text": ""}])  # 空行
        content.append([
            {"tag": "text", "text": f"⏰ 汇总时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"}
        ])
        
        return self.send_rich_text("📊 每日空投汇总", content)

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
            {"tag": "text", "text": "❌ 空投监控错误警报", "style": ["bold"]}
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
        test_message = f"🧪 空投监控飞书推送测试 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        return self.send_text(test_message)


def create_airdrop_notifier(webhook_url: str) -> AirdropNotifier:
    """
    创建空投通知器实例
    
    Args:
        webhook_url: webhook地址
        
    Returns:
        空投通知器实例
    """
    return AirdropNotifier(webhook_url)


if __name__ == "__main__":
    # 测试代码
    from config_loader import load_config
    
    print("🧪 空投飞书通知模块测试")
    
    try:
        # 加载配置
        config = load_config()
        notifier = AirdropNotifier(config.feishu_webhook_url)
        
        # 测试连接
        print("测试连接...")
        if notifier.test_connection():
            print("✅ 连接测试成功")
            
            # 测试空投提醒
            print("测试空投提醒...")
            test_airdrop = AirdropInfo(
                name="测试空投项目",
                token="TEST",
                points="100",
                amount="500",
                time="20:00",
                date="2025-10-30",
                status="announced",
                type="tge"
            )
            
            if notifier.send_airdrop_reminder(test_airdrop, "3小时前"):
                print("✅ 空投提醒测试成功")
            else:
                print("❌ 空投提醒测试失败")
        else:
            print("❌ 连接测试失败")
            
    except Exception as e:
        print(f"❌ 测试失败: {e}")