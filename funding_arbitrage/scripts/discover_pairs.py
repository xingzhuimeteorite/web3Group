import ccxt
import json
import os
import sys

# 将项目根目录添加到 sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, '..'))
sys.path.append(project_root)

from utils.config_loader import load_config
from utils.exchange_loader import get_exchange_from_config

def discover_and_filter_pairs(exchange):
    """
    连接到交易所，发现所有可用的永续合约交易对，并根据交易量进行筛选和排序。
    """
    try:
        # 加载市场
        markets = exchange.load_markets()

        # 筛选出 USDT 或 USDC 本位的永续合约
        perpetual_pairs = []
        for symbol, market in markets.items():
            if market['swap'] and market['active'] and (symbol.endswith(':USDT') or symbol.endswith(':USDC')):
                perpetual_pairs.append(symbol)

        if not perpetual_pairs:
            print("未能找到任何 USDT/USDC 本位的永续合约。")
            return

        # 获取所有交易对的 ticker 数据
        tickers = exchange.fetch_tickers(perpetual_pairs)

        # 筛选并格式化数据
        filtered_pairs = []
        for symbol, ticker in tickers.items():
            if ticker and ticker.get('quoteVolume') is not None:
                # 我们关心以报价货币计价的交易量（例如 USDT 或 USDC）
                if ticker['quoteVolume'] > 0:
                    filtered_pairs.append({
                        'symbol': symbol,
                        'quoteVolume': ticker['quoteVolume']
                    })

        # 按 24 小时交易量降序排序
        sorted_pairs = sorted(filtered_pairs, key=lambda x: x['quoteVolume'], reverse=True)

        return sorted_pairs

    except ccxt.AuthenticationError as e:
        print(f"交易所认证失败: {e}")
    except ccxt.NetworkError as e:
        print(f"网络连接错误: {e}")
    except Exception as e:
        print(f"发生未知错误: {e}")
    return None

def display_results(pairs):
    """
    将排名前10的交易对格式化为可直接复制的字符串。
    """
    if not pairs:
        print("没有可供显示的交易对。")
        return

    top_10_pairs = pairs[:10]
    formatted_strings = [f'"{p["symbol"]}"' for p in top_10_pairs]
    print(',\n'.join(formatted_strings))


if __name__ == "__main__":
    config, _ = load_config()
    if config:
        exchange = get_exchange_from_config(config)
        if exchange:
            print(f"正在从 {exchange.id} 获取交易对信息，请稍候...")
            sorted_pairs = discover_and_filter_pairs(exchange)
            if sorted_pairs:
                display_results(sorted_pairs)