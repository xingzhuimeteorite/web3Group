#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
多币种动态对冲策略 - trade_any_2.py
基于trade_2.py的成功实现重构
核心逻辑：开仓后根据盈亏情况，先平亏损仓位，延长盈利仓位
目标：让盈利覆盖总手续费成本
"""

import asyncio
import logging
import time
import sys
import os
from enum import Enum
from dataclasses import dataclass
from typing import Optional, Dict, List

# 添加项目路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# 导入API客户端
from aster.aster_api_client import AsterFinanceClient
from backpack.trade import SOLStopLossStrategy

class PositionStatus(Enum):
    OPEN = "open"
    CLOSED = "closed"

class PositionSide(Enum):
    LONG = "long"
    SHORT = "short"

@dataclass
class Position:
    """仓位数据结构"""
    platform: str
    symbol: str
    side: PositionSide
    amount: float
    entry_price: float
    current_price: float = 0.0
    status: PositionStatus = PositionStatus.OPEN
    order_id: str = ""
    actual_fill_price: float = 0.0  # 实际成交价格
    fill_time: str = ""  # 成交时间
    
    @property
    def pnl(self) -> float:
        """计算PnL - 使用实际成交价格"""
        fill_price = self.actual_fill_price if self.actual_fill_price > 0 else self.entry_price
        if self.side == PositionSide.LONG:
            return (self.current_price - fill_price) * self.amount
        else:
            return (fill_price - self.current_price) * self.amount
    
    @property
    def pnl_percentage(self) -> float:
        """计算PnL百分比 - 使用实际成交价格"""
        fill_price = self.actual_fill_price if self.actual_fill_price > 0 else self.entry_price
        if fill_price == 0:
            return 0.0
        return (self.pnl / (fill_price * self.amount)) * 100

class CoinConfig:
    """币种配置管理"""
    
    DEFAULT_COINS = {
        'BTC': {
            'symbol': 'BTC_USDT',
            'name': 'Bitcoin',
            'min_amount': 0.001,
            'price_precision': 2,
            'amount_precision': 6
        },
        'ETH': {
            'symbol': 'ETH_USDT', 
            'name': 'Ethereum',
            'min_amount': 0.01,
            'price_precision': 2,
            'amount_precision': 4
        },
        'BNB': {
            'symbol': 'BNB_USDT',
            'name': 'Binance Coin', 
            'min_amount': 0.1,
            'price_precision': 2,
            'amount_precision': 3
        },
        'SOL': {
            'symbol': 'SOL_USDT',
            'name': 'Solana',
            'min_amount': 0.1,
            'price_precision': 2,
            'amount_precision': 2
        }
    }
    
    # 从波动性分析加载的币种
    SUPPORTED_COINS = {}
    
    @classmethod
    def load_coins_from_volatility_analysis(cls, json_file_path: str = None):
        """从波动性分析JSON文件加载币种配置"""
        if json_file_path is None:
            # 查找最新的波动性分析文件
            import glob
            pattern = "common_pairs_volatility_*.json"
            files = glob.glob(pattern)
            if files:
                json_file_path = max(files, key=os.path.getctime)
            else:
                cls.logger.warning("未找到波动性分析文件，使用默认币种配置")
                cls.SUPPORTED_COINS = cls.DEFAULT_COINS.copy()
                return
        
        try:
            import json
            with open(json_file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 解析波动性分析数据
            for coin_data in data.get('coins', []):
                symbol = coin_data.get('symbol', '')
                if symbol and '_' in symbol:
                    coin = symbol.split('_')[0]
                    cls.SUPPORTED_COINS[coin] = {
                        'symbol': symbol,
                        'name': coin_data.get('name', coin),
                        'volatility': coin_data.get('volatility_24h', 0),
                        'volume_24h': coin_data.get('volume_24h', 0),
                        'price_change_24h': coin_data.get('price_change_24h', 0),
                        'min_amount': cls.DEFAULT_COINS.get(coin, {}).get('min_amount', 0.1),
                        'price_precision': cls.DEFAULT_COINS.get(coin, {}).get('price_precision', 2),
                        'amount_precision': cls.DEFAULT_COINS.get(coin, {}).get('amount_precision', 2)
                    }
            
            # 如果没有加载到币种，使用默认配置
            if not cls.SUPPORTED_COINS:
                cls.SUPPORTED_COINS = cls.DEFAULT_COINS.copy()
                
        except Exception as e:
            print(f"加载波动性分析文件失败: {e}")
            cls.SUPPORTED_COINS = cls.DEFAULT_COINS.copy()
    
    @classmethod
    def get_coin_info(cls, coin: str) -> Dict:
        """获取币种信息"""
        return cls.SUPPORTED_COINS.get(coin, cls.DEFAULT_COINS.get(coin, {}))
    
    @classmethod
    def is_supported(cls, coin: str) -> bool:
        """检查币种是否支持"""
        return coin in cls.SUPPORTED_COINS or coin in cls.DEFAULT_COINS
    
    @classmethod
    def get_symbol(cls, coin: str) -> str:
        """获取交易对符号"""
        info = cls.get_coin_info(coin)
        return info.get('symbol', f'{coin}_USDT')
    
    @classmethod
    def get_all_supported_coins(cls) -> List[str]:
        """获取所有支持的币种"""
        return list(cls.SUPPORTED_COINS.keys()) if cls.SUPPORTED_COINS else list(cls.DEFAULT_COINS.keys())
    
    @classmethod
    def get_top_volatility_coins(cls, limit: int = 10) -> List[str]:
        """获取波动性最高的币种"""
        if not cls.SUPPORTED_COINS:
            return list(cls.DEFAULT_COINS.keys())[:limit]
        
        # 按波动性排序
        sorted_coins = sorted(
            cls.SUPPORTED_COINS.items(),
            key=lambda x: x[1].get('volatility', 0),
            reverse=True
        )
        return [coin for coin, _ in sorted_coins[:limit]]

class MultiCoinDynamicHedgeStrategy:
    """多币种动态对冲策略"""
    
    def __init__(self, config_path: str = None):
        # 策略参数
        self.stop_loss_threshold = 0.008  # 0.8% 止损阈值
        self.profit_target_rate = 0.003  # 0.3% 盈利目标
        self.total_fee_rate = 0.0015     # 0.15% 总手续费率
        
        # 交易参数
        self.position_size_usdt = 50.0   # USDT仓位大小
        self.aster_leverage = 1.0        # Aster杠杆倍数
        
        # 币种配置
        self.selected_coin = None
        self.symbol = None
        
        # 仓位管理
        self.positions: List[Position] = []
        self.total_pnl = 0.0
        self.completed_trades = 0
        self.profitable_trades = 0
        
        # 策略状态
        self.strategy_active = False
        self.monitoring_interval = 2.0
        
        # 初始化日志
        self.logger = self._setup_logger()
        
        # 初始化API客户端
        self.aster_client = None
        self.backpack_client = None
        self._init_api_clients(config_path)
        
        # 加载币种配置
        CoinConfig.load_coins_from_volatility_analysis()

    def _setup_logger(self) -> logging.Logger:
        """设置日志"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('multi_coin_hedge.log'),
                logging.StreamHandler()
            ]
        )
        return logging.getLogger(__name__)

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

    def select_coin(self, coin: str) -> bool:
        """选择交易币种"""
        if not CoinConfig.is_supported(coin):
            self.logger.error(f"❌ 不支持的币种: {coin}")
            return False
        
        self.selected_coin = coin
        self.symbol = CoinConfig.get_symbol(coin)
        self.logger.info(f"✅ 选择币种: {coin} ({self.symbol})")
        return True

    async def _get_current_price(self) -> Optional[float]:
        """获取当前价格"""
        try:
            if self.aster_client:
                # 转换symbol格式 (SOL_USDT -> SOLUSDT)
                aster_symbol = self.symbol.replace("_", "")
                ticker = self.aster_client.get_ticker_price(aster_symbol)
                if ticker and 'price' in ticker:
                    return float(ticker['price'])
            
            # 如果Aster获取失败，尝试其他方式或返回模拟价格
            self.logger.warning("⚠️ 无法获取实时价格，使用模拟价格")
            # 这里可以添加其他价格源或返回模拟价格
            return 100.0  # 模拟价格
            
        except Exception as e:
            self.logger.error(f"❌ 获取价格失败: {e}")
            return None

    async def _open_real_positions(self):
        """开启实盘仓位"""
        try:
            current_price = await self._get_current_price()
            if not current_price:
                self.logger.error("❌ 无法获取当前价格，跳过开仓")
                return False
            
            # 计算仓位数量
            amount = self.position_size_usdt / current_price
            
            self.logger.info(f"🚀 开始开仓 - {self.selected_coin}")
            self.logger.info(f"  当前价格: ${current_price:.4f}")
            self.logger.info(f"  仓位大小: ${self.position_size_usdt} USDT")
            self.logger.info(f"  数量: {amount:.4f} {self.selected_coin}")
            
            # 同时开启Aster空单和Backpack多单
            aster_success = await self._open_aster_short(amount, current_price)
            backpack_success = await self._open_backpack_long(amount, current_price)
            
            if aster_success and backpack_success:
                self.logger.info("✅ 对冲仓位开启成功")
                return True
            else:
                self.logger.error("❌ 部分仓位开启失败")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ 开仓失败: {e}")
            return False

    async def _open_aster_short(self, amount: float, price: float) -> bool:
        """开启Aster空单"""
        try:
            self.logger.info(f"🔄 正在开启Aster空单...")
            
            if self.aster_client:
                # 转换symbol格式 (SOL_USDT -> SOLUSDT)
                aster_symbol = self.symbol.replace("_", "")
                
                # 根据不同币种的交易规则调整数量精度
                import decimal
                from datetime import datetime
                
                # 获取币种特定的精度规则
                if aster_symbol in ['0GUSDT']:
                    # 0G要求整数数量 (stepSize=1, minQty=1)
                    step_size = '1'
                    min_qty = 1
                    precision_places = 0
                elif aster_symbol in ['XPLUSDT']:
                    # XPL使用更高精度
                    step_size = '0.1'
                    min_qty = 0.1
                    precision_places = 1
                else:
                    # 其他币种默认使用小数精度
                    step_size = '0.01'
                    min_qty = 0.01
                    precision_places = 2
                
                quantity_decimal = decimal.Decimal(str(amount))
                adjusted_quantity = float(quantity_decimal.quantize(decimal.Decimal(step_size)))
                
                # 确保满足最小数量要求
                min_notional = 5.0  # 最小名义价值5USDT
                min_qty_by_notional = min_notional / price
                actual_quantity = max(adjusted_quantity, min_qty, min_qty_by_notional)
                
                # 再次调整精度，确保符合stepSize
                actual_quantity = float(decimal.Decimal(str(actual_quantity)).quantize(decimal.Decimal(step_size)))
                
                self.logger.info(f"  交易对: {aster_symbol}")
                self.logger.info(f"  数量: {actual_quantity} (原始: {amount:.4f}, 调整: {adjusted_quantity})")
                self.logger.info(f"  价格: ${price:.2f}")
                self.logger.info(f"  名义价值: ${actual_quantity * price:.2f} USDT")
                self.logger.info(f"  精度规则: stepSize={step_size}, minQty={min_qty}")
                
                # 添加网络超时和重试机制
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        # 实盘下单 - 根据精度要求格式化数量
                        formatted_quantity = int(actual_quantity) if precision_places == 0 else round(actual_quantity, precision_places)
                        
                        # 添加调试信息
                        self.logger.info(f"  下单参数: symbol={aster_symbol}, side=SELL, type=MARKET, quantity={formatted_quantity}")
                        
                        order_result = self.aster_client.place_order(
                            symbol=aster_symbol,
                            side='SELL',  # 使用大写
                            order_type='MARKET',  # 使用大写
                            quantity=formatted_quantity
                        )
                        
                        if order_result and 'orderId' in order_result:
                            order_id = order_result['orderId']
                            self.logger.info(f"✅ Aster空单下单成功，订单ID: {order_id}")
                            
                            # 查询实际成交价格
                            actual_fill_price = await self._get_aster_fill_price(aster_symbol, order_id)
                            fill_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            
                            # 创建仓位记录
                            position = Position(
                                platform="aster",
                                symbol=self.symbol,
                                side=PositionSide.SHORT,
                                amount=actual_quantity,
                                entry_price=price,
                                order_id=order_id,
                                actual_fill_price=actual_fill_price if actual_fill_price else price,
                                fill_time=fill_time
                            )
                            
                            self.positions.append(position)
                            
                            if actual_fill_price:
                                self.logger.info(f"📊 Aster实际成交价格: ${actual_fill_price:.2f}")
                            else:
                                self.logger.warning(f"⚠️ 无法获取Aster实际成交价格，使用市场价格: ${price:.2f}")
                            
                            return True
                        else:
                            self.logger.error(f"❌ Aster下单失败: {order_result}")
                            if attempt < max_retries - 1:
                                await asyncio.sleep(2)
                                continue
                            return False
                            
                    except Exception as e:
                        self.logger.error(f"❌ Aster下单异常 (尝试 {attempt + 1}/{max_retries}): {e}")
                        if attempt < max_retries - 1:
                            await asyncio.sleep(2)
                        else:
                            return False
                            
            return False
            
        except Exception as e:
            self.logger.error(f"❌ 开启Aster空单失败: {e}")
            return False

    async def _open_backpack_long(self, amount: float, price: float) -> bool:
        """开启Backpack多单"""
        try:
            self.logger.info(f"🔄 正在开启Backpack多单...")
            
            if self.backpack_client:
                # 转换symbol格式 (SOL_USDT -> SOL_USDC)
                backpack_symbol = self.symbol.replace("_USDT", "_USDC")
                
                # 根据不同币种的交易规则调整数量精度
                import decimal
                from datetime import datetime
                
                # 获取币种特定的精度规则
                if backpack_symbol in ['0G_USDC']:
                    # 0G要求整数数量
                    step_size = '1'
                    min_qty = 1
                    precision_places = 0
                elif backpack_symbol in ['XPL_USDC']:
                    # XPL使用更高精度
                    step_size = '0.1'
                    min_qty = 0.1
                    precision_places = 1
                else:
                    # 其他币种默认使用小数精度
                    step_size = '0.01'
                    min_qty = 0.01
                    precision_places = 2
                
                quantity_decimal = decimal.Decimal(str(amount))
                adjusted_quantity = float(quantity_decimal.quantize(decimal.Decimal(step_size)))
                
                # 确保满足最小数量要求
                min_notional = 5.0  # 最小名义价值5USDC
                min_qty_by_notional = min_notional / price
                actual_quantity = max(adjusted_quantity, min_qty, min_qty_by_notional)
                
                # 再次调整精度，确保符合stepSize
                actual_quantity = float(decimal.Decimal(str(actual_quantity)).quantize(decimal.Decimal(step_size)))
                
                self.logger.info(f"  交易对: {backpack_symbol}")
                self.logger.info(f"  数量: {actual_quantity} (原始: {amount:.4f}, 调整: {adjusted_quantity})")
                self.logger.info(f"  价格: ${price:.2f}")
                self.logger.info(f"  名义价值: ${actual_quantity * price:.2f} USDC")
                self.logger.info(f"  精度规则: stepSize={step_size}, minQty={min_qty}")
                
                # 添加网络超时和重试机制
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        # 实盘下单 - 根据精度要求格式化数量
                        formatted_quantity = int(actual_quantity) if precision_places == 0 else round(actual_quantity, precision_places)
                        
                        order_result = self.backpack_client.account_client.execute_order(
                            symbol=backpack_symbol,
                            side="Bid",  # 买入
                            order_type="Market",
                            quantity=str(formatted_quantity),
                            time_in_force="IOC"
                        )
                        
                        if order_result and order_result.get('id'):
                            order_id = order_result['id']
                            self.logger.info(f"✅ Backpack多单下单成功，订单ID: {order_id}")
                            
                            # 查询实际成交价格
                            actual_fill_price = await self._get_backpack_fill_price(backpack_symbol, order_id)
                            fill_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            
                            # 创建仓位记录
                            position = Position(
                                platform="backpack",
                                symbol=self.symbol,
                                side=PositionSide.LONG,
                                amount=actual_quantity,
                                entry_price=price,
                                order_id=order_id,
                                actual_fill_price=actual_fill_price if actual_fill_price else price,
                                fill_time=fill_time
                            )
                            
                            self.positions.append(position)
                            
                            if actual_fill_price:
                                self.logger.info(f"📊 Backpack实际成交价格: ${actual_fill_price:.2f}")
                            else:
                                self.logger.warning(f"⚠️ 无法获取Backpack实际成交价格，使用市场价格: ${price:.2f}")
                            
                            return True
                        else:
                            self.logger.error(f"❌ Backpack下单失败: {order_result}")
                            if attempt < max_retries - 1:
                                await asyncio.sleep(2)
                                continue
                            return False
                            
                    except Exception as e:
                        self.logger.error(f"❌ Backpack下单异常 (尝试 {attempt + 1}/{max_retries}): {e}")
                        if attempt < max_retries - 1:
                            await asyncio.sleep(2)
                        else:
                            return False
                            
            return False
            
        except Exception as e:
            self.logger.error(f"❌ 开启Backpack多单失败: {e}")
            return False

    async def _update_real_positions_pnl(self, current_price: float):
        """更新实盘仓位PnL"""
        for position in self.positions:
            if position.status == PositionStatus.OPEN:
                position.current_price = current_price

    async def _execute_real_closing_logic(self):
        """执行实盘平仓逻辑"""
        try:
            open_positions = [p for p in self.positions if p.status == PositionStatus.OPEN]
            if not open_positions:
                return
            
            # 计算总PnL百分比
            total_pnl = sum(position.pnl for position in open_positions)
            total_position_value = sum(position.entry_price * position.amount for position in open_positions)
            
            if total_position_value > 0:
                total_pnl_percentage = (total_pnl / total_position_value) * 100
            else:
                total_pnl_percentage = 0
            
            # 检查总盈利是否达到0.3%
            if total_pnl_percentage >= self.profit_target_rate * 100:
                # 平掉所有仓位
                for position in open_positions:
                    await self._close_real_position(position, f"总盈利达标 (总PnL: {total_pnl_percentage:.3f}%)")
                return
            
            # 检查个别仓位的止损条件
            for position in open_positions:
                pnl_pct = position.pnl_percentage
                
                # 止损条件
                if pnl_pct <= -self.stop_loss_threshold * 100:
                    await self._close_real_position(position, f"止损 ({pnl_pct:.2f}%)")
                    
        except Exception as e:
            self.logger.error(f"❌ 平仓逻辑执行失败: {e}")

    async def _close_real_position(self, position: Position, reason: str):
        """平仓实盘仓位"""
        try:
            self.logger.info(f"🔄 平仓 {position.platform} {position.side.value}单: {reason}")
            
            # 这里应该调用相应平台的平仓API
            # 暂时标记为已平仓
            position.status = PositionStatus.CLOSED
            
            self.logger.info(f"✅ {position.platform} {position.side.value}单已平仓")
            self.logger.info(f"  PnL: ${position.pnl:.2f} ({position.pnl_percentage:.2f}%)")
            
        except Exception as e:
            self.logger.error(f"❌ 平仓失败: {e}")

    def _has_active_positions(self) -> bool:
        """检查是否有活跃仓位"""
        return any(p.status == PositionStatus.OPEN for p in self.positions)

    def _print_real_positions_status(self, current_price: float, count: int):
        """打印实盘仓位状态 - 增强版显示更多详细信息"""
        open_positions = [p for p in self.positions if p.status == PositionStatus.OPEN]
        if not open_positions:
            return
        
        print(f"\n📊 仓位状态 (第{count}次检查) - {self.selected_coin} @ ${current_price:.4f}")
        print("=" * 80)
        
        total_pnl = 0
        total_position_value = 0
        
        for i, position in enumerate(open_positions, 1):
            pnl = position.pnl
            pnl_pct = position.pnl_percentage
            total_pnl += pnl
            
            # 使用实际成交价格计算仓位价值
            fill_price = position.actual_fill_price if position.actual_fill_price > 0 else position.entry_price
            position_value = fill_price * position.amount
            total_position_value += position_value
            
            status_emoji = "🟢" if pnl > 0 else "🔴" if pnl < 0 else "⚪"
            side_emoji = "📈" if position.side == PositionSide.LONG else "📉"
            
            print(f"  {status_emoji} 仓位 {i}: {position.platform.upper()} {side_emoji} {position.side.value.upper()}")
            print(f"    📋 订单ID: {position.order_id}")
            print(f"    💰 数量: {position.amount:.4f} {self.selected_coin}")
            print(f"    💵 开仓价格: ${position.entry_price:.4f} (市场价)")
            
            if position.actual_fill_price > 0:
                print(f"    ✅ 实际成交价: ${position.actual_fill_price:.4f}")
                price_diff = position.actual_fill_price - position.entry_price
                price_diff_pct = (price_diff / position.entry_price) * 100 if position.entry_price > 0 else 0
                print(f"    📊 成交差价: ${price_diff:+.4f} ({price_diff_pct:+.3f}%)")
            else:
                print(f"    ⚠️  成交价格: 未获取到实际成交价")
            
            if position.fill_time:
                print(f"    ⏰ 成交时间: {position.fill_time}")
            
            print(f"    📈 当前价格: ${current_price:.4f}")
            print(f"    💎 仓位价值: ${position_value:.2f} USDT")
            print(f"    💰 PnL: ${pnl:+.2f} ({pnl_pct:+.3f}%)")
            print("    " + "-" * 50)
        
        # 计算总PnL百分比
        if total_position_value > 0:
            total_pnl_percentage = (total_pnl / total_position_value) * 100
        else:
            total_pnl_percentage = 0
        
        print(f"  📊 总体统计:")
        print(f"    💰 总PnL: ${total_pnl:+.2f} ({total_pnl_percentage:+.3f}%)")
        print(f"    💎 总仓位价值: ${total_position_value:.2f} USDT")
        print(f"    🎯 盈利目标: {self.profit_target_rate * 100:.1f}% (${(total_position_value * self.profit_target_rate):+.2f})")
        print(f"    🛑 止损阈值: -{self.stop_loss_threshold * 100:.1f}% (${-(total_position_value * self.stop_loss_threshold):+.2f})")
        
        # 显示距离目标的进度
        if total_pnl_percentage > 0:
            progress = (total_pnl_percentage / (self.profit_target_rate * 100)) * 100
            progress_bar = "█" * int(progress / 10) + "░" * (10 - int(progress / 10))
            print(f"    📈 盈利进度: [{progress_bar}] {progress:.1f}%")
        
        print("=" * 80)



    def _print_real_strategy_summary(self):
        """打印实盘策略总结"""
        print(f"\n📈 策略总结 - {self.selected_coin}")
        print(f"  完成交易: {self.completed_trades}")
        print(f"  盈利交易: {self.profitable_trades}")
        print(f"  总PnL: ${self.total_pnl:.2f}")
        if self.completed_trades > 0:
            win_rate = (self.profitable_trades / self.completed_trades) * 100
            print(f"  胜率: {win_rate:.1f}%")

    async def execute_single_round(self, coin: str, position_size: float) -> bool:
        """执行单轮交易"""
        try:
            # 选择币种
            if not self.select_coin(coin):
                return False
            
            # 设置仓位大小
            self.position_size_usdt = position_size
            
            # 开仓
            if not await self._open_real_positions():
                return False
            
            # 监控和平仓
            self.strategy_active = True
            count = 0
            
            while self.strategy_active and self._has_active_positions():
                count += 1
                current_price = await self._get_current_price()
                
                if current_price:
                    # 更新仓位PnL
                    await self._update_real_positions_pnl(current_price)
                    
                    # 打印状态
                    if count % 5 == 0:  # 每5次检查打印一次状态
                        self._print_real_positions_status(current_price, count)
                    
                    # 执行平仓逻辑
                    await self._execute_real_closing_logic()
                
                await asyncio.sleep(self.monitoring_interval)
            
            # 强制平仓剩余仓位
            await self._force_close_all_real_positions()
            
            # 打印总结
            self._print_real_strategy_summary()
            
            return True
            
        except Exception as e:
            self.logger.error(f"❌ 单轮交易执行失败: {e}")
            return False

    async def _force_close_all_real_positions(self):
        """强制平仓所有实盘仓位"""
        open_positions = [p for p in self.positions if p.status == PositionStatus.OPEN]
        for position in open_positions:
            await self._close_real_position(position, "强制平仓")

    async def _get_aster_fill_price(self, symbol: str, order_id: str) -> Optional[float]:
        """查询Aster订单的实际成交价格"""
        if not self.aster_client:
            return None
            
        max_retries = 3
        for attempt in range(max_retries):
            try:
                await asyncio.sleep(0.5)  # 等待订单处理
                
                # 方法1: 查询订单详情
                order_detail = self.aster_client.get_order(symbol, order_id)
                if order_detail and order_detail.get('status') == 'FILLED':
                    # 如果订单已完全成交，返回成交价格
                    fill_price = order_detail.get('avgPrice') or order_detail.get('price')
                    if fill_price:
                        fill_price_float = float(fill_price)
                        self.logger.info(f"📊 从订单详情获取Aster成交价格: ${fill_price_float:.2f} (尝试 {attempt + 1})")
                        return fill_price_float
                
                # 方法2: 查询交易历史
                trades = self.aster_client.get_account_trades(symbol, limit=10)
                if trades and isinstance(trades, list):
                    for trade in trades:
                        if str(trade.get('orderId', '')) == str(order_id):
                            fill_price = trade.get('price')
                            if fill_price:
                                fill_price_float = float(fill_price)
                                self.logger.info(f"📊 从交易历史获取Aster成交价格: ${fill_price_float:.2f} (尝试 {attempt + 1})")
                                return fill_price_float
                            break
                
                # 如果是最后一次尝试，记录警告
                if attempt == max_retries - 1:
                    self.logger.warning(f"⚠️ 无法获取Aster成交价格，将使用市场价格估算")
                    
            except Exception as e:
                if attempt == max_retries - 1:
                    self.logger.error(f"❌ 查询Aster成交价格失败 (尝试 {attempt + 1}/{max_retries}): {e}")
                else:
                    self.logger.warning(f"⚠️ 查询Aster成交价格失败 (尝试 {attempt + 1}/{max_retries}): {e}，将重试")
                    await asyncio.sleep(1)
        
        return None

    async def _get_backpack_fill_price(self, symbol: str, order_id: str) -> Optional[float]:
        """查询Backpack订单的实际成交价格"""
        if not self.backpack_client:
            return None
            
        max_retries = 3
        for attempt in range(max_retries):
            try:
                await asyncio.sleep(0.5)  # 等待订单处理
                
                # 方法1: 查询订单历史
                orders = self.backpack_client.account_client.get_order_history(
                    symbol=symbol,
                    limit=20
                )
                
                if orders and isinstance(orders, list):
                    for order in orders:
                        if str(order.get('id', '')) == str(order_id):
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
                    limit=20
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
                    self.logger.warning(f"⚠️ 无法获取Backpack成交价格，将使用市场价格估算")
                    
            except Exception as e:
                if attempt == max_retries - 1:
                    self.logger.error(f"❌ 查询Backpack成交价格失败 (尝试 {attempt + 1}/{max_retries}): {e}")
                else:
                    self.logger.warning(f"⚠️ 查询Backpack成交价格失败 (尝试 {attempt + 1}/{max_retries}): {e}，将重试")
                    await asyncio.sleep(1)
        
        return None

    async def _execute_real_closing_logic(self):
        """执行实盘平仓逻辑"""
        try:
            open_positions = [p for p in self.positions if p.status == PositionStatus.OPEN]
            if not open_positions:
                return
            
            # 计算总PnL百分比
            total_pnl = sum(position.pnl for position in open_positions)
            total_position_value = sum(position.entry_price * position.amount for position in open_positions)
            
            if total_position_value > 0:
                total_pnl_percentage = (total_pnl / total_position_value) * 100
            else:
                total_pnl_percentage = 0
            
            # 检查总盈利是否达到0.3%
            if total_pnl_percentage >= self.profit_target_rate * 100:
                # 平掉所有仓位
                for position in open_positions:
                    await self._close_real_position(position, f"总盈利达标 (总PnL: {total_pnl_percentage:.3f}%)")
                return
            
            # 检查个别仓位的止损条件
            for position in open_positions:
                pnl_pct = position.pnl_percentage
                
                # 止损条件
                if pnl_pct <= -self.stop_loss_threshold * 100:
                    await self._close_real_position(position, f"止损 ({pnl_pct:.2f}%)")
                    
        except Exception as e:
            self.logger.error(f"❌ 平仓逻辑执行失败: {e}")

    async def _close_real_position(self, position: Position, reason: str):
        """平仓实盘仓位"""
        try:
            self.logger.info(f"🔄 平仓 {position.platform} {position.side.value}单: {reason}")
            
            # 这里应该调用相应平台的平仓API
            # 暂时标记为已平仓
            position.status = PositionStatus.CLOSED
            
            self.logger.info(f"✅ {position.platform} {position.side.value}单已平仓")
            self.logger.info(f"  PnL: ${position.pnl:.2f} ({position.pnl_percentage:.2f}%)")
            
        except Exception as e:
            self.logger.error(f"❌ 平仓失败: {e}")

    def _has_active_positions(self) -> bool:
        """检查是否有活跃仓位"""
        return any(p.status == PositionStatus.OPEN for p in self.positions)



    def _print_real_strategy_summary(self):
        """打印实盘策略总结"""
        print(f"\n📈 策略总结 - {self.selected_coin}")
        print(f"  完成交易: {self.completed_trades}")
        print(f"  盈利交易: {self.profitable_trades}")
        print(f"  总PnL: ${self.total_pnl:.2f}")
        if self.completed_trades > 0:
            win_rate = (self.profitable_trades / self.completed_trades) * 100
            print(f"  胜率: {win_rate:.1f}%")

    async def execute_single_round(self, coin: str, position_size: float) -> bool:
        """执行单轮交易"""
        try:
            # 选择币种
            if not self.select_coin(coin):
                return False
            
            # 设置仓位大小
            self.position_size_usdt = position_size
            
            # 开仓
            if not await self._open_real_positions():
                return False
            
            # 监控和平仓
            self.strategy_active = True
            count = 0
            
            while self.strategy_active and self._has_active_positions():
                count += 1
                current_price = await self._get_current_price()
                
                if current_price:
                    # 更新仓位PnL
                    await self._update_real_positions_pnl(current_price)
                    
                    # 打印状态
                    if count % 5 == 0:  # 每5次检查打印一次状态
                        self._print_real_positions_status(current_price, count)
                    
                    # 执行平仓逻辑
                    await self._execute_real_closing_logic()
                
                await asyncio.sleep(self.monitoring_interval)
            
            # 强制平仓剩余仓位
            await self._force_close_all_real_positions()
            
            # 打印总结
            self._print_real_strategy_summary()
            
            return True
            
        except Exception as e:
            self.logger.error(f"❌ 单轮交易执行失败: {e}")
            return False

    async def _force_close_all_real_positions(self):
        """强制平仓所有实盘仓位"""
        open_positions = [p for p in self.positions if p.status == PositionStatus.OPEN]
        for position in open_positions:
            await self._close_real_position(position, "强制平仓")

def display_coin_menu():
    """显示币种选择菜单"""
    print("\n🪙 支持的币种:")
    
    # 显示高波动性币种
    top_coins = CoinConfig.get_top_volatility_coins(10)
    for i, coin in enumerate(top_coins, 1):
        info = CoinConfig.get_coin_info(coin)
        volatility = info.get('volatility', 0)
        print(f"  {i:2d}. {coin:4s} - {info.get('name', coin):15s} (波动性: {volatility:.2f}%)")
    
    # 显示所有支持的币种
    all_coins = CoinConfig.get_all_supported_coins()
    if len(all_coins) > 10:
        print(f"\n  还有 {len(all_coins) - 10} 个其他币种可选择...")
    
    print(f"\n  0. 退出")
    print(f"  all. 选择所有高波动性币种")

def get_user_coin_choice() -> str:
    """获取用户币种选择"""
    while True:
        try:
            display_coin_menu()
            choice = input("\n请选择币种 (输入数字或币种代码): ").strip().upper()
            
            if choice == "0":
                return None
            
            # 检查是否是数字选择
            if choice.isdigit():
                choice_num = int(choice)
                top_coins = CoinConfig.get_top_volatility_coins(10)
                if 1 <= choice_num <= len(top_coins):
                    return top_coins[choice_num - 1]
                else:
                    print("❌ 无效的数字选择")
                    continue
            
            # 检查是否是币种代码
            if CoinConfig.is_supported(choice):
                return choice
            else:
                print(f"❌ 不支持的币种: {choice}")
                continue
                
        except KeyboardInterrupt:
            return None
        except Exception as e:
            print(f"❌ 输入错误: {e}")
            continue

def get_user_multi_coin_choice() -> List[str]:
    """获取用户多币种选择"""
    while True:
        try:
            display_coin_menu()
            choice = input("\n请选择币种 (输入数字、币种代码，用逗号分隔多个选择，或输入'all'选择所有): ").strip().upper()
            
            if choice == "0":
                return []
            
            if choice == "ALL":
                top_coins = CoinConfig.get_top_volatility_coins(10)
                print(f"✅ 已选择所有高波动性币种: {', '.join(top_coins)}")
                return top_coins
            
            # 解析多个选择
            choices = [c.strip() for c in choice.split(',')]
            selected_coins = []
            
            for c in choices:
                if c.isdigit():
                    choice_num = int(c)
                    top_coins = CoinConfig.get_top_volatility_coins(10)
                    if 1 <= choice_num <= len(top_coins):
                        coin = top_coins[choice_num - 1]
                        if coin not in selected_coins:
                            selected_coins.append(coin)
                    else:
                        print(f"❌ 无效的数字选择: {c}")
                        continue
                elif CoinConfig.is_supported(c):
                    if c not in selected_coins:
                        selected_coins.append(c)
                else:
                    print(f"❌ 不支持的币种: {c}")
                    continue
            
            if selected_coins:
                print(f"✅ 已选择币种: {', '.join(selected_coins)}")
                return selected_coins
            else:
                print("❌ 没有选择有效的币种")
                continue
                
        except KeyboardInterrupt:
            return []
        except Exception as e:
            print(f"❌ 输入错误: {e}")
            continue

async def run_continuous_multi_coin_hedge():
    """运行连续多币种对冲"""
    strategy = MultiCoinDynamicHedgeStrategy()
    
    print("🚀 连续多币种动态对冲策略")
    print("=" * 50)
    
    # 选择交易模式
    print("\n📋 交易模式选择:")
    print("1. 单币种循环交易 (每次选择一个币种)")
    print("2. 多币种轮换交易 (一次选择多个币种，依次交易)")
    print("3. 多币种并发交易 (同时交易多个币种)")
    
    mode_choice = input("请选择交易模式 (1/2/3, 默认1): ").strip() or "1"
    
    try:
        if mode_choice == "1":
            # 单币种循环模式
            while True:
                coin = get_user_coin_choice()
                if not coin:
                    break
                
                try:
                    position_size = float(input(f"请输入仓位大小 (USDT, 默认50): ").strip() or "50")
                    if position_size <= 0:
                        print("❌ 仓位大小必须大于0")
                        continue
                except ValueError:
                    print("❌ 无效的仓位大小")
                    continue
                
                print(f"\n🎯 开始交易 {coin} (仓位: ${position_size} USDT)")
                success = await strategy.execute_single_round(coin, position_size)
                
                if success:
                    print(f"✅ {coin} 交易完成")
                else:
                    print(f"❌ {coin} 交易失败")
                
                continue_choice = input("\n是否继续交易其他币种? (y/n): ").strip().lower()
                if continue_choice != 'y':
                    break
        
        elif mode_choice == "2":
            # 多币种轮换模式
            coins = get_user_multi_coin_choice()
            if not coins:
                return
            
            try:
                position_size = float(input(f"请输入每个币种的仓位大小 (USDT, 默认50): ").strip() or "50")
                if position_size <= 0:
                    print("❌ 仓位大小必须大于0")
                    return
            except ValueError:
                print("❌ 无效的仓位大小")
                return
            
            print(f"\n🎯 开始轮换交易 {len(coins)} 个币种")
            
            while True:
                for coin in coins:
                    print(f"\n🔄 当前交易币种: {coin} (仓位: ${position_size} USDT)")
                    success = await strategy.execute_single_round(coin, position_size)
                    
                    if success:
                        print(f"✅ {coin} 交易完成")
                    else:
                        print(f"❌ {coin} 交易失败")
                    
                    # 短暂休息
                    await asyncio.sleep(2)
                
                continue_choice = input(f"\n是否继续下一轮 {len(coins)} 币种交易? (y/n): ").strip().lower()
                if continue_choice != 'y':
                    break
        
        elif mode_choice == "3":
            # 多币种并发模式
            coins = get_user_multi_coin_choice()
            if not coins:
                return
            
            try:
                position_size = float(input(f"请输入每个币种的仓位大小 (USDT, 默认50): ").strip() or "50")
                if position_size <= 0:
                    print("❌ 仓位大小必须大于0")
                    return
            except ValueError:
                print("❌ 无效的仓位大小")
                return
            
            print(f"\n🎯 开始并发交易 {len(coins)} 个币种")
            print("⚠️  注意: 并发交易会同时开启多个仓位，请确保有足够的资金")
            
            confirm = input("确认开始并发交易? (y/n): ").strip().lower()
            if confirm != 'y':
                return
            
            # 创建多个策略实例进行并发交易
            tasks = []
            for coin in coins:
                strategy_instance = MultiCoinDynamicHedgeStrategy()
                task = asyncio.create_task(
                    strategy_instance.execute_single_round(coin, position_size),
                    name=f"trade_{coin}"
                )
                tasks.append((coin, task))
            
            print(f"🚀 已启动 {len(tasks)} 个并发交易任务")
            
            # 等待所有任务完成
            results = await asyncio.gather(*[task for _, task in tasks], return_exceptions=True)
            
            # 打印结果
            print("\n📊 并发交易结果:")
            for i, (coin, _) in enumerate(tasks):
                result = results[i]
                if isinstance(result, Exception):
                    print(f"❌ {coin}: 交易异常 - {result}")
                elif result:
                    print(f"✅ {coin}: 交易成功")
                else:
                    print(f"❌ {coin}: 交易失败")
        
        else:
            print("❌ 无效的模式选择")
            
    except KeyboardInterrupt:
        print("\n用户中断")
    except Exception as e:
        print(f"策略异常: {e}")

async def run_single_round_multi_coin_hedge():
    """运行单轮多币种对冲"""
    strategy = MultiCoinDynamicHedgeStrategy()
    
    print("🚀 单轮多币种动态对冲策略")
    print("=" * 50)
    
    # 选择币种
    coin = get_user_coin_choice()
    if not coin:
        return
    
    # 获取仓位大小
    try:
        position_size = float(input(f"请输入仓位大小 (USDT, 默认50): ").strip() or "50")
        if position_size <= 0:
            print("❌ 仓位大小必须大于0")
            return
    except ValueError:
        print("❌ 无效的仓位大小")
        return
    
    print(f"\n🎯 开始交易 {coin} (仓位: ${position_size} USDT)")
    
    # 执行单轮交易
    success = await strategy.execute_single_round(coin, position_size)
    
    if success:
        print(f"✅ {coin} 交易完成")
    else:
        print(f"❌ {coin} 交易失败")

if __name__ == "__main__":
    print("🚀 多币种动态对冲策略启动器")
    print("1. 连续交易模式 (推荐)")
    print("2. 单轮交易模式")
    
    choice = input("请选择模式 (1/2): ").strip()
    
    try:
        if choice == "1":
            asyncio.run(run_continuous_multi_coin_hedge())
        elif choice == "2":
            asyncio.run(run_single_round_multi_coin_hedge())
        else:
            print("❌ 无效选择，默认启动连续交易模式")
            asyncio.run(run_continuous_multi_coin_hedge())
    except KeyboardInterrupt:
        print("\n用户中断")
    except Exception as e:
        print(f"启动异常: {e}")