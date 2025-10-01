#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
实盘动态对冲策略 - trade_2.py
核心逻辑：开仓后根据盈亏情况，先平亏损仓位，延长盈利仓位
目标：让盈利覆盖总手续费成本
"""

import asyncio
import json
import time
import logging
from typing import Dict, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import sys
import os

# 添加项目路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# 导入API客户端
from aster.aster_api_client import AsterFinanceClient
# 启用Backpack客户端
from backpack.trade import SOLStopLossStrategy

class PositionStatus(Enum):
    ACTIVE = "active"
    CLOSED = "closed"

class PositionSide(Enum):
    LONG = "long"
    SHORT = "short"

@dataclass
class Position:
    """仓位数据结构"""
    position_id: str
    platform: str
    symbol: str
    side: PositionSide
    amount: float
    entry_price: float
    current_price: float
    status: PositionStatus
    pnl: float = 0.0
    pnl_percentage: float = 0.0
    order_id: Optional[str] = None

class RealDynamicHedgeStrategy:
    """实盘动态对冲策略"""
    
    def __init__(self, 
                 config_path: str = None,
                 stop_loss_threshold: float = 0.0001, # 0.01% 止损阈值 (超极快触发)
                 profit_target_rate: float = 0.0005,  # 0.05% 盈利目标 (超极易达到)
                 position_size_usdt: float = 25.0,    # USDT仓位大小
                 aster_leverage: float = 1.0,         # Aster杠杆倍数
                 monitoring_interval: float = 1.0):   # 监控间隔（秒）(更频繁检查)
        
        # 策略参数 - 可配置
        self.stop_loss_threshold = stop_loss_threshold
        self.profit_target_rate = profit_target_rate
        self.total_fee_rate = 0.0015  # 0.15% 总手续费率（相对固定）
        
        # 交易参数 - 可配置
        self.position_size_usdt = position_size_usdt
        self.aster_leverage = aster_leverage
        
        # 仓位管理
        self.positions: Dict[str, Position] = {}
        self.total_pnl = 0.0
        self.completed_trades = 0
        self.profitable_trades = 0
        
        # 策略状态
        self.strategy_active = False
        self.monitoring_interval = monitoring_interval  # 使用参数值
        
        # 初始化日志
        self._setup_logging()
        
        # 初始化API客户端
        self.aster_client = None
        self.backpack_client = None
        self._init_api_clients(config_path)
    
    def _setup_logging(self):
        """设置日志"""
        logging.basicConfig(
            level=logging.DEBUG,  # 改为DEBUG级别以显示详细日志
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('dynamic_hedge_real.log'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)
    
    def _init_api_clients(self, config_path: str = None):
        """初始化API客户端"""
        try:
            # 初始化Aster客户端
            aster_config_path = config_path or "aster/config.json"
            if os.path.exists(aster_config_path):
                # 加载Aster配置
                from aster.config_loader import ConfigLoader
                aster_config = ConfigLoader(aster_config_path)
                credentials = aster_config.get_api_credentials()
                
                # 根据testnet设置选择base_url
                base_url = "https://testnet.asterdex.com" if aster_config.get('testnet', False) else "https://fapi.asterdex.com"
                
                self.aster_client = AsterFinanceClient(
                    api_key=credentials['api_key'],
                    secret_key=credentials['secret_key'],
                    base_url=base_url
                )
                self.logger.info("✅ Aster API客户端初始化成功")
            else:
                self.logger.warning("⚠️ Aster配置文件未找到，使用模拟模式")
            
            # 初始化Backpack客户端
            backpack_config_path = "backpack/config.json"
            if os.path.exists(backpack_config_path):
                # 启用Backpack客户端初始化
                self.backpack_client = SOLStopLossStrategy(backpack_config_path)
                self.logger.info("✅ Backpack API客户端初始化成功")
            else:
                self.logger.warning("⚠️ Backpack配置文件未找到，使用模拟模式")
                
        except Exception as e:
            self.logger.error(f"❌ API客户端初始化失败: {e}")
            self.logger.info("💡 将使用模拟模式运行")
    
    async def execute_real_dynamic_hedge(self, symbol: str, position_size_usdt: float = None) -> bool:
        """执行实盘动态对冲策略 - 单轮交易"""
        if position_size_usdt:
            self.position_size_usdt = position_size_usdt
            
        self.logger.info(f"\n🚀 启动单轮动态对冲交易")
        self.logger.info(f"💰 交易金额: ${self.position_size_usdt} USDT")
        self.logger.info(f"🎯 策略目标: 盈利 > {self.profit_target_rate*100:.2f}% (覆盖手续费)")
        
        try:
            # 1. 获取当前价格
            price_data = await self._get_current_price(symbol)
            if not price_data:
                self.logger.error("❌ 无法获取当前价格")
                return False
            
            # 使用主价格进行开仓
            main_price, _, _ = price_data
            
            # 2. 同时开仓
            success = await self._open_real_hedge_positions(symbol, main_price)
            if not success:
                self.logger.error("❌ 开仓失败")
                return False
            
            # 3. 动态监控和平仓
            self.strategy_active = True
            await self._monitor_and_close_real_positions(symbol)
            
            self.logger.info(f"✅ 本轮交易完成")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ 单轮交易异常: {e}")
            await self._force_close_all_real_positions()
            return False
    
    async def _get_current_price(self, symbol: str) -> Optional[Tuple[float, float]]:
        """获取当前价格，返回(backpack_price, aster_price)"""
        backpack_price = None
        aster_price = None
        
        try:
            # 同时获取Backpack和Aster价格
            if self.backpack_client:
                try:
                    # 转换符号格式：SOL-USDT -> SOL_USDC
                    backpack_symbol = symbol.replace('-', '_').replace('USDT', 'USDC')
                    price = await self.backpack_client.get_current_price(backpack_symbol)
                    if price and float(price) > 0:
                        backpack_price = float(price)
                except Exception as e:
                    error_msg = str(e)
                    if "503" in error_msg or "Service Temporarily Unavailable" in error_msg:
                        self.logger.warning(f"⚠️ Backpack API暂时不可用")
                    else:
                        self.logger.warning(f"⚠️ Backpack价格获取失败: {e}")
            
            # 获取Aster价格
            if self.aster_client:
                try:
                    # 转换符号格式：SOL-USDT -> SOLUSDT
                    aster_symbol = symbol.replace('-', '')
                    price_data = self.aster_client.get_ticker_price(aster_symbol)
                    if price_data and 'price' in price_data:
                        price = float(price_data['price'])
                        if price > 0:
                            aster_price = price
                except Exception as e:
                    self.logger.warning(f"⚠️ Aster价格获取失败: {e}")
            
            # 返回价格对，优先使用Backpack价格作为主价格
            main_price = backpack_price if backpack_price else aster_price
            if main_price:
                return main_price, backpack_price, aster_price
            else:
                raise Exception("所有价格源都无法获取价格")
            
        except Exception as e:
            self.logger.error(f"❌ 获取价格失败: {e}")
            raise e
    
    async def _open_real_hedge_positions(self, symbol: str, entry_price: float) -> bool:
        """开启实盘对冲仓位"""
        self.logger.info(f"\n📈 开启对冲仓位 @ ${entry_price:.2f}")
        
        # 保存开仓价格用于后续监控显示
        self.entry_price = entry_price
        
        try:
            # 获取各平台的实际价格
            price_data = await self._get_current_price(symbol)
            if not price_data:
                self.logger.error("❌ 无法获取当前价格，开仓失败")
                return False
            
            main_price, backpack_price, aster_price = price_data
            
            # 计算仓位大小 - 修正为相等仓位策略
            # 两边仓位数量相等，便于单边止损+限价获利
            quantity = self.position_size_usdt / main_price
            aster_quantity = quantity  # Aster空单
            backpack_quantity = quantity  # Backpack多单
            
            self.logger.info(f"💰 计算仓位大小 (相等仓位策略):")
            self.logger.info(f"  Aster空单: {aster_quantity:.4f} {symbol} (杠杆{self.aster_leverage}x)")
            self.logger.info(f"  Backpack多单: {backpack_quantity:.4f} {symbol} (相等数量)")
            self.logger.info(f"  💡 策略: {self.stop_loss_threshold*100:.1f}%止损 + {self.profit_target_rate*100:.1f}%限价获利")
            
            # 并发开启两个仓位，使用各自的实际价格
            import asyncio
            aster_task = asyncio.create_task(self._open_aster_short(symbol, aster_quantity, aster_price))
            backpack_task = asyncio.create_task(self._open_backpack_long(symbol, backpack_quantity, backpack_price))
            
            # 等待两个任务完成
            aster_success, backpack_success = await asyncio.gather(aster_task, backpack_task, return_exceptions=True)
            
            # 处理异常结果
            if isinstance(aster_success, Exception):
                self.logger.error(f"❌ Aster开仓异常: {aster_success}")
                aster_success = False
            if isinstance(backpack_success, Exception):
                self.logger.error(f"❌ Backpack开仓异常: {backpack_success}")
                backpack_success = False
            
            # 检查是否至少有一个平台成功开仓
            if aster_success or backpack_success:
                if aster_success and backpack_success:
                    self.logger.info("✅ 对冲仓位开仓成功")
                else:
                    self.logger.info("⚠️ 部分仓位开仓成功，继续运行")
                return True
            else:
                self.logger.error("❌ 所有仓位开仓失败")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ 开仓异常: {e}")
            return False
    
    async def _open_aster_short(self, symbol: str, quantity: float, price: float) -> bool:
        """开启Aster空单"""
        try:
            self.logger.info(f"🔄 正在开启Aster空单...")
            
            if self.aster_client:
                # 转换symbol格式 (SOL-USDT -> SOLUSDT)
                aster_symbol = symbol.replace("-", "")
                
                # 根据Aster交易规则调整数量精度
                # SOLUSDT: quantityPrecision=2, minQty=0.01, stepSize=0.01
                import decimal
                quantity_decimal = decimal.Decimal(str(quantity))
                # 调整到2位小数精度，并确保符合stepSize=0.01
                adjusted_quantity = float(quantity_decimal.quantize(decimal.Decimal('0.01')))
                
                # 确保满足最小数量要求
                min_qty = 0.01  # 根据API规则
                min_notional = 5.0  # 最小名义价值5USDT
                min_qty_by_notional = min_notional / price
                actual_quantity = max(adjusted_quantity, min_qty, min_qty_by_notional)
                
                # 再次调整精度
                actual_quantity = float(decimal.Decimal(str(actual_quantity)).quantize(decimal.Decimal('0.01')))
                
                self.logger.info(f"  交易对: {aster_symbol}")
                self.logger.info(f"  数量: {actual_quantity:.2f} (原始: {quantity:.4f}, 调整: {adjusted_quantity:.2f})")
                self.logger.info(f"  价格: ${price:.2f}")
                self.logger.info(f"  名义价值: ${actual_quantity * price:.2f} USDT")
                
                # 添加网络超时和重试机制
                import asyncio
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        # 实盘下单 - 注意这里不是async方法
                        order_result = self.aster_client.place_order(
                            symbol=aster_symbol,
                            side='SELL',  # 使用大写
                            order_type='MARKET',  # 使用大写
                            quantity=round(actual_quantity, 2)  # 数量精度2位小数
                        )
                        
                        if order_result and 'orderId' in order_result:
                            order_id = order_result['orderId']
                            self.logger.info(f"✅ Aster空单下单成功: {order_id}")
                            
                            # 查询实际成交价格
                            actual_fill_price = await self._get_aster_fill_price(aster_symbol, order_id)
                            if actual_fill_price:
                                price = actual_fill_price  # 使用实际成交价格
                                self.logger.info(f"📊 Aster实际成交价格: ${actual_fill_price:.2f}")
                            
                            break
                        else:
                            self.logger.warning(f"⚠️ Aster空单下单失败 (尝试 {attempt + 1}/{max_retries}): {order_result}")
                            if attempt == max_retries - 1:
                                raise Exception(f"下单失败: {order_result}")
                            await asyncio.sleep(2)  # 等待2秒后重试
                            
                    except Exception as e:
                        self.logger.warning(f"⚠️ Aster下单尝试 {attempt + 1}/{max_retries} 失败: {e}")
                        if attempt == max_retries - 1:
                            raise e
                        await asyncio.sleep(2)  # 等待2秒后重试
                        
            else:
                # 没有API配置时直接返回失败
                self.logger.error("❌ 没有Aster API配置")
                return False
            
            # 创建仓位记录 - 使用实际下单数量
            position = Position(
                position_id=f"aster_short_{int(time.time())}",
                platform="aster",
                symbol=symbol,
                side=PositionSide.SHORT,
                amount=actual_quantity,  # 使用实际下单数量而不是原始数量
                entry_price=price,
                current_price=price,
                status=PositionStatus.ACTIVE,
                order_id=order_id
            )
            
            self.positions["aster"] = position
            self.logger.info(f"  Aster空单: {actual_quantity:.4f} {symbol} @ ${price:.2f}")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Aster空单开仓失败: {e}")
            return False
    
    async def _open_backpack_long(self, symbol: str, quantity: float, price: float) -> bool:
        """开启Backpack多单"""
        try:
            self.logger.info(f"🔄 正在开启Backpack多单...")
            
            if self.backpack_client and hasattr(self.backpack_client, 'account_client'):
                # 实盘下单 - 使用正确的API调用
                from bpx.constants.enums import OrderTypeEnum, TimeInForceEnum
                import decimal
                
                # 转换symbol格式 (SOL-USDT -> SOL_USDC)
                backpack_symbol = "SOL_USDC" if symbol.startswith("SOL") else symbol
                
                # 格式化数量 - 使用更严格的精度控制
                quantity_decimal = decimal.Decimal(str(quantity))
                # Backpack通常要求最多2位小数
                quantity_str = str(quantity_decimal.quantize(decimal.Decimal('0.01')))
                
                self.logger.info(f"  交易对: {backpack_symbol}")
                self.logger.info(f"  数量: {quantity_str} (原始: {quantity:.4f})")
                self.logger.info(f"  价格: ${price:.2f}")
                
                # 添加网络超时和重试机制
                import asyncio
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        order_result = self.backpack_client.account_client.execute_order(
                            symbol=backpack_symbol,
                            side="Bid",  # 买入
                            order_type=OrderTypeEnum.MARKET,
                            quantity=quantity_str,
                            time_in_force=TimeInForceEnum.IOC
                        )
                        
                        # 处理API返回结果
                        if order_result:
                            # 如果返回的是字符串，检查是否是错误响应
                            if isinstance(order_result, str):
                                if "503 Service Temporarily Unavailable" in order_result:
                                    raise Exception("Backpack API服务暂时不可用 (503)")
                                elif "html" in order_result.lower():
                                    raise Exception("Backpack API返回HTML错误页面")
                                else:
                                    try:
                                        import json
                                        order_result = json.loads(order_result)
                                    except:
                                        raise Exception(f"无法解析订单结果: {order_result[:100]}")
                            
                            # 检查订单是否成功
                            if isinstance(order_result, dict) and order_result.get('id'):
                                order_id = order_result['id']
                                self.logger.info(f"✅ Backpack多单下单成功: {order_id}")
                                
                                # 查询实际成交价格
                                actual_fill_price = await self._get_backpack_fill_price(backpack_symbol, order_id)
                                if actual_fill_price:
                                    price = actual_fill_price  # 使用实际成交价格
                                    self.logger.info(f"📊 Backpack实际成交价格: ${actual_fill_price:.2f}")
                                
                                break
                            else:
                                self.logger.warning(f"⚠️ Backpack多单下单失败 (尝试 {attempt + 1}/{max_retries}): {order_result}")
                                if attempt == max_retries - 1:
                                    raise Exception(f"下单失败: {order_result}")
                                await asyncio.sleep(2)
                        else:
                            self.logger.warning(f"⚠️ Backpack多单下单失败: 无返回结果 (尝试 {attempt + 1}/{max_retries})")
                            if attempt == max_retries - 1:
                                raise Exception("下单失败: 无返回结果")
                            await asyncio.sleep(2)
                            
                    except Exception as e:
                        error_msg = str(e)
                        self.logger.warning(f"⚠️ Backpack下单尝试 {attempt + 1}/{max_retries} 失败: {error_msg}")
                        
                        # 检查是否是503错误或HTML响应
                        if "503" in error_msg or "html" in error_msg.lower() or "Service Temporarily Unavailable" in error_msg:
                            self.logger.error(f"❌ Backpack API服务不可用 (尝试 {attempt + 1}/{max_retries}): {error_msg}")
                            if attempt == max_retries - 1:
                                raise Exception(f"Backpack API服务持续不可用: {error_msg}")
                            await asyncio.sleep(5)  # 等待5秒后重试
                        else:
                            if attempt == max_retries - 1:
                                raise e
                            await asyncio.sleep(2)  # 等待2秒后重试
                        
            else:
                # 没有API配置时直接返回失败
                self.logger.error("❌ 没有Backpack API配置")
                return False
            
            # 创建仓位记录 - 使用实际下单数量
            actual_quantity = float(quantity_str)  # 转换为实际下单数量
            position = Position(
                position_id=f"backpack_long_{int(time.time())}",
                platform="backpack",
                symbol=symbol,
                side=PositionSide.LONG,
                amount=actual_quantity,  # 使用实际下单数量而不是原始数量
                entry_price=price,
                current_price=price,
                status=PositionStatus.ACTIVE,
                order_id=order_id
            )
            
            self.positions["backpack"] = position
            self.logger.info(f"  Backpack多单: {actual_quantity:.4f} {symbol} @ ${price:.2f}")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Backpack多单开仓失败: {e}")
            return False
    
    async def _monitor_and_close_real_positions(self, symbol: str):
        """监控并执行实盘平仓策略"""
        self.logger.info(f"\n📊 开始实时监控...")
        
        monitor_count = 0
        while self.strategy_active and self._has_active_positions():
            monitor_count += 1
            
            try:
                # 获取当前价格 (main_price, backpack_price, aster_price)
                price_data = await self._get_current_price(symbol)
                if not price_data:
                    self.logger.warning("⚠️ 价格获取失败，跳过本次监控")
                    await asyncio.sleep(self.monitoring_interval)
                    continue
                
                main_price, backpack_price, aster_price = price_data
                
                # 更新仓位PnL (使用各平台的实际价格)
                self._update_real_positions_pnl_with_platform_prices(backpack_price, aster_price)
                
                # 执行动态平仓逻辑
                await self._execute_real_closing_logic()
                
                # 每次都显示完整状态信息
                self._print_real_positions_status(main_price, backpack_price, aster_price, monitor_count)
                
                # 安全检查：最大监控时间
                if monitor_count > 500:  # 约83分钟 (1000 * 5s)
                    self.logger.warning("⏰ 达到最大监控时间，强制平仓")
                    await self._force_close_all_real_positions()
                    break
                
                await asyncio.sleep(self.monitoring_interval)
                
            except Exception as e:
                self.logger.error(f"❌ 监控异常: {e}")
                await asyncio.sleep(self.monitoring_interval)
        
        self.logger.info(f"\n🏁 本轮交易完成")
    
    def _update_real_positions_pnl_with_platform_prices(self, backpack_price: float, aster_price: float):
        """更新实盘仓位PnL - 使用各平台的实际价格"""
        for platform, position in self.positions.items():
            if position.status != PositionStatus.ACTIVE:
                continue
            
            # 根据平台使用对应的价格
            if platform == 'backpack':
                current_price = backpack_price
            elif platform == 'aster':
                current_price = aster_price
            else:
                continue
                
            position.current_price = current_price
            
            if position.side == PositionSide.LONG:
                # 多单PnL
                position.pnl = (current_price - position.entry_price) * position.amount
                position.pnl_percentage = (current_price - position.entry_price) / position.entry_price
            else:
                # 空单PnL
                position.pnl = (position.entry_price - current_price) * position.amount
                position.pnl_percentage = (position.entry_price - current_price) / position.entry_price
    
    def _update_real_positions_pnl(self, current_price: float):
        """更新实盘仓位PnL - 保留原方法作为备用"""
        for position in self.positions.values():
            if position.status != PositionStatus.ACTIVE:
                continue
                
            position.current_price = current_price
            
            if position.side == PositionSide.LONG:
                # 多单PnL
                position.pnl = (current_price - position.entry_price) * position.amount
                position.pnl_percentage = (current_price - position.entry_price) / position.entry_price
            else:
                # 空单PnL
                position.pnl = (position.entry_price - current_price) * position.amount
                position.pnl_percentage = (position.entry_price - current_price) / position.entry_price
    
    async def _execute_real_closing_logic(self):
        try:
            active_positions = [pos for pos in self.positions.values() if pos.status == PositionStatus.ACTIVE]
            
            if len(active_positions) == 0:
                return
            
            # 检查所有限价单状态
            for position in active_positions:
                await self._check_limit_order_status(position)
            
            # 重新获取活跃仓位（可能有限价单成交）
            active_positions = [pos for pos in self.positions.values() if pos.status == PositionStatus.ACTIVE]
            
            if len(active_positions) == 1:
                # 只剩一个仓位，检查是否达到盈利目标或止损
                position = active_positions[0]
                
                # 详细日志：单仓位状态检查
                self.logger.debug(f"🔍 单仓位检查 - {position.platform}: PnL={position.pnl_percentage*100:.3f}%, 止损阈值=-{self.stop_loss_threshold*100:.1f}%")
                
                # 如果还没有设置限价单，且仓位盈利，设置1.2%限价单
                if not hasattr(position, 'limit_order_id') or not position.limit_order_id:
                    if position.pnl_percentage > 0:  # 盈利时设置1.2%限价单
                        self.logger.info(f"✅ {position.platform}仓位盈利{position.pnl_percentage*100:.3f}%，设置{self.profit_target_rate*100:.1f}%限价单")
                        await self._set_profit_limit_order(position)
                    else:
                        self.logger.debug(f"⏳ {position.platform}仓位未盈利({position.pnl_percentage*100:.3f}%)，暂不设置限价单")
                
                # 检查止损条件 (0.8%) 或强制平仓条件 (测试用)
                if position.pnl_percentage <= -self.stop_loss_threshold:
                    self.logger.warning(f"🚨 单仓止损触发！{position.platform}: {position.pnl_percentage*100:.3f}% <= -{self.stop_loss_threshold*100:.1f}%")
                    await self._close_real_position(position, f"单仓止损 ({position.pnl_percentage*100:.2f}%)")
                elif position.pnl_percentage >= 0.0001:  # 测试用：盈利0.01%时强制平仓
                    self.logger.warning(f"🧪 测试强制平仓！{position.platform}: {position.pnl_percentage*100:.3f}% >= 0.01%")
                    await self._close_real_position(position, f"测试强制平仓 ({position.pnl_percentage*100:.2f}%)")
                else:
                    self.logger.debug(f"✅ {position.platform}仓位未达平仓条件: {position.pnl_percentage*100:.3f}%")
                    
            elif len(active_positions) == 2:
                # 两个仓位都活跃，执行新的单边止损策略
                aster_pos = next((pos for pos in active_positions if pos.platform == "aster"), None)
                backpack_pos = next((pos for pos in active_positions if pos.platform == "backpack"), None)
                
                if aster_pos and backpack_pos:
                    # 详细日志：双仓位状态检查
                    self.logger.debug(f"🔍 双仓位检查 - Aster: {aster_pos.pnl_percentage*100:.3f}%, Backpack: {backpack_pos.pnl_percentage*100:.3f}%, 止损阈值: -{self.stop_loss_threshold*100:.1f}%")
                    
                    # 检查是否有任意一方达到0.8%亏损
                    losing_pos = None
                    profitable_pos = None
                    
                    if aster_pos.pnl_percentage <= -self.stop_loss_threshold:  # Aster亏损0.8%
                        losing_pos = aster_pos
                        profitable_pos = backpack_pos
                        self.logger.warning(f"🚨 Aster达到止损条件: {aster_pos.pnl_percentage*100:.3f}% <= -{self.stop_loss_threshold*100:.1f}%")
                    elif backpack_pos.pnl_percentage <= -self.stop_loss_threshold:  # Backpack亏损0.8%
                        losing_pos = backpack_pos
                        profitable_pos = aster_pos
                        self.logger.warning(f"🚨 Backpack达到止损条件: {backpack_pos.pnl_percentage*100:.3f}% <= -{self.stop_loss_threshold*100:.1f}%")
                    else:
                        self.logger.debug(f"✅ 双仓位均未达止损条件 - Aster: {aster_pos.pnl_percentage*100:.3f}%, Backpack: {backpack_pos.pnl_percentage*100:.3f}%")
                    
                    # 如果有一方达到0.8%亏损，平掉亏损方
                    if losing_pos:
                        self.logger.info(f"🎯 执行单边止损策略 - 平仓{losing_pos.platform}({losing_pos.pnl_percentage*100:.3f}%)，保留{profitable_pos.platform}({profitable_pos.pnl_percentage*100:.3f}%)")
                        await self._close_real_position(losing_pos, f"{self.stop_loss_threshold*100:.1f}%止损触发 ({losing_pos.pnl_percentage*100:.2f}%)")
                        
                        # 为盈利方设置1.2%限价单
                        if profitable_pos:
                            self.logger.info(f"💡 {profitable_pos.platform}方向判断为盈利方向，设置{self.profit_target_rate*100:.1f}%限价单")
                            await self._set_profit_limit_order(profitable_pos)
                
        except Exception as e:
            self.logger.error(f"❌ 执行平仓逻辑异常: {e}")
    
    async def _set_profit_limit_order(self, position: Position):
        """为盈利仓位设置限价单"""
        try:
            # 计算限价单价格（目标盈利）
            if position.side == PositionSide.LONG:
                # 多单：设置更高的卖出限价
                limit_price = position.entry_price * (1 + self.profit_target_rate)
                order_side = 'SELL'  # Aster需要大写
            else:
                # 空单：设置更低的买入限价
                limit_price = position.entry_price * (1 - self.profit_target_rate)
                order_side = 'BUY'  # Aster需要大写
            
            self.logger.info(f"📋 为{position.platform} {position.side.value}仓设置限价单")
            self.logger.info(f"   限价价格: ${limit_price:.2f} (目标盈利: {self.profit_target_rate*100:.2f}%)")
            
            limit_order_id = None
            
            if position.platform == "aster" and self.aster_client:
                # Aster限价单 - 修复参数格式
                try:
                    order_result = self.aster_client.place_order(
                        symbol=position.symbol.replace('-', ''),  # 转换符号格式: SOL-USDT -> SOLUSDT
                        side=order_side,  # BUY/SELL
                        order_type='LIMIT',  # 使用order_type参数
                        quantity=round(position.amount, 2),  # 数量精度2位小数
                        price=round(limit_price, 4),  # 价格精度4位小数
                        timeInForce='GTC'  # 添加必需的timeInForce参数
                    )
                    
                    if order_result and 'orderId' in order_result:
                        limit_order_id = order_result['orderId']
                    elif order_result and 'id' in order_result:
                        limit_order_id = order_result['id']
                    else:
                        self.logger.error(f"❌ Aster限价单返回格式异常: {order_result}")
                        
                except Exception as aster_error:
                    self.logger.error(f"❌ Aster限价单下单失败: {aster_error}")
                    return
                    
            elif position.platform == "backpack" and self.backpack_client:
                # Backpack限价单 - 使用正确的API调用
                try:
                    from bpx.constants.enums import OrderTypeEnum, TimeInForceEnum
                    
                    # 转换side格式：long -> Bid, short -> Ask
                    backpack_side = "Bid" if order_side.lower() == "buy" else "Ask"
                    
                    order_result = self.backpack_client.account_client.execute_order(
                        symbol=position.symbol,
                        side=backpack_side,
                        order_type=OrderTypeEnum.LIMIT,
                        quantity=str(position.amount),
                        price=str(limit_price),
                        time_in_force=TimeInForceEnum.GTC  # Good Till Cancelled
                    )
                    
                    # 处理API返回结果 - 可能是字符串或字典
                    if order_result:
                        # 如果返回的是字符串，尝试解析为JSON
                        if isinstance(order_result, str):
                            try:
                                import json
                                order_result = json.loads(order_result)
                            except:
                                self.logger.error(f"❌ Backpack限价单返回格式异常: {order_result[:100]}")
                                return
                        
                        # 检查订单是否成功
                        if isinstance(order_result, dict) and order_result.get('id'):
                            limit_order_id = order_result['id']
                            self.logger.info(f"✅ Backpack限价单下单成功: {limit_order_id}")
                        else:
                            self.logger.error(f"❌ Backpack限价单下单失败: {order_result}")
                            return
                    else:
                        self.logger.error("❌ Backpack限价单下单失败: 无返回结果")
                        return
                        
                except Exception as backpack_error:
                    self.logger.error(f"❌ Backpack限价单下单失败: {backpack_error}")
                    return
            else:
                # 没有API配置时返回失败
                self.logger.error("❌ 没有API配置，无法设置限价单")
                return
            
            if limit_order_id:
                position.limit_order_id = limit_order_id
                position.limit_price = limit_price
                self.logger.info(f"✅ 限价单设置成功: {limit_order_id}")
            else:
                self.logger.error(f"❌ 限价单设置失败")
                
        except Exception as e:
            self.logger.error(f"❌ 设置限价单异常: {e}")
    
    async def _check_limit_order_status(self, position: Position):
        """检查限价单状态"""
        try:
            if not hasattr(position, 'limit_order_id') or not position.limit_order_id:
                return
            
            order_status = None
            
            if position.platform == "aster" and self.aster_client:
                # 查询Aster订单状态
                order_info = await self.aster_client.get_order_status(position.limit_order_id)
                if order_info:
                    order_status = order_info.get('status')
                    
            elif position.platform == "backpack" and self.backpack_client:
                # 查询Backpack订单状态
                order_info = await self.backpack_client.get_order_status(position.limit_order_id)
                if order_info:
                    order_status = order_info.get('status')
            else:
                # 没有API配置时无法检查订单状态
                self.logger.warning(f"⚠️ 无法检查限价单状态: 没有API配置")
                return
            
            # 处理订单状态
            if order_status == 'filled':
                # 限价单成交，平仓
                position.status = PositionStatus.CLOSED
                self.total_pnl += position.pnl
                self.completed_trades += 1
                self.profitable_trades += 1
                
                self.logger.info(f"💰 {position.platform} {position.side.value}仓限价单成交")
                self.logger.info(f"   成交价格: ${position.limit_price:.2f}")
                self.logger.info(f"   盈亏: ${position.pnl:+.2f} ({position.pnl_percentage*100:+.2f}%)")
                
            elif order_status == 'cancelled' or order_status == 'rejected':
                # 订单被取消或拒绝，重新设置
                self.logger.warning(f"⚠️ 限价单状态异常: {order_status}，重新设置")
                position.limit_order_id = None
                await self._set_profit_limit_order(position)
                
        except Exception as e:
            self.logger.error(f"❌ 检查限价单状态异常: {e}")

    async def _close_real_position(self, position: Position, reason: str):
        """平仓实盘仓位"""
        try:
            # 如果有限价单，先取消
            if hasattr(position, 'limit_order_id') and position.limit_order_id:
                await self._cancel_limit_order(position)
            
            success = False
            
            if position.platform == "aster" and self.aster_client:
                # Aster仓位平仓 - 使用place_order方法 (同步调用)
                close_result = self.aster_client.place_order(
                    symbol=position.symbol.replace('-', ''),  # 转换符号格式: SOL-USDT -> SOLUSDT
                    side='BUY' if position.side == PositionSide.SHORT else 'SELL',  # 确保大写
                    order_type='MARKET',  # 确保大写
                    quantity=round(position.amount, 2)  # 数量精度2位小数
                )
                success = close_result is not None and 'orderId' in close_result
                
            elif position.platform == "backpack" and self.backpack_client:
                # 平Backpack仓位 - 修复API调用和符号格式
                try:
                    from bpx.constants.enums import OrderTypeEnum, TimeInForceEnum
                    
                    # 转换符号格式: SOL-USDT -> SOL_USDC
                    backpack_symbol = "SOL_USDC"  # Backpack使用固定符号
                    
                    self.logger.info(f"🔄 正在平仓Backpack {position.side.value}仓...")
                    self.logger.info(f"   交易对: {backpack_symbol}")
                    self.logger.info(f"   数量: {position.amount}")
                    self.logger.info(f"   方向: {'卖出' if position.side == PositionSide.LONG else '买入'}")
                    
                    close_result = self.backpack_client.account_client.execute_order(
                        symbol=backpack_symbol,
                        side='Ask' if position.side == PositionSide.LONG else 'Bid',  # Ask=卖出, Bid=买入
                        order_type=OrderTypeEnum.MARKET,
                        quantity=str(position.amount),
                        time_in_force=TimeInForceEnum.IOC
                    )
                    
                    if close_result and 'id' in close_result:
                        self.logger.info(f"✅ Backpack平仓订单提交成功: {close_result['id']}")
                        success = True
                    else:
                        self.logger.error(f"❌ Backpack平仓失败: {close_result}")
                        success = False
                        
                except Exception as close_error:
                    self.logger.error(f"❌ Backpack平仓异常: {close_error}")
                    success = False
            else:
                # 没有API配置时无法平仓
                self.logger.error(f"❌ 无法平仓{position.platform}仓位: 没有API配置")
                return
            
            if success:
                position.status = PositionStatus.CLOSED
                self.total_pnl += position.pnl
                self.completed_trades += 1
                
                if position.pnl > 0:
                    self.profitable_trades += 1
                    self.logger.info(f"💰 {position.platform} {position.side.value}仓平仓成功 - {reason}")
                else:
                    self.logger.info(f"📝 {position.platform} {position.side.value}仓平仓成功 - {reason}")
                
                self.logger.info(f"   盈亏: ${position.pnl:+.2f} ({position.pnl_percentage*100:+.2f}%)")
                self.logger.info(f"   平仓价格: ${position.current_price:.2f}")
            else:
                self.logger.error(f"❌ {position.platform}仓位平仓失败")
                
        except Exception as e:
            self.logger.error(f"❌ 平仓异常: {e}")
    
    async def _cancel_limit_order(self, position: Position):
        """取消限价单"""
        try:
            if not hasattr(position, 'limit_order_id') or not position.limit_order_id:
                return
            
            success = False
            
            if position.platform == "aster" and self.aster_client:
                # Aster需要symbol参数来取消订单
                cancel_result = self.aster_client.cancel_order(
                    symbol=position.symbol.replace('-', ''),  # 转换符号格式
                    order_id=int(position.limit_order_id)
                )
                success = cancel_result is not None
                
            elif position.platform == "backpack" and self.backpack_client:
                cancel_result = await self.backpack_client.cancel_order(position.limit_order_id)
                success = cancel_result is not None
            else:
                # 没有API配置时无法取消订单
                self.logger.error(f"❌ 无法取消限价单: 没有API配置")
                return
            
            if success:
                self.logger.info(f"🚫 取消限价单: {position.limit_order_id}")
                position.limit_order_id = None
            else:
                self.logger.warning(f"⚠️ 取消限价单失败: {position.limit_order_id}")
                
        except Exception as e:
            self.logger.error(f"❌ 取消限价单异常: {e}")
    
    async def _force_close_all_real_positions(self):
        """强制平仓所有活跃仓位"""
        try:
            active_positions = [pos for pos in self.positions.values() if pos.status == PositionStatus.ACTIVE]
            
            for position in active_positions:
                # 取消所有限价单
                if hasattr(position, 'limit_order_id') and position.limit_order_id:
                    await self._cancel_limit_order(position)
                
                # 强制平仓
                await self._close_real_position(position, "强制平仓")
                
        except Exception as e:
            self.logger.error(f"❌ 强制平仓异常: {e}")
    
    def _has_active_positions(self) -> bool:
        """检查是否有活跃仓位"""
        return any(pos.status == PositionStatus.ACTIVE for pos in self.positions.values())
    
    def _print_real_positions_status(self, main_price: float, backpack_price: float, aster_price: float, count: int):
        """打印实盘仓位状态 - 清晰显示Aster和Backpack开仓信息对比"""
        active_count = sum(1 for p in self.positions.values() if p.status == PositionStatus.ACTIVE)
        
        # 计算价格变化率 (使用主价格)
        if hasattr(self, 'entry_price') and self.entry_price:
            price_change_rate = ((main_price - self.entry_price) / self.entry_price) * 100
        else:
            price_change_rate = 0.0
        
        self.logger.info(f"📊 监控 {count:3d}: 开仓价 ${getattr(self, 'entry_price', 0.0):6.2f} | 当前价 ${main_price:6.2f} | 变化率 {price_change_rate:+5.2f}%")
        self.logger.info(f"💰 市场价格: Backpack ${backpack_price:6.2f} | Aster ${aster_price:6.2f} | 活跃仓位: {active_count}")
        
        # 分别显示Aster和Backpack的详细仓位信息，使用各自的当前价格
        aster_position = self.positions.get('aster')
        backpack_position = self.positions.get('backpack')
        
        if aster_position and aster_position.status == PositionStatus.ACTIVE:
            side_text = "空单" if aster_position.side == PositionSide.SHORT else "多单"
            # 使用Aster的实际价格
            self.logger.info(f"🔴 Aster {side_text}: {aster_position.amount:.4f} SOL | 买入价 ${aster_position.entry_price:.2f} | 当前价 ${aster_price:.2f} | PnL: {aster_position.pnl_percentage*100:+5.2f}% (${aster_position.pnl:+.2f})")
        
        if backpack_position and backpack_position.status == PositionStatus.ACTIVE:
            side_text = "多单" if backpack_position.side == PositionSide.LONG else "空单"
            # 使用Backpack的实际价格
            self.logger.info(f"🟢 Backpack {side_text}: {backpack_position.amount:.4f} SOL | 买入价 ${backpack_position.entry_price:.2f} | 当前价 ${backpack_price:.2f} | PnL: {backpack_position.pnl_percentage*100:+5.2f}% (${backpack_position.pnl:+.2f})")
        
        # 显示总体对冲效果
        if aster_position and backpack_position and aster_position.status == PositionStatus.ACTIVE and backpack_position.status == PositionStatus.ACTIVE:
            total_pnl = aster_position.pnl + backpack_position.pnl
            self.logger.info(f"⚖️  对冲总PnL: ${total_pnl:+.2f} | 价差: ${abs(backpack_price - aster_price):.2f}")
    
    def print_final_results(self):
        """打印最终结果"""
        self.logger.info("\n" + "="*60)
        self.logger.info("📊 实盘动态对冲策略结果")
        self.logger.info("="*60)
        
        # 仓位详情
        for platform, position in self.positions.items():
            # 获取平台中文名称和图标
            if platform == "aster":
                platform_name = "🔴 Aster"
                side_name = "空单" if position.side.value == "short" else "多单"
            else:  # backpack
                platform_name = "🟢 Backpack"
                side_name = "多单" if position.side.value == "long" else "空单"
            
            self.logger.info(f"\n【{platform_name} {side_name}】:")
            self.logger.info(f"  订单ID: {position.order_id}")
            self.logger.info(f"  入场价格: ${position.entry_price:.2f}")
            self.logger.info(f"  平仓价格: ${position.current_price:.2f}")
            self.logger.info(f"  数量: {position.amount:.4f} SOL")
            self.logger.info(f"  盈亏: ${position.pnl:+.2f} ({position.pnl_percentage*100:+.2f}%)")
            self.logger.info(f"  状态: {position.status.value}")
        
        # 总体统计
        win_rate = (self.profitable_trades / max(1, self.completed_trades)) * 100
        fee_cost = self.position_size_usdt * self.total_fee_rate
        net_profit = self.total_pnl - fee_cost
        
        self.logger.info(f"\n总体结果:")
        self.logger.info(f"  完成交易: {self.completed_trades}")
        self.logger.info(f"  盈利交易: {self.profitable_trades}")
        self.logger.info(f"  胜率: {win_rate:.1f}%")
        self.logger.info(f"  总盈亏: ${self.total_pnl:.2f}")
        self.logger.info(f"  手续费成本: ${fee_cost:.2f}")
        self.logger.info(f"  净盈利: ${net_profit:+.2f}")
        
        # 策略评估
        self.logger.info(f"\n💡 策略评估:")
        if net_profit > 0:
            self.logger.info(f"  ✅ 策略成功！净盈利 ${net_profit:.2f}")
            self.logger.info(f"  ✅ 成功覆盖手续费成本")
        else:
            self.logger.info(f"  ❌ 策略亏损 ${net_profit:.2f}")
            self.logger.info(f"  ❌ 未能覆盖手续费成本")
        
        self.logger.info("="*60)
    
    async def stop_strategy(self):
        """停止策略"""
        self.logger.info("🛑 收到停止信号，正在安全退出...")
        self.strategy_active = False
        await self._force_close_all_real_positions()
    
    async def _get_aster_fill_price(self, symbol: str, order_id: str) -> Optional[float]:
        """查询Aster订单的实际成交价格"""
        max_retries = 3
        retry_delay = 1.0
        
        for attempt in range(max_retries):
            try:
                # 等待一小段时间确保订单已成交
                await asyncio.sleep(0.5 + attempt * 0.3)  # 递增等待时间
                
                # 查询订单详情 (同步方法，不需要await)
                order_details = self.aster_client.get_order(symbol=symbol, order_id=int(order_id))
                if order_details and order_details.get('status') == 'FILLED':
                    # 如果订单已完全成交，返回成交价格
                    fill_price = float(order_details.get('avgPrice', 0))
                    if fill_price > 0:
                        self.logger.info(f"📊 从订单详情获取Aster成交价格: ${fill_price:.2f} (尝试 {attempt + 1})")
                        return fill_price
                
                # 如果订单详情查询失败，尝试查询交易历史 (同步方法，不需要await)
                trades = self.aster_client.get_account_trades(symbol=symbol, limit=20)
                if trades:
                    for trade in trades:
                        if trade.get('orderId') == int(order_id):
                            fill_price = float(trade.get('price', 0))
                            self.logger.info(f"📊 从交易历史获取Aster成交价格: ${fill_price:.2f} (尝试 {attempt + 1})")
                            return fill_price
                
                # 如果是最后一次尝试，记录警告
                if attempt == max_retries - 1:
                    self.logger.warning(f"⚠️ 经过 {max_retries} 次尝试，未找到Aster订单 {order_id} 的成交记录")
                else:
                    self.logger.debug(f"🔄 第 {attempt + 1} 次尝试未找到Aster成交记录，{retry_delay}秒后重试")
                    await asyncio.sleep(retry_delay)
                    
            except Exception as e:
                if attempt == max_retries - 1:
                    self.logger.error(f"❌ 查询Aster成交价格失败 (尝试 {attempt + 1}/{max_retries}): {e}")
                else:
                    self.logger.warning(f"⚠️ 查询Aster成交价格失败 (尝试 {attempt + 1}/{max_retries}): {e}，将重试")
                    await asyncio.sleep(retry_delay)
        
        return None
    
    async def _get_backpack_fill_price(self, symbol: str, order_id: str) -> Optional[float]:
        """查询Backpack订单的实际成交价格"""
        max_retries = 3
        retry_delay = 1.0
        
        for attempt in range(max_retries):
            try:
                # 等待一小段时间确保订单已成交
                await asyncio.sleep(0.5 + attempt * 0.3)  # 递增等待时间
                
                if not self.backpack_client or not hasattr(self.backpack_client, 'account_client'):
                    self.logger.warning("⚠️ Backpack客户端未配置")
                    return None
                
                # 尝试查询订单状态和成交信息
                try:
                    # 方法1: 查询订单历史 (包含已成交订单)
                    order_history = self.backpack_client.account_client.get_order_history(
                        symbol=symbol,
                        limit=20  # 增加查询数量
                    )
                    
                    if order_history and isinstance(order_history, list):
                        # 查找匹配的订单ID
                        for order in order_history:
                            if str(order.get('id', '')) == str(order_id):
                                # 检查订单状态
                                if order.get('status') == 'Filled':
                                    # 获取成交价格
                                    fill_price = order.get('price') or order.get('avgFillPrice')
                                    if fill_price:
                                        fill_price_float = float(fill_price)
                                        self.logger.info(f"📊 从订单历史获取Backpack成交价格: ${fill_price_float:.2f} (尝试 {attempt + 1})")
                                        return fill_price_float
                                break
                    
                    # 方法2: 查询成交记录 (fills)
                    fills = self.backpack_client.account_client.get_fill_history(
                        symbol=symbol,
                        limit=20  # 增加查询数量
                    )
                    
                    if fills and isinstance(fills, list):
                        # 查找匹配的订单ID的成交记录
                        for fill in fills:
                            if str(fill.get('orderId', '')) == str(order_id):
                                fill_price = fill.get('price')
                                if fill_price:
                                    fill_price_float = float(fill_price)
                                    self.logger.info(f"📊 从成交记录获取Backpack成交价格: ${fill_price_float:.2f} (尝试 {attempt + 1})")
                                    return fill_price_float
                                break
                    
                    # 如果是最后一次尝试，记录警告
                    if attempt == max_retries - 1:
                        self.logger.warning(f"⚠️ 经过 {max_retries} 次尝试，未找到Backpack订单 {order_id} 的成交记录")
                    else:
                        self.logger.debug(f"🔄 第 {attempt + 1} 次尝试未找到Backpack成交记录，{retry_delay}秒后重试")
                        await asyncio.sleep(retry_delay)
                        continue  # 继续下一次尝试
                        
                except Exception as api_error:
                    if attempt == max_retries - 1:
                        self.logger.warning(f"⚠️ Backpack API查询失败 (尝试 {attempt + 1}/{max_retries}): {api_error}")
                        
                        # 最后的备用方法: 使用当前市场价格作为估算
                        try:
                            current_price = await self.backpack_client.get_current_price(symbol)
                            if current_price:
                                current_price_float = float(current_price)
                                self.logger.info(f"📊 使用当前市场价格作为Backpack成交价格估算: ${current_price_float:.2f}")
                                return current_price_float
                        except Exception as price_error:
                            self.logger.warning(f"⚠️ 获取当前价格也失败: {price_error}")
                    else:
                        self.logger.warning(f"⚠️ Backpack API查询失败 (尝试 {attempt + 1}/{max_retries}): {api_error}，将重试")
                        await asyncio.sleep(retry_delay)
                        continue  # 继续下一次尝试
                    
            except Exception as e:
                if attempt == max_retries - 1:
                    self.logger.error(f"❌ 查询Backpack成交价格失败 (尝试 {attempt + 1}/{max_retries}): {e}")
                else:
                    self.logger.warning(f"⚠️ 查询Backpack成交价格失败 (尝试 {attempt + 1}/{max_retries}): {e}，将重试")
                    await asyncio.sleep(retry_delay)
        
        return None

async def run_continuous_dynamic_hedge():
    """运行连续动态对冲策略"""
    
    # 策略参数配置 - 可根据需要调整
    STOP_LOSS_THRESHOLD = 0.008    # 0.2% 止损阈值 (缩小以便快速测试)
    PROFIT_TARGET_RATE = 0.003     # 0.3% 盈利目标 (缩小以便快速测试)
    POSITION_SIZE_USDT = 50.0      # USDT仓位大小
    ASTER_LEVERAGE = 1.0           # Aster杠杆倍数
    MONITORING_INTERVAL = 5.0      # 监控间隔（秒）- 缩短以便更频繁检查
    
    # 创建策略实例
    strategy = RealDynamicHedgeStrategy(
        stop_loss_threshold=STOP_LOSS_THRESHOLD,
        profit_target_rate=PROFIT_TARGET_RATE,
        position_size_usdt=POSITION_SIZE_USDT,
        aster_leverage=ASTER_LEVERAGE,
        monitoring_interval=MONITORING_INTERVAL
    )
    
    print("🎯 实盘动态对冲策略 - 连续交易模式")
    print("💡 核心思想: 亏损先止损，盈利延长持有，目标覆盖手续费")
    print("🔄 连续交易: 每轮完成后自动开始新一轮")
    print("⚠️  请确保已正确配置API密钥")
    print(f"📊 策略参数: 止损{STOP_LOSS_THRESHOLD*100:.1f}% | 盈利目标{PROFIT_TARGET_RATE*100:.1f}% | 仓位${POSITION_SIZE_USDT}")
    
    # 交易参数
    symbol = "SOL-USDT"
    
    round_number = 1
    
    try:
        while True:  # 无限循环，连续交易
            try:
                print(f"\n🎯 ===== 第 {round_number} 轮交易开始 =====")
                
                # 重置轮次统计
                round_start_pnl = strategy.total_pnl
                round_start_trades = strategy.completed_trades
                
                # 执行本轮策略
                success = await strategy.execute_real_dynamic_hedge(symbol, POSITION_SIZE_USDT)
                
                # 计算本轮收益
                round_pnl = strategy.total_pnl - round_start_pnl
                round_trades = strategy.completed_trades - round_start_trades
                
                print(f"✅ 第 {round_number} 轮交易完成")
                print(f"   本轮交易数: {round_trades}")
                print(f"   本轮盈亏: ${round_pnl:+.2f}")
                print(f"   累计盈亏: ${strategy.total_pnl:+.2f}")
                
                if not success:
                    print("⚠️ 本轮交易未成功，等待30秒后重试...")
                    await asyncio.sleep(30)
                else:
                    # 等待一段时间再开始下一轮
                    wait_time = 10  # 等待10秒
                    print(f"⏳ 等待 {wait_time} 秒后开始下一轮...")
                    await asyncio.sleep(wait_time)
                
                round_number += 1
                
            except Exception as round_error:
                print(f"❌ 第 {round_number} 轮交易异常: {round_error}")
                # 强制平仓当前轮次的所有仓位
                await strategy.stop_strategy()
                # 等待后继续下一轮
                await asyncio.sleep(30)
                round_number += 1
                continue
            
    except KeyboardInterrupt:
        print("\n🛑 用户中断，正在安全退出...")
        await strategy.stop_strategy()
        # 显示最终结果
        strategy.print_final_results()
    except Exception as e:
        print(f"❌ 策略执行异常: {e}")
        await strategy.stop_strategy()
        strategy.print_final_results()

async def run_single_round_hedge():
    """运行单轮动态对冲策略"""
    
    # 策略参数配置 - 可根据需要调整
    STOP_LOSS_THRESHOLD = 0.008    # 0.2% 止损阈值 (缩小以便快速测试)
    PROFIT_TARGET_RATE = 0.003     # 0.3% 盈利目标 (缩小以便快速测试)
    POSITION_SIZE_USDT = 50.0      # USDT仓位大小
    ASTER_LEVERAGE = 1.0           # Aster杠杆倍数
    MONITORING_INTERVAL = 5.0      # 监控间隔（秒）- 缩短以便更频繁检查
    
    # 创建策略实例
    strategy = RealDynamicHedgeStrategy(
        stop_loss_threshold=STOP_LOSS_THRESHOLD,
        profit_target_rate=PROFIT_TARGET_RATE,
        position_size_usdt=POSITION_SIZE_USDT,
        aster_leverage=ASTER_LEVERAGE,
        monitoring_interval=MONITORING_INTERVAL
    )
    
    print("🎯 实盘动态对冲策略 - 单轮模式")
    print("💡 核心思想: 亏损先止损，盈利延长持有，目标覆盖手续费")
    print("⚠️  请确保已正确配置API密钥")
    print(f"📊 策略参数: 止损{STOP_LOSS_THRESHOLD*100:.1f}% | 盈利目标{PROFIT_TARGET_RATE*100:.1f}% | 仓位${POSITION_SIZE_USDT}")
    
    # 交易参数
    symbol = "SOL-USDT"
    
    try:
        # 执行策略
        success = await strategy.execute_real_dynamic_hedge(symbol, POSITION_SIZE_USDT)
        
        if success:
            # 显示最终结果
            strategy.print_final_results()
        else:
            print("❌ 实盘动态对冲策略执行失败")
             
    except KeyboardInterrupt:
        print("\n🛑 用户中断，正在安全退出...")
        await strategy.stop_strategy()
        # 显示最终结果
        strategy.print_final_results()
    except Exception as e:
        print(f"❌ 策略执行异常: {e}")
        await strategy.stop_strategy()
        strategy.print_final_results()


if __name__ == "__main__":
    print("🚀 动态对冲策略启动器")
    print("1. 连续交易模式 (推荐)")
    print("2. 单轮交易模式")
    
    choice = input("请选择模式 (1/2): ").strip()
    
    try:
        if choice == "1":
            asyncio.run(run_continuous_dynamic_hedge())
        elif choice == "2":
            asyncio.run(run_single_round_hedge())
        else:
            print("❌ 无效选择，默认启动连续交易模式")
            asyncio.run(run_continuous_dynamic_hedge())
    except KeyboardInterrupt:
        print("\n用户中断")
    except Exception as e:
        print(f"启动异常: {e}")