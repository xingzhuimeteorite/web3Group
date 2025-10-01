#!/usr/bin/env python3
"""
快速平仓测试脚本 - 测试修改后的平台标注格式
"""

import asyncio
import sys
import os

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from trade_2 import RealDynamicHedgeStrategy

async def test_quick_close():
    """测试快速平仓功能"""
    print("🧪 快速平仓测试 - 验证平台标注格式")
    
    # 创建策略实例，使用极小的阈值快速触发平仓
    strategy = RealDynamicHedgeStrategy(
        stop_loss_threshold=0.0001,  # 0.01% 止损 (极易触发)
        profit_target_rate=0.0005,   # 0.05% 盈利目标 (极易达到)
        position_size_usdt=25.0,     # 较小仓位
        monitoring_interval=0.5      # 0.5秒监控间隔
    )
    
    try:
        # 执行单轮对冲交易
        success = await strategy.execute_real_dynamic_hedge("SOL", 25.0)
        
        if success:
            print("✅ 测试完成，检查最终结果的平台标注格式")
        else:
            print("❌ 测试失败")
            
    except KeyboardInterrupt:
        print("\n⚠️ 用户中断测试")
        await strategy.stop_strategy()
    except Exception as e:
        print(f"❌ 测试异常: {e}")
        await strategy.stop_strategy()

if __name__ == "__main__":
    asyncio.run(test_quick_close())
"""
快速验证平仓逻辑测试脚本
使用极小参数快速触发平仓条件
"""

import asyncio
import sys
import os

# 添加项目路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from trade_2 import RealDynamicHedgeStrategy

async def quick_close_test():
    """快速平仓逻辑测试"""
    print("🚀 快速平仓逻辑验证测试")
    print("=" * 50)
    
    # 使用极小参数，确保快速触发
    strategy = RealDynamicHedgeStrategy(
        stop_loss_threshold=0.0001,    # 0.01% - 极小止损
        profit_target_rate=0.0005,     # 0.05% - 极小盈利目标
        position_size_usdt=25.0,       # 较小仓位
        monitoring_interval=0.5        # 0.5秒监控
    )
    
    print(f"📊 测试参数:")
    print(f"   止损阈值: {strategy.stop_loss_threshold*100:.3f}%")
    print(f"   盈利目标: {strategy.profit_target_rate*100:.3f}%")
    print(f"   仓位大小: ${strategy.position_size_usdt}")
    print(f"   监控间隔: {strategy.monitoring_interval}秒")
    print()
    
    try:
        # 执行单轮对冲交易
        print("🎯 开始执行对冲交易...")
        success = await strategy.execute_real_dynamic_hedge("SOL-USDT", strategy.position_size_usdt)
        
        if success:
            print("✅ 对冲交易执行成功，开始监控...")
            # 监控直到平仓
            await strategy._monitor_and_close_real_positions("SOL-USDT")
        else:
            print("❌ 对冲交易执行失败")
            
    except KeyboardInterrupt:
        print("\n⚠️ 用户中断测试")
        await strategy.stop_strategy()
    except Exception as e:
        print(f"❌ 测试异常: {e}")
        await strategy.stop_strategy()
    finally:
        print("\n📊 最终结果:")
        strategy.print_final_results()

if __name__ == "__main__":
    print("⚡ 快速平仓逻辑验证")
    print("使用极小参数(0.01%止损, 0.05%盈利)快速触发平仓")
    print("按Ctrl+C可随时停止")
    print()
    
    asyncio.run(quick_close_test())