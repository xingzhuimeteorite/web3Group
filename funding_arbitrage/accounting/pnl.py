"""
该模块负责处理盈利与亏损（PnL）的计算，包括资金费套利策略的成本建模。
"""

def get_round_trip_cost_rate(costs: dict, trading_fee_info: dict = None) -> float:
    """
    以小数形式计算总的往返交易成本率。

    一个往返交易涉及开仓和平仓一个双腿头寸（例如，现货和永续合约）。
    这意味着总共有4笔交易（现货买入、永续卖出、现货卖出、永续买入）。
    计算优先使用动态获取的手续费，并包括所有交易的预估滑点。

    Args:
        costs (dict): 包含成本参数的字典，如 'taker_bps' 和 'slippage_bps'。
        trading_fee_info (dict, optional): 从交易所API获取的特定交易对的手续费信息。
                                            如果提供，将使用其中的 'taker' 费率。

    Returns:
        float: 总的往返成本，以小数表示（例如，0.004 代表 0.4%）。
    """
    slippage_bps = costs.get('slippage_bps', 0)

    # 优先使用动态获取的 Taker 费率
    if trading_fee_info and 'taker' in trading_fee_info:
        # taker 费率是小数形式，例如 0.001
        taker_rate = trading_fee_info['taker']
        taker_bps = taker_rate * 10000
    else:
        # 回退到配置文件中的静态 Taker 费率
        taker_bps = costs.get('taker_bps', 0)

    # 单笔交易的成本（一条腿的一个方向）
    one_trade_cost_bps = taker_bps + slippage_bps

    # 4笔交易的总成本（两条腿的往返）
    total_cost_bps = 4 * one_trade_cost_bps
    
    return total_cost_bps / 10000.0


def calculate_breakeven_days(daily_funding_rate: float, costs: dict) -> float:
    """
    计算在考虑日资金费率和借贷成本的情况下，达到盈亏平衡所需的天数。

    Args:
        daily_funding_rate (float): 日资金费率，以小数表示（例如，0.0001 代表 0.01%）。
        costs (dict): 包含成本参数的字典。

    Returns:
        float: 达到盈亏平衡所需的天数。如果净日费率不为正，则返回无穷大（float('inf')）。
    """
    # 资本成本（例如，持有现货的成本）可以建模为每日借贷利率。
    daily_borrow_rate = costs.get('borrowRateDaily', 0)

    net_daily_rate = daily_funding_rate - daily_borrow_rate

    if net_daily_rate <= 0:
        return float('inf')

    round_trip_cost_rate = get_round_trip_cost_rate(costs)

    days_to_breakeven = round_trip_cost_rate / net_daily_rate
    return days_to_breakeven