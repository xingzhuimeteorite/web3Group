#!/usr/bin/env python3
"""
API连接测试工具
用于验证Aster和Backpack两个平台的API是否正常工作
"""

import asyncio
import sys
import os
import json
import logging
from typing import Optional, Dict, Any

# 添加项目路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from aster.aster_api_client import AsterFinanceClient
from aster.config_loader import ConfigLoader as AsterConfigLoader
from backpack.trade import SOLStopLossStrategy
from backpack.config_loader import ConfigLoader as BackpackConfigLoader

class APITester:
    """API测试器"""
    
    def __init__(self):
        self.logger = self._setup_logging()
        self.aster_client = None
        self.backpack_client = None
        self.test_results = {
            'aster': {'connected': False, 'tests': {}},
            'backpack': {'connected': False, 'tests': {}}
        }
    
    def _setup_logging(self):
        """设置日志"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.StreamHandler(sys.stdout)
            ]
        )
        return logging.getLogger(__name__)
    
    async def initialize_clients(self):
        """初始化API客户端"""
        self.logger.info("🚀 开始初始化API客户端...")
        
        # 初始化Aster客户端
        await self._init_aster_client()
        
        # 初始化Backpack客户端
        await self._init_backpack_client()
    
    async def _init_aster_client(self):
        """初始化Aster客户端"""
        try:
            self.logger.info("📡 初始化Aster API客户端...")
            
            # 检查配置文件
            config_path = "aster/config.json"
            if not os.path.exists(config_path):
                self.logger.warning(f"⚠️ Aster配置文件不存在: {config_path}")
                self.logger.info("💡 请复制 aster/config.json copy.template 为 aster/config.json 并填入正确的API密钥")
                return
            
            # 加载配置
            config_loader = AsterConfigLoader(config_path)
            
            if not config_loader.is_configured():
                self.logger.warning("⚠️ Aster API密钥未配置")
                return
            
            # 获取API凭证
            credentials = config_loader.get_api_credentials()
            
            # 创建客户端
            self.aster_client = AsterFinanceClient(
                api_key=credentials['api_key'],
                secret_key=credentials['secret_key'],
                base_url=credentials['base_url']
            )
            
            self.test_results['aster']['connected'] = True
            self.logger.info("✅ Aster客户端初始化成功")
            
        except Exception as e:
            self.logger.error(f"❌ Aster客户端初始化失败: {e}")
    
    async def _init_backpack_client(self):
        """初始化Backpack客户端"""
        try:
            self.logger.info("📡 初始化Backpack API客户端...")
            
            # 检查配置文件
            config_path = "backpack/config.json"
            if not os.path.exists(config_path):
                self.logger.warning(f"⚠️ Backpack配置文件不存在: {config_path}")
                self.logger.info("💡 请复制 backpack/config.json.template 为 backpack/config.json 并填入正确的API密钥")
                return
            
            # 创建Backpack策略实例（包含API客户端）
            self.backpack_client = SOLStopLossStrategy(config_path=config_path)
            
            # 检查是否有有效的客户端
            if hasattr(self.backpack_client, 'public_client') and self.backpack_client.public_client:
                self.test_results['backpack']['connected'] = True
                self.logger.info("✅ Backpack客户端初始化成功")
            else:
                self.logger.warning("⚠️ Backpack客户端初始化但可能配置不完整")
            
        except Exception as e:
            self.logger.error(f"❌ Backpack客户端初始化失败: {e}")
    
    async def test_aster_api(self):
        """测试Aster API功能"""
        if not self.aster_client:
            self.logger.warning("⚠️ Aster客户端未初始化，跳过测试")
            return
        
        self.logger.info("🧪 开始测试Aster API...")
        
        # 测试1: 获取账户信息
        await self._test_aster_account_info()
        
        # 测试2: 获取价格信息
        await self._test_aster_price_info()
        
        # 测试3: 获取24小时行情
        await self._test_aster_ticker_info()
    
    async def _test_aster_account_info(self):
        """测试Aster账户信息"""
        try:
            self.logger.info("  📊 测试获取账户信息...")
            account_info = self.aster_client.get_account_info()
            
            if account_info:
                self.logger.info("  ✅ 账户信息获取成功")
                self.test_results['aster']['tests']['account_info'] = True
                
                # 显示余额信息
                if 'balances' in account_info:
                    self.logger.info("  💰 账户余额:")
                    for balance in account_info['balances'][:5]:  # 只显示前5个
                        asset = balance.get('asset', 'Unknown')
                        free = balance.get('free', '0')
                        locked = balance.get('locked', '0')
                        if float(free) > 0 or float(locked) > 0:
                            self.logger.info(f"    {asset}: 可用={free}, 冻结={locked}")
            else:
                self.logger.warning("  ⚠️ 账户信息为空")
                self.test_results['aster']['tests']['account_info'] = False
                
        except Exception as e:
            self.logger.error(f"  ❌ 获取账户信息失败: {e}")
            self.test_results['aster']['tests']['account_info'] = False
    
    async def _test_aster_price_info(self):
        """测试Aster价格信息"""
        try:
            self.logger.info("  💹 测试获取价格信息...")
            
            # 测试获取SOL价格
            price = await self.aster_client.get_current_price("SOLUSDT")
            
            if price and price > 0:
                self.logger.info(f"  ✅ SOL价格获取成功: ${price:.2f}")
                self.test_results['aster']['tests']['price_info'] = True
            else:
                self.logger.warning("  ⚠️ 价格信息无效")
                self.test_results['aster']['tests']['price_info'] = False
                
        except Exception as e:
            self.logger.error(f"  ❌ 获取价格信息失败: {e}")
            self.test_results['aster']['tests']['price_info'] = False
    
    async def _test_aster_ticker_info(self):
        """测试Aster行情信息"""
        try:
            self.logger.info("  📈 测试获取24小时行情...")
            
            ticker = self.aster_client.get_24hr_ticker("SOLUSDT")
            
            if ticker:
                self.logger.info("  ✅ 24小时行情获取成功")
                self.test_results['aster']['tests']['ticker_info'] = True
                
                # 显示关键信息
                if isinstance(ticker, dict):
                    price = ticker.get('lastPrice', 'N/A')
                    change = ticker.get('priceChangePercent', 'N/A')
                    volume = ticker.get('volume', 'N/A')
                    self.logger.info(f"    价格: {price}, 涨跌幅: {change}%, 成交量: {volume}")
            else:
                self.logger.warning("  ⚠️ 行情信息为空")
                self.test_results['aster']['tests']['ticker_info'] = False
                
        except Exception as e:
            self.logger.error(f"  ❌ 获取行情信息失败: {e}")
            self.test_results['aster']['tests']['ticker_info'] = False
    
    async def test_backpack_api(self):
        """测试Backpack API功能"""
        if not self.backpack_client:
            self.logger.warning("⚠️ Backpack客户端未初始化，跳过测试")
            return
        
        self.logger.info("🧪 开始测试Backpack API...")
        
        # 测试1: 获取价格信息
        await self._test_backpack_price_info()
        
        # 测试2: 获取市场信息
        await self._test_backpack_market_info()
    
    async def _test_backpack_price_info(self):
        """测试Backpack价格信息"""
        try:
            self.logger.info("  💹 测试获取价格信息...")
            
            # 使用SOLStopLossStrategy的get_current_price方法
            price = await self.backpack_client.get_current_price("SOL_USDC")
            
            if price and price > 0:
                self.logger.info(f"  ✅ SOL价格获取成功: ${price:.2f}")
                self.test_results['backpack']['tests']['price_info'] = True
            else:
                self.logger.warning("  ⚠️ 价格信息无效")
                self.test_results['backpack']['tests']['price_info'] = False
                
        except Exception as e:
            self.logger.error(f"  ❌ 获取价格信息失败: {e}")
            self.test_results['backpack']['tests']['price_info'] = False
    
    async def _test_backpack_market_info(self):
        """测试Backpack市场信息"""
        try:
            self.logger.info("  📊 测试获取市场信息...")
            
            if hasattr(self.backpack_client, 'public_client') and self.backpack_client.public_client:
                # 获取所有ticker信息
                tickers = self.backpack_client.public_client.get_tickers()
                
                if tickers and len(tickers) > 0:
                    self.logger.info(f"  ✅ 市场信息获取成功，共{len(tickers)}个交易对")
                    self.test_results['backpack']['tests']['market_info'] = True
                    
                    # 显示SOL相关的交易对
                    sol_pairs = [t for t in tickers if 'SOL' in t.get('symbol', '')][:3]
                    if sol_pairs:
                        self.logger.info("  📈 SOL相关交易对:")
                        for ticker in sol_pairs:
                            symbol = ticker.get('symbol', 'Unknown')
                            price = ticker.get('lastPrice', 'N/A')
                            self.logger.info(f"    {symbol}: {price}")
                else:
                    self.logger.warning("  ⚠️ 市场信息为空")
                    self.test_results['backpack']['tests']['market_info'] = False
            else:
                self.logger.warning("  ⚠️ Backpack公共客户端不可用")
                self.test_results['backpack']['tests']['market_info'] = False
                
        except Exception as e:
            self.logger.error(f"  ❌ 获取市场信息失败: {e}")
            self.test_results['backpack']['tests']['market_info'] = False
    
    def print_test_summary(self):
        """打印测试结果摘要"""
        self.logger.info("\n" + "="*60)
        self.logger.info("📋 API测试结果摘要")
        self.logger.info("="*60)
        
        # Aster结果
        aster_status = "✅ 连接成功" if self.test_results['aster']['connected'] else "❌ 连接失败"
        self.logger.info(f"🔸 Aster API: {aster_status}")
        
        if self.test_results['aster']['connected']:
            for test_name, result in self.test_results['aster']['tests'].items():
                status = "✅ 通过" if result else "❌ 失败"
                self.logger.info(f"  - {test_name}: {status}")
        
        # Backpack结果
        backpack_status = "✅ 连接成功" if self.test_results['backpack']['connected'] else "❌ 连接失败"
        self.logger.info(f"🔸 Backpack API: {backpack_status}")
        
        if self.test_results['backpack']['connected']:
            for test_name, result in self.test_results['backpack']['tests'].items():
                status = "✅ 通过" if result else "❌ 失败"
                self.logger.info(f"  - {test_name}: {status}")
        
        # 总体状态
        aster_ok = self.test_results['aster']['connected'] and all(self.test_results['aster']['tests'].values())
        backpack_ok = self.test_results['backpack']['connected'] and all(self.test_results['backpack']['tests'].values())
        
        self.logger.info("\n" + "="*60)
        if aster_ok and backpack_ok:
            self.logger.info("🎉 所有API测试通过！可以进行真实交易")
        elif aster_ok or backpack_ok:
            self.logger.info("⚠️ 部分API可用，建议检查配置后再进行交易")
        else:
            self.logger.info("❌ 所有API测试失败，请检查配置文件和网络连接")
        self.logger.info("="*60)

async def main():
    """主函数"""
    print("🧪 API连接测试工具")
    print("=" * 50)
    
    tester = APITester()
    
    try:
        # 初始化客户端
        await tester.initialize_clients()
        
        # 测试Aster API
        await tester.test_aster_api()
        
        # 测试Backpack API
        await tester.test_backpack_api()
        
        # 打印测试摘要
        tester.print_test_summary()
        
    except KeyboardInterrupt:
        print("\n⚠️ 用户中断测试")
    except Exception as e:
        print(f"❌ 测试过程中发生错误: {e}")

if __name__ == "__main__":
    asyncio.run(main())