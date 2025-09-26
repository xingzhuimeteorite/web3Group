"""
Backpack Exchange 网格策略优化模块
提供网格策略的动态调整和执行效率优化功能
"""

import decimal
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
import statistics
import json


class GridOptimizer:
    """网格策略优化器"""
    
    def __init__(self, config):
        self.config = config
        self.price_history = []  # 价格历史记录
        self.grid_performance = {}  # 网格性能统计
        self.volatility_window = 50  # 波动率计算窗口
        self.performance_window = 100  # 性能统计窗口
        
        # 优化参数
        self.min_grid_interval = decimal.Decimal(str(config.get('trading_settings.min_grid_interval', 20)))
        self.max_grid_interval = decimal.Decimal(str(config.get('trading_settings.max_grid_interval', 100)))
        self.volatility_threshold_low = 0.02  # 低波动率阈值
        self.volatility_threshold_high = 0.08  # 高波动率阈值
        
    def update_price_history(self, price: decimal.Decimal, timestamp: datetime = None):
        """更新价格历史"""
        if timestamp is None:
            timestamp = datetime.now()
            
        self.price_history.append({
            'price': price,
            'timestamp': timestamp
        })
        
        # 保持历史记录在合理范围内
        if len(self.price_history) > self.performance_window * 2:
            self.price_history = self.price_history[-self.performance_window:]
    
    def calculate_volatility(self) -> float:
        """计算价格波动率"""
        if len(self.price_history) < self.volatility_window:
            return 0.05  # 默认波动率
            
        recent_prices = [float(p['price']) for p in self.price_history[-self.volatility_window:]]
        
        # 计算对数收益率
        returns = []
        for i in range(1, len(recent_prices)):
            returns.append((recent_prices[i] - recent_prices[i-1]) / recent_prices[i-1])
        
        if not returns:
            return 0.05
            
        return statistics.stdev(returns) if len(returns) > 1 else 0.05
    
    def calculate_optimal_grid_interval(self, current_price: decimal.Decimal) -> decimal.Decimal:
        """根据市场波动率计算最优网格间距"""
        volatility = self.calculate_volatility()
        
        # 基于波动率调整网格间距
        if volatility < self.volatility_threshold_low:
            # 低波动率：使用较小的网格间距
            optimal_interval = self.min_grid_interval
        elif volatility > self.volatility_threshold_high:
            # 高波动率：使用较大的网格间距
            optimal_interval = self.max_grid_interval
        else:
            # 中等波动率：线性插值
            ratio = (volatility - self.volatility_threshold_low) / (self.volatility_threshold_high - self.volatility_threshold_low)
            optimal_interval = self.min_grid_interval + (self.max_grid_interval - self.min_grid_interval) * decimal.Decimal(str(ratio))
        
        # 确保间距是价格的合理比例
        price_based_interval = current_price * decimal.Decimal('0.01')  # 1%的价格变动
        optimal_interval = max(optimal_interval, price_based_interval)
        
        return optimal_interval
    
    def update_grid_performance(self, grid_id: str, action: str, profit: decimal.Decimal = None):
        """更新网格性能统计"""
        if grid_id not in self.grid_performance:
            self.grid_performance[grid_id] = {
                'trades': 0,
                'successful_trades': 0,
                'total_profit': decimal.Decimal('0'),
                'last_activity': datetime.now(),
                'efficiency_score': 0.0
            }
        
        grid_stats = self.grid_performance[grid_id]
        grid_stats['last_activity'] = datetime.now()
        
        if action == 'trade_completed':
            grid_stats['trades'] += 1
            grid_stats['successful_trades'] += 1
            if profit is not None:
                grid_stats['total_profit'] += profit
        elif action == 'trade_failed':
            grid_stats['trades'] += 1
        
        # 计算效率分数
        if grid_stats['trades'] > 0:
            success_rate = grid_stats['successful_trades'] / grid_stats['trades']
            avg_profit = float(grid_stats['total_profit']) / grid_stats['successful_trades'] if grid_stats['successful_trades'] > 0 else 0
            grid_stats['efficiency_score'] = success_rate * max(0, avg_profit * 1000)  # 放大利润影响
    
    def get_grid_recommendations(self, current_price: decimal.Decimal, num_grids: int) -> Dict:
        """获取网格配置建议"""
        optimal_interval = self.calculate_optimal_grid_interval(current_price)
        volatility = self.calculate_volatility()
        
        # 计算建议的网格数量
        if volatility > self.volatility_threshold_high:
            recommended_grids = max(2, num_grids - 1)  # 高波动率时减少网格数量
        elif volatility < self.volatility_threshold_low:
            recommended_grids = min(10, num_grids + 1)  # 低波动率时增加网格数量
        else:
            recommended_grids = num_grids
        
        # 计算建议的订单金额调整
        if volatility > self.volatility_threshold_high:
            order_size_multiplier = 0.8  # 高波动率时减少单笔订单金额
        elif volatility < self.volatility_threshold_low:
            order_size_multiplier = 1.2  # 低波动率时增加单笔订单金额
        else:
            order_size_multiplier = 1.0
        
        return {
            'optimal_grid_interval': optimal_interval,
            'recommended_num_grids': recommended_grids,
            'order_size_multiplier': order_size_multiplier,
            'current_volatility': volatility,
            'volatility_level': self._get_volatility_level(volatility),
            'should_adjust': abs(float(optimal_interval) - float(self.config.get('trading_settings.grid_price_interval', 40))) > 5
        }
    
    def _get_volatility_level(self, volatility: float) -> str:
        """获取波动率水平描述"""
        if volatility < self.volatility_threshold_low:
            return "LOW"
        elif volatility > self.volatility_threshold_high:
            return "HIGH"
        else:
            return "MEDIUM"
    
    def should_realign_grids(self, current_price: decimal.Decimal, active_grids: Dict, 
                           current_interval: decimal.Decimal) -> Tuple[bool, str]:
        """判断是否需要重新调整网格"""
        recommendations = self.get_grid_recommendations(current_price, len(active_grids))
        
        # 检查间距是否需要调整
        optimal_interval = recommendations['optimal_grid_interval']
        interval_diff_pct = abs(float(optimal_interval - current_interval)) / float(current_interval)
        
        if interval_diff_pct > 0.2:  # 间距差异超过20%
            return True, f"网格间距需要调整：当前 {current_interval}，建议 {optimal_interval:.0f}"
        
        # 检查网格数量是否需要调整
        if recommendations['recommended_num_grids'] != len(active_grids):
            return True, f"网格数量需要调整：当前 {len(active_grids)}，建议 {recommendations['recommended_num_grids']}"
        
        # 检查网格性能
        inactive_grids = self._find_inactive_grids()
        if len(inactive_grids) > len(active_grids) * 0.3:  # 超过30%的网格不活跃
            return True, f"发现 {len(inactive_grids)} 个不活跃网格，建议重新调整"
        
        return False, "网格配置良好，无需调整"
    
    def _find_inactive_grids(self) -> List[str]:
        """找出不活跃的网格"""
        inactive_grids = []
        cutoff_time = datetime.now() - timedelta(hours=2)  # 2小时内无活动视为不活跃
        
        for grid_id, stats in self.grid_performance.items():
            if stats['last_activity'] < cutoff_time and stats['efficiency_score'] < 1.0:
                inactive_grids.append(grid_id)
        
        return inactive_grids
    
    def get_optimization_summary(self) -> Dict:
        """获取优化摘要"""
        volatility = self.calculate_volatility()
        total_grids = len(self.grid_performance)
        active_grids = len([g for g in self.grid_performance.values() 
                           if g['last_activity'] > datetime.now() - timedelta(hours=1)])
        
        total_profit = sum(stats['total_profit'] for stats in self.grid_performance.values())
        total_trades = sum(stats['trades'] for stats in self.grid_performance.values())
        successful_trades = sum(stats['successful_trades'] for stats in self.grid_performance.values())
        
        success_rate = successful_trades / total_trades if total_trades > 0 else 0
        
        return {
            'current_volatility': volatility,
            'volatility_level': self._get_volatility_level(volatility),
            'total_grids_tracked': total_grids,
            'active_grids_1h': active_grids,
            'total_profit': float(total_profit),
            'total_trades': total_trades,
            'success_rate': success_rate,
            'avg_profit_per_trade': float(total_profit) / successful_trades if successful_trades > 0 else 0
        }
    
    def export_performance_data(self, filepath: str):
        """导出性能数据"""
        data = {
            'timestamp': datetime.now().isoformat(),
            'price_history': [{'price': float(p['price']), 'timestamp': p['timestamp'].isoformat()} 
                             for p in self.price_history[-100:]],  # 最近100个价格点
            'grid_performance': {k: {
                'trades': v['trades'],
                'successful_trades': v['successful_trades'],
                'total_profit': float(v['total_profit']),
                'last_activity': v['last_activity'].isoformat(),
                'efficiency_score': v['efficiency_score']
            } for k, v in self.grid_performance.items()},
            'optimization_summary': self.get_optimization_summary()
        }
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)