#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
任意币种交易策略
目标：通过任意币种交易获取Aster积分，支持参数化配置
基于 aster/trade.py 架构，扩展支持多币种
"""

import time
import json
import logging
import argparse
import sys
import os
import glob
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple, List
from dataclasses import dataclass

# 添加aster目录到路径
sys.path.append(os.path.join(os.path.dirname(__file__), 'aster'))

from aster_api_client import AsterFinanceClient
from config_loader import ConfigLoader
from retry_handler import smart_retry, network_retry, api_retry, critical_retry, reset_circuit_breaker, get_circuit_breaker_status

class AnyCoinTradingStrategy:
    """任意币种交易策略类"""
    
    def __init__(self, 
                 symbol: str = "SOLUSDT",
                 direction: str = "long", 
                 position_size: float = 25.0,
                 leverage: int = 2,
                 profit_threshold: float = 0.008,
                 stop_loss_threshold: float = 0.006,
                 min_holding_time: int = 1800,
                 config_path: str = "config.json"):
        """初始化策略
        
        Args:
            symbol: 交易对符号 (如 SOLUSDT, BTCUSDT, ETHUSDT)
            direction: 交易方向 ('long', 'short', 'auto')
            position_size: 每次开仓金额 (USDT)
            leverage: 杠杆倍数
            profit_threshold: 止盈阈值 (小数形式，如0.008表示0.8%)
            stop_loss_threshold: 止损阈值 (小数形式，如0.006表示0.6%)
            min_holding_time: 最小持仓时间 (秒)
            config_path: 配置文件路径
        """
        self.config_loader = ConfigLoader(config_path)
        self.client = AsterFinanceClient(
            api_key=self.config_loader.get('api_key'),
            secret_key=self.config_loader.get('secret_key'),
            base_url=self.config_loader.get('base_url')
        )
        
        # 策略参数
        self.symbol = symbol.upper()
        self.position_size = position_size
        self.leverage = leverage
        self.fee_rate = 0.0005  # 手续费率 0.05%
        self.profit_threshold = profit_threshold
        self.stop_loss_threshold = stop_loss_threshold
        self.min_holding_time = min_holding_time
        
        # 交易方向控制
        self.direction = direction.lower()
        self.valid_directions = ['long', 'short', 'auto']
        if self.direction not in self.valid_directions:
            raise ValueError(f"无效的交易方向: {direction}. 支持的方向: {self.valid_directions}")
        
        # 状态跟踪
        self.current_position = None
        self.entry_time = None
        self.entry_price = None
        self.position_id = None
        self.current_side = None  # 'BUY' 或 'SELL'
        
        # 获取币种信息
        self.base_asset = self._extract_base_asset(symbol)
        
        # 设置日志
        self._setup_logger()
        
        direction_name = {"long": "多单", "short": "空单", "auto": "自动"}[self.direction]
        self.logger.info(f"🚀 {self.base_asset}交易策略初始化完成 - {direction_name}模式")
        self.logger.info(f"📊 策略参数: 交易对={self.symbol}, 仓位={self.position_size}USDT, 杠杆={self.leverage}x")
        self.logger.info(f"🎯 止盈={self.profit_threshold*100}%, 止损={self.stop_loss_threshold*100}%")
        self.logger.info(f"⏰ 最小持仓时间={self.min_holding_time}秒")
    
    def _setup_logger(self):
        """设置日志"""
        log_filename = f"{self.base_asset.lower()}_strategy.log"
        
        # 创建logger
        self.logger = logging.getLogger(f"{self.base_asset}_strategy")
        self.logger.setLevel(logging.INFO)
        
        # 避免重复添加handler
        if not self.logger.handlers:
            # 文件handler
            file_handler = logging.FileHandler(log_filename)
            file_handler.setLevel(logging.INFO)
            
            # 控制台handler
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)
            
            # 格式化
            formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            file_handler.setFormatter(formatter)
            console_handler.setFormatter(formatter)
            
            self.logger.addHandler(file_handler)
            self.logger.addHandler(console_handler)
    
    def _extract_base_asset(self, symbol: str) -> str:
        """从交易对中提取基础资产名称"""
        symbol = symbol.upper()
        if symbol.endswith('USDT'):
            return symbol[:-4]
        elif symbol.endswith('USDC'):
            return symbol[:-4]
        elif symbol.endswith('BTC'):
            return symbol[:-3]
        elif symbol.endswith('ETH'):
            return symbol[:-3]
        else:
            # 默认返回前3个字符
            return symbol[:3]
    
    @network_retry
    def get_current_price(self) -> float:
        """获取当前价格"""
        try:
            ticker = self.client.get_ticker_price(self.symbol)
            return float(ticker['price'])
        except Exception as e:
            self.logger.error(f"❌ 获取{self.symbol}价格失败: {e}")
            raise
    
    def calculate_fees(self, trade_amount: float) -> float:
        """计算交易手续费"""
        return trade_amount * self.fee_rate
    
    def calculate_profit_loss(self, entry_price: float, current_price: float, quantity: float, side: str) -> Tuple[float, float]:
        """计算盈亏和盈亏率 (支持多空双向)
        
        Args:
            entry_price: 入场价格
            current_price: 当前价格
            quantity: 持仓数量
            side: 交易方向 ('BUY'/'SELL')
        """
        if side == "BUY":  # 多单
            price_diff = current_price - entry_price
            pnl = price_diff * quantity
            pnl_percentage = (current_price - entry_price) / entry_price
        else:  # 空单
            price_diff = entry_price - current_price
            pnl = price_diff * quantity
            pnl_percentage = (entry_price - current_price) / entry_price
        
        return pnl, pnl_percentage
    
    def detect_market_direction(self) -> str:
        """检测市场方向"""
        try:
            current_price = self.get_current_price()
            if not current_price:
                self.logger.warning("⚠️ 无法获取价格，默认做多")
                return "BUY"
            
            # 基于时间的轮换策略
            current_hour = datetime.now().hour
            
            if current_hour % 2 == 1:
                direction = "BUY"
                reason = f"时间策略 (第{current_hour}小时-奇数)"
            else:
                direction = "SELL" 
                reason = f"时间策略 (第{current_hour}小时-偶数)"
            
            direction_name = "多单" if direction == "BUY" else "空单"
            self.logger.info(f"🎯 自动检测方向: {direction_name} ({reason})")
            
            return direction
            
        except Exception as e:
            self.logger.error(f"❌ 方向检测失败: {e}，默认做多")
            return "BUY"
    
    @api_retry
    def check_account_balance(self) -> float:
        """检查账户余额"""
        try:
            account_info = self.client.get_account_info()
            available_balance = float(account_info['availableBalance'])
            self.logger.info(f"💰 可用余额: {available_balance:.2f} USDT")
            return available_balance
        except Exception as e:
            self.logger.error(f"❌ 获取账户信息失败: {e}")
            raise
    
    def calculate_position_size(self, balance: float, price: float) -> float:
        """计算合适的持仓大小"""
        import math
        
        # 交易规则 - 根据不同币种可能需要调整
        min_notional = 30.0  # 最小名义价值
        min_quantity = 0.01  # 最小数量
        step_size = 0.01    # 数量步长
        
        # 根据币种调整精度
        if self.base_asset in ['BTC']:
            min_quantity = 0.001
            step_size = 0.001
        elif self.base_asset in ['ETH']:
            min_quantity = 0.01
            step_size = 0.01
        elif self.base_asset in ['SOL', 'BNB']:
            min_quantity = 0.01
            step_size = 0.01
        elif self.base_asset in ['0G']:  # 0G币种需要更高精度
            min_quantity = 1.0
            step_size = 1.0
        else:
            # 其他币种使用默认精度
            min_quantity = 0.1
            step_size = 0.1
        
        # 使用配置的仓位大小
        target_value = min(self.position_size, balance * 0.8)
        target_value = max(target_value, min_notional)
        
        quantity = target_value / price / self.leverage
        
        # 计算满足最小名义价值的数量
        required_quantity = min_notional / price
        
        # 取较大值，确保满足所有要求
        quantity = max(quantity, required_quantity, min_quantity)
        
        # 向上取整到步长的倍数
        quantity = math.ceil(quantity / step_size) * step_size
        
        # 验证订单价值是否满足最小名义价值要求
        order_value = quantity * price
        if order_value < min_notional:
            quantity = math.ceil(min_notional / price / step_size) * step_size
        
        self.logger.info(f"📊 计算持仓大小:")
        self.logger.info(f"   目标价值: {target_value:.2f} USDT")
        self.logger.info(f"   最小名义价值: {min_notional} USDT") 
        self.logger.info(f"   计算数量: {quantity} {self.base_asset}")
        self.logger.info(f"   实际价值: {quantity * price:.2f} USDT")
        
        return quantity
    
    @critical_retry
    def open_position(self, side: str = None) -> bool:
        """开仓 (支持多空双向)"""
        try:
            # 确定交易方向
            if side is None:
                if self.direction == "long":
                    side = "BUY"
                elif self.direction == "short":
                    side = "SELL"
                elif self.direction == "auto":
                    side = self.detect_market_direction()
                else:
                    self.logger.error(f"❌ 无效的策略方向: {self.direction}")
                    return False
            
            # 检查余额
            balance = self.check_account_balance()
            if balance < self.position_size:
                self.logger.warning(f"⚠️ 余额不足: {balance:.2f} < {self.position_size}")
                return False
            
            # 获取当前价格
            current_price = self.get_current_price()
            if not current_price:
                return False
            
            # 计算数量
            quantity = self.calculate_position_size(balance, current_price)
            
            # 计算预期手续费
            trade_value = quantity * current_price
            expected_fee = self.calculate_fees(trade_value)
            
            side_name = "多单" if side == "BUY" else "空单"
            self.logger.info(f"📈 准备开{side_name}:")
            self.logger.info(f"   价格: {current_price:.4f} USDT")
            self.logger.info(f"   数量: {quantity:.6f} {self.base_asset}")
            self.logger.info(f"   价值: {trade_value:.2f} USDT")
            self.logger.info(f"   预期手续费: {expected_fee:.4f} USDT")
            
            # 使用市价单开仓
            order = self.client.place_order(
                symbol=self.symbol,
                side=side,
                order_type="MARKET",
                quantity=quantity
            )
            
            if order and order.get('orderId'):
                self.position_id = order['orderId']
                self.entry_price = current_price
                self.entry_time = datetime.now()
                self.current_side = side
                self.current_position = {
                    'quantity': quantity,
                    'entry_price': current_price,
                    'entry_time': self.entry_time,
                    'order_id': self.position_id,
                    'side': side
                }
                
                # 计算止盈止损价格
                if side == "BUY":
                    take_profit_price = current_price * (1 + self.profit_threshold)
                    stop_loss_price = current_price * (1 - self.stop_loss_threshold)
                else:
                    take_profit_price = current_price * (1 - self.profit_threshold)
                    stop_loss_price = current_price * (1 + self.stop_loss_threshold)
                
                self.logger.info(f"✅ {side_name}开仓成功!")
                self.logger.info(f"   订单ID: {self.position_id}")
                self.logger.info(f"   入场价: {current_price:.4f} USDT")
                self.logger.info(f"   数量: {quantity:.6f} {self.base_asset}")
                self.logger.info(f"   🎯 止盈价格: {take_profit_price:.4f} USDT")
                self.logger.info(f"   🛑 止损价格: {stop_loss_price:.4f} USDT")
                return True
            else:
                self.logger.error(f"❌ 开仓失败: {order}")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ 开仓异常: {e}")
            raise

    @critical_retry
    def close_position(self, reason: str = "手动平仓") -> bool:
        """平仓"""
        try:
            if not self.current_position:
                self.logger.warning("⚠️ 没有持仓需要平仓")
                return False
            
            current_price = self.get_current_price()
            if not current_price:
                return False
            
            quantity = self.current_position['quantity']
            original_side = self.current_position['side']
            
            # 确定平仓方向
            close_side = "SELL" if original_side == "BUY" else "BUY"
            
            # 使用市价单平仓
            order = self.client.place_order(
                symbol=self.symbol,
                side=close_side,
                order_type="MARKET",
                quantity=quantity
            )
            
            if order and order.get('orderId'):
                # 计算盈亏
                pnl, pnl_percentage = self.calculate_profit_loss(
                    self.entry_price, current_price, quantity, original_side
                )
                
                # 计算手续费
                trade_value = quantity * current_price
                close_fee = self.calculate_fees(trade_value)
                open_fee = self.calculate_fees(quantity * self.entry_price)
                total_fee = open_fee + close_fee
                
                # 净盈亏
                net_pnl = pnl - total_fee
                
                # 持仓时间
                holding_time = datetime.now() - self.entry_time
                holding_hours = holding_time.total_seconds() / 3600
                
                self.logger.info(f"📊 平仓完成 - {reason}")
                self.logger.info(f"   入场价: {self.entry_price:.4f} USDT")
                self.logger.info(f"   出场价: {current_price:.4f} USDT")
                self.logger.info(f"   价格变动: {pnl_percentage*100:.2f}%")
                self.logger.info(f"   毛盈亏: {pnl:.4f} USDT")
                self.logger.info(f"   手续费: {total_fee:.4f} USDT")
                self.logger.info(f"   净盈亏: {net_pnl:.4f} USDT")
                self.logger.info(f"   持仓时间: {holding_hours:.2f} 小时")
                
                # 积分估算
                trade_volume = (quantity * self.entry_price) + (quantity * current_price)
                base_points = trade_volume * 0.1
                holding_bonus = 5.0 if holding_hours >= 1.0 else 1.0
                estimated_points = base_points * holding_bonus
                
                self.logger.info(f"🎯 预估积分: {estimated_points:.2f} (交易量积分 + {holding_bonus}x持仓加成)")
                
                # 重置状态
                self.current_position = None
                self.entry_time = None
                self.entry_price = None
                self.position_id = None
                self.current_side = None
                
                return True
            else:
                self.logger.error(f"❌ 平仓失败: {order}")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ 平仓异常: {e}")
            raise

    @api_retry
    def monitor_position(self) -> bool:
        """监控持仓状态并执行止盈止损"""
        try:
            positions = self.client.get_position_risk()
            target_position = None
            
            for pos in positions:
                if pos.get('symbol') == self.symbol and float(pos.get('positionAmt', 0)) != 0:
                    target_position = pos
                    break
            
            if not target_position:
                self.logger.info(f"❌ 没有找到{self.symbol}持仓")
                return True
            
            position_amt = float(target_position.get('positionAmt', 0))
            entry_price = float(target_position.get('entryPrice', 0))
            unrealized_pnl = float(target_position.get('unRealizedProfit', 0))
            
            if position_amt == 0 or entry_price == 0:
                self.logger.info("❌ 持仓数据异常")
                return True
            
            # 获取当前价格
            current_price = self.get_current_price()
            
            # 判断持仓方向
            is_long = position_amt > 0
            side = "BUY" if is_long else "SELL"
            
            # 计算盈亏百分比
            if is_long:
                pnl_percentage = (current_price - entry_price) / entry_price * 100
                take_profit_price = entry_price * (1 + self.profit_threshold)
                stop_loss_price = entry_price * (1 - self.stop_loss_threshold)
            else:
                pnl_percentage = (entry_price - current_price) / entry_price * 100
                take_profit_price = entry_price * (1 - self.profit_threshold)
                stop_loss_price = entry_price * (1 + self.stop_loss_threshold)
            
            position_type = "多单" if is_long else "空单"
            
            self.logger.info(f"\n📊 持仓监控 ({position_type}):")
            self.logger.info(f"   持仓数量: {abs(position_amt)} {self.base_asset}")
            self.logger.info(f"   入场价格: {entry_price:.4f} USDT")
            self.logger.info(f"   当前价格: {current_price:.4f} USDT")
            self.logger.info(f"   止盈价格: {take_profit_price:.4f} USDT")
            self.logger.info(f"   止损价格: {stop_loss_price:.4f} USDT")
            self.logger.info(f"   当前盈亏: {unrealized_pnl:.4f} USDT ({pnl_percentage:+.2f}%)")
            
            # 检查止盈条件
            if is_long and current_price >= take_profit_price:
                self.logger.info(f"🎯 多单触发止盈! 当前价格 {current_price:.4f} >= 止盈价格 {take_profit_price:.4f}")
                return self.close_position_by_amount(position_amt, "止盈")
            elif not is_long and current_price <= take_profit_price:
                self.logger.info(f"🎯 空单触发止盈! 当前价格 {current_price:.4f} <= 止盈价格 {take_profit_price:.4f}")
                return self.close_position_by_amount(position_amt, "止盈")
            
            # 检查止损条件
            if is_long and current_price <= stop_loss_price:
                self.logger.info(f"🛑 多单触发止损! 当前价格 {current_price:.4f} <= 止损价格 {stop_loss_price:.4f}")
                return self.close_position_by_amount(position_amt, "止损")
            elif not is_long and current_price >= stop_loss_price:
                self.logger.info(f"🛑 空单触发止损! 当前价格 {current_price:.4f} >= 止损价格 {stop_loss_price:.4f}")
                return self.close_position_by_amount(position_amt, "止损")
            
            return False
            
        except Exception as e:
            self.logger.error(f"❌ 监控持仓失败: {e}")
            raise
    
    def close_position_by_amount(self, position_amt: float, reason: str) -> bool:
        """根据持仓数量平仓"""
        try:
            self.logger.info(f"\n🔄 执行平仓 - 原因: {reason}")
            
            side = 'SELL' if position_amt > 0 else 'BUY'
            quantity = abs(position_amt)
            
            order = self.client.place_order(
                symbol=self.symbol,
                side=side,
                order_type='MARKET',
                quantity=quantity
            )
            
            if order and order.get('orderId'):
                self.logger.info(f"✅ 平仓成功! 订单ID: {order['orderId']}")
                return True
            else:
                self.logger.error(f"❌ 平仓失败: {order}")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ 平仓异常: {e}")
            return False
    
    def run_strategy(self):
        """运行完整策略"""
        try:
            direction_name = {"long": "多单", "short": "空单", "auto": "自动"}[self.direction]
            self.logger.info(f"\n🚀 开始执行{self.base_asset}交易策略 ({direction_name})")
            self.logger.info("=" * 60)
            
            # 1. 检查是否已有持仓
            has_position = False
            try:
                positions = self.client.get_position_risk()
                for pos in positions:
                    if pos.get('symbol') == self.symbol and float(pos.get('positionAmt', 0)) != 0:
                        has_position = True
                        self.logger.info(f"📊 发现现有{self.symbol}持仓，直接进入监控模式...")
                        break
            except:
                pass
            
            # 2. 如果没有持仓，尝试开仓
            if not has_position:
                self.logger.info(f"\n🎯 开始开仓 ({direction_name})...")
                if not self.open_position():
                    self.logger.error("❌ 开仓失败，策略终止")
                    return
                
                self.logger.info("✅ 开仓成功，等待3秒后开始监控...")
                time.sleep(3)
            
            # 3. 持续监控持仓
            self.logger.info("\n👀 开始持仓监控...")
            monitor_count = 0
            max_monitors = 1000
            
            while monitor_count < max_monitors:
                monitor_count += 1
                self.logger.info(f"\n🔍 第 {monitor_count} 次监控检查...")
                
                position_closed = self.monitor_position()
                
                if position_closed:
                    self.logger.info("🎉 持仓已平仓，策略执行完成!")
                    break
                
                self.logger.info("⏰ 等待30秒后继续监控...")
                time.sleep(30)
            
            if monitor_count >= max_monitors:
                self.logger.warning("⚠️ 达到最大监控次数，策略自动退出")
            
            # 4. 生成最终报告
            self.generate_final_report()
            
        except KeyboardInterrupt:
            self.logger.warning("\n⚠️ 用户中断策略执行")
            self.logger.info("正在检查当前持仓状态...")
            try:
                self.monitor_position()
            except:
                pass
            
        except Exception as e:
            self.logger.error(f"❌ 策略执行出错: {e}")
            self.logger.info("正在检查当前持仓状态...")
            try:
                self.monitor_position()
            except:
                pass
    
    def generate_final_report(self) -> None:
        """生成最终交易报告"""
        try:
            self.logger.info("\n📊 生成最终交易报告...")
            
            account_info = self.client.get_account_info()
            final_balance = float(account_info.get('availableBalance', 0))
            
            trades = self.client.get_account_trades(self.symbol, limit=10)
            
            self.logger.info(f"\n📈 {self.base_asset}交易总结:")
            self.logger.info(f"💰 当前余额: {final_balance:.2f} USDT")
            
            if trades:
                total_fee = sum(float(trade.get('commission', 0)) for trade in trades)
                total_volume = sum(float(trade.get('quoteQty', 0)) for trade in trades)
                
                self.logger.info(f"📊 交易统计:")
                self.logger.info(f"   总交易笔数: {len(trades)}")
                self.logger.info(f"   总交易量: {total_volume:.2f} USDT")
                self.logger.info(f"   总手续费: {total_fee:.4f} USDT")
                
                estimated_points = self.estimate_points(total_volume, 1.0, 1.0)
                self.logger.info(f"🎯 预估积分: {estimated_points:.0f} 分")
            
            self.logger.info("\n✅ 策略执行完成!")
            
        except Exception as e:
            self.logger.error(f"❌ 生成报告失败: {e}")
    
    def estimate_points(self, volume: float, holding_hours: float, taker_ratio: float) -> float:
        """估算Aster积分"""
        volume_points = volume * 2
        
        if holding_hours >= 1.0:
            holding_multiplier = 5.0
        else:
            holding_multiplier = 1.0
        
        taker_multiplier = 1.0 + taker_ratio
        total_points = volume_points * holding_multiplier * taker_multiplier
        
        return total_points

@dataclass
class VolatilityData:
    """波动率数据"""
    symbol: str
    name: str
    current_price: float
    price_change_24h: float
    price_change_percentage_24h: float
    volatility_1h: float
    volatility_24h: float
    volatility_7d: float
    volume_24h: float
    market_cap: float
    platforms: List[str]
    volatility_score: float
    risk_level: str
    recommendation: str


def load_volatility_data() -> Optional[List[VolatilityData]]:
    """从上级目录加载最新的波动率数据"""
    try:
        # 获取上级目录路径
        parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        
        # 搜索波动率数据文件
        pattern = os.path.join(parent_dir, "common_pairs_volatility_*.json")
        files = glob.glob(pattern)
        
        if not files:
            logging.warning("⚠️ 未找到波动率数据文件")
            return None
        
        # 获取最新的文件
        latest_file = max(files, key=os.path.getctime)
        logging.info(f"📊 加载波动率数据: {os.path.basename(latest_file)}")
        
        with open(latest_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        volatility_list = []
        for coin in data.get('coins', []):
            volatility_data = VolatilityData(
                symbol=coin['symbol'],
                name=coin['name'],
                current_price=coin['current_price'],
                price_change_24h=coin['price_change_24h'],
                price_change_percentage_24h=coin['price_change_percentage_24h'],
                volatility_1h=coin['volatility_1h'],
                volatility_24h=coin['volatility_24h'],
                volatility_7d=coin['volatility_7d'],
                volume_24h=coin['volume_24h'],
                market_cap=coin['market_cap'],
                platforms=coin['platforms'],
                volatility_score=coin['volatility_score'],
                risk_level=coin['risk_level'],
                recommendation=coin['recommendation']
            )
            volatility_list.append(volatility_data)
        
        logging.info(f"✅ 成功加载 {len(volatility_list)} 个币种的波动率数据")
        return volatility_list
        
    except Exception as e:
        logging.error(f"❌ 加载波动率数据失败: {e}")
        return None


def get_high_volatility_symbols(limit: int = 10) -> List[str]:
    """获取高波动率币种列表"""
    volatility_data = load_volatility_data()
    if not volatility_data:
        # 如果没有波动率数据，返回默认币种
        return ['SOLUSDT', 'BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'ADAUSDT']
    
    # 按波动率评分排序，返回前N个
    sorted_data = sorted(volatility_data, key=lambda x: x.volatility_score, reverse=True)
    return [data.symbol for data in sorted_data[:limit]]


def get_trading_symbols():
    """获取支持的交易对列表，优先显示高波动率币种"""
    # 基础币种列表
    base_symbols = {
        'BTC': {'symbol': 'BTCUSDT', 'name': 'Bitcoin'},
        'ETH': {'symbol': 'ETHUSDT', 'name': 'Ethereum'},
        'SOL': {'symbol': 'SOLUSDT', 'name': 'Solana'},
        'BNB': {'symbol': 'BNBUSDT', 'name': 'Binance Coin'},
        'ADA': {'symbol': 'ADAUSDT', 'name': 'Cardano'},
        'DOT': {'symbol': 'DOTUSDT', 'name': 'Polkadot'},
        'MATIC': {'symbol': 'MATICUSDT', 'name': 'Polygon'},
        'AVAX': {'symbol': 'AVAXUSDT', 'name': 'Avalanche'},
        'LINK': {'symbol': 'LINKUSDT', 'name': 'Chainlink'},
        'UNI': {'symbol': 'UNIUSDT', 'name': 'Uniswap'}
    }
    
    # 尝试加载波动率数据
    volatility_data = load_volatility_data()
    if volatility_data:
        # 如果有波动率数据，优先显示高波动率币种
        high_vol_symbols = {}
        for data in volatility_data[:10]:  # 取前10个高波动率币种
            symbol_parts = data.symbol.split('_')
            if len(symbol_parts) >= 2:
                base = symbol_parts[0]
                full_symbol = f"{base}USDT"
                high_vol_symbols[base] = {'symbol': full_symbol, 'name': data.name}
        
        # 合并高波动率币种和基础币种
        all_symbols = {**high_vol_symbols, **base_symbols}
        return dict(list(all_symbols.items())[:15])  # 最多返回15个
    
    return base_symbols

def display_symbol_menu():
    """显示交易对选择菜单"""
    symbols = get_trading_symbols()
    
    # 检查是否有波动率数据
    volatility_data = load_volatility_data()
    if volatility_data:
        print(f"\n📊 基于最新波动率数据 (共{len(volatility_data)}个币种)")
        print("🔥 高波动率币种优先显示")
    
    print("\n🪙 支持的交易对:")
    
    items = list(symbols.items())
    for i, (code, info) in enumerate(items, 1):
        symbol_name = info['symbol']
        full_name = info['name']
        
        # 如果有波动率数据，显示额外信息
        vol_info = ""
        if volatility_data:
            # 查找对应的波动率数据
            for vol_data in volatility_data:
                if vol_data.symbol.replace('_', '') == symbol_name.replace('USDT', '_USDT'):
                    vol_info = f" 📈{vol_data.volatility_score:.0f}分"
                    break
        
        print(f"  {i:2d}. {code:6s} - {full_name:15s} ({symbol_name}){vol_info}")
    
    print(f"  0. 退出")
    
    if volatility_data:
        print(f"\n💡 提示: 评分越高表示波动率越大，潜在收益和风险也越高")

def get_user_symbol_choice():
    """获取用户交易对选择"""
    symbols = get_trading_symbols()
    symbol_list = list(symbols.keys())
    
    while True:
        try:
            display_symbol_menu()
            choice = input("\n请选择交易对 (输入数字或币种代码，默认SOL): ").strip().upper()
            
            if choice == "":
                return "SOLUSDT"
            
            if choice == "0":
                return None
            
            # 检查是否是数字选择
            if choice.isdigit():
                choice_num = int(choice)
                if 1 <= choice_num <= len(symbol_list):
                    selected_code = symbol_list[choice_num - 1]
                    return symbols[selected_code]['symbol']
                else:
                    print("❌ 无效的数字选择")
                    continue
            
            # 检查是否是币种代码
            if choice in symbols:
                return symbols[choice]['symbol']
            else:
                print(f"❌ 不支持的币种: {choice}")
                continue
                
        except KeyboardInterrupt:
            return None
        except Exception as e:
            print(f"❌ 输入错误: {e}")
            continue

def get_user_direction_choice():
    """获取用户交易方向选择"""
    print("\n📈 交易方向选择:")
    print("  1. 多单 (long) - 看涨")
    print("  2. 空单 (short) - 看跌") 
    print("  3. 自动 (auto) - 系统自动判断")
    
    while True:
        try:
            choice = input("请选择交易方向 (1/2/3，默认1-多单): ").strip()
            
            if choice == "" or choice == "1":
                return "long"
            elif choice == "2":
                return "short"
            elif choice == "3":
                return "auto"
            else:
                print("❌ 无效选择，请输入1、2或3")
                continue
                
        except KeyboardInterrupt:
            return "long"
        except Exception as e:
            print(f"❌ 输入错误: {e}")
            continue

def get_user_position_size():
    """获取用户仓位大小"""
    print("\n💰 仓位大小设置:")
    print("  推荐仓位: 25-100 USDT")
    
    while True:
        try:
            choice = input("请输入仓位大小 (USDT，默认25): ").strip()
            
            if choice == "":
                return 25.0
            
            size = float(choice)
            if size <= 0:
                print("❌ 仓位大小必须大于0")
                continue
            elif size < 10:
                print("⚠️ 仓位过小可能无法满足最小交易要求")
                confirm = input("是否继续? (y/n，默认n): ").strip().lower()
                if confirm != 'y':
                    continue
            elif size > 1000:
                print("⚠️ 仓位较大，请确认风险承受能力")
                confirm = input("是否继续? (y/n，默认n): ").strip().lower()
                if confirm != 'y':
                    continue
            
            return size
            
        except ValueError:
            print("❌ 请输入有效的数字")
            continue
        except KeyboardInterrupt:
            return 25.0
        except Exception as e:
            print(f"❌ 输入错误: {e}")
            continue

def get_user_advanced_settings():
    """获取用户高级设置"""
    print("\n⚙️ 高级设置 (可直接回车使用默认值):")
    
    # 杠杆设置
    while True:
        try:
            leverage_input = input("杠杆倍数 (1-10，默认2): ").strip()
            if leverage_input == "":
                leverage = 2
                break
            leverage = int(leverage_input)
            if 1 <= leverage <= 10:
                break
            else:
                print("❌ 杠杆倍数必须在1-10之间")
        except ValueError:
            print("❌ 请输入有效的整数")
        except KeyboardInterrupt:
            leverage = 2
            break
    
    # 止盈设置
    while True:
        try:
            profit_input = input("止盈阈值 (0.5-5.0%，默认0.8%): ").strip()
            if profit_input == "":
                profit_threshold = 0.008
                break
            profit_pct = float(profit_input.rstrip('%'))
            if 0.5 <= profit_pct <= 5.0:
                profit_threshold = profit_pct / 100
                break
            else:
                print("❌ 止盈阈值必须在0.5%-5.0%之间")
        except ValueError:
            print("❌ 请输入有效的数字")
        except KeyboardInterrupt:
            profit_threshold = 0.008
            break
    
    # 止损设置
    while True:
        try:
            loss_input = input("止损阈值 (0.3-3.0%，默认0.6%): ").strip()
            if loss_input == "":
                stop_loss_threshold = 0.006
                break
            loss_pct = float(loss_input.rstrip('%'))
            if 0.3 <= loss_pct <= 3.0:
                stop_loss_threshold = loss_pct / 100
                break
            else:
                print("❌ 止损阈值必须在0.3%-3.0%之间")
        except ValueError:
            print("❌ 请输入有效的数字")
        except KeyboardInterrupt:
            stop_loss_threshold = 0.006
            break
    
    # 循环次数
    while True:
        try:
            loops_input = input("循环执行次数 (1-100，默认1): ").strip()
            if loops_input == "":
                loops = 1
                break
            loops = int(loops_input)
            if 1 <= loops <= 10000:
                break
            else:
                print("❌ 循环次数必须在1-10000之间")
        except ValueError:
            print("❌ 请输入有效的整数")
        except KeyboardInterrupt:
            loops = 1
            break
    
    return {
        'leverage': leverage,
        'profit_threshold': profit_threshold,
        'stop_loss_threshold': stop_loss_threshold,
        'loops': loops
    }

def get_interactive_config():
    """获取交互式配置"""
    print("🚀 任意币种交易策略配置向导")
    print("=" * 50)
    
    # 获取交易对
    symbol = get_user_symbol_choice()
    if symbol is None:
        return None
    
    # 获取交易方向
    direction = get_user_direction_choice()
    
    # 获取仓位大小
    position_size = get_user_position_size()
    
    # 询问是否需要高级设置
    print("\n🔧 是否需要自定义高级设置?")
    advanced_choice = input("(y/n，默认n使用推荐设置): ").strip().lower()
    
    if advanced_choice == 'y':
        advanced = get_user_advanced_settings()
    else:
        advanced = {
            'leverage': 2,
            'profit_threshold': 0.008,
            'stop_loss_threshold': 0.006,
            'loops': 1
        }
    
    return {
        'symbol': symbol,
        'direction': direction,
        'position_size': position_size,
        **advanced,
        'min_holding_time': 1800,
        'config_path': 'config.json'
    }

def parse_arguments():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description='任意币种交易策略')
    
    parser.add_argument('--symbol', '-s', type=str, default='SOLUSDT',
                       help='交易对符号 (如 SOLUSDT, BTCUSDT, ETHUSDT)')
    parser.add_argument('--direction', '-d', type=str, default='long',
                       choices=['long', 'short', 'auto'],
                       help='交易方向: long(多单), short(空单), auto(自动)')
    parser.add_argument('--position-size', '-p', type=float, default=25.0,
                       help='每次开仓金额 (USDT)')
    parser.add_argument('--leverage', '-l', type=int, default=2,
                       help='杠杆倍数')
    parser.add_argument('--profit-threshold', type=float, default=0.008,
                       help='止盈阈值 (小数形式，如0.008表示0.8%%)')
    parser.add_argument('--stop-loss-threshold', type=float, default=0.006,
                       help='止损阈值 (小数形式，如0.006表示0.6%%)')
    parser.add_argument('--min-holding-time', type=int, default=1800,
                       help='最小持仓时间 (秒)')
    parser.add_argument('--config', '-c', type=str, default='config.json',
                       help='配置文件路径')
    parser.add_argument('--loops', type=int, default=100,
                       help='循环执行次数 (默认100次)')
    parser.add_argument('--interactive', '-i', action='store_true',
                       help='使用交互式配置模式')
    
    return parser.parse_args()

def main():
    """主函数"""
    args = parse_arguments()
    
    # 检查是否使用交互式模式
    if args.interactive or len(sys.argv) == 1:
        # 交互式配置
        config = get_interactive_config()
        if config is None:
            print("👋 已退出")
            return
        
        # 显示配置摘要
        print("\n📋 配置摘要:")
        print("=" * 50)
        print(f"📊 交易对: {config['symbol']}")
        print(f"📈 方向: {config['direction']}")
        print(f"💰 仓位: {config['position_size']} USDT")
        print(f"🔧 杠杆: {config['leverage']}x")
        print(f"🎯 止盈: {config['profit_threshold']*100}%")
        print(f"🛑 止损: {config['stop_loss_threshold']*100}%")
        print(f"🔄 循环: {config['loops']}次")
        print("=" * 50)
        
        # 确认开始
        confirm = input("\n是否开始交易? (y/n，默认y): ").strip().lower()
        if confirm == 'n':
            print("👋 已取消")
            return
        
        # 使用交互式配置
        symbol = config['symbol']
        direction = config['direction']
        position_size = config['position_size']
        leverage = config['leverage']
        profit_threshold = config['profit_threshold']
        stop_loss_threshold = config['stop_loss_threshold']
        loops = config['loops']
        min_holding_time = config['min_holding_time']
        config_path = config['config_path']
        
    else:
        # 命令行参数模式
        print("🚀 任意币种交易策略启动")
        print("=" * 50)
        print(f"📊 交易参数:")
        print(f"   交易对: {args.symbol}")
        print(f"   方向: {args.direction}")
        print(f"   仓位大小: {args.position_size} USDT")
        print(f"   杠杆: {args.leverage}x")
        print(f"   止盈: {args.profit_threshold*100}%")
        print(f"   止损: {args.stop_loss_threshold*100}%")
        print(f"   最小持仓时间: {args.min_holding_time}秒")
        print(f"   循环次数: {args.loops}")
        print("=" * 50)
        
        # 使用命令行参数
        symbol = args.symbol
        direction = args.direction
        position_size = args.position_size
        leverage = args.leverage
        profit_threshold = args.profit_threshold
        stop_loss_threshold = args.stop_loss_threshold
        loops = args.loops
        min_holding_time = args.min_holding_time
        config_path = args.config
    
    total_pnl = 0.0
    consecutive_failures = 0
    max_consecutive_failures = 3
    
    try:
        for loop in range(loops):
            print(f"\n🔄 开始第 {loop + 1}/{loops} 轮策略...")
            
            # 检查熔断器状态
            cb_status = get_circuit_breaker_status()
            if cb_status['state'] == 'OPEN':
                wait_time = cb_status.get('time_until_retry', 0)
                print(f"🚨 熔断器开启中，等待 {wait_time:.0f} 秒后重试...")
                if wait_time > 0:
                    time.sleep(min(wait_time, 60))
                    continue
            
            try:
                # 创建策略实例
                strategy = AnyCoinTradingStrategy(
                    symbol=symbol,
                    direction=direction,
                    position_size=position_size,
                    leverage=leverage,
                    profit_threshold=profit_threshold,
                    stop_loss_threshold=stop_loss_threshold,
                    min_holding_time=min_holding_time,
                    config_path=config_path
                )
                
                # 检查账户状态
                balance = strategy.check_account_balance()
                if balance < position_size:
                    print(f"❌ 账户余额不足: {balance:.2f} USDT < {position_size} USDT")
                    break
                
                # 记录开始余额
                start_balance = balance
                
                # 运行策略
                strategy.run_strategy()
                
                # 计算本轮盈亏
                end_balance = strategy.check_account_balance()
                loop_pnl = end_balance - start_balance
                total_pnl += loop_pnl
                
                print(f"\n📊 第 {loop + 1} 轮完成:")
                print(f"   本轮盈亏: {loop_pnl:+.4f} USDT")
                print(f"   累计盈亏: {total_pnl:+.4f} USDT")
                print(f"   当前余额: {end_balance:.2f} USDT")
                
                consecutive_failures = 0
                
                # 如果不是最后一轮，等待60秒
                if loop < loops - 1:
                    print("⏰ 等待20秒后开始下一轮...")
                    time.sleep(20)
                    
            except Exception as e:
                consecutive_failures += 1
                print(f"❌ 第 {loop + 1} 轮策略执行失败: {e}")
                
                if consecutive_failures >= max_consecutive_failures:
                    print(f"🚨 连续失败 {consecutive_failures} 次，尝试重置熔断器...")
                    reset_circuit_breaker()
                    consecutive_failures = 0
                    
                    print("⏰ 等待 300 秒后重试...")
                    time.sleep(300)
                else:
                    wait_time = consecutive_failures * 30
                    print(f"⏰ 等待 {wait_time} 秒后重试...")
                    time.sleep(wait_time)
        
        print(f"\n🏆 策略执行完成!")
        print(f"   总轮数: {loops}")
        print(f"   总盈亏: {total_pnl:+.4f} USDT")
        
    except KeyboardInterrupt:
        print(f"\n⚠️ 用户中断，累计盈亏: {total_pnl:+.4f} USDT")
    except Exception as e:
        print(f"❌ 程序运行失败: {e}")

if __name__ == "__main__":
    main()