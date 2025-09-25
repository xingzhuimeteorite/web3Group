#!/usr/bin/env python3
"""
Aster Finance 公开API测试脚本
测试不需要API密钥的公开接口
"""

import sys
import json
from datetime import datetime
from .aster_api_client import AsterFinanceClient


def print_separator(title: str):
    """打印分隔符"""
    print("\n" + "="*50)
    print(f" {title}")
    print("="*50)


def test_ping(client: AsterFinanceClient):
    """测试服务器连通性"""
    print_separator("测试服务器连通性")
    try:
        result = client.ping()
        print("✅ 服务器连通性测试成功")
        print(f"响应: {result}")
    except Exception as e:
        print(f"❌ 服务器连通性测试失败: {e}")


def test_server_time(client: AsterFinanceClient):
    """测试获取服务器时间"""
    print_separator("获取服务器时间")
    try:
        result = client.get_server_time()
        server_time = result.get('serverTime', 0)
        readable_time = datetime.fromtimestamp(server_time / 1000).strftime('%Y-%m-%d %H:%M:%S')
        
        print("✅ 获取服务器时间成功")
        print(f"服务器时间戳: {server_time}")
        print(f"可读时间: {readable_time}")
    except Exception as e:
        print(f"❌ 获取服务器时间失败: {e}")


def test_exchange_info(client: AsterFinanceClient):
    """测试获取交易规则和交易对信息"""
    print_separator("获取交易规则和交易对信息")
    try:
        result = client.get_exchange_info()
        
        print("✅ 获取交易规则成功")
        print(f"时区: {result.get('timezone', 'N/A')}")
        print(f"服务器时间: {result.get('serverTime', 'N/A')}")
        
        symbols = result.get('symbols', [])
        print(f"交易对数量: {len(symbols)}")
        
        # 显示前5个交易对的信息
        if symbols:
            print("\n前5个交易对:")
            for i, symbol in enumerate(symbols[:5]):
                print(f"  {i+1}. {symbol.get('symbol', 'N/A')} - 状态: {symbol.get('status', 'N/A')}")
                
    except Exception as e:
        print(f"❌ 获取交易规则失败: {e}")


def test_ticker_price(client: AsterFinanceClient):
    """测试获取最新价格"""
    print_separator("获取最新价格")
    try:
        # 获取所有交易对价格
        result = client.get_ticker_price()
        
        if isinstance(result, list):
            print(f"✅ 获取价格成功，共 {len(result)} 个交易对")
            
            # 显示前10个交易对的价格
            print("\n前10个交易对价格:")
            for i, ticker in enumerate(result[:10]):
                symbol = ticker.get('symbol', 'N/A')
                price = ticker.get('price', 'N/A')
                print(f"  {i+1}. {symbol}: {price}")
        else:
            print("✅ 获取价格成功")
            print(f"响应: {result}")
            
    except Exception as e:
        print(f"❌ 获取价格失败: {e}")


def test_24hr_ticker(client: AsterFinanceClient):
    """测试获取24小时价格变动"""
    print_separator("获取24小时价格变动")
    try:
        # 获取所有交易对的24小时统计
        result = client.get_24hr_ticker()
        
        if isinstance(result, list):
            print(f"✅ 获取24小时统计成功，共 {len(result)} 个交易对")
            
            # 显示前5个交易对的统计
            print("\n前5个交易对24小时统计:")
            for i, ticker in enumerate(result[:5]):
                symbol = ticker.get('symbol', 'N/A')
                price_change = ticker.get('priceChange', 'N/A')
                price_change_percent = ticker.get('priceChangePercent', 'N/A')
                volume = ticker.get('volume', 'N/A')
                print(f"  {i+1}. {symbol}:")
                print(f"     价格变动: {price_change} ({price_change_percent}%)")
                print(f"     成交量: {volume}")
        else:
            print("✅ 获取24小时统计成功")
            print(f"响应: {result}")
            
    except Exception as e:
        print(f"❌ 获取24小时统计失败: {e}")


def main():
    """主函数"""
    print("Aster Finance 公开API测试")
    print("此测试不需要API密钥")
    
    # 创建客户端（不需要API密钥）
    client = AsterFinanceClient()
    
    # 运行测试
    test_ping(client)
    test_server_time(client)
    test_exchange_info(client)
    test_ticker_price(client)
    test_24hr_ticker(client)
    
    print_separator("测试完成")
    print("所有公开API测试已完成")


if __name__ == "__main__":
    main()