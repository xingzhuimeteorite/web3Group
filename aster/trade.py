#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SOL多单交易策略
目标：通过SOL多单交易获取Aster积分，控制风险和成本
"""

import time
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
from aster_api_client import AsterFinanceClient
from config_loader import ConfigLoader
from retry_handler import smart_retry, network_retry, api_retry, critical_retry, reset_circuit_breaker, get_circuit_breaker_status

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('sol_strategy.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class SOLBidirectionalStrategy:
    """SOL双向交易策略类"""
    
    def __init__(self, config_path: str = "config.json", direction: str = "long"):
        """初始化策略
        
        Args:
            config_path: 配置文件路径
            direction: 交易方向 ('long', 'short', 'auto')
        """
        self.config_loader = ConfigLoader(config_path)
        self.client = AsterFinanceClient(
            api_key=self.config_loader.get('api_key'),
            secret_key=self.config_loader.get('secret_key'),
            base_url=self.config_loader.get('base_url')
        )
        
        # 策略参数
        self.symbol = "SOLUSDT"
        self.position_size = 50.0  # 每次开仓金额 (USDT) - 杠杆后总金额需要*2
        self.leverage = 2  # 杠杆倍数 - 2倍杠杆后达到50U
        self.fee_rate = 0.0005  # 手续费率 0.05%
        self.profit_threshold = 0.008  # 止盈阈值 0.8%
        self.stop_loss_threshold = 0.006  # 止损阈值 0.6%
        self.min_holding_time = 1800  # 最小持仓时间 30分钟 (获得5倍积分)
        
        # 交易方向控制
        self.direction = direction.lower()  # 'long', 'short', 'auto'
        self.valid_directions = ['long', 'short', 'auto']
        if self.direction not in self.valid_directions:
            raise ValueError(f"无效的交易方向: {direction}. 支持的方向: {self.valid_directions}")
        
        # 状态跟踪
        self.current_position = None
        self.entry_time = None
        self.entry_price = None
        self.position_id = None
        self.current_side = None  # 'BUY' 或 'SELL'
        
        direction_name = {"long": "多单", "short": "空单", "auto": "自动"}[self.direction]
        logger.info(f"🚀 SOL双向策略初始化完成 - {direction_name}模式")
        logger.info(f"📊 策略参数: 仓位={self.position_size}USDT, 杠杆={self.leverage}x, 手续费={self.fee_rate*100}%")
        logger.info(f"🎯 止盈={self.profit_threshold*100}%, 止损={self.stop_loss_threshold*100}%")
    
    @network_retry
    def get_current_price(self) -> float:
        """获取SOL当前价格"""
        try:
            ticker = self.client.get_ticker_price(self.symbol)
            return float(ticker['price'])
        except Exception as e:
            logger.error(f"❌ 获取价格失败: {e}")
            raise  # 让重试装饰器处理
    
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
        """检测市场方向 (改进版本)
        
        Returns:
            'BUY' 或 'SELL'
        """
        try:
            # 获取最近的价格数据进行简单趋势判断
            current_price = self.get_current_price()
            if not current_price:
                logger.warning("⚠️ 无法获取价格，默认做多")
                return "BUY"
            
            # 简单的趋势检测策略
            # 1. 基于时间的轮换策略
            from datetime import datetime
            current_hour = datetime.now().hour
            
            # 2. 基于价格的简单判断 (可以扩展为更复杂的技术指标)
            # 这里使用一个简单的规则：奇数小时做多，偶数小时做空
            if current_hour % 2 == 1:
                direction = "BUY"
                reason = f"时间策略 (第{current_hour}小时-奇数)"
            else:
                direction = "SELL" 
                reason = f"时间策略 (第{current_hour}小时-偶数)"
            
            # 3. 可以添加更多策略，如：
            # - RSI指标判断超买超卖
            # - 移动平均线趋势
            # - 成交量分析
            # - 市场情绪指标
            
            direction_name = "多单" if direction == "BUY" else "空单"
            logger.info(f"🎯 自动检测方向: {direction_name} ({reason})")
            
            return direction
            
        except Exception as e:
            logger.error(f"❌ 方向检测失败: {e}，默认做多")
            return "BUY"
    
    @api_retry
    def check_account_balance(self) -> float:
        """检查账户余额"""
        try:
            account_info = self.client.get_account_info()
            available_balance = float(account_info['availableBalance'])
            logger.info(f"💰 可用余额: {available_balance:.2f} USDT")
            return available_balance
        except Exception as e:
            logger.error(f"❌ 获取账户信息失败: {e}")
            raise  # 让重试装饰器处理
    
    def calculate_position_size(self, balance: float, price: float) -> float:
        """
        计算合适的持仓大小
        
        Args:
            balance: 账户余额
            price: 当前价格
            
        Returns:
            持仓数量
        """
        import math
        
        # 交易规则
        min_notional = 30.0  # 最小名义价值5 USDT
        min_quantity = 0.01  # 最小数量
        step_size = 0.01    # 数量步长
        
        # 使用用户配置的开仓金额，但确保满足最小名义价值
        target_value = min(self.position_size, balance * 0.8)  # 最多使用80%余额
        target_value = max(target_value, min_notional)  # 确保不小于最小名义价值
        
        # 目标名义价值=配置的仓位大小×杠杆；据此计算数量
        quantity = (target_value * self.leverage) / price
        
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
        
        print(f"📊 计算持仓大小:")
        print(f"   目标价值: {target_value:.2f} USDT")
        print(f"   最小名义价值: {min_notional} USDT") 
        print(f"   计算数量: {quantity} SOL")
        print(f"   实际价值: {quantity * price:.2f} USDT")
        
        return quantity
    
    @critical_retry
    def open_position(self, side: str = None) -> bool:
        """开仓 (支持多空双向)
        
        Args:
            side: 交易方向 ('BUY'/'SELL')，如果为None则根据策略方向自动确定
        """
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
                    logger.error(f"❌ 无效的策略方向: {self.direction}")
                    return False

            # 在下单前确保交易对杠杆设置为策略要求
            try:
                resp = self.client.change_initial_leverage(self.symbol, self.leverage)
                logger.info(f"🔧 已设置杠杆: {self.symbol} -> {self.leverage}x")
            except Exception as e:
                logger.warning(f"⚠️ 设置杠杆失败，继续使用交易所当前杠杆: {e}")
            
            # 检查余额
            balance = self.check_account_balance()
            if balance < self.position_size:
                logger.warning(f"⚠️ 余额不足: {balance:.2f} < {self.position_size}")
                return False
            
            # 获取当前价格
            current_price = self.get_current_price()
            if not current_price:
                return False
            
            # 计算数量 (使用新的计算方法)
            quantity = self.calculate_position_size(balance, current_price)
            
            # 计算预期手续费
            trade_value = quantity * current_price
            expected_fee = self.calculate_fees(trade_value)
            
            side_name = "多单" if side == "BUY" else "空单"
            logger.info(f"📈 准备开{side_name}:")
            logger.info(f"   价格: {current_price:.4f} USDT")
            logger.info(f"   数量: {quantity:.6f} SOL")
            logger.info(f"   价值: {trade_value:.2f} USDT")
            logger.info(f"   预期手续费: {expected_fee:.4f} USDT")
            
            # 使用市价单开仓 (Taker订单，获得2倍积分)
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
                take_profit_price = current_price * (1 + self.profit_threshold)
                stop_loss_price = current_price * (1 - self.stop_loss_threshold)
                
                logger.info(f"✅ 多单开仓成功!")
                logger.info(f"   订单ID: {self.position_id}")
                logger.info(f"   入场价: {current_price:.4f} USDT")
                logger.info(f"   数量: {quantity:.6f} SOL")
                logger.info(f"   🎯 止盈价格: {take_profit_price:.4f} USDT (+{self.profit_threshold*100:.1f}%)")
                logger.info(f"   🛑 止损价格: {stop_loss_price:.4f} USDT (-{self.stop_loss_threshold*100:.1f}%)")
                return True
            else:
                logger.error(f"❌ 开仓失败: {order}")
                return False
                
        except Exception as e:
            logger.error(f"❌ 开仓异常: {e}")
            raise  # 让重试装饰器处理

    @critical_retry
    def close_position(self, reason: str = "手动平仓") -> bool:
        """平仓"""
        try:
            if not self.current_position:
                logger.warning("⚠️ 没有持仓需要平仓")
                return False
            
            current_price = self.get_current_price()
            if not current_price:
                return False
            
            quantity = self.current_position['quantity']
            
            # 使用市价单平仓 (Taker订单)
            order = self.client.place_order(
                symbol=self.symbol,
                side="SELL",
                order_type="MARKET",
                quantity=quantity
            )
            
            if order and order.get('orderId'):
                # 计算盈亏
                pnl, pnl_percentage = self.calculate_profit_loss(
                    self.entry_price, current_price, quantity
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
                
                logger.info(f"📊 平仓完成 - {reason}")
                logger.info(f"   入场价: {self.entry_price:.4f} USDT")
                logger.info(f"   出场价: {current_price:.4f} USDT")
                logger.info(f"   价格变动: {pnl_percentage*100:.2f}%")
                logger.info(f"   毛盈亏: {pnl:.4f} USDT")
                logger.info(f"   手续费: {total_fee:.4f} USDT")
                logger.info(f"   净盈亏: {net_pnl:.4f} USDT")
                logger.info(f"   持仓时间: {holding_hours:.2f} 小时")
                
                # 积分估算
                trade_volume = (quantity * self.entry_price) + (quantity * current_price)
                base_points = trade_volume * 0.1  # Taker订单2倍积分
                holding_bonus = 5.0 if holding_hours >= 1.0 else 1.0
                estimated_points = base_points * holding_bonus
                
                logger.info(f"🎯 预估积分: {estimated_points:.2f} (交易量积分 + {holding_bonus}x持仓加成)")
                
                # 重置状态
                self.current_position = None
                self.entry_time = None
                self.entry_price = None
                self.position_id = None
                
                return True
            else:
                logger.error(f"❌ 平仓失败: {order}")
                return False
                
        except Exception as e:
            logger.error(f"❌ 平仓异常: {e}")
            raise  # 让重试装饰器处理

    @api_retry
    def monitor_position(self) -> bool:
        """
        监控持仓状态并执行止盈止损
        
        Returns:
            True: 持仓已平仓, False: 持仓继续持有
        """
        try:
            positions = self.client.get_position_risk()
            sol_position = None
            
            for pos in positions:
                if pos.get('symbol') == 'SOLUSDT' and float(pos.get('positionAmt', 0)) != 0:
                    sol_position = pos
                    break
            
            if not sol_position:
                print("❌ 没有找到SOL持仓")
                return True
            
            position_amt = float(sol_position.get('positionAmt', 0))
            entry_price = float(sol_position.get('entryPrice', 0))
            unrealized_pnl = float(sol_position.get('unRealizedProfit', 0))
            
            if position_amt == 0 or entry_price == 0:
                print("❌ 持仓数据异常")
                return True
            
            # 获取当前价格
            ticker = self.client.get_ticker_price('SOLUSDT')
            current_price = float(ticker['price'])
            
            # 判断持仓方向
            is_long = position_amt > 0
            side = "BUY" if is_long else "SELL"
            
            # 计算盈亏百分比 (支持多空双向)
            if is_long:  # 多单
                pnl_percentage = (current_price - entry_price) / entry_price * 100
                take_profit_price = entry_price * (1 + self.profit_threshold)
                stop_loss_price = entry_price * (1 - self.stop_loss_threshold)
            else:  # 空单
                pnl_percentage = (entry_price - current_price) / entry_price * 100
                take_profit_price = entry_price * (1 - self.profit_threshold)
                stop_loss_price = entry_price * (1 + self.stop_loss_threshold)
            
            # 计算持仓时间
            import time
            current_time = int(time.time() * 1000)
            # 注意：这里无法直接获取开仓时间，使用估算
            holding_hours = 0  # 实际应用中需要记录开仓时间
            
            position_type = "多单" if is_long else "空单"
            
            # 计算到期平仓时间 - 修复变量名错误
            min_holding_hours = self.min_holding_time / 3600  # 转换为小时
            # 使用当前时间估算到期时间
            from datetime import datetime, timedelta
            estimated_entry_time = datetime.now() - timedelta(hours=holding_hours)
            expiry_time = estimated_entry_time + timedelta(seconds=self.min_holding_time)
            expiry_time_str = expiry_time.strftime("%H:%M:%S")
            
            print(f"\n📊 持仓监控 ({position_type}):")
            print(f"   持仓数量: {abs(position_amt)} SOL")
            print(f"   入场价格: {entry_price:.4f} USDT")
            print(f"   当前价格: {current_price:.4f} USDT")
            print(f"   止盈价格: {take_profit_price:.4f} USDT (+{self.profit_threshold*100}%)")
            print(f"   止损价格: {stop_loss_price:.4f} USDT (-{self.stop_loss_threshold*100}%)")
            print(f"   当前盈亏: {unrealized_pnl:.4f} USDT ({pnl_percentage:+.2f}%)")
            print(f"   持仓时间: {holding_hours:.1f} 小时")
            print(f"   到期时间: {expiry_time_str} (最小持仓{min_holding_hours:.1f}小时)")
            
            # 检查止盈条件 (多空双向)
            if is_long and current_price >= take_profit_price:
                print(f"🎯 多单触发止盈! 当前价格 {current_price:.4f} >= 止盈价格 {take_profit_price:.4f}")
                return self.close_position_by_amount(position_amt, "止盈")
            elif not is_long and current_price <= take_profit_price:
                print(f"🎯 空单触发止盈! 当前价格 {current_price:.4f} <= 止盈价格 {take_profit_price:.4f}")
                return self.close_position_by_amount(position_amt, "止盈")
            
            # 检查止损条件 (多空双向)
            if is_long and current_price <= stop_loss_price:
                print(f"🛑 多单触发止损! 当前价格 {current_price:.4f} <= 止损价格 {stop_loss_price:.4f}")
                return self.close_position_by_amount(position_amt, "止损")
            elif not is_long and current_price >= stop_loss_price:
                print(f"🛑 空单触发止损! 当前价格 {current_price:.4f} >= 止损价格 {stop_loss_price:.4f}")
                return self.close_position_by_amount(position_amt, "止损")
            
            # 检查最小持仓时间（为了获得5x积分）
            if holding_hours >= 1.0 and pnl_percentage > 0.5:
                print(f"⏰ 已持仓1小时且有盈利，可考虑获利了结")
                # 这里可以添加更复杂的退出逻辑
            
            return False
            
        except Exception as e:
            print(f"❌ 监控持仓失败: {e}")
            raise  # 让重试装饰器处理
    
    def close_position_by_amount(self, position_amt: float, reason: str) -> bool:
        """
        平仓
        
        Args:
            position_amt: 持仓数量
            reason: 平仓原因
            
        Returns:
            是否成功平仓
        """
        try:
            print(f"\n🔄 执行平仓 - 原因: {reason}")
            
            # 平仓（卖出）
            side = 'SELL' if position_amt > 0 else 'BUY'
            quantity = abs(position_amt)
            
            order = self.client.place_order(
                symbol='SOLUSDT',
                side=side,
                order_type='MARKET',
                quantity=quantity
            )
            
            print(f"✅ 平仓订单已提交:")
            print(f"   订单ID: {order.get('orderId')}")
            print(f"   数量: {quantity} SOL")
            print(f"   方向: {side}")
            
            # 等待订单执行
            import time
            time.sleep(2)
            
            # 检查平仓结果
            final_positions = self.client.get_position_risk()
            for pos in final_positions:
                if pos.get('symbol') == 'SOLUSDT':
                    final_amt = float(pos.get('positionAmt', 0))
                    if abs(final_amt) < 0.001:  # 基本为0
                        print(f"🎉 平仓成功! {reason}完成")
                        
                        # 获取最终盈亏
                        account_info = self.client.get_account_info()
                        final_balance = float(account_info.get('availableBalance', 0))
                        print(f"💰 当前余额: {final_balance:.2f} USDT")
                        
                        return True
                    else:
                        print(f"⚠️ 平仓可能未完全执行，剩余持仓: {final_amt}")
                        return False
            
            return True
            
        except Exception as e:
            print(f"❌ 平仓失败: {e}")
            return False
    
    def check_exit_conditions(self) -> Optional[str]:
        """检查是否需要平仓"""
        if not self.current_position:
            return None
        
        current_price = self.get_current_price()
        if not current_price:
            return None
        
        # 计算盈亏
        pnl, pnl_percentage = self.calculate_profit_loss(
            self.entry_price, current_price, self.current_position['quantity']
        )
        
        # 计算手续费
        quantity = self.current_position['quantity']
        open_fee = self.calculate_fees(quantity * self.entry_price)
        close_fee = self.calculate_fees(quantity * current_price)
        total_fee = open_fee + close_fee
        
        # 净盈亏
        net_pnl = pnl - total_fee
        
        # 持仓时间
        holding_time = datetime.now() - self.entry_time
        holding_hours = holding_time.total_seconds() / 3600
        
        # 计算当前止盈止损价格
        take_profit_price = self.entry_price * (1 + self.profit_threshold)
        stop_loss_price = self.entry_price * (1 - self.stop_loss_threshold)
        
        logger.info(f"📊 持仓状态检查:")
        logger.info(f"   入场价格: {self.entry_price:.4f} USDT")
        logger.info(f"   当前价格: {current_price:.4f} USDT")
        logger.info(f"   🎯 止盈价格: {take_profit_price:.4f} USDT")
        logger.info(f"   🛑 止损价格: {stop_loss_price:.4f} USDT")
        logger.info(f"   盈亏率: {pnl_percentage*100:.2f}%")
        logger.info(f"   净盈亏: {net_pnl:.4f} USDT")
        logger.info(f"   持仓时间: {holding_hours:.2f} 小时")
        
        # 止损检查
        if pnl_percentage <= -self.stop_loss_threshold:
            return f"止损触发 (亏损{abs(pnl_percentage)*100:.2f}%)"
        
        # 止盈检查 (盈利能覆盖手续费)
        if net_pnl > 0 and pnl_percentage >= self.profit_threshold:
            return f"止盈触发 (盈利{pnl_percentage*100:.2f}%, 净盈利{net_pnl:.4f}USDT)"
        
        # 最小持仓时间检查 + 盈利覆盖手续费
        min_holding_hours = self.min_holding_time / 3600  # 转换为小时
        if holding_hours >= min_holding_hours and net_pnl > 0:
            return f"达到最小持仓时间且盈利 (持仓{holding_hours:.2f}h, 净盈利{net_pnl:.4f}USDT)"
        
        return None
    
    def run_strategy(self) -> None:
        """
        运行完整的SOL双向策略
        包括开仓、监控、止盈止损
        """
        direction_name = {"long": "多单", "short": "空单", "auto": "自动"}[self.direction]
        print(f"🚀 启动SOL{direction_name}策略...")
        print(f"📊 策略参数:")
        print(f"   交易方向: {direction_name}")
        print(f"   持仓大小: {self.position_size} USDT")
        print(f"   杠杆倍数: {self.leverage}x")
        print(f"   止盈阈值: {self.profit_threshold*100}%")
        print(f"   止损阈值: {self.stop_loss_threshold*100}%")
        print(f"   手续费率: {self.fee_rate*100}%")
        
        try:
            # 1. 检查是否已有持仓
            positions = self.client.get_position_risk()
            has_position = False
            
            for pos in positions:
                if pos.get('symbol') == 'SOLUSDT' and float(pos.get('positionAmt', 0)) != 0:
                    has_position = True
                    print("📊 发现现有SOL持仓，直接进入监控模式...")
                    break
            
            # 2. 如果没有持仓，尝试开仓
            if not has_position:
                print(f"\n🎯 开始开仓 ({direction_name})...")
                if not self.open_position():
                    print("❌ 开仓失败，策略终止")
                    return
                
                print("✅ 开仓成功，等待3秒后开始监控...")
                import time
                time.sleep(3)
            
            # 3. 持续监控持仓
            print("\n👀 开始持仓监控...")
            monitor_count = 0
            max_monitors = 1000  # 最大监控次数，防止无限循环
            
            while monitor_count < max_monitors:
                monitor_count += 1
                print(f"\n🔍 第 {monitor_count} 次监控检查...")
                
                # 监控持仓状态
                position_closed = self.monitor_position()
                
                if position_closed:
                    print("🎉 持仓已平仓，策略执行完成!")
                    break
                
                # 等待30秒后再次检查
                print("⏰ 等待30秒后继续监控...")
                import time
                time.sleep(30)
            
            if monitor_count >= max_monitors:
                print("⚠️ 达到最大监控次数，策略自动退出")
            
            # 4. 生成最终报告
            self.generate_final_report()
            
        except KeyboardInterrupt:
            print("\n⚠️ 用户中断策略执行")
            print("正在检查当前持仓状态...")
            self.monitor_position()
            
        except Exception as e:
            print(f"❌ 策略执行出错: {e}")
            print("正在检查当前持仓状态...")
            try:
                self.monitor_position()
            except:
                pass
    
    def generate_final_report(self) -> None:
        """生成最终交易报告"""
        try:
            print("\n📊 生成最终交易报告...")
            
            # 获取账户信息
            account_info = self.client.get_account_info()
            final_balance = float(account_info.get('availableBalance', 0))
            
            # 获取最近交易记录
            trades = self.client.get_account_trades('SOLUSDT', limit=10)
            
            print(f"\n📈 交易总结:")
            print(f"💰 当前余额: {final_balance:.2f} USDT")
            
            if trades:
                total_fee = sum(float(trade.get('commission', 0)) for trade in trades)
                total_volume = sum(float(trade.get('quoteQty', 0)) for trade in trades)
                
                print(f"📊 交易统计:")
                print(f"   总交易笔数: {len(trades)}")
                print(f"   总交易量: {total_volume:.2f} USDT")
                print(f"   总手续费: {total_fee:.4f} USDT")
                
                # 估算积分
                estimated_points = self.estimate_points(total_volume, 1.0, 1.0)  # 假设持仓1小时，100% Taker
                print(f"🎯 预估积分: {estimated_points:.0f} 分")
            
            print("\n✅ 策略执行完成!")
            
        except Exception as e:
            print(f"❌ 生成报告失败: {e}")
    
    def estimate_points(self, volume: float, holding_hours: float, taker_ratio: float) -> float:
        """
        估算Aster积分
        
        Args:
            volume: 交易量 (USDT)
            holding_hours: 持仓小时数
            taker_ratio: Taker交易比例
            
        Returns:
            预估积分
        """
        # Aster积分规则（简化版）
        volume_points = volume * 2  # 每1 USDT交易量 = 2积分
        
        # 持仓时间加成
        if holding_hours >= 1.0:
            holding_multiplier = 5.0  # 持仓1小时以上 = 5x积分
        else:
            holding_multiplier = 1.0
        
        # Taker交易加成
        taker_multiplier = 1.0 + taker_ratio  # Taker交易额外积分
        
        total_points = volume_points * holding_multiplier * taker_multiplier
        
        return total_points

def main():
    """主函数 - 支持双向交易"""
    print("🚀 SOL双向循环策略启动")
    print("=" * 50)
    
    # 循环参数
    max_loops = 1000  # 最大循环次数
    current_loop = 0
    total_pnl = 0.0
    consecutive_failures = 0  # 连续失败计数
    max_consecutive_failures = 3  # 最大连续失败次数
    
    # 策略方向设置 (可以修改这里来控制交易方向)
    # 选项: "long" (只做多), "short" (只做空), "auto" (自动检测)
    strategy_direction = "long"  # 默认自动检测方向
    
    try:
        while current_loop < max_loops:
            current_loop += 1
            print(f"\n🔄 开始第 {current_loop} 轮策略...")
            
            # 检查熔断器状态
            cb_status = get_circuit_breaker_status()
            if cb_status['state'] == 'OPEN':
                wait_time = cb_status.get('time_until_retry', 0)
                print(f"🚨 熔断器开启中，等待 {wait_time:.0f} 秒后重试...")
                if wait_time > 0:
                    time.sleep(min(wait_time, 60))  # 最多等待60秒
                    continue
            
            try:
                # 创建策略实例 (使用新的双向策略类)
                strategy = SOLBidirectionalStrategy(direction=strategy_direction)
                
                # 检查账户状态
                balance = strategy.check_account_balance()
                if balance < strategy.position_size:
                    print(f"❌ 账户余额不足: {balance:.2f} USDT < {strategy.position_size} USDT")
                    print("🛑 循环终止")
                    break
                
                # 获取当前价格
                current_price = strategy.get_current_price()
                if not current_price:
                    print("❌ 无法获取SOL价格，跳过本轮")
                    consecutive_failures += 1
                    if consecutive_failures >= max_consecutive_failures:
                        print(f"🚨 连续失败 {consecutive_failures} 次，策略终止")
                        break
                    continue
                
                print(f"💰 账户余额: {balance:.2f} USDT")
                print(f"📈 SOL当前价格: {current_price:.4f} USDT")
                print(f"🎯 第 {current_loop}/{max_loops} 轮策略 (方向: {strategy_direction})")
                print("=" * 50)
                
                # 记录开始余额
                start_balance = balance
                
                # 运行策略
                strategy.run_strategy()
                
                # 计算本轮盈亏
                end_balance = strategy.check_account_balance()
                loop_pnl = end_balance - start_balance
                total_pnl += loop_pnl
                
                print(f"\n📊 第 {current_loop} 轮完成:")
                print(f"   本轮盈亏: {loop_pnl:+.4f} USDT")
                print(f"   累计盈亏: {total_pnl:+.4f} USDT")
                print(f"   当前余额: {end_balance:.2f} USDT")
                
                # 重置连续失败计数
                consecutive_failures = 0
                
                # 如果不是最后一轮，等待60秒
                if current_loop < max_loops:
                    print("⏰ 等待60秒后开始下一轮...")
                    time.sleep(60)
                    
            except Exception as e:
                consecutive_failures += 1
                logger.error(f"❌ 第 {current_loop} 轮策略执行失败: {e}")
                
                # 检查是否需要重置熔断器
                if consecutive_failures >= max_consecutive_failures:
                    print(f"🚨 连续失败 {consecutive_failures} 次，尝试重置熔断器...")
                    reset_circuit_breaker()
                    consecutive_failures = 0  # 重置计数
                    
                    # 等待更长时间再重试
                    print("⏰ 等待 300 秒后重试...")
                    time.sleep(300)
                else:
                    # 短暂等待后继续
                    wait_time = consecutive_failures * 30  # 递增等待时间
                    print(f"⏰ 等待 {wait_time} 秒后重试...")
                    time.sleep(wait_time)
        
        print(f"\n🏆 循环策略完成!")
        print(f"   总轮数: {current_loop}")
        print(f"   总盈亏: {total_pnl:+.4f} USDT")
        print(f"   策略方向: {strategy_direction}")
        
        # 显示最终熔断器状态
        final_cb_status = get_circuit_breaker_status()
        print(f"🔧 熔断器最终状态: {final_cb_status['state']}")
        
    except KeyboardInterrupt:
        print(f"\n⚠️ 用户中断，已完成 {current_loop} 轮")
        print(f"   累计盈亏: {total_pnl:+.4f} USDT")
    except Exception as e:
        logger.error(f"❌ 程序异常: {e}")
        print(f"❌ 程序运行失败: {e}")
        
        # 显示熔断器状态用于调试
        cb_status = get_circuit_breaker_status()
        print(f"🔧 熔断器状态: {cb_status}")

if __name__ == "__main__":
    main()