"""
Backpack Exchange 风险管理模块
实现止损、资金管理和风险控制功能
"""

import decimal
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import json
import os

class BackpackRiskManager:
    def __init__(self, config_loader=None):
        """
        初始化风险管理器
        
        Args:
            config_loader: 配置加载器实例
        """
        self.config = config_loader
        
        # 风险管理参数
        self.max_loss_percentage = decimal.Decimal(str(self.config.get('risk_management.max_loss_percentage', 5.0))) if config_loader else decimal.Decimal('5.0')
        self.stop_loss_percentage = decimal.Decimal(str(self.config.get('risk_management.stop_loss', 2.0))) if config_loader else decimal.Decimal('2.0')
        self.max_position_size = decimal.Decimal(str(self.config.get('risk_management.max_position_size', 1000))) if config_loader else decimal.Decimal('1000')
        self.daily_loss_limit = decimal.Decimal(str(self.config.get('risk_management.daily_loss_limit', 100))) if config_loader else decimal.Decimal('100')
        
        # 风险状态跟踪
        self.initial_balance = None
        self.daily_pnl = decimal.Decimal('0')
        self.total_pnl = decimal.Decimal('0')
        self.last_reset_date = datetime.now().date()
        self.emergency_stop = False
        self.risk_alerts = []
        
        # 持仓风险跟踪
        self.position_entries = {}  # 记录每个网格的入场价格和数量
        self.max_drawdown = decimal.Decimal('0')
        self.peak_balance = decimal.Decimal('0')
        
        # 风险日志文件
        self.risk_log_file = self.config.get('logging.risk_log_file', 'risk_log.txt') if config_loader else 'risk_log.txt'
        
    def set_initial_balance(self, usdc_balance: decimal.Decimal, base_coin_balance: decimal.Decimal, current_price: decimal.Decimal):
        """
        设置初始余额，用于计算盈亏
        
        Args:
            usdc_balance: USDC余额
            base_coin_balance: 基础币种余额
            current_price: 当前价格
        """
        total_value = usdc_balance + (base_coin_balance * current_price)
        if self.initial_balance is None:
            self.initial_balance = total_value
            self.peak_balance = total_value
            self._log_risk_event(f"初始余额设置: {total_value:.2f} USDC")
        
    def update_balance(self, usdc_balance: decimal.Decimal, base_coin_balance: decimal.Decimal, current_price: decimal.Decimal) -> Dict:
        """
        更新余额并计算风险指标
        
        Args:
            usdc_balance: 当前USDC余额
            base_coin_balance: 当前基础币种余额
            current_price: 当前价格
            
        Returns:
            风险评估结果
        """
        current_total_value = usdc_balance + (base_coin_balance * current_price)
        
        # 重置每日PnL
        current_date = datetime.now().date()
        if current_date != self.last_reset_date:
            self.daily_pnl = decimal.Decimal('0')
            self.last_reset_date = current_date
            self._log_risk_event(f"每日PnL重置，日期: {current_date}")
        
        # 计算PnL
        if self.initial_balance is not None:
            self.total_pnl = current_total_value - self.initial_balance
            total_pnl_percentage = (self.total_pnl / self.initial_balance) * 100
            
            # 更新峰值余额和最大回撤
            if current_total_value > self.peak_balance:
                self.peak_balance = current_total_value
            
            current_drawdown = ((self.peak_balance - current_total_value) / self.peak_balance) * 100
            if current_drawdown > self.max_drawdown:
                self.max_drawdown = current_drawdown
        else:
            total_pnl_percentage = decimal.Decimal('0')
            current_drawdown = decimal.Decimal('0')
        
        # 风险检查
        risk_status = self._assess_risk(total_pnl_percentage, current_drawdown, current_total_value)
        
        return {
            'current_balance': current_total_value,
            'total_pnl': self.total_pnl,
            'total_pnl_percentage': total_pnl_percentage,
            'daily_pnl': self.daily_pnl,
            'max_drawdown': self.max_drawdown,
            'current_drawdown': current_drawdown,
            'risk_level': risk_status['risk_level'],
            'should_stop_trading': risk_status['should_stop_trading'],
            'risk_alerts': risk_status['alerts'],
            'emergency_stop': self.emergency_stop
        }
    
    def _assess_risk(self, total_pnl_percentage: decimal.Decimal, current_drawdown: decimal.Decimal, current_balance: decimal.Decimal) -> Dict:
        """
        评估当前风险水平
        
        Args:
            total_pnl_percentage: 总盈亏百分比
            current_drawdown: 当前回撤百分比
            current_balance: 当前余额
            
        Returns:
            风险评估结果
        """
        alerts = []
        risk_level = "LOW"
        should_stop_trading = False
        
        # 检查最大亏损限制
        if abs(total_pnl_percentage) >= self.max_loss_percentage:
            alerts.append(f"总亏损达到限制: {total_pnl_percentage:.2f}% >= {self.max_loss_percentage}%")
            risk_level = "CRITICAL"
            should_stop_trading = True
            self.emergency_stop = True
        
        # 检查止损
        elif abs(total_pnl_percentage) >= self.stop_loss_percentage:
            alerts.append(f"触发止损: {total_pnl_percentage:.2f}% >= {self.stop_loss_percentage}%")
            risk_level = "HIGH"
        
        # 检查回撤
        if current_drawdown >= 10:  # 10%回撤警告
            alerts.append(f"回撤过大: {current_drawdown:.2f}%")
            if risk_level == "LOW":
                risk_level = "MEDIUM"
        
        # 检查每日亏损限制
        if abs(self.daily_pnl) >= self.daily_loss_limit:
            alerts.append(f"每日亏损达到限制: {self.daily_pnl:.2f} >= {self.daily_loss_limit}")
            risk_level = "HIGH"
            should_stop_trading = True
        
        # 记录风险警告
        for alert in alerts:
            if alert not in self.risk_alerts:
                self.risk_alerts.append(alert)
                self._log_risk_event(f"风险警告: {alert}")
        
        return {
            'risk_level': risk_level,
            'should_stop_trading': should_stop_trading,
            'alerts': alerts
        }
    
    def check_position_risk(self, grid_id: str, entry_price: decimal.Decimal, current_price: decimal.Decimal, position_size: decimal.Decimal) -> Dict:
        """
        检查单个持仓的风险
        
        Args:
            grid_id: 网格ID
            entry_price: 入场价格
            current_price: 当前价格
            position_size: 持仓数量
            
        Returns:
            持仓风险评估
        """
        # 记录持仓信息
        self.position_entries[grid_id] = {
            'entry_price': entry_price,
            'position_size': position_size,
            'entry_time': datetime.now()
        }
        
        # 计算持仓盈亏
        position_value = position_size * current_price
        entry_value = position_size * entry_price
        position_pnl = position_value - entry_value
        position_pnl_percentage = (position_pnl / entry_value) * 100 if entry_value > 0 else decimal.Decimal('0')
        
        # 检查持仓大小限制
        position_risk = "LOW"
        alerts = []
        
        if position_value > self.max_position_size:
            alerts.append(f"持仓过大: {position_value:.2f} > {self.max_position_size}")
            position_risk = "HIGH"
        
        # 检查单个持仓止损
        if position_pnl_percentage <= -self.stop_loss_percentage:
            alerts.append(f"持仓止损: {position_pnl_percentage:.2f}%")
            position_risk = "CRITICAL"
        
        return {
            'grid_id': grid_id,
            'position_pnl': position_pnl,
            'position_pnl_percentage': position_pnl_percentage,
            'position_value': position_value,
            'risk_level': position_risk,
            'alerts': alerts
        }
    
    def should_reduce_position_size(self, current_risk_level: str) -> Tuple[bool, decimal.Decimal]:
        """
        根据风险水平决定是否应该减少持仓大小
        
        Args:
            current_risk_level: 当前风险水平
            
        Returns:
            (是否减少持仓, 建议的持仓比例)
        """
        if current_risk_level == "CRITICAL":
            return True, decimal.Decimal('0.2')  # 减少到20%
        elif current_risk_level == "HIGH":
            return True, decimal.Decimal('0.5')  # 减少到50%
        elif current_risk_level == "MEDIUM":
            return True, decimal.Decimal('0.8')  # 减少到80%
        else:
            return False, decimal.Decimal('1.0')  # 保持100%
    
    def get_risk_summary(self) -> Dict:
        """
        获取风险管理摘要
        
        Returns:
            风险摘要信息
        """
        return {
            'emergency_stop': self.emergency_stop,
            'total_pnl': self.total_pnl,
            'daily_pnl': self.daily_pnl,
            'max_drawdown': self.max_drawdown,
            'active_positions': len(self.position_entries),
            'recent_alerts': self.risk_alerts[-5:] if len(self.risk_alerts) > 5 else self.risk_alerts,
            'risk_parameters': {
                'max_loss_percentage': self.max_loss_percentage,
                'stop_loss_percentage': self.stop_loss_percentage,
                'max_position_size': self.max_position_size,
                'daily_loss_limit': self.daily_loss_limit
            }
        }
    
    def reset_emergency_stop(self):
        """
        重置紧急停止状态（需要手动确认）
        """
        self.emergency_stop = False
        self.risk_alerts.clear()
        self._log_risk_event("紧急停止状态已重置")
    
    def _log_risk_event(self, message: str):
        """
        记录风险事件到日志文件
        
        Args:
            message: 日志消息
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"{timestamp} - {message}\n"
        
        try:
            with open(self.risk_log_file, 'a', encoding='utf-8') as f:
                f.write(log_entry)
        except Exception as e:
            print(f"写入风险日志失败: {e}")
    
    def update_daily_pnl(self, trade_pnl: decimal.Decimal):
        """
        更新每日盈亏
        
        Args:
            trade_pnl: 交易盈亏
        """
        self.daily_pnl += trade_pnl
        self.total_pnl += trade_pnl