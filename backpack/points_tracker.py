"""
Backpack Exchange 积分追踪和优化模块
基于官方积分系统规则实现交易积分的计算和优化
"""

import decimal
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import json

class BackpackPointsTracker:
    """Backpack Exchange 积分追踪器"""
    
    def __init__(self):
        self.trading_volume_24h = decimal.Decimal('0')
        self.trading_volume_weekly = decimal.Decimal('0')
        self.maker_volume = decimal.Decimal('0')
        self.taker_volume = decimal.Decimal('0')
        self.trade_count = 0
        self.estimated_points = decimal.Decimal('0')
        self.last_reset_time = datetime.now()
        
        # Backpack 积分系统参数（基于官方文档）
        self.points_config = {
            'volume_multiplier': decimal.Decimal('1.0'),  # 每1 USDC交易量 = 1积分
            'maker_bonus': decimal.Decimal('1.2'),        # Maker订单额外20%积分
            'taker_penalty': decimal.Decimal('0.8'),      # Taker订单减少20%积分
            'min_trade_for_points': decimal.Decimal('10'), # 最小交易量要求
            'weekly_distribution_day': 4,  # 周五分发积分 (0=周一)
        }
    
    def record_trade(self, volume_usdc: decimal.Decimal, is_maker: bool, 
                    trade_time: Optional[datetime] = None):
        """记录交易并计算积分"""
        if trade_time is None:
            trade_time = datetime.now()
            
        # 检查是否需要重置周期统计
        self._check_and_reset_periods(trade_time)
        
        # 更新交易统计
        self.trading_volume_24h += volume_usdc
        self.trading_volume_weekly += volume_usdc
        self.trade_count += 1
        
        if is_maker:
            self.maker_volume += volume_usdc
        else:
            self.taker_volume += volume_usdc
        
        # 计算本次交易积分
        trade_points = self._calculate_trade_points(volume_usdc, is_maker)
        self.estimated_points += trade_points
        
        return trade_points
    
    def _calculate_trade_points(self, volume_usdc: decimal.Decimal, is_maker: bool) -> decimal.Decimal:
        """计算单次交易积分"""
        if volume_usdc < self.points_config['min_trade_for_points']:
            return decimal.Decimal('0')
        
        base_points = volume_usdc * self.points_config['volume_multiplier']
        
        if is_maker:
            return base_points * self.points_config['maker_bonus']
        else:
            return base_points * self.points_config['taker_penalty']
    
    def _check_and_reset_periods(self, current_time: datetime):
        """检查并重置周期性统计"""
        # 重置24小时统计
        if (current_time - self.last_reset_time).days >= 1:
            self.trading_volume_24h = decimal.Decimal('0')
            self.last_reset_time = current_time
        
        # 重置周统计（每周五重置）
        if current_time.weekday() == self.points_config['weekly_distribution_day']:
            if (current_time - self.last_reset_time).days >= 7:
                self.trading_volume_weekly = decimal.Decimal('0')
                self.maker_volume = decimal.Decimal('0')
                self.taker_volume = decimal.Decimal('0')
                self.estimated_points = decimal.Decimal('0')
    
    def get_maker_ratio(self) -> decimal.Decimal:
        """获取Maker订单比例"""
        total_volume = self.maker_volume + self.taker_volume
        if total_volume == 0:
            return decimal.Decimal('0')
        return self.maker_volume / total_volume
    
    def get_points_summary(self) -> Dict:
        """获取积分统计摘要"""
        return {
            'estimated_points': float(self.estimated_points),
            'trading_volume_24h': float(self.trading_volume_24h),
            'trading_volume_weekly': float(self.trading_volume_weekly),
            'maker_volume': float(self.maker_volume),
            'taker_volume': float(self.taker_volume),
            'maker_ratio': float(self.get_maker_ratio()),
            'trade_count': self.trade_count,
            'points_per_dollar': float(self.estimated_points / self.trading_volume_weekly) if self.trading_volume_weekly > 0 else 0
        }
    
    def optimize_for_points(self, current_price: decimal.Decimal, 
                          grid_price_interval: decimal.Decimal) -> Dict:
        """为积分优化提供建议"""
        maker_ratio = self.get_maker_ratio()
        
        suggestions = {
            'prefer_maker_orders': maker_ratio < decimal.Decimal('0.7'),
            'suggested_order_type': 'limit' if maker_ratio < decimal.Decimal('0.7') else 'market',
            'price_adjustment': decimal.Decimal('0'),
            'reasoning': []
        }
        
        if maker_ratio < decimal.Decimal('0.5'):
            suggestions['price_adjustment'] = grid_price_interval * decimal.Decimal('0.1')
            suggestions['reasoning'].append("Maker比例过低，建议调整价格增加Maker订单")
        
        if self.trading_volume_weekly < decimal.Decimal('1000'):
            suggestions['reasoning'].append("周交易量较低，建议增加交易频率")
        
        return suggestions

    def save_to_file(self, filepath: str):
        """保存积分数据到文件"""
        data = {
            'timestamp': datetime.now().isoformat(),
            'points_summary': self.get_points_summary(),
            'config': {k: float(v) for k, v in self.points_config.items() if isinstance(v, decimal.Decimal)}
        }
        
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"保存积分数据失败: {e}")
    
    def load_from_file(self, filepath: str):
        """从文件加载积分数据"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                summary = data.get('points_summary', {})
                
                self.estimated_points = decimal.Decimal(str(summary.get('estimated_points', 0)))
                self.trading_volume_24h = decimal.Decimal(str(summary.get('trading_volume_24h', 0)))
                self.trading_volume_weekly = decimal.Decimal(str(summary.get('trading_volume_weekly', 0)))
                self.maker_volume = decimal.Decimal(str(summary.get('maker_volume', 0)))
                self.taker_volume = decimal.Decimal(str(summary.get('taker_volume', 0)))
                self.trade_count = summary.get('trade_count', 0)
                
        except Exception as e:
            print(f"加载积分数据失败: {e}")