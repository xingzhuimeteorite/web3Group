"""
性能指标监控和分析模块
Performance Metrics Monitoring and Analysis Module
"""

import time
import asyncio
import statistics
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from collections import deque, defaultdict
import json
import os
import threading
import psutil
import decimal

class PerformanceMonitor:
    """性能监控器"""
    
    def __init__(self, config):
        self.config = config
        self.performance_log_file = config.get('performance.log_file', 'logs/performance.log')
        self.metrics_retention_hours = config.get('performance.metrics_retention_hours', 24)
        self.sampling_interval = config.get('performance.sampling_interval', 60)  # 秒
        
        # 性能指标存储
        self.execution_times = defaultdict(deque)  # 执行时间记录
        self.api_response_times = deque(maxlen=1000)  # API响应时间
        self.memory_usage = deque(maxlen=1000)  # 内存使用情况
        self.cpu_usage = deque(maxlen=1000)  # CPU使用情况
        self.trade_latency = deque(maxlen=1000)  # 交易延迟
        self.order_success_rate = deque(maxlen=1000)  # 订单成功率
        
        # 交易性能指标
        self.trade_metrics = {
            'total_trades': 0,
            'successful_trades': 0,
            'failed_trades': 0,
            'total_volume': decimal.Decimal('0'),
            'total_fees': decimal.Decimal('0'),
            'profit_loss': decimal.Decimal('0'),
            'max_drawdown': decimal.Decimal('0'),
            'win_rate': 0.0,
            'avg_trade_time': 0.0,
            'trades_per_hour': 0.0
        }
        
        # 网格性能指标
        self.grid_metrics = defaultdict(lambda: {
            'trades': 0,
            'success_rate': 0.0,
            'avg_profit': decimal.Decimal('0'),
            'total_volume': decimal.Decimal('0'),
            'execution_time': 0.0
        })
        
        # 系统性能指标
        self.system_metrics = {
            'uptime': 0,
            'avg_memory_usage': 0.0,
            'avg_cpu_usage': 0.0,
            'peak_memory_usage': 0.0,
            'peak_cpu_usage': 0.0,
            'api_calls_per_minute': 0.0,
            'avg_api_response_time': 0.0
        }
        
        # 实时监控数据
        self.real_time_metrics = {
            'current_memory_mb': 0.0,
            'current_cpu_percent': 0.0,
            'active_orders': 0,
            'pending_operations': 0,
            'last_trade_time': None,
            'current_balance_usdc': 0.0,
            'current_balance_base': 0.0,
            'current_pnl': decimal.Decimal('0')
        }
        
        # 性能阈值和警报
        self.performance_thresholds = {
            'max_memory_mb': config.get('performance.max_memory_mb', 500),
            'max_cpu_percent': config.get('performance.max_cpu_percent', 80),
            'max_api_response_time': config.get('performance.max_api_response_time', 5.0),
            'min_success_rate': config.get('performance.min_success_rate', 0.8),
            'max_trade_latency': config.get('performance.max_trade_latency', 10.0)
        }
        
        # 监控状态
        self.monitoring_active = False
        self.start_time = datetime.now()
        self.last_cleanup = datetime.now()
        
        # 确保日志目录存在
        os.makedirs(os.path.dirname(self.performance_log_file), exist_ok=True)
        
        # 启动后台监控线程
        self.monitor_thread = None
        self.start_monitoring()
    
    def start_monitoring(self):
        """启动性能监控"""
        if not self.monitoring_active:
            self.monitoring_active = True
            self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
            self.monitor_thread.start()
    
    def stop_monitoring(self):
        """停止性能监控"""
        self.monitoring_active = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5)
    
    def _monitor_loop(self):
        """监控循环"""
        while self.monitoring_active:
            try:
                self._collect_system_metrics()
                self._check_performance_thresholds()
                self._cleanup_old_metrics()
                time.sleep(self.sampling_interval)
            except Exception as e:
                self._log_error(f"监控循环异常: {e}")
    
    def _collect_system_metrics(self):
        """收集系统性能指标"""
        try:
            # 内存使用情况
            memory_info = psutil.virtual_memory()
            current_memory_mb = memory_info.used / 1024 / 1024
            self.memory_usage.append(current_memory_mb)
            self.real_time_metrics['current_memory_mb'] = current_memory_mb
            
            # CPU使用情况
            current_cpu = psutil.cpu_percent(interval=1)
            self.cpu_usage.append(current_cpu)
            self.real_time_metrics['current_cpu_percent'] = current_cpu
            
            # 更新系统指标
            if self.memory_usage:
                self.system_metrics['avg_memory_usage'] = statistics.mean(self.memory_usage)
                self.system_metrics['peak_memory_usage'] = max(self.memory_usage)
            
            if self.cpu_usage:
                self.system_metrics['avg_cpu_usage'] = statistics.mean(self.cpu_usage)
                self.system_metrics['peak_cpu_usage'] = max(self.cpu_usage)
            
            # 运行时间
            self.system_metrics['uptime'] = (datetime.now() - self.start_time).total_seconds()
            
        except Exception as e:
            self._log_error(f"收集系统指标异常: {e}")
    
    def record_execution_time(self, operation: str, execution_time: float):
        """记录操作执行时间"""
        self.execution_times[operation].append({
            'time': execution_time,
            'timestamp': datetime.now()
        })
        
        # 限制存储数量
        if len(self.execution_times[operation]) > 1000:
            self.execution_times[operation].popleft()
    
    def record_api_response_time(self, response_time: float):
        """记录API响应时间"""
        self.api_response_times.append({
            'time': response_time,
            'timestamp': datetime.now()
        })
        
        # 更新平均响应时间
        if self.api_response_times:
            self.system_metrics['avg_api_response_time'] = statistics.mean([r['time'] for r in self.api_response_times])
    
    def record_trade_performance(self, trade_type: str, success: bool, 
                               execution_time: float, volume: decimal.Decimal = None,
                               profit: decimal.Decimal = None, grid_id: str = None):
        """记录交易性能"""
        # 更新总体交易指标
        self.trade_metrics['total_trades'] += 1
        if success:
            self.trade_metrics['successful_trades'] += 1
        else:
            self.trade_metrics['failed_trades'] += 1
        
        if volume:
            self.trade_metrics['total_volume'] += volume
        
        if profit:
            self.trade_metrics['profit_loss'] += profit
        
        # 记录交易延迟
        self.trade_latency.append({
            'latency': execution_time,
            'timestamp': datetime.now(),
            'trade_type': trade_type,
            'success': success
        })
        
        # 更新成功率
        success_rate = self.trade_metrics['successful_trades'] / self.trade_metrics['total_trades']
        self.trade_metrics['win_rate'] = success_rate
        self.order_success_rate.append({
            'rate': success_rate,
            'timestamp': datetime.now()
        })
        
        # 更新平均交易时间
        if self.trade_latency:
            self.trade_metrics['avg_trade_time'] = statistics.mean([t['latency'] for t in self.trade_latency])
        
        # 更新网格特定指标
        if grid_id:
            grid_metric = self.grid_metrics[grid_id]
            grid_metric['trades'] += 1
            if success:
                grid_metric['success_rate'] = (grid_metric['success_rate'] * (grid_metric['trades'] - 1) + 1) / grid_metric['trades']
            else:
                grid_metric['success_rate'] = (grid_metric['success_rate'] * (grid_metric['trades'] - 1)) / grid_metric['trades']
            
            if volume:
                grid_metric['total_volume'] += volume
            if profit:
                grid_metric['avg_profit'] = (grid_metric['avg_profit'] * (grid_metric['trades'] - 1) + profit) / grid_metric['trades']
            
            grid_metric['execution_time'] = (grid_metric['execution_time'] * (grid_metric['trades'] - 1) + execution_time) / grid_metric['trades']
        
        # 记录最后交易时间
        self.real_time_metrics['last_trade_time'] = datetime.now()
    
    def update_balance_metrics(self, usdc_balance: float, base_balance: float, current_pnl: decimal.Decimal):
        """更新余额相关指标"""
        self.real_time_metrics['current_balance_usdc'] = usdc_balance
        self.real_time_metrics['current_balance_base'] = base_balance
        self.real_time_metrics['current_pnl'] = current_pnl
        
        # 更新最大回撤
        if current_pnl < self.trade_metrics['max_drawdown']:
            self.trade_metrics['max_drawdown'] = current_pnl
    
    def _check_performance_thresholds(self):
        """检查性能阈值并发出警报"""
        alerts = []
        
        # 检查内存使用
        if self.real_time_metrics['current_memory_mb'] > self.performance_thresholds['max_memory_mb']:
            alerts.append(f"内存使用过高: {self.real_time_metrics['current_memory_mb']:.1f}MB")
        
        # 检查CPU使用
        if self.real_time_metrics['current_cpu_percent'] > self.performance_thresholds['max_cpu_percent']:
            alerts.append(f"CPU使用过高: {self.real_time_metrics['current_cpu_percent']:.1f}%")
        
        # 检查API响应时间
        if self.api_response_times and self.system_metrics['avg_api_response_time'] > self.performance_thresholds['max_api_response_time']:
            alerts.append(f"API响应时间过长: {self.system_metrics['avg_api_response_time']:.2f}s")
        
        # 检查成功率
        if self.trade_metrics['win_rate'] < self.performance_thresholds['min_success_rate']:
            alerts.append(f"交易成功率过低: {self.trade_metrics['win_rate']:.2%}")
        
        # 记录警报
        if alerts:
            self._log_performance_alert(alerts)
    
    def _cleanup_old_metrics(self):
        """清理过期的性能指标"""
        if datetime.now() - self.last_cleanup > timedelta(hours=1):
            cutoff_time = datetime.now() - timedelta(hours=self.metrics_retention_hours)
            
            # 清理执行时间记录
            for operation in self.execution_times:
                while (self.execution_times[operation] and 
                       self.execution_times[operation][0]['timestamp'] < cutoff_time):
                    self.execution_times[operation].popleft()
            
            # 清理其他时间序列数据
            for deque_data in [self.api_response_times, self.trade_latency, self.order_success_rate]:
                while (deque_data and 
                       deque_data[0]['timestamp'] < cutoff_time):
                    deque_data.popleft()
            
            self.last_cleanup = datetime.now()
    
    def get_performance_summary(self) -> Dict[str, Any]:
        """获取性能摘要"""
        # 计算每小时交易数
        if self.system_metrics['uptime'] > 0:
            self.trade_metrics['trades_per_hour'] = (self.trade_metrics['total_trades'] * 3600) / self.system_metrics['uptime']
        
        return {
            'timestamp': datetime.now().isoformat(),
            'uptime_hours': self.system_metrics['uptime'] / 3600,
            'trade_metrics': {
                'total_trades': self.trade_metrics['total_trades'],
                'success_rate': self.trade_metrics['win_rate'],
                'trades_per_hour': self.trade_metrics['trades_per_hour'],
                'avg_trade_time': self.trade_metrics['avg_trade_time'],
                'total_volume': float(self.trade_metrics['total_volume']),
                'current_pnl': float(self.trade_metrics['profit_loss']),
                'max_drawdown': float(self.trade_metrics['max_drawdown'])
            },
            'system_metrics': {
                'current_memory_mb': self.real_time_metrics['current_memory_mb'],
                'avg_memory_mb': self.system_metrics['avg_memory_usage'],
                'peak_memory_mb': self.system_metrics['peak_memory_usage'],
                'current_cpu_percent': self.real_time_metrics['current_cpu_percent'],
                'avg_cpu_percent': self.system_metrics['avg_cpu_usage'],
                'peak_cpu_percent': self.system_metrics['peak_cpu_usage'],
                'avg_api_response_time': self.system_metrics['avg_api_response_time']
            },
            'real_time_status': {
                'active_orders': self.real_time_metrics['active_orders'],
                'last_trade_time': self.real_time_metrics['last_trade_time'].isoformat() if self.real_time_metrics['last_trade_time'] else None,
                'current_balance_usdc': self.real_time_metrics['current_balance_usdc'],
                'current_balance_base': self.real_time_metrics['current_balance_base']
            }
        }
    
    def get_grid_performance(self) -> Dict[str, Any]:
        """获取网格性能统计"""
        grid_stats = {}
        for grid_id, metrics in self.grid_metrics.items():
            grid_stats[grid_id] = {
                'trades': metrics['trades'],
                'success_rate': metrics['success_rate'],
                'avg_profit': float(metrics['avg_profit']),
                'total_volume': float(metrics['total_volume']),
                'avg_execution_time': metrics['execution_time']
            }
        return grid_stats
    
    def get_execution_time_stats(self, operation: str) -> Dict[str, float]:
        """获取特定操作的执行时间统计"""
        if operation not in self.execution_times or not self.execution_times[operation]:
            return {}
        
        times = [record['time'] for record in self.execution_times[operation]]
        return {
            'count': len(times),
            'avg': statistics.mean(times),
            'min': min(times),
            'max': max(times),
            'median': statistics.median(times),
            'std_dev': statistics.stdev(times) if len(times) > 1 else 0
        }
    
    def export_performance_data(self, filepath: str = None) -> str:
        """导出性能数据"""
        if not filepath:
            filepath = f"performance_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        export_data = {
            'export_timestamp': datetime.now().isoformat(),
            'performance_summary': self.get_performance_summary(),
            'grid_performance': self.get_grid_performance(),
            'execution_time_stats': {op: self.get_execution_time_stats(op) for op in self.execution_times.keys()}
        }
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False, default=str)
        
        return filepath
    
    def _log_performance_alert(self, alerts: List[str]):
        """记录性能警报"""
        alert_message = f"[PERFORMANCE ALERT] {datetime.now().isoformat()}: {'; '.join(alerts)}"
        self._log_message(alert_message)
    
    def _log_error(self, message: str):
        """记录错误信息"""
        error_message = f"[ERROR] {datetime.now().isoformat()}: {message}"
        self._log_message(error_message)
    
    def _log_message(self, message: str):
        """记录日志消息"""
        try:
            with open(self.performance_log_file, 'a', encoding='utf-8') as f:
                f.write(message + '\n')
        except Exception as e:
            print(f"无法写入性能日志: {e}")
    
    def __del__(self):
        """析构函数，确保监控线程正确关闭"""
        self.stop_monitoring()