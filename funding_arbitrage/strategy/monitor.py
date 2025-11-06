import ccxt
from typing import Dict, Any

def get_perp_symbol(base_symbol: str) -> str:
    """
    从基础交易对（如 'BTC/USDT'）构建永续合约符号（如 'BTC/USDT:USDT'）。
    这是 ccxt 中访问 Bitget 等交易所永续合约的标准格式。
    """
    if ':' in base_symbol:
        return base_symbol  # 已经是永续合约符号
    quote_currency = base_symbol.split('/')[1]
    return f"{base_symbol}:{quote_currency}"

def fetch_funding_info(exchange: ccxt.Exchange, symbol: str) -> Dict[str, Any]:
    """
    获取指定交易对的资金费率信息，并计算日化费率。

    :param exchange: ccxt 交易所实例。
    :param symbol: 基础交易对，例如 'BTC/USDT'。
    :return: 包含资金费率、日化费率等信息的字典。
    """
    perp_symbol = get_perp_symbol(symbol)
    print(f"正在为永续合约 '{perp_symbol}' 获取资金费率...")

    try:
        if not exchange.has.get('fetchFundingRate'):
            raise NotImplementedError(f"交易所 '{exchange.id}' 不支持 fetchFundingRate 方法。")

        funding_rate_data = exchange.fetch_funding_rate(perp_symbol)

        funding_rate = funding_rate_data.get('fundingRate')
        if funding_rate is None:
            raise ValueError("API 返回的数据中未找到 'fundingRate'。")

        # 蓝图要求：dailyFunding = fundingRate * (24 / intervalHours)
        # Bitget 通常为 8 小时结算一次，即每天 3 次。
        interval_hours = 8
        daily_funding_rate = funding_rate * (24 / interval_hours)

        return {
            'symbol': perp_symbol,
            'funding_rate': funding_rate,
            'daily_funding_rate': daily_funding_rate,
            'funding_timestamp': funding_rate_data.get('fundingTimestamp'),
            'next_funding_time': funding_rate_data.get('nextFundingTime'),
            'raw_data': funding_rate_data
        }

    except Exception as e:
        print(f"获取资金费率时出错: {e}")
        # 将原始异常再次抛出，以便上层调用者可以决定如何处理
        raise