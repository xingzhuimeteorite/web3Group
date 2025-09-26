"""
Backpack Exchange 增强日志记录和监控模块
提供详细的交易日志、性能监控和报告功能
"""

import os
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import decimal
from pathlib import Path


class EnhancedLogger:
    """增强的日志记录器"""
    
    def __init__(self, config):
        self.config = config
        self.log_dir = Path(config.get('logging.log_directory', 'logs'))
        self.log_dir.mkdir(exist_ok=True)
        
        # 设置不同类型的日志文件
        self.trade_log_file = self.log_dir / 'trade_detailed.log'
        self.performance_log_file = self.log_dir / 'performance.log'
        self.error_log_file = self.log_dir / 'errors.log'
        self.summary_log_file = self.log_dir / 'daily_summary.log'
        
        # 配置日志记录器
        self._setup_loggers()
        
        # 性能统计
        self.session_stats = {
            'start_time': datetime.now(),
            'total_trades': 0,
            'successful_trades': 0,
            'failed_trades': 0,
            'total_volume': decimal.Decimal('0'),
            'total_fees': decimal.Decimal('0'),
            'total_profit': decimal.Decimal('0'),
            'grid_activities': {},
            'error_count': 0,
            'warnings': []
        }
        
    def _setup_loggers(self):
        """设置不同类型的日志记录器"""
        # 交易日志记录器
        self.trade_logger = logging.getLogger('trade')
        self.trade_logger.setLevel(logging.INFO)
        trade_handler = logging.FileHandler(self.trade_log_file, encoding='utf-8')
        trade_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        trade_handler.setFormatter(trade_formatter)
        self.trade_logger.addHandler(trade_handler)
        
        # 性能日志记录器
        self.performance_logger = logging.getLogger('performance')
        self.performance_logger.setLevel(logging.INFO)
        perf_handler = logging.FileHandler(self.performance_log_file, encoding='utf-8')
        perf_formatter = logging.Formatter('%(asctime)s - %(message)s')
        perf_handler.setFormatter(perf_formatter)
        self.performance_logger.addHandler(perf_handler)
        
        # 错误日志记录器
        self.error_logger = logging.getLogger('error')
        self.error_logger.setLevel(logging.ERROR)
        error_handler = logging.FileHandler(self.error_log_file, encoding='utf-8')
        error_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s - %(exc_info)s')
        error_handler.setFormatter(error_formatter)
        self.error_logger.addHandler(error_handler)
        
        # 控制台输出（可选）
        if self.config.get('logging.console_output', True):
            console_handler = logging.StreamHandler()
            console_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            console_handler.setFormatter(console_formatter)
            
            self.trade_logger.addHandler(console_handler)
            self.performance_logger.addHandler(console_handler)
            self.error_logger.addHandler(console_handler)
    
    def log_trade_attempt(self, grid_id: str, action: str, price: decimal.Decimal, 
                         quantity: decimal.Decimal, order_details: Dict):
        """记录交易尝试"""
        message = (
            f"交易尝试 - 网格: {grid_id}, 动作: {action}, "
            f"价格: {price}, 数量: {quantity:.6f}, "
            f"订单详情: {json.dumps(order_details, default=str, ensure_ascii=False)}"
        )
        self.trade_logger.info(message)
        
        # 更新统计
        self.session_stats['total_trades'] += 1
        if grid_id not in self.session_stats['grid_activities']:
            self.session_stats['grid_activities'][grid_id] = {'attempts': 0, 'successes': 0}
        self.session_stats['grid_activities'][grid_id]['attempts'] += 1
    
    def log_trade_result(self, grid_id: str, action: str, success: bool, 
                        filled_price: decimal.Decimal = None, filled_quantity: decimal.Decimal = None,
                        fees: decimal.Decimal = None, profit: decimal.Decimal = None,
                        error_message: str = None):
        """记录交易结果"""
        if success:
            message = (
                f"交易成功 - 网格: {grid_id}, 动作: {action}, "
                f"成交价: {filled_price}, 成交量: {filled_quantity:.6f}, "
                f"手续费: {fees:.6f} USDC"
            )
            if profit is not None:
                message += f", 利润: {profit:.6f} USDC"
            
            self.trade_logger.info(message)
            self.session_stats['successful_trades'] += 1
            self.session_stats['grid_activities'][grid_id]['successes'] += 1
            
            if fees:
                self.session_stats['total_fees'] += fees
            if profit:
                self.session_stats['total_profit'] += profit
            if filled_quantity and filled_price:
                self.session_stats['total_volume'] += filled_quantity * filled_price
        else:
            message = f"交易失败 - 网格: {grid_id}, 动作: {action}"
            if error_message:
                message += f", 错误: {error_message}"
            
            self.trade_logger.warning(message)
            self.session_stats['failed_trades'] += 1
    
    def log_grid_status(self, active_grids: Dict, current_price: decimal.Decimal):
        """记录网格状态"""
        grid_summary = []
        for grid_id, grid_info in active_grids.items():
            summary = {
                'grid_id': grid_id,
                'status': grid_info['status'],
                'coin_qty': float(grid_info.get('coin_qty', 0)),
                'last_buy_price': float(grid_info.get('last_buy_price', 0)) if grid_info.get('last_buy_price') else None,
                'allocated_usdc': float(grid_info.get('allocated_usdc', 0))
            }
            grid_summary.append(summary)
        
        message = (
            f"网格状态更新 - 当前价格: {current_price}, "
            f"活跃网格数: {len(active_grids)}, "
            f"详情: {json.dumps(grid_summary, ensure_ascii=False, indent=2)}"
        )
        self.performance_logger.info(message)
    
    def log_balance_update(self, usdc_balance: decimal.Decimal, base_coin_balance: decimal.Decimal,
                          total_value: decimal.Decimal, price: decimal.Decimal):
        """记录余额更新"""
        message = (
            f"余额更新 - USDC: {usdc_balance:.2f}, "
            f"基础币种: {base_coin_balance:.6f}, "
            f"总价值: {total_value:.2f} USDC, "
            f"当前价格: {price}"
        )
        self.performance_logger.info(message)
    
    def log_risk_event(self, risk_level: str, event_type: str, details: Dict):
        """记录风险事件"""
        message = (
            f"风险事件 - 等级: {risk_level}, 类型: {event_type}, "
            f"详情: {json.dumps(details, default=str, ensure_ascii=False)}"
        )
        
        if risk_level in ['HIGH', 'CRITICAL']:
            self.error_logger.error(message)
        else:
            self.performance_logger.warning(message)
        
        self.session_stats['warnings'].append({
            'timestamp': datetime.now(),
            'risk_level': risk_level,
            'event_type': event_type,
            'details': details
        })
    
    def log_optimization_event(self, event_type: str, old_config: Dict, new_config: Dict, reason: str):
        """记录优化事件"""
        message = (
            f"优化事件 - 类型: {event_type}, "
            f"原配置: {json.dumps(old_config, default=str, ensure_ascii=False)}, "
            f"新配置: {json.dumps(new_config, default=str, ensure_ascii=False)}, "
            f"原因: {reason}"
        )
        self.performance_logger.info(message)
    
    def log_error(self, error_type: str, error_message: str, context: Dict = None):
        """记录错误"""
        message = f"错误 - 类型: {error_type}, 消息: {error_message}"
        if context:
            message += f", 上下文: {json.dumps(context, default=str, ensure_ascii=False)}"
        
        self.error_logger.error(message)
        self.session_stats['error_count'] += 1
    
    def generate_session_summary(self) -> Dict:
        """生成会话摘要"""
        session_duration = datetime.now() - self.session_stats['start_time']
        
        summary = {
            'session_start': self.session_stats['start_time'].isoformat(),
            'session_duration_minutes': session_duration.total_seconds() / 60,
            'total_trades': self.session_stats['total_trades'],
            'successful_trades': self.session_stats['successful_trades'],
            'failed_trades': self.session_stats['failed_trades'],
            'success_rate': (self.session_stats['successful_trades'] / self.session_stats['total_trades'] 
                           if self.session_stats['total_trades'] > 0 else 0),
            'total_volume_usdc': float(self.session_stats['total_volume']),
            'total_fees_usdc': float(self.session_stats['total_fees']),
            'total_profit_usdc': float(self.session_stats['total_profit']),
            'net_profit_usdc': float(self.session_stats['total_profit'] - self.session_stats['total_fees']),
            'error_count': self.session_stats['error_count'],
            'warning_count': len(self.session_stats['warnings']),
            'grid_performance': {}
        }
        
        # 计算每个网格的性能
        for grid_id, activity in self.session_stats['grid_activities'].items():
            if activity['attempts'] > 0:
                summary['grid_performance'][grid_id] = {
                    'attempts': activity['attempts'],
                    'successes': activity['successes'],
                    'success_rate': activity['successes'] / activity['attempts']
                }
        
        return summary
    
    def write_daily_summary(self):
        """写入每日摘要"""
        summary = self.generate_session_summary()
        
        with open(self.summary_log_file, 'a', encoding='utf-8') as f:
            f.write(f"{datetime.now().isoformat()}: {json.dumps(summary, ensure_ascii=False, indent=2)}\n")
        
        return summary
    
    def get_recent_logs(self, log_type: str = 'trade', lines: int = 50) -> List[str]:
        """获取最近的日志记录"""
        log_files = {
            'trade': self.trade_log_file,
            'performance': self.performance_log_file,
            'error': self.error_log_file
        }
        
        log_file = log_files.get(log_type, self.trade_log_file)
        
        if not log_file.exists():
            return []
        
        with open(log_file, 'r', encoding='utf-8') as f:
            all_lines = f.readlines()
            return all_lines[-lines:] if len(all_lines) > lines else all_lines
    
    def cleanup_old_logs(self, days_to_keep: int = 30):
        """清理旧日志文件"""
        cutoff_date = datetime.now() - timedelta(days=days_to_keep)
        
        for log_file in [self.trade_log_file, self.performance_log_file, 
                        self.error_log_file, self.summary_log_file]:
            if log_file.exists():
                # 检查文件修改时间
                file_mtime = datetime.fromtimestamp(log_file.stat().st_mtime)
                if file_mtime < cutoff_date:
                    # 创建备份文件名
                    backup_name = f"{log_file.stem}_{file_mtime.strftime('%Y%m%d')}.bak"
                    backup_path = log_file.parent / backup_name
                    
                    # 重命名为备份文件
                    log_file.rename(backup_path)
                    print(f"日志文件已备份: {backup_path}")
    
    def export_analytics_data(self, filepath: str):
        """导出分析数据"""
        analytics_data = {
            'export_timestamp': datetime.now().isoformat(),
            'session_summary': self.generate_session_summary(),
            'recent_trades': self.get_recent_logs('trade', 100),
            'recent_performance': self.get_recent_logs('performance', 50),
            'recent_errors': self.get_recent_logs('error', 20)
        }
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(analytics_data, f, ensure_ascii=False, indent=2)