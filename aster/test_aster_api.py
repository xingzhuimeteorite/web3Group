#!/usr/bin/env python3
"""
Aster Finance API 完整测试脚本
包含公开API和私有API测试
"""

import sys
import json
from datetime import datetime
from .aster_api_client import AsterFinanceClient
from .config_loader import ConfigLoader


def print_separator(title: str):
    """打印分隔符"""
    print("\n" + "="*60)
    print(f" {title}")
    print("="*60)


def test_public_apis(client: AsterFinanceClient):
    """测试公开API"""
    print_separator("公开API测试")
    
    # 测试连通性
    try:
        print("1. 测试服务器连通性...")
        result = client.ping()
        print("   ✅ 连通性测试成功")
    except Exception as e:
        print(f"   ❌ 连通性测试失败: {e}")
    
    # 测试服务器时间
    try:
        print("2. 获取服务器时间...")
        result = client.get_server_time()
        server_time = result.get('serverTime', 0)
        readable_time = datetime.fromtimestamp(server_time / 1000).strftime('%Y-%m-%d %H:%M:%S')
        print(f"   ✅ 服务器时间: {readable_time}")
    except Exception as e:
        print(f"   ❌ 获取服务器时间失败: {e}")
    
    # 测试交易规则
    try:
        print("3. 获取交易规则...")
        result = client.get_exchange_info()
        symbols = result.get('symbols', [])
        print(f"   ✅ 获取成功，共 {len(symbols)} 个交易对")
        
        # 找到BTCUSDT交易对
        btc_symbol = None
        for symbol in symbols:
            if symbol.get('symbol') == 'BTCUSDT':
                btc_symbol = symbol
                break
        
        if btc_symbol:
            print(f"   📊 BTCUSDT状态: {btc_symbol.get('status', 'N/A')}")
        
    except Exception as e:
        print(f"   ❌ 获取交易规则失败: {e}")
    
    # 测试价格信息
    try:
        print("4. 获取价格信息...")
        result = client.get_ticker_price("BTCUSDT")
        if isinstance(result, dict):
            price = result.get('price', 'N/A')
            print(f"   ✅ BTCUSDT当前价格: {price}")
        else:
            print("   ✅ 获取价格成功")
    except Exception as e:
        print(f"   ❌ 获取价格失败: {e}")


def test_private_apis(client: AsterFinanceClient):
    """测试私有API（需要API密钥）"""
    print_separator("私有API测试")
    
    # 测试账户信息
    try:
        print("1. 获取账户信息...")
        result = client.get_account_info()
        
        total_wallet_balance = result.get('totalWalletBalance', 'N/A')
        total_unrealized_pnl = result.get('totalUnrealizedPnL', 'N/A')
        
        print(f"   ✅ 账户信息获取成功")
        print(f"   💰 钱包总余额: {total_wallet_balance}")
        print(f"   📈 未实现盈亏: {total_unrealized_pnl}")
        
        # 显示资产信息
        assets = result.get('assets', [])
        if assets:
            print("   💼 资产详情:")
            for asset in assets[:5]:  # 只显示前5个
                asset_name = asset.get('asset', 'N/A')
                wallet_balance = asset.get('walletBalance', 'N/A')
                unrealized_pnl = asset.get('unrealizedPnL', 'N/A')
                if float(wallet_balance) > 0:
                    print(f"      {asset_name}: 余额={wallet_balance}, 未实现盈亏={unrealized_pnl}")
        
    except Exception as e:
        print(f"   ❌ 获取账户信息失败: {e}")
        if "API-key format invalid" in str(e):
            print("   💡 提示: 请检查API密钥格式是否正确")
        elif "Signature for this request is not valid" in str(e):
            print("   💡 提示: 请检查密钥签名是否正确")
    
    # 测试持仓信息
    try:
        print("2. 获取持仓信息...")
        result = client.get_position_risk()
        
        print(f"   ✅ 持仓信息获取成功")
        
        # 显示有持仓的交易对
        active_positions = [pos for pos in result if float(pos.get('positionAmt', 0)) != 0]
        
        if active_positions:
            print(f"   📊 当前持仓 ({len(active_positions)} 个):")
            for pos in active_positions:
                symbol = pos.get('symbol', 'N/A')
                position_amt = pos.get('positionAmt', 'N/A')
                unrealized_pnl = pos.get('unRealizedProfit', 'N/A')
                print(f"      {symbol}: 数量={position_amt}, 未实现盈亏={unrealized_pnl}")
        else:
            print("   📊 当前无持仓")
            
    except Exception as e:
        print(f"   ❌ 获取持仓信息失败: {e}")


def main():
    """主函数"""
    print("🚀 Aster Finance API 测试脚本")
    print("基于官方文档: https://github.com/asterdex/api-docs/blob/master/aster-finance-futures-api_CN.md")
    
    # 加载配置
    config = ConfigLoader()
    
    print_separator("配置检查")
    
    if config.is_configured():
        print("✅ 检测到API配置")
        credentials = config.get_api_credentials()
        client = AsterFinanceClient(**credentials)
        
        # 运行所有测试
        test_public_apis(client)
        test_private_apis(client)
        
    else:
        print("⚠️  未检测到有效的API配置")
        print("📝 将只运行公开API测试")
        print("\n如需测试私有API，请:")
        print("1. 复制 config.json.template 为 config.json")
        print("2. 在 config.json 中填入您的API密钥")
        
        # 只运行公开API测试
        client = AsterFinanceClient()
        test_public_apis(client)
    
    print_separator("测试完成")
    print("🎉 所有测试已完成!")
    
    if not config.is_configured():
        print("\n💡 提示:")
        print("- 公开API测试不需要API密钥")
        print("- 私有API测试需要有效的API密钥")
        print("- 请在Aster Finance官网申请API密钥后再测试私有API")


if __name__ == "__main__":
    main()