#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SOL止损止盈交易策略 - Backpack交易所版本
基于aster策略逻辑，实现止损止盈的交易方式
"""

import asyncio
import time
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
import decimal

from bpx.account import Account
from bpx.public import Public
from bpx.constants.enums import OrderTypeEnum, TimeInForceEnum
from config_loader import ConfigLoader
from enhanced_logger import EnhancedLogger
from risk_manager import BackpackRiskManager
from performance_monitor import PerformanceMonitor

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('sol_stop_loss_strategy.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class SOLStopLossStrategy:
    """SOL止损止盈策略类"""
    
    def __init__(self, config_path: str = "config.json"):
        """初始化策略"""
        self.config = ConfigLoader(config_path)
        
        # 初始化客户端
        credentials = self.config.get_api_credentials()
        self.account_client = Account(
            public_key=credentials.get('api_key'),
            secret_key=credentials.get('secret_key')
        )
        self.public_client = Public()
        
        # 获取市场精度信息
        self.quantity_decimals = {}
        self.price_decimals = {}
        try:
            markets_info = self.public_client.get_markets()
            if isinstance(markets_info, list):
                for m in markets_info:
                    symbol = m['symbol']
                    if 'quantity' in m['filters'] and 'minQuantity' in m['filters']['quantity']:
                        self.quantity_decimals[symbol] = self.get_decimal_places_from_tick_size(m['filters']['quantity']['minQuantity'])
                    if 'price' in m['filters'] and 'tickSize' in m['filters']['price']:
                        self.price_decimals[symbol] = self.get_decimal_places_from_tick_size(m['filters']['price']['tickSize'])
        except Exception as e:
            logger.warning(f"⚠️ 获取市场精度信息失败: {e}，使用默认精度")
            self.quantity_decimals['SOL_USDC'] = 5  # 默认SOL精度
            self.price_decimals['SOL_USDC'] = 2     # 默认价格精度
        
        # 策略参数 (优化后的刷分参数)
        self.symbol = "SOL_USDC"
        self.base_coin = "SOL"
        self.position_size_usdc = decimal.Decimal('50.0')  # 每次开仓金额 (USDC)
        self.profit_threshold = decimal.Decimal('0.004')  # 止盈阈值 0.4% (降低门槛)
        self.stop_loss_threshold = decimal.Decimal('0.008')  # 止损阈值 0.8% (适当放宽)
        self.min_holding_time = 1200  # 最小持仓时间 20分钟 (缩短时间)
        
        # 状态跟踪
        self.current_position = None
        self.entry_time = None
        self.entry_price = None
        self.position_quantity = None
        self.order_id = None
        
        # 工具类
        self.enhanced_logger = EnhancedLogger(self.config)
        self.risk_manager = BackpackRiskManager(self.config)
        self.performance_monitor = PerformanceMonitor(self.config)
        
        logger.info("🚀 SOL止损止盈策略初始化完成")
        logger.info(f"📊 策略参数: 仓位={self.position_size_usdc}USDC")
        logger.info(f"🎯 止盈={self.profit_threshold*100}%, 止损={self.stop_loss_threshold*100}%")
        logger.info(f"🔧 交易精度: 数量={self.quantity_decimals.get(self.symbol, 5)}位, 价格={self.price_decimals.get(self.symbol, 2)}位")
    
    def get_decimal_places_from_tick_size(self, tick_size: str) -> int:
        """从tick size获取小数位数"""
        try:
            decimal_places = len(tick_size.split('.')[1]) if '.' in tick_size else 0
            return decimal_places
        except:
            return 8  # 默认8位小数
    
    async def get_current_price(self) -> Optional[decimal.Decimal]:
        """获取SOL当前价格"""
        try:
            tickers = self.public_client.get_tickers()
            ticker = next((t for t in tickers if t.get('symbol') == self.symbol), None)
            if ticker and 'lastPrice' in ticker:
                return decimal.Decimal(str(ticker['lastPrice']))
            return None
        except Exception as e:
            logger.error(f"❌ 获取价格失败: {e}")
            return None
    
    async def get_account_balance(self) -> Tuple[decimal.Decimal, decimal.Decimal]:
        """获取账户余额"""
        try:
            balances = self.account_client.get_balances()
            usdc_balance = decimal.Decimal('0')
            sol_balance = decimal.Decimal('0')
            
            if isinstance(balances, dict):
                usdc_balance = decimal.Decimal(str(balances.get('USDC', {}).get('available', 0)))
                sol_balance = decimal.Decimal(str(balances.get('SOL', {}).get('available', 0)))
            
            return usdc_balance, sol_balance
        except Exception as e:
            logger.error(f"❌ 获取余额失败: {e}")
            return decimal.Decimal('0'), decimal.Decimal('0')
    
    def calculate_profit_loss(self, entry_price: decimal.Decimal, current_price: decimal.Decimal, 
                            quantity: decimal.Decimal) -> Tuple[decimal.Decimal, decimal.Decimal]:
        """计算盈亏和盈亏率"""
        price_diff = current_price - entry_price
        pnl = price_diff * quantity
        pnl_percentage = price_diff / entry_price
        return pnl, pnl_percentage
    
    async def open_position(self) -> bool:
        """开仓买入SOL"""
        try:
            # 检查余额
            usdc_balance, sol_balance = await self.get_account_balance()
            if usdc_balance < self.position_size_usdc:
                logger.warning(f"⚠️ USDC余额不足: {usdc_balance} < {self.position_size_usdc}")
                return False
            
            # 获取当前价格
            current_price = await self.get_current_price()
            if not current_price:
                return False
            
            # 计算购买数量
            quantity = self.position_size_usdc / current_price
            qty_decimal_places = self.quantity_decimals.get(self.symbol, 5)
            quantity = quantity.quantize(decimal.Decimal('1e-' + str(qty_decimal_places)), rounding=decimal.ROUND_DOWN)
            
            logger.info(f"📈 准备开仓买入SOL:")
            logger.info(f"   价格: {current_price} USDC")
            logger.info(f"   数量: {quantity} SOL")
            logger.info(f"   价值: {self.position_size_usdc} USDC")
            
            # 使用市价单买入
            order = self.account_client.execute_order(
                symbol=self.symbol,
                side="Bid",  # 买入
                order_type=OrderTypeEnum.MARKET,
                quantity=str(quantity),
                time_in_force=TimeInForceEnum.IOC
            )
            
            if order and order.get('id'):
                self.order_id = order['id']
                self.entry_price = current_price
                self.entry_time = datetime.now()
                self.position_quantity = quantity
                self.current_position = {
                    'quantity': quantity,
                    'entry_price': current_price,
                    'entry_time': self.entry_time,
                    'order_id': self.order_id
                }
                
                # 计算止盈止损价格
                take_profit_price = current_price * (decimal.Decimal('1') + self.profit_threshold)
                stop_loss_price = current_price * (decimal.Decimal('1') - self.stop_loss_threshold)
                
                logger.info(f"✅ 开仓成功!")
                logger.info(f"   订单ID: {self.order_id}")
                logger.info(f"   入场价: {current_price} USDC")
                logger.info(f"   数量: {quantity} SOL")
                logger.info(f"   🎯 止盈价格: {take_profit_price} USDC (+{self.profit_threshold*100}%)")
                logger.info(f"   🛑 止损价格: {stop_loss_price} USDC (-{self.stop_loss_threshold*100}%)")
                
                # 记录到日志
                try:
                    self.enhanced_logger.log_trade_execution(
                        "BUY", self.symbol, str(quantity), str(current_price), 
                        self.order_id, "开仓买入"
                    )
                except AttributeError:
                    # 如果方法不存在，使用基本日志记录
                    logger.info(f"📝 交易记录: BUY {quantity} {self.base_coin} @ {current_price} USDC")
                
                return True
            else:
                logger.error(f"❌ 开仓失败: {order}")
                return False
                
        except Exception as e:
            logger.error(f"❌ 开仓异常: {e}")
            return False
    
    async def close_position(self, reason: str = "手动平仓") -> bool:
        """平仓卖出SOL"""
        try:
            if not self.current_position:
                logger.warning("⚠️ 没有持仓需要平仓")
                return False
            
            current_price = await self.get_current_price()
            if not current_price:
                return False
            
            quantity = self.current_position['quantity']
            
            logger.info(f"📉 准备平仓卖出SOL - {reason}")
            logger.info(f"   当前价格: {current_price} USDC")
            logger.info(f"   卖出数量: {quantity} SOL")
            
            # 使用市价单卖出
            order = self.account_client.execute_order(
                symbol=self.symbol,
                side="Ask",  # 卖出
                order_type=OrderTypeEnum.MARKET,
                quantity=str(quantity),
                time_in_force=TimeInForceEnum.IOC
            )
            
            if order and order.get('id'):
                # 计算盈亏
                pnl, pnl_percentage = self.calculate_profit_loss(
                    self.entry_price, current_price, quantity
                )
                
                # 持仓时间
                holding_time = datetime.now() - self.entry_time
                holding_hours = holding_time.total_seconds() / 3600
                
                logger.info(f"📊 平仓完成 - {reason}")
                logger.info(f"   入场价: {self.entry_price} USDC")
                logger.info(f"   出场价: {current_price} USDC")
                logger.info(f"   价格变动: {pnl_percentage*100:.2f}%")
                logger.info(f"   盈亏: {pnl:.4f} USDC")
                logger.info(f"   持仓时间: {holding_hours:.2f} 小时")
                
                # 记录到日志
                try:
                    self.enhanced_logger.log_trade_execution(
                        "SELL", self.symbol, str(quantity), str(current_price), 
                        order['id'], reason
                    )
                except AttributeError:
                    # 如果方法不存在，使用基本日志记录
                    logger.info(f"📝 交易记录: SELL {quantity} {self.base_coin} @ {current_price} USDC - {reason}")
                
                # 重置状态
                self.current_position = None
                self.entry_time = None
                self.entry_price = None
                self.position_quantity = None
                self.order_id = None
                
                return True
            else:
                logger.error(f"❌ 平仓失败: {order}")
                return False
                
        except Exception as e:
            logger.error(f"❌ 平仓异常: {e}")
            return False
    
    async def check_exit_conditions(self) -> Optional[str]:
        """检查是否需要平仓"""
        if not self.current_position:
            return None
        
        current_price = await self.get_current_price()
        if not current_price:
            return None
        
        # 计算盈亏
        pnl, pnl_percentage = self.calculate_profit_loss(
            self.entry_price, current_price, self.current_position['quantity']
        )
        
        # 持仓时间
        holding_time = datetime.now() - self.entry_time
        holding_hours = holding_time.total_seconds() / 3600
        
        # 计算当前止盈止损价格
        take_profit_price = self.entry_price * (decimal.Decimal('1') + self.profit_threshold)
        stop_loss_price = self.entry_price * (decimal.Decimal('1') - self.stop_loss_threshold)
        
        # 计算到期平仓时间
        min_holding_hours = self.min_holding_time / 3600  # 转换为小时
        expiry_time = self.entry_time + timedelta(seconds=self.min_holding_time)
        expiry_time_str = expiry_time.strftime("%H:%M:%S")
        
        logger.info(f"📊 持仓状态检查:")
        logger.info(f"   入场价格: {self.entry_price} USDC")
        logger.info(f"   当前价格: {current_price} USDC")
        logger.info(f"   🎯 止盈价格: {take_profit_price} USDC")
        logger.info(f"   🛑 止损价格: {stop_loss_price} USDC")
        logger.info(f"   盈亏率: {pnl_percentage*100:.2f}%")
        logger.info(f"   盈亏: {pnl:.4f} USDC")
        logger.info(f"   持仓时间: {holding_hours:.2f} 小时")
        logger.info(f"   到期时间: {expiry_time_str} (最小持仓{min_holding_hours:.1f}小时)")
        
        # 止损检查
        if current_price <= stop_loss_price:
            return f"止损触发 (当前价格 {current_price} <= 止损价格 {stop_loss_price})"
        
        # 止盈检查
        if current_price >= take_profit_price:
            return f"止盈触发 (当前价格 {current_price} >= 止盈价格 {take_profit_price})"
        
        # 检查最小持仓时间后的盈利退出
        min_holding_hours = self.min_holding_time / 3600  # 转换为小时
        if holding_hours >= min_holding_hours and pnl_percentage > decimal.Decimal('0.002'):  # 0.2%盈利
            return f"持仓{min_holding_hours:.1f}小时且有盈利，获利了结 (盈利{pnl_percentage*100:.2f}%)"
        
        return None
    
    async def run_strategy(self):
        """运行策略主循环"""
        logger.info("🚀 开始运行SOL止损止盈策略")
        
        try:
            while True:
                # 如果没有持仓，尝试开仓
                if not self.current_position:
                    logger.info("💰 当前无持仓，准备开仓...")
                    
                    # 检查风险管理
                    usdc_balance, sol_balance = await self.get_account_balance()
                    current_price = await self.get_current_price()
                    
                    if current_price:
                        logger.info(f"💰 账户余额: USDC={usdc_balance}, SOL={sol_balance}")
                        logger.info(f"📈 SOL当前价格: {current_price} USDC")
                        
                        # 尝试开仓
                        if await self.open_position():
                            logger.info("✅ 开仓成功，开始监控...")
                        else:
                            logger.warning("⚠️ 开仓失败，等待下次机会...")
                    
                    # 等待30秒后重试
                    await asyncio.sleep(30)
                
                else:
                    # 有持仓，检查退出条件
                    exit_reason = await self.check_exit_conditions()
                    
                    if exit_reason:
                        logger.info(f"🔄 触发平仓条件: {exit_reason}")
                        if await self.close_position(exit_reason):
                            logger.info("✅ 平仓成功，等待下次开仓机会...")
                            # 平仓后等待60秒再开始下一轮
                            await asyncio.sleep(60)
                        else:
                            logger.error("❌ 平仓失败，继续监控...")
                    
                    # 每30秒检查一次
                    await asyncio.sleep(30)
                    
        except KeyboardInterrupt:
            logger.info("⚠️ 用户中断策略")
            if self.current_position:
                logger.info("🔄 检测到持仓，执行平仓...")
                await self.close_position("用户中断")
        except Exception as e:
            logger.error(f"❌ 策略运行异常: {e}")
            if self.current_position:
                logger.info("🔄 异常情况下执行平仓...")
                await self.close_position("异常平仓")

async def main():
    """主函数"""
    print("🚀 SOL止损止盈策略启动")
    print("=" * 50)
    
    try:
        strategy = SOLStopLossStrategy()
        await strategy.run_strategy()
        
    except Exception as e:
        logger.error(f"❌ 程序运行失败: {e}")
        print(f"❌ 程序运行失败: {e}")

if __name__ == "__main__":
    asyncio.run(main())