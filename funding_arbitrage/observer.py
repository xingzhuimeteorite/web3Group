import json
import os
import sys
import time
from datetime import datetime

# 将项目根目录添加到 Python 路径中，以便导入其他模块
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = current_dir  # 将 project_root 指向 funding_arbitrage 目录
sys.path.insert(0, os.path.abspath(os.path.join(current_dir, '..')))

from funding_arbitrage.strategy.monitor import fetch_funding_info, get_perp_symbol
from funding_arbitrage.accounting.pnl import calculate_breakeven_days, get_round_trip_cost_rate
from funding_arbitrage.utils.logger import setup_logger
from funding_arbitrage.utils.recorder import CsvRecorder
from funding_arbitrage.utils.config_loader import load_config
from funding_arbitrage.utils.exchange_loader import get_exchange_from_config


def main():
    """
    主函数，执行资金费套利机会的观察和分析。
    """
    # 构造配置文件的绝对路径
    config, config_path = load_config()

    # 设置日志记录器
    logger = setup_logger(project_root)

    # 初始化CSV记录器
    csv_header = ['timestamp', 'symbol', 'funding_rate', 'daily_funding_rate', 'round_trip_cost_rate', 'breakeven_days', 'signal']
    recorder = CsvRecorder(project_root, 'funding_opportunities.csv', csv_header)

    logger.info("观察者模式启动。")

    # 获取监控时间间隔
    monitor_config = config.get('monitor', {})
    interval_sec = monitor_config.get('intervalSec', 600)

    # 从配置中获取网络设置
    network_config = config.get('network', {})
    proxies = network_config.get('proxies')
    timeout_sec = network_config.get('timeout_sec', 20)

    # 1. 初始化交易所 (一次性)
    try:
        logger.info("正在初始化交易所...")
        perp_exchange = get_exchange_from_config(config)
        if not perp_exchange:
            sys.exit(1) # 如果交易所初始化失败，则退出

        # 同样的方式可以用于现货交易所，如果需要的话
        # spot_exchange = get_exchange_from_config(config, 'spot') 

        logger.info("交易所初始化成功。")

    except Exception as e:
        logger.error(f"交易所初始化失败: {e}")
        sys.exit(1)

    # 2. 测试连接并获取余额 (一次性)
    try:
        logger.info("正在获取账户余额...")
        # spot_balance = spot_exchange.fetch_balance()
        perp_balance = perp_exchange.fetch_balance()
        
        # spot_usdt = spot_balance['total'].get('USDT', 0)
        perp_usdt = perp_balance['total'].get('USDT', 0)

        # logger.info(f"  - 现货账户 USDT 余额: {spot_usdt}")
        logger.info(f"  - 永续账户 USDT 余额: {perp_usdt}")

        logger.info("账户余额获取成功。")

    except Exception as e:
        logger.error(f"获取余额失败: {e}")
        logger.error("请检查您的 API 密钥权限、网络连接和代理设置。")
        sys.exit(1)

    while True:
        try:
            # 2.5. 获取交易所手续费率
            trading_fees = None
            try:
                if perp_exchange.has.get('fetchTradingFees'):
                    trading_fees = perp_exchange.fetch_trading_fees()
                    logger.info("已成功从交易所动态获取手续费率。")
                else:
                    logger.warning(f"交易所 '{perp_exchange.id}' 不支持动态获取手续费率，将使用配置文件中的静态费率。")
            except Exception as e:
                logger.error(f"获取手续费率时出错，将回退到静态费率: {e}")

            # 3. 遍历所有配置的交易对，获取资金费率并进行分析
            for symbol_to_check in config['symbols']:
                logger.info(f"\n正在为交易对 {symbol_to_check} 分析资金费套利机会...")
                funding_info = fetch_funding_info(perp_exchange, symbol_to_check)

                if funding_info:
                    logger.info(f"  - 当前资金费率: {funding_info['funding_rate']:.6f}")
                    logger.info(f"  - 估算日化费率: {funding_info['daily_funding_rate']:.6f}")
                    
                    # 初始化信号和回本天数，以确保在任何情况下都存在
                    signal_text = "数据不足"
                    breakeven_days = float('inf')
                    
                    # 4. 计算成本和盈亏平衡点
                    try:
                        costs = config.get('costs', {})
                        specific_fee_info = trading_fees.get(symbol_to_check) if trading_fees else None

                        if specific_fee_info:
                            logger.info(f"  - 动态获取的 {symbol_to_check} 手续费率: Taker={specific_fee_info['taker']:.4f}, Maker={specific_fee_info['maker']:.4f}")

                        round_trip_cost_rate = get_round_trip_cost_rate(costs, specific_fee_info)
                        logger.info(f"  - 预估往返成本率: {round_trip_cost_rate:.4%}")

                        daily_funding_rate = funding_info['daily_funding_rate']
                        if daily_funding_rate > 0:
                            breakeven_days = round_trip_cost_rate / daily_funding_rate
                            logger.info(f"  - 成本盈亏平衡天数: {breakeven_days:.2f} 天")
                        else:
                            breakeven_days = float('inf')
                            logger.warning("  - 成本盈亏平衡天数: 在当前费率下无法回本")

                        # 5. 对比开仓阈值 (综合考虑回本周期)
                        breakeven_days_threshold = config['thresholds']['breakeven_days']
                        logger.info(f"  - 可接受的回本天数阈值: {breakeven_days_threshold} 天")
                        
                        if breakeven_days <= breakeven_days_threshold:
                            logger.info("  - 信号: \033[92m满足开仓条件，存在潜在机会。\033[0m")
                            signal_text = "满足开仓条件"
                        else:
                            logger.info("  - 信号: \033[91m未满足开仓条件（回本周期过长），继续观察。\033[0m")
                            signal_text = "未满足开仓条件"

                    except Exception as e:
                        logger.error(f"在为 {symbol_to_check} 计算成本或信号时出错: {e}")
                        signal_text = "计算错误"

                    # 准备要保存的数据
                    data_to_save = {
                        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'symbol': symbol_to_check,
                        'funding_rate': funding_info['funding_rate'],
                        'daily_funding_rate': funding_info['daily_funding_rate'],
                        'round_trip_cost_rate': round_trip_cost_rate,
                        'breakeven_days': breakeven_days,
                        'signal': signal_text
                    }
                    recorder.record(data_to_save)

                else:
                    logger.warning(f"未能获取 {symbol_to_check} 的资金费率信息。")
                    # 即使失败也记录，以便追踪问题
                    data_to_save = {
                        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'symbol': symbol_to_check,
                        'funding_rate': 'N/A',
                        'daily_funding_rate': 'N/A',
                        'round_trip_cost_rate': 'N/A',
                        'breakeven_days': 'N/A',
                        'signal': '获取失败'
                    }
                    recorder.record(data_to_save)

        except Exception as e:
            logger.error(f"主循环发生未知错误: {e}")
            logger.info(f"本轮观察周期完成。将在 {interval_sec} 秒后开始下一轮...")
        except Exception as e:
            logger.error(f"在主循环中发生未预料的错误: {e}", exc_info=True)
            # 可以在这里添加更复杂的错误处理，比如连续失败N次后退出
            logger.info(f"将跳过本轮，在 {interval_sec} 秒后重试...")

        time.sleep(interval_sec)


if __name__ == "__main__":
    main()