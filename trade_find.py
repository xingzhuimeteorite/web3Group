#!/usr/bin/env python3
"""
加密货币波动率分析工具 - trade_find.py
分析两个平台中都有的代币对，并列出波动最大的前十个币种
"""

import asyncio
import logging
import time
import statistics
import json
import sys
import os
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional, Set
from dataclasses import dataclass
import requests

# 添加当前目录到Python路径，支持从不同位置运行
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

# 导入API客户端
try:
    from aster.aster_api_client import AsterFinanceClient
    from bpx.public import Public as BackpackPublic
    from bpx.account import Account as BackpackAccount
    from backpack.config_loader import ConfigLoader
except ImportError as e:
    print(f"导入API客户端失败: {e}")
    print("请确保相关模块已正确安装")

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
    platforms: List[str]  # 新增：支持的平台列表
    
    @property
    def volatility_score(self) -> float:
        """综合波动率评分 (0-100)"""
        # 优化后的评分算法，提高敏感度和区分度
        
        # 1小时波动率评分 (权重25%, 放大系数500)
        vol_1h_score = min(abs(self.volatility_1h) * 500, 25)
        
        # 24小时波动率评分 (权重35%, 放大系数200)  
        vol_24h_score = min(abs(self.volatility_24h) * 200, 35)
        
        # 7天波动率评分 (权重25%, 放大系数50)
        vol_7d_score = min(abs(self.volatility_7d) * 50, 25)
        
        # 24小时价格变化评分 (权重10%, 直接使用百分比)
        price_change_score = min(abs(self.price_change_percentage_24h), 10)
        
        # 成交量活跃度评分 (权重5%)
        volume_ratio = self.volume_24h / self.market_cap if self.market_cap > 0 else 0
        volume_score = min(volume_ratio * 500, 5)
        
        total_score = vol_1h_score + vol_24h_score + vol_7d_score + price_change_score + volume_score
        
        return min(total_score, 100)  # 确保不超过100分
    
    @property
    def risk_level(self) -> str:
        """风险等级"""
        score = self.volatility_score
        if score >= 60:
            return "极高"
        elif score >= 40:
            return "高"
        elif score >= 25:
            return "中等"
        elif score >= 15:
            return "低"
        else:
            return "极低"
    
    @property
    def recommendation(self) -> str:
        """交易建议"""
        score = self.volatility_score
        if score >= 50:
            return "🔥 强烈推荐 - 高波动高收益"
        elif score >= 30:
            return "✅ 推荐 - 适中波动稳定收益"
        elif score >= 20:
            return "⚠️ 谨慎 - 低波动有限收益"
        elif score >= 10:
            return "📊 可考虑 - 波动较低"
        else:
            return "❌ 不推荐 - 波动过低"

class CryptoVolatilityAnalyzer:
    """加密货币波动率分析器"""
    
    def __init__(self):
        # 初始化API客户端
        self.aster_client = None
        self.backpack_client = None
        self.backpack_account = None
        
        try:
            # 初始化Aster客户端
            self.aster_client = AsterFinanceClient()
            
            # 初始化Backpack客户端
            self.backpack_client = BackpackPublic()
            
            # 尝试加载Backpack配置
            try:
                config = ConfigLoader("backpack/config.json")
                credentials = config.get_api_credentials()
                self.backpack_account = BackpackAccount(
                    public_key=credentials.get('api_key'),
                    secret_key=credentials.get('secret_key')
                )
            except Exception as e:
                print(f"⚠️ Backpack账户配置加载失败: {e}")
                
        except Exception as e:
            print(f"⚠️ API客户端初始化失败: {e}")
        
        self.logger = self._setup_logger()
        
        # API配置
        self.coingecko_base_url = "https://api.coingecko.com/api/v3"

    def _setup_logger(self) -> logging.Logger:
        """设置日志"""
        logger = logging.getLogger(__name__)
        logger.setLevel(logging.INFO)
        
        # 避免重复添加处理器
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        
        return logger

    async def get_aster_trading_pairs(self) -> Set[str]:
        """获取Aster平台支持的交易对列表"""
        try:
            if not self.aster_client:
                self.logger.error("Aster客户端未初始化")
                return set()
            
            # 获取交易所信息
            exchange_info = self.aster_client.get_exchange_info()
            if not exchange_info or 'symbols' not in exchange_info:
                self.logger.error("获取Aster交易对信息失败")
                return set()
            
            trading_pairs = set()
            for symbol_info in exchange_info['symbols']:
                if symbol_info.get('status') == 'TRADING':
                    symbol = symbol_info.get('symbol', '')
                    # 转换为标准格式 (例如: BTCUSDT -> BTC_USDT)
                    if symbol.endswith('USDT'):
                        base = symbol[:-4]
                        trading_pairs.add(f"{base}_USDT")
                    elif symbol.endswith('USDC'):
                        base = symbol[:-4]
                        trading_pairs.add(f"{base}_USDC")
            
            self.logger.info(f"🔴 Aster平台支持 {len(trading_pairs)} 个交易对")
            # 添加调试信息，显示前几个交易对
            if trading_pairs:
                sample_pairs = list(trading_pairs)[:5]
                self.logger.info(f"Aster交易对示例: {sample_pairs}")
            return trading_pairs
            
        except Exception as e:
            self.logger.error(f"获取Aster交易对失败: {e}")
            return set()

    async def get_backpack_trading_pairs(self) -> Set[str]:
        """获取Backpack平台支持的交易对列表"""
        try:
            if not self.backpack_client:
                self.logger.error("Backpack客户端未初始化")
                return set()
            
            # 获取市场信息
            markets_info = self.backpack_client.get_markets()
            if not markets_info:
                self.logger.error("获取Backpack市场信息失败")
                return set()
            
            trading_pairs = set()
            if isinstance(markets_info, list):
                for market in markets_info:
                    symbol = market.get('symbol', '')
                    if symbol:
                        trading_pairs.add(symbol)
            
            self.logger.info(f"🟢 Backpack平台支持 {len(trading_pairs)} 个交易对")
            # 添加调试信息，显示前几个交易对
            if trading_pairs:
                sample_pairs = list(trading_pairs)[:5]
                self.logger.info(f"Backpack交易对示例: {sample_pairs}")
            return trading_pairs
            
        except Exception as e:
            self.logger.error(f"获取Backpack交易对失败: {e}")
            return set()

    async def get_common_trading_pairs(self) -> Set[str]:
        """获取两个平台共有的交易对"""
        try:
            # 获取两个平台的交易对
            aster_pairs = await self.get_aster_trading_pairs()
            backpack_pairs = await self.get_backpack_trading_pairs()
            
            # 标准化交易对格式进行比较
            def normalize_pair(pair):
                """标准化交易对格式，去除PERP后缀，统一为基础币种_报价币种格式"""
                # 去除PERP后缀
                if pair.endswith('_PERP'):
                    pair = pair[:-5]
                
                # 将USDT转换为USDC进行比较（因为两个平台主要报价币种不同）
                if pair.endswith('_USDT'):
                    base = pair[:-5]
                    return f"{base}_USDC"
                
                return pair
            
            # 标准化两个平台的交易对
            normalized_aster = {normalize_pair(pair) for pair in aster_pairs}
            normalized_backpack = {normalize_pair(pair) for pair in backpack_pairs}
            
            # 找出共同的交易对
            common_normalized = normalized_aster.intersection(normalized_backpack)
            
            # 将标准化的交易对映射回原始格式
            common_pairs = set()
            for normalized_pair in common_normalized:
                # 找到对应的原始Aster交易对
                for aster_pair in aster_pairs:
                    if normalize_pair(aster_pair) == normalized_pair:
                        common_pairs.add(aster_pair)
                        break
            
            self.logger.info(f"🎯 找到 {len(common_pairs)} 个共同交易对")
            if common_pairs:
                self.logger.info(f"共同交易对: {sorted(list(common_pairs))}")
            
            return common_pairs
            
        except Exception as e:
            self.logger.error(f"获取共同交易对失败: {e}")
            return set()

    def symbol_to_coingecko_id(self, symbol: str) -> Optional[str]:
        """将交易对符号转换为CoinGecko ID"""
        # 提取基础币种
        if '_' in symbol:
            base_symbol = symbol.split('_')[0]
        else:
            base_symbol = symbol
        
        # 映射表
        symbol_mapping = {
            'BTC': 'bitcoin',
            'ETH': 'ethereum', 
            'SOL': 'solana',
            'BNB': 'binancecoin',
            'ADA': 'cardano',
            'DOT': 'polkadot',
            'LINK': 'chainlink',
            'UNI': 'uniswap',
            'AVAX': 'avalanche-2',
            'MATIC': 'matic-network',
            'ATOM': 'cosmos',
            'NEAR': 'near',
            'FTM': 'fantom',
            'ALGO': 'algorand',
            'XRP': 'ripple',
            'LTC': 'litecoin',
            'BCH': 'bitcoin-cash',
            'ETC': 'ethereum-classic',
            'XLM': 'stellar',
            'VET': 'vechain'
        }
        
        return symbol_mapping.get(base_symbol.upper())

    async def get_coingecko_data(self, coin_ids: List[str]) -> Dict:
        """从CoinGecko获取数据"""
        try:
            # 获取当前价格和基本信息
            ids_str = ','.join(coin_ids)
            url = f"{self.coingecko_base_url}/simple/price"
            params = {
                'ids': ids_str,
                'vs_currencies': 'usd',
                'include_24hr_change': 'true',
                'include_24hr_vol': 'true',
                'include_market_cap': 'true'
            }
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            return response.json()
            
        except Exception as e:
            self.logger.error(f"❌ 获取CoinGecko数据失败: {e}")
            return {}
    
    async def get_platform_kline_data(self, symbol: str, platform: str, interval: str = '1h', limit: int = 24) -> List[List]:
        """从指定平台获取K线数据"""
        try:
            if platform.lower() == 'aster':
                # 转换符号格式：BTC_USDT -> BTCUSDT (Aster API需要无下划线格式)
                aster_symbol = symbol.replace('_', '') if '_' in symbol else symbol
                self.logger.debug(f"📊 调用Aster K线API: {aster_symbol} (原始: {symbol})")
                
                # 使用Aster API获取K线数据
                result = self.aster_client.get_klines(aster_symbol, interval, limit)
                if result and isinstance(result, list):
                    self.logger.debug(f"✅ 从Aster获取到 {len(result)} 条K线数据")
                    return result
                else:
                    self.logger.warning(f"⚠️ Aster K线数据格式异常: {result}")
                    return []
                    
            elif platform.lower() == 'backpack':
                # Backpack可能没有K线接口，使用24小时统计数据
                if hasattr(self.backpack_client, 'get_klines'):
                    result = self.backpack_client.get_klines(symbol, interval, limit)
                    if result and isinstance(result, list):
                        self.logger.debug(f"✅ 从Backpack获取到 {len(result)} 条K线数据")
                        return result
                else:
                    # 如果没有K线接口，返回空列表，后续使用24小时统计数据
                    self.logger.debug(f"📊 Backpack暂不支持K线数据，将使用24小时统计")
                    return []
                    
        except Exception as e:
            self.logger.warning(f"⚠️ 从{platform}获取K线数据失败: {e}")
            
        return []

    async def get_platform_24hr_stats(self, symbol: str, platform: str) -> Dict:
        """从指定平台获取24小时统计数据"""
        try:
            if platform.lower() == 'aster':
                # 转换符号格式：BTC_USDT -> BTCUSDT (Aster API需要无下划线格式)
                aster_symbol = symbol.replace('_', '') if '_' in symbol else symbol
                self.logger.debug(f"📊 调用Aster 24小时统计API: {aster_symbol} (原始: {symbol})")
                
                # 使用Aster API获取24小时统计
                result = self.aster_client.get_24hr_ticker(aster_symbol)
                if result and isinstance(result, dict):
                    self.logger.debug(f"✅ 从Aster获取24小时统计数据")
                    return result
                    
            elif platform.lower() == 'backpack':
                # 使用Backpack API获取价格信息
                if hasattr(self.backpack_client, 'get_tickers'):
                    tickers = self.backpack_client.get_tickers()
                    if isinstance(tickers, list):
                        ticker = next((t for t in tickers if t.get('symbol') == symbol), None)
                        if ticker:
                            self.logger.debug(f"✅ 从Backpack获取价格统计数据")
                            return ticker
                            
        except Exception as e:
            self.logger.warning(f"⚠️ 从{platform}获取24小时统计失败: {e}")
            
        return {}
    
    def calculate_volatility(self, prices: List[float]) -> float:
        """计算价格波动率 (标准差)"""
        if len(prices) < 2:
            return 0.0
        
        # 计算价格变化率
        returns = []
        for i in range(1, len(prices)):
            if prices[i-1] != 0:
                returns.append((prices[i] - prices[i-1]) / prices[i-1])
        
        if not returns:
            return 0.0
        
        # 返回标准差 (波动率) 并转换为百分比
        volatility = statistics.stdev(returns) if len(returns) > 1 else 0.0
        return volatility * 100  # 转换为百分比
    
    def calculate_price_range_volatility(self, klines: List[List]) -> float:
        """基于高低价差计算波动率"""
        if not klines or len(klines) < 2:
            return 0.0
        
        volatilities = []
        for kline in klines:
            high = float(kline[2])  # 最高价
            low = float(kline[3])   # 最低价
            close = float(kline[4]) # 收盘价
            
            if close > 0:
                # 计算单根K线的波动率 (高低价差/收盘价)
                volatility = ((high - low) / close) * 100
                volatilities.append(volatility)
        
        # 返回平均波动率
        return sum(volatilities) / len(volatilities) if volatilities else 0.0
    
    async def analyze_coin_volatility(self, symbol: str, platforms: List[str] = None) -> Optional[VolatilityData]:
        """分析单个币种的波动率 - 直接使用平台数据"""
        try:
            # 提取币种名称
            base_symbol = symbol.split('_')[0] if '_' in symbol else symbol
            coin_name = base_symbol.upper()
            
            self.logger.info(f"📊 分析 {coin_name} ({symbol}) 波动率...")
            
            # 初始化数据
            current_price = 0.0
            price_change_24h = 0.0
            volume_24h = 0.0
            market_cap = 0.0
            volatility_1h = 0.0
            volatility_24h = 0.0
            volatility_7d = 0.0
            
            # 从各平台获取数据
            platform_data = {}
            for platform in (platforms or ['Aster', 'Backpack']):
                try:
                    # 获取24小时统计数据
                    stats_24hr = await self.get_platform_24hr_stats(symbol, platform)
                    if stats_24hr:
                        platform_data[platform] = stats_24hr
                        
                        # 提取价格和变化信息
                        if platform.lower() == 'aster':
                            current_price = float(stats_24hr.get('lastPrice', 0))
                            price_change_24h = float(stats_24hr.get('priceChangePercent', 0))
                            volume_24h = float(stats_24hr.get('volume', 0))
                            
                        elif platform.lower() == 'backpack':
                            current_price = float(stats_24hr.get('lastPrice', 0))
                            # Backpack可能没有24小时变化数据，使用价格差异计算
                            if 'prevClosePrice' in stats_24hr:
                                prev_price = float(stats_24hr['prevClosePrice'])
                                if prev_price > 0:
                                    price_change_24h = ((current_price - prev_price) / prev_price) * 100
                            volume_24h = float(stats_24hr.get('volume', 0))
                            
                    # 尝试获取K线数据计算波动率
                    klines_1h = await self.get_platform_kline_data(symbol, platform, '1h', 24)
                    if klines_1h and len(klines_1h) > 1:
                        # 计算1小时波动率
                        prices = [float(kline[4]) for kline in klines_1h]  # 收盘价
                        volatility_1h = max(volatility_1h, self.calculate_volatility(prices))
                        
                        # 计算价格范围波动率
                        range_volatility = self.calculate_price_range_volatility(klines_1h)
                        volatility_1h = max(volatility_1h, range_volatility)
                        
                    # 获取更长期的K线数据
                    klines_24h = await self.get_platform_kline_data(symbol, platform, '1h', 168)  # 7天
                    if klines_24h and len(klines_24h) > 1:
                        prices = [float(kline[4]) for kline in klines_24h]
                        volatility_24h = max(volatility_24h, self.calculate_volatility(prices))
                        volatility_7d = max(volatility_7d, self.calculate_volatility(prices[-168:]))
                        
                except Exception as e:
                    self.logger.warning(f"⚠️ 从{platform}获取{symbol}数据失败: {e}")
                    continue
            
            # 如果没有获取到K线数据，使用24小时价格变化作为波动率估算
            if volatility_1h == 0.0 and volatility_24h == 0.0:
                if abs(price_change_24h) > 0:
                    # 使用24小时价格变化作为波动率的粗略估算
                    volatility_24h = abs(price_change_24h)
                    volatility_1h = abs(price_change_24h) / 24  # 简单估算1小时波动率
                    volatility_7d = abs(price_change_24h) * 1.5  # 简单估算7天波动率
                    self.logger.debug(f"📊 使用价格变化估算波动率: 1h={volatility_1h:.2f}%, 24h={volatility_24h:.2f}%")
            
            # 如果仍然没有价格数据，尝试从CoinGecko获取基础信息
            if current_price == 0.0:
                coingecko_id = self.symbol_to_coingecko_id(symbol)
                if coingecko_id:
                    coingecko_data = await self.get_coingecko_data([coingecko_id])
                    coin_data = coingecko_data.get(coingecko_id, {})
                    if coin_data:
                        current_price = coin_data.get('usd', 0)
                        if price_change_24h == 0:
                            price_change_24h = coin_data.get('usd_24h_change', 0)
                        if volume_24h == 0:
                            volume_24h = coin_data.get('usd_24h_vol', 0)
                        market_cap = coin_data.get('usd_market_cap', 0)
            
            # 确保有基本数据才创建VolatilityData对象
            if current_price > 0:
                self.logger.debug(f"📊 {coin_name} 波动率: 1h={volatility_1h:.2f}%, 24h={volatility_24h:.2f}%, 7d={volatility_7d:.2f}%")
                
                return VolatilityData(
                    symbol=symbol,
                    name=coin_name,
                    current_price=current_price,
                    price_change_24h=price_change_24h,
                    price_change_percentage_24h=price_change_24h,
                    volatility_1h=volatility_1h,
                    volatility_24h=volatility_24h,
                    volatility_7d=volatility_7d,
                    volume_24h=volume_24h,
                    market_cap=market_cap,
                    platforms=platforms or ['Aster', 'Backpack']
                )
            else:
                self.logger.warning(f"⚠️ 无法获取 {symbol} 的有效价格数据")
                return None
                
        except Exception as e:
            self.logger.error(f"❌ 分析 {symbol} 波动率失败: {e}")
            return None
    
    async def analyze_all_pairs_volatility(self, limit: int = 50) -> List[VolatilityData]:
        """分析所有平台的交易对波动率，寻找高波动率币种"""
        try:
            self.logger.info(f"🎯 开始分析所有交易对波动率 (限制前{limit}个)...")
            
            # 获取两个平台的所有交易对
            aster_pairs = await self.get_aster_trading_pairs()
            backpack_pairs = await self.get_backpack_trading_pairs()
            
            # 合并所有交易对，去重
            all_pairs = aster_pairs.union(backpack_pairs)
            
            self.logger.info(f"📊 总共发现 {len(all_pairs)} 个独特交易对")
            
            # 按交易量排序，优先分析主流币种
            priority_symbols = [
                'BTC_USDT', 'ETH_USDT', 'BNB_USDT', 'ADA_USDT', 'XRP_USDT',
                'SOL_USDT', 'DOT_USDT', 'AVAX_USDT', 'MATIC_USDT', 'LINK_USDT',
                'UNI_USDT', 'LTC_USDT', 'BCH_USDT', 'ATOM_USDT', 'FIL_USDT',
                'TRX_USDT', 'ETC_USDT', 'XLM_USDT', 'VET_USDT', 'ICP_USDT'
            ]
            
            # 重新排序：优先分析主流币种
            sorted_pairs = []
            for symbol in priority_symbols:
                if symbol in all_pairs:
                    sorted_pairs.append(symbol)
            
            # 添加剩余的交易对
            remaining_pairs = [pair for pair in all_pairs if pair not in sorted_pairs]
            sorted_pairs.extend(list(remaining_pairs)[:limit-len(sorted_pairs)])
            
            volatility_results = []
            
            for i, symbol in enumerate(sorted_pairs[:limit], 1):
                try:
                    # 确定支持的平台
                    platforms = []
                    if symbol in aster_pairs:
                        platforms.append('Aster')
                    if symbol in backpack_pairs:
                        platforms.append('Backpack')
                    
                    self.logger.info(f"📊 [{i}/{min(limit, len(sorted_pairs))}] 分析 {symbol} (平台: {', '.join(platforms)})")
                    
                    # 分析波动率
                    volatility_data = await self.analyze_coin_volatility(symbol, platforms)
                    
                    if volatility_data:
                        volatility_results.append(volatility_data)
                        self.logger.info(f"✅ {symbol} 波动率评分: {volatility_data.volatility_score:.2f}")
                    else:
                        self.logger.warning(f"⚠️ 跳过 {symbol} - 数据不足")
                    
                    # 添加延迟避免API限制
                    await asyncio.sleep(0.1)
                    
                except Exception as e:
                    self.logger.error(f"❌ 分析 {symbol} 失败: {e}")
                    continue
            
            # 按波动率评分排序
            volatility_results.sort(key=lambda x: x.volatility_score, reverse=True)
            
            self.logger.info(f"🎯 完成分析，找到 {len(volatility_results)} 个有效币种")
            
            return volatility_results
            
        except Exception as e:
            self.logger.error(f"❌ 分析所有交易对波动率失败: {e}")
            return []
    
    async def analyze_common_pairs_volatility(self) -> List[VolatilityData]:
        """分析两个平台共有代币对的波动率"""
        self.logger.info("🎯 开始分析共有代币对波动率...")
        
        # 获取共同交易对
        common_pairs = await self.get_common_trading_pairs()
        if not common_pairs:
            self.logger.error("❌ 未找到共同交易对")
            return []
        
        results = []
        
        for symbol in sorted(common_pairs):
            volatility_data = await self.analyze_coin_volatility(symbol, ['Aster', 'Backpack'])
            if volatility_data:
                results.append(volatility_data)
            
            # 避免API限制，添加延迟
            await asyncio.sleep(1)
        
        # 按波动率评分排序，取前10个
        results.sort(key=lambda x: x.volatility_score, reverse=True)
        top_10_results = results[:10]
        
        self.logger.info(f"✅ 成功分析 {len(results)} 个共有代币对，选出波动最大的前 {len(top_10_results)} 个")
        
        return top_10_results

    def print_top_volatility_analysis(self, volatility_data: List[VolatilityData]):
        """打印前十个波动最大币种的分析结果"""
        if not volatility_data:
            self.logger.error("❌ 没有可分析的数据")
            return

        print("\n" + "="*90)
        print("🎯 两个平台共有代币对 - 波动最大的前十个币种")
        print("="*90)
        print(f"📅 分析时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"🔴 Aster平台 & 🟢 Backpack平台")
        print(f"📊 分析币种数量: {len(volatility_data)}")
        
        print("\n📈 波动率详细分析:")
        print("-"*90)
        
        for i, data in enumerate(volatility_data, 1):
            platforms_str = " & ".join([f"🔴 {p}" if p == "Aster" else f"🟢 {p}" for p in data.platforms])
            
            print(f"\n{i}. {data.name} ({data.symbol})")
            print(f"   🏢 支持平台: {platforms_str}")
            print(f"   💰 当前价格: ${data.current_price:,.2f}")
            print(f"   📊 24h涨跌: {data.price_change_percentage_24h:+.2f}%")
            print(f"   📈 1小时波动率: {data.volatility_1h*100:.2f}%")
            print(f"   📈 24小时波动率: {data.volatility_24h*100:.2f}%")
            print(f"   📈 7天波动率: {data.volatility_7d*100:.2f}%")
            print(f"   💎 24h成交量: ${data.volume_24h:,.0f}")
            print(f"   🏆 波动率评分: {data.volatility_score:.1f}/100")
            print(f"   ⚠️ 风险等级: {data.risk_level}")
            print(f"   💡 交易建议: {data.recommendation}")
        
        print("\n" + "="*90)
        print("🏆 波动率排名 (前十名)")
        print("="*90)
        
        for i, data in enumerate(volatility_data, 1):
            emoji = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i:2d}."
            print(f"{emoji} {data.symbol:12} - 评分: {data.volatility_score:5.1f} - {data.recommendation}")
        
        # 推荐总结
        if volatility_data:
            best_coin = volatility_data[0]
            print(f"\n🎯 最佳选择推荐:")
            print(f"   币种: {best_coin.name} ({best_coin.symbol})")
            print(f"   理由: 波动率评分最高 ({best_coin.volatility_score:.1f}/100)")
            print(f"   预期: {best_coin.recommendation}")
            print(f"   平台: 🔴 Aster & 🟢 Backpack 双平台支持")
        
        # 风险提示
        print(f"\n⚠️ 风险提示:")
        print(f"   - 高波动率意味着高收益潜力，但同时伴随高风险")
        print(f"   - 建议根据个人风险承受能力选择合适的币种")
        print(f"   - 市场瞬息万变，请结合实时行情做出决策")
        print(f"   - 两个平台的价格可能存在差异，注意套利机会")
        
        print("="*90)
    
    def save_analysis_to_file(self, volatility_data: List[VolatilityData], filename: str = None):
        """保存分析结果到文件"""
        if not filename:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"top_volatility_pairs_{timestamp}.json"
        
        try:
            # 转换为可序列化的格式
            data_dict = {
                'analysis_time': datetime.now().isoformat(),
                'description': '两个平台共有代币对 - 波动最大的前十个币种',
                'platforms': ['Aster', 'Backpack'],
                'total_analyzed': len(volatility_data),
                'coins': []
            }
            
            for i, data in enumerate(volatility_data, 1):
                coin_dict = {
                    'rank': i,
                    'symbol': data.symbol,
                    'name': data.name,
                    'platforms': data.platforms,
                    'current_price': data.current_price,
                    'price_change_24h': data.price_change_24h,
                    'price_change_percentage_24h': data.price_change_percentage_24h,
                    'volatility_1h': data.volatility_1h,
                    'volatility_24h': data.volatility_24h,
                    'volatility_7d': data.volatility_7d,
                    'volume_24h': data.volume_24h,
                    'market_cap': data.market_cap,
                    'volatility_score': data.volatility_score,
                    'risk_level': data.risk_level,
                    'recommendation': data.recommendation
                }
                data_dict['coins'].append(coin_dict)
            
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(data_dict, f, indent=2, ensure_ascii=False)
            
            self.logger.info(f"✅ 分析结果已保存到: {filename}")
            
        except Exception as e:
            self.logger.error(f"❌ 保存文件失败: {e}")

async def run_volatility_analysis():
    """运行波动率分析 - 先获取共同币种，再计算波动率"""
    analyzer = CryptoVolatilityAnalyzer()
    
    try:
        # 第一步：获取两个平台的共同币种
        analyzer.logger.info("🔍 正在获取Aster和Backpack平台的共同币种...")
        common_pairs = await analyzer.get_common_trading_pairs()
        
        if not common_pairs:
            analyzer.logger.error("❌ 未找到共同的交易对")
            return None
        
        analyzer.logger.info(f"✅ 找到 {len(common_pairs)} 个共同交易对: {', '.join(sorted(common_pairs))}")
        
        # 第二步：针对共同币种计算波动率
        analyzer.logger.info("📊 开始分析共同币种的波动率...")
        volatility_data = await analyzer.analyze_common_pairs_volatility()
        
        if not volatility_data:
            analyzer.logger.error("❌ 未能获取到有效的波动率数据")
            return None
        
        # 按波动率评分排序，显示前10个
        volatility_data = sorted(volatility_data, key=lambda x: x.volatility_score, reverse=True)[:10]
        
        # 打印分析结果
        analyzer.print_top_volatility_analysis(volatility_data)
        
        # 保存到文件
        filename = f"common_pairs_volatility_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        analyzer.save_analysis_to_file(volatility_data, filename)
        
        # 返回推荐的币种
        if volatility_data:
            best_coin = volatility_data[0]
            return f"{best_coin.name} ({best_coin.symbol}) - 评分: {best_coin.volatility_score:.1f}"
        
        return None
        
    except Exception as e:
        analyzer.logger.error(f"❌ 运行分析异常: {e}")
        return None

if __name__ == "__main__":
    print("🎯 共同币种波动率分析工具")
    print("🔴 Aster平台 & 🟢 Backpack平台")
    print("📊 先获取共同币种，再分析波动率")
    print("-" * 50)
    
    try:
        print("📊 开始分析...")
        recommended_coin = asyncio.run(run_volatility_analysis())

        if recommended_coin:
            print(f"\n🎯 最终推荐: {recommended_coin}")
            print("💡 建议用于套利交易策略")
        else:
            print("\n❌ 分析未能完成")
            
    except KeyboardInterrupt:
        print("\n⚠️ 用户中断")
    except Exception as e:
        print(f"❌ 启动异常: {e}")