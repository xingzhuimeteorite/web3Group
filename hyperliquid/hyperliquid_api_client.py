#!/usr/bin/env python3
"""
Hyperliquid 官方 API 客户端
基于官方文档实现核心功能
"""

import requests
import json
import time
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from config import HYPERLIQUID_API_BASE_URL, REQUEST_CONFIG


@dataclass
class UserPosition:
    """用户仓位信息"""
    user_address: str
    coin: str
    position_size: float  # 正数为多头，负数为空头
    entry_price: float
    mark_price: float
    liquidation_price: Optional[float]
    leverage: float
    margin_used: float
    position_value_usd: float
    unrealized_pnl: float
    unrealized_pnl_percentage: float
    funding_fee: float
    margin_mode: str  # cross 或 isolated


class HyperliquidAPIClient:
    """Hyperliquid 官方 API 客户端"""
    
    def __init__(self, base_url: str = None, timeout: int = None):
        self.base_url = base_url or HYPERLIQUID_API_BASE_URL
        self.timeout = timeout or REQUEST_CONFIG.get("timeout", 10)
        self.session = requests.Session()
        
        # 设置请求头
        self.session.headers.update({
            'Content-Type': 'application/json',
            'User-Agent': 'HyperliquidWhaleMonitor/1.0'
        })
    
    def _request(self, method: str, endpoint: str, data: Dict = None) -> Dict[str, Any]:
        """发送 API 请求"""
        url = f"{self.base_url}{endpoint}"
        
        try:
            if method.upper() == 'POST':
                response = self.session.post(url, json=data, timeout=self.timeout)
            else:
                response = self.session.get(url, params=data, timeout=self.timeout)
            
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.RequestException as e:
            print(f"❌ API 请求失败: {e}")
            return {}
        except json.JSONDecodeError as e:
            print(f"❌ JSON 解析失败: {e}")
            return {}
    
    def get_user_positions(self, user_address: str) -> List[UserPosition]:
        """获取用户的所有仓位信息"""
        data = {
            "type": "clearinghouseState",
            "user": user_address
        }
        
        response = self._request('POST', '/info', data)
        
        if not response or 'assetPositions' not in response:
            return []
        
        positions = []
        
        for asset_position in response.get('assetPositions', []):
            position_data = asset_position.get('position', {})
            
            if not position_data or float(position_data.get('szi', 0)) == 0:
                continue  # 跳过空仓位
            
            # 计算仓位价值
            position_size = float(position_data.get('szi', 0))
            mark_price = float(position_data.get('entryPx', 0))  # 使用入场价作为标记价格的近似
            position_value = abs(position_size * mark_price)
            
            # 计算未实现盈亏百分比
            unrealized_pnl = float(position_data.get('unrealizedPnl', 0))
            pnl_percentage = 0.0
            if position_value > 0:
                pnl_percentage = unrealized_pnl / position_value
            
            position = UserPosition(
                user_address=user_address,
                coin=position_data.get('coin', ''),
                position_size=position_size,
                entry_price=float(position_data.get('entryPx', 0)),
                mark_price=mark_price,  # 需要从其他接口获取实时价格
                liquidation_price=float(position_data.get('liquidationPx', 0)) if position_data.get('liquidationPx') else None,
                leverage=float(position_data.get('leverage', {}).get('value', 1)),
                margin_used=float(position_data.get('marginUsed', 0)),
                position_value_usd=position_value,
                unrealized_pnl=unrealized_pnl,
                unrealized_pnl_percentage=pnl_percentage,
                funding_fee=float(position_data.get('cumFunding', {}).get('allTime', 0)),
                margin_mode=position_data.get('leverage', {}).get('type', 'cross')
            )
            
            positions.append(position)
        
        return positions
    
    def get_market_prices(self) -> Dict[str, float]:
        """获取所有市场的当前价格"""
        data = {"type": "metaAndAssetCtxs"}
        
        response = self._request('POST', '/info', data)
        
        if not response or len(response) < 2:
            return {}
        
        prices = {}
        
        # 获取币种信息
        meta_info = response[0]
        asset_contexts = response[1]
        
        universe = meta_info.get('universe', [])
        
        for i, coin_info in enumerate(universe):
            coin_name = coin_info.get('name', '')
            if i < len(asset_contexts) and coin_name:
                asset_ctx = asset_contexts[i]
                mark_price = float(asset_ctx.get('markPx', 0))
                if mark_price > 0:
                    prices[coin_name] = mark_price
        
        return prices
    
    def get_user_positions_with_current_prices(self, user_address: str) -> List[UserPosition]:
        """获取用户仓位信息并更新当前市场价格"""
        positions = self.get_user_positions(user_address)
        
        if not positions:
            return positions
        
        # 获取当前市场价格
        current_prices = self.get_market_prices()
        
        # 更新仓位的当前价格和PnL
        for position in positions:
            if position.coin in current_prices:
                current_price = current_prices[position.coin]
                position.mark_price = current_price
                
                # 重新计算仓位价值和PnL
                position.position_value_usd = abs(position.position_size * current_price)
                
                # 计算未实现盈亏
                if position.position_size > 0:  # 多头
                    position.unrealized_pnl = (current_price - position.entry_price) * position.position_size
                else:  # 空头
                    position.unrealized_pnl = (position.entry_price - current_price) * abs(position.position_size)
                
                # 计算PnL百分比
                if position.position_value_usd > 0:
                    position.unrealized_pnl_percentage = position.unrealized_pnl / position.position_value_usd
        
        return positions
    
    def get_leaderboard_addresses(self, limit: int = 100) -> List[str]:
        """
        获取排行榜地址（模拟实现）
        注意：Hyperliquid 官方 API 可能没有直接的排行榜接口
        这里提供一个框架，实际需要根据可用的接口调整
        """
        # 这是一个示例实现，实际可能需要通过其他方式获取地址
        # 比如：分析交易历史、从已知的大户地址开始等
        
        sample_addresses = [
            "0x5b5d2c60c060c060c060c060c060c060c060c060",  # 示例地址
            "0xc2a3e5f2e5f2e5f2e5f2e5f2e5f2e5f2e5f2e5f2",
            "0x5d2f9bb79bb79bb79bb79bb79bb79bb79bb79bb7",
            "0x4044794c794c794c794c794c794c794c794c794c",
            "0xb9fed365d365d365d365d365d365d365d365d365"
        ]
        
        return sample_addresses[:limit]
    
    def batch_get_positions(self, addresses: List[str]) -> Dict[str, List[UserPosition]]:
        """批量获取多个地址的仓位信息"""
        results = {}
        
        for address in addresses:
            try:
                positions = self.get_user_positions_with_current_prices(address)
                if positions:  # 只保存有仓位的地址
                    results[address] = positions
                
                # 添加延迟避免触发速率限制
                time.sleep(0.1)
                
            except Exception as e:
                print(f"⚠️ 获取地址 {address} 仓位失败: {e}")
                continue
        
        return results
    
    def find_whale_positions(self, min_position_value: float = 1000000) -> Dict[str, List[UserPosition]]:
        """发现巨鲸仓位（基于已知地址列表）"""
        # 获取地址列表
        addresses = self.get_leaderboard_addresses()
        
        # 批量获取仓位
        all_positions = self.batch_get_positions(addresses)
        
        # 筛选巨鲸仓位
        whale_positions = {}
        
        for address, positions in all_positions.items():
            whale_positions_for_address = []
            
            for position in positions:
                if position.position_value_usd >= min_position_value:
                    whale_positions_for_address.append(position)
            
            if whale_positions_for_address:
                whale_positions[address] = whale_positions_for_address
        
        return whale_positions
    
    def get_account_summary(self, user_address: str) -> Dict[str, Any]:
        """获取账户摘要信息"""
        data = {
            "type": "clearinghouseState",
            "user": user_address
        }
        
        response = self._request('POST', '/info', data)
        
        if not response:
            return {}
        
        margin_summary = response.get('marginSummary', {})
        
        return {
            'account_value': float(margin_summary.get('accountValue', 0)),
            'total_margin_used': float(margin_summary.get('totalMarginUsed', 0)),
            'total_position_value': float(margin_summary.get('totalNtlPos', 0)),
            'withdrawable': float(response.get('withdrawable', 0)),
            'position_count': len(response.get('assetPositions', []))
        }


if __name__ == "__main__":
    # 测试代码
    client = HyperliquidAPIClient()
    
    # 测试获取市场价格
    print("🔍 获取市场价格...")
    prices = client.get_market_prices()
    print(f"获取到 {len(prices)} 个币种价格")
    
    # 显示前几个价格
    for i, (coin, price) in enumerate(list(prices.items())[:5]):
        print(f"  {coin}: ${price:.4f}")
    
    print("\n🐋 搜索巨鲸仓位...")
    whale_positions = client.find_whale_positions(min_position_value=100000)  # 10万美元以上
    
    if whale_positions:
        print(f"发现 {len(whale_positions)} 个巨鲸地址")
        for address, positions in whale_positions.items():
            print(f"\n📍 地址: {address[:10]}...")
            for pos in positions:
                print(f"  {pos.coin}: ${pos.position_value_usd:,.2f} ({pos.position_size:+.4f})")
    else:
        print("未发现巨鲸仓位")