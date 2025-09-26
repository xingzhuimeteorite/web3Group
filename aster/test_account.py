#!/usr/bin/env python3
"""
账户连接测试脚本
检查API密钥配置和账户权限
"""

import json
import os
from aster_api_client import AsterFinanceClient
from config_loader import ConfigLoader

def test_account_connection():
    """测试账户连接和权限"""
    print("=" * 50)
    print(" 🔐 账户连接测试")
    print("=" * 50)
    
    # 检查配置文件
    config_path = "config.json"
    if not os.path.exists(config_path):
        print("❌ 配置文件 config.json 不存在")
        print("📝 请复制 config.json copy.template 为 config.json 并填入您的API密钥")
        print("\n步骤:")
        print("1. cp 'config.json copy.template' config.json")
        print("2. 编辑 config.json，填入您的 api_key 和 secret_key")
        return False
    
    try:
        # 加载配置
        config_loader = ConfigLoader(config_path)
        config = config_loader.config
        
        # 检查API密钥是否已配置
        if config['api_key'] == 'your_api_key_here' or config['secret_key'] == 'your_secret_key_here':
            print("❌ API密钥未配置")
            print("📝 请在 config.json 中填入您的真实API密钥")
            return False
        
        # 创建客户端
        client = AsterFinanceClient(
            api_key=config['api_key'],
            secret_key=config['secret_key'],
            base_url=config['base_url']
        )
        
        print(f"✅ 配置文件加载成功")
        print(f"📡 API地址: {config['base_url']}")
        print(f"🔑 API密钥: {config['api_key'][:8]}...")
        
        # 测试账户信息
        print("\n" + "=" * 50)
        print(" 📊 获取账户信息")
        print("=" * 50)
        
        account_info = client.get_account_info()
        
        if 'code' in account_info and account_info['code'] != 200:
            print(f"❌ 获取账户信息失败: {account_info.get('msg', '未知错误')}")
            return False
        
        print("✅ 账户信息获取成功")
        
        # 显示账户基本信息
        if 'totalWalletBalance' in account_info:
            total_balance = float(account_info['totalWalletBalance'])
            available_balance = float(account_info['availableBalance'])
            total_unrealized_pnl = float(account_info.get('totalUnrealizedPnL', 0))
            
            print(f"💰 总钱包余额: {total_balance:.4f} USDT")
            print(f"💵 可用余额: {available_balance:.4f} USDT")
            print(f"📈 未实现盈亏: {total_unrealized_pnl:.4f} USDT")
            
            # 检查余额是否足够进行网格交易
            if available_balance >= 100:
                print("✅ 账户余额充足，可以进行网格交易")
                
                # 推荐配置
                if available_balance >= 500:
                    print("💡 推荐配置: 500 USDT + 2倍杠杆")
                elif available_balance >= 300:
                    print("💡 推荐配置: 300 USDT + 2倍杠杆")
                elif available_balance >= 200:
                    print("💡 推荐配置: 200 USDT + 1-2倍杠杆")
                else:
                    print("💡 推荐配置: 100 USDT + 1倍杠杆")
            else:
                print("⚠️  账户余额较少，建议至少100 USDT进行网格交易")
        
        # 测试持仓信息
        print("\n" + "=" * 50)
        print(" 📋 获取持仓信息")
        print("=" * 50)
        
        positions = client.get_position_risk()
        
        if isinstance(positions, list):
            active_positions = [pos for pos in positions if float(pos.get('positionAmt', 0)) != 0]
            
            print(f"✅ 持仓信息获取成功")
            print(f"📊 总持仓数: {len(positions)}")
            print(f"🔥 活跃持仓: {len(active_positions)}")
            
            if active_positions:
                print("\n活跃持仓:")
                for pos in active_positions[:5]:  # 显示前5个
                    symbol = pos['symbol']
                    size = float(pos['positionAmt'])
                    entry_price = float(pos['entryPrice'])
                    unrealized_pnl = float(pos['unRealizedProfit'])
                    
                    print(f"  {symbol}: {size:.4f} @ {entry_price:.4f} (PnL: {unrealized_pnl:.4f})")
        
        print("\n" + "=" * 50)
        print(" ✅ 账户测试完成")
        print("=" * 50)
        print("🎉 您的账户已准备就绪，可以运行SOL网格交易机器人！")
        
        return True
        
    except FileNotFoundError:
        print("❌ 配置文件未找到")
        return False
    except json.JSONDecodeError:
        print("❌ 配置文件格式错误")
        return False
    except Exception as e:
        print(f"❌ 连接测试失败: {str(e)}")
        return False

def main():
    """主函数"""
    print("🤖 SOL网格交易机器人 - 账户连接测试")
    print("=" * 50)
    
    success = test_account_connection()
    
    if success:
        print("\n🚀 下一步: 运行 python sol_grid_launcher.py 开始网格交易")
    else:
        print("\n🔧 请先解决上述问题，然后重新运行此测试")

if __name__ == "__main__":
    main()