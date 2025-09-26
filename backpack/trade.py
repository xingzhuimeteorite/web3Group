import asyncio
import random
from datetime import datetime
import os
import decimal
import time

from bpx.account import Account
from bpx.public import Public
from bpx.constants.enums import OrderTypeEnum, TimeInForceEnum
from config_loader import ConfigLoader
from points_tracker import BackpackPointsTracker
from risk_manager import BackpackRiskManager
from grid_optimizer import GridOptimizer
from enhanced_logger import EnhancedLogger
from error_handler import BackpackErrorHandler
from performance_monitor import PerformanceMonitor

# 设置 Decimal 的全局精度上下文
decimal.getcontext().prec = 28 

# 加载配置文件
config = ConfigLoader()

# 全局变量用于统计成功买卖次数和总手续费
success_buy = 0
success_sell = 0
total_fees_usdc = decimal.Decimal('0')

# 这个顶层的 last_buy_price_usdc 全局变量在当前网格实现中不再直接使用，但为了兼容性保留
last_buy_price_usdc = None 

# 日志文件配置
# 从配置文件加载交易参数
LOG_FILE_PATH = config.get('logging.log_file_path', 'trade_summary_log.txt')

# 网格策略配置
GRID_PRICE_INTERVAL = decimal.Decimal(str(config.get('trading_settings.grid_price_interval', 40)))
GRID_USDC_PER_ORDER = decimal.Decimal(str(config.get('trading_settings.grid_usdc_per_order', 50)))
NUM_GRIDS = config.get('trading_settings.num_grids', 3)

OUT_WANT = decimal.Decimal(str(config.get('trading_settings.out_want', 0.004)))

# 用于存储所有活动网格的状态 (这是全局变量的定义)
active_grids = {} 

# 初始化积分追踪器
# 初始化全局组件
points_tracker = BackpackPointsTracker()
risk_manager = BackpackRiskManager(config)
grid_optimizer = GridOptimizer(config)
enhanced_logger = EnhancedLogger(config)
error_handler = BackpackErrorHandler(config)
performance_monitor = PerformanceMonitor(config)

def now_str():
    """返回当前时间戳的格式化字符串。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def get_decimal_places_from_tick_size(tick_size: str) -> int:
    """根据 tickSize 字符串计算小数位数。"""
    if '1e-' in tick_size:
        return int(tick_size.split('1e-')[-1])
    if '.' in tick_size:
        return len(tick_size.split('.')[-1])
    return 0

def write_to_log_file(data: str):
    """将给定的数据字符串追加写入日志文件。"""
    try:
        with open(LOG_FILE_PATH, 'a', encoding='utf-8') as f:
            f.write(data + "\n")
    except Exception as e:
        print(now_str(), f"错误: 写入日志文件失败: {e}")

async def execute_buy_order(client: Account, public_client: Public, symbol: str, 
                            trade_pct: int, 
                            order_usdc_amount: decimal.Decimal, price: decimal.Decimal, 
                            quantity_decimals: dict, price_decimals: dict, grid_id: str):
    """执行买入订单逻辑。"""
    global success_buy, total_fees_usdc

    start_time = time.time()  # 记录开始时间
    
    print(now_str(), f"--- 开始买入流程 (网格 {grid_id})：尝试买入 {symbol} ---")
    
    # 记录交易尝试
    enhanced_logger.log_trade_attempt(grid_id, 'BUY', price, order_usdc_amount / price, {
        'symbol': symbol,
        'order_usdc_amount': float(order_usdc_amount),
        'target_price': float(price)
    })

    # 1. 取消现有挂单 (网格内只允许有一个挂单)
    print(now_str(), f"步骤1：检查 {symbol} 挂单 (网格 {grid_id})...")
    open_orders = client.get_open_orders(symbol=symbol) 
    if open_orders:
        print(now_str(), f"步骤1.1：发现 {len(open_orders)} 个 {symbol} 挂单，正在取消...")
        cancel_res = client.cancel_all_orders(symbol=symbol)
        print(now_str(), f"步骤1.2：取消订单结果: {cancel_res}")
        await asyncio.sleep(1) 
    else:
        print(now_str(), "步骤1：无挂单需要取消。")

    # 2. 获取当前账户余额和市场最新价格
    print(now_str(), "步骤2：获取账户余额和市场最新价格...")
    bal = client.get_balances() 
    if not isinstance(bal, dict):
        print(now_str(), f"步骤2.1：获取余额失败或格式错误: {bal}")
        return False, None, None, None 
    
    tickers = public_client.get_tickers() 
    # 从 symbol 动态获取基础代币名称
    base_coin_symbol = symbol.split('_')[0] 
    base_usdc_ticker = next((t for t in tickers if t.get('symbol') == symbol), None) # 使用 symbol 来查找 ticker
    
    if not base_usdc_ticker or 'lastPrice' not in base_usdc_ticker:
        print(now_str(), f"步骤2.2：未找到 {symbol} 的最新价格信息。")
        return False, None, None, None 
    
    current_price_float = float(base_usdc_ticker['lastPrice'])
    usdc_available_float = float(bal.get('USDC', {}).get('available', 0))

    current_price_dec_local = decimal.Decimal(str(current_price_float)) 
    usdc_available_dec = decimal.Decimal(str(usdc_available_float))

    print(now_str(), f"步骤2.3：当前 USDC 可用: {usdc_available_dec:.2f}, 最新价格: {price}") 

    if usdc_available_dec < decimal.Decimal('1'): 
        print(now_str(), "步骤2.4：USDC 余额不足（小于1），无法买入。")
        return False, None, None, None

    # 3. 计算购买数量
    print(now_str(), "步骤3：计算购买数量...")
    actual_usdc_to_spend_dec = min(order_usdc_amount, usdc_available_dec - decimal.Decimal('2')) 
    if actual_usdc_to_spend_dec <= decimal.Decimal('0'):
        print(now_str(), f"步骤3.1：计算可用于买入的 USDC 数量不足（实际可用不足）。")
        return False, None, None, None
        
    raw_qty_dec = actual_usdc_to_spend_dec / price 
    qty_decimal_places = quantity_decimals.get(symbol, 8)
    qty_dec = raw_qty_dec.quantize(decimal.Decimal('1e-' + str(qty_decimal_places)), rounding=decimal.ROUND_DOWN)
    qty_str = "{:.{}f}".format(qty_dec, qty_decimal_places).rstrip('0').rstrip('.')

    if qty_dec <= decimal.Decimal('0'):
        print(now_str(), f"步骤3.2：计算出的买入数量 {qty_str} 无效（小于等于0）。")
        return False, None, None, None

    print(now_str(), f"步骤3.3：计算得准备挂买单 {symbol}: 数量={qty_str}, 价格={price}") 

    # 4. 执行买单
    print(now_str(), "步骤4：执行买单...")
    try:
        price_decimal_places = price_decimals.get(symbol, 2) 
        price_str = "{:.{}f}".format(price, price_decimal_places).rstrip('0').rstrip('.') 
        
        res = client.execute_order(
            symbol=symbol,
            side='Bid',
            order_type=OrderTypeEnum.LIMIT,
            price=price_str,
            quantity=qty_str,
            time_in_force=TimeInForceEnum.GTC 
        )
        print(now_str(), f"步骤3.1：买单请求响应: {res}")

        if isinstance(res, dict) and res.get('status') in ['Filled', 'New', 'PartiallyFilled']:
            # 显示详细的订单信息
            print(now_str(), f"📋 卖单详细信息 (网格 {grid_id}):")
            print(now_str(), f"  ├─ 订单ID: {res.get('id', 'N/A')}")
            print(now_str(), f"  ├─ 交易对: {symbol}")
            print(now_str(), f"  ├─ 订单类型: {res.get('orderType', 'N/A')}")
            print(now_str(), f"  ├─ 订单状态: {res.get('status', 'N/A')}")
            print(now_str(), f"  ├─ 订单价格: {price_str} USDC")
            print(now_str(), f"  ├─ 订单数量: {qty_str} {base_coin_symbol}")
            print(now_str(), f"  ├─ 订单金额: {float(price_str) * float(qty_str):.2f} USDC")
            
            # 如果有成交信息，显示成交详情
            if 'executedQuantity' in res and float(res.get('executedQuantity', '0')) > 0:
                executed_qty = res.get('executedQuantity', '0')
                executed_value = float(executed_qty) * float(price_str)
                print(now_str(), f"  ├─ 已成交数量: {executed_qty} {base_coin_symbol}")
                print(now_str(), f"  ├─ 已成交金额: {executed_value:.2f} USDC")
                
                # 显示剩余未成交部分
                if res.get('status') == 'PartiallyFilled':
                    remaining_qty = float(qty_str) - float(executed_qty)
                    remaining_value = remaining_qty * float(price_str)
                    print(now_str(), f"  ├─ 剩余数量: {remaining_qty:.6f} {base_coin_symbol}")
                    print(now_str(), f"  ├─ 剩余金额: {remaining_value:.2f} USDC")
            
            # 计算和显示手续费详情
            current_trade_fees_usdc = decimal.Decimal('0')
            if 'fills' in res and isinstance(res['fills'], list):
                print(now_str(), f"  ├─ 成交明细 ({len(res['fills'])} 笔):")
                for i, fill in enumerate(res['fills'], 1):
                    fill_qty = fill.get('quantity', '0')
                    fill_price = fill.get('price', '0')
                    fill_value = float(fill_qty) * float(fill_price)
                    fee_amount = decimal.Decimal(fill.get('fee', '0'))
                    fee_asset = fill.get('feeAsset', 'N/A')
                    
                    print(now_str(), f"  │  └─ 成交 {i}: {fill_qty} {base_coin_symbol} @ {fill_price} USDC = {fill_value:.2f} USDC")
                    print(now_str(), f"  │     └─ 手续费: {fee_amount} {fee_asset}")
                    
                    # 转换手续费为USDC
                    if fee_asset == 'USDC':
                        current_trade_fees_usdc += fee_amount
                    else:
                        # 尝试转换其他资产的手续费为USDC
                        all_tickers = public_client.get_tickers()
                        conversion_symbol = f"{fee_asset}_USDC"
                        conversion_ticker = next((t for t in all_tickers if t.get('symbol') == conversion_symbol), None)
                        if conversion_ticker and 'lastPrice' in conversion_ticker:
                            conversion_price = decimal.Decimal(str(conversion_ticker['lastPrice']))
                            fee_in_usdc = fee_amount * conversion_price
                            current_trade_fees_usdc += fee_in_usdc
                            print(now_str(), f"  │     └─ 手续费(USDC): {fee_in_usdc:.6f} USDC (按 {conversion_price} 汇率)")
                        else:
                            print(now_str(), f"  │     └─ 手续费转换失败: 无法获取 {conversion_symbol} 汇率")
            
            print(now_str(), f"  └─ 本次总手续费: {current_trade_fees_usdc:.6f} USDC")
            
            total_fees_usdc += current_trade_fees_usdc
            
            if res.get('status') == 'Filled':
                success_buy += 1
                # 记录积分 - 买入订单通常是Maker订单（挂单）
                trade_volume_usdc = price * qty_dec
                points_earned = points_tracker.record_trade(trade_volume_usdc, is_maker=True)
                
                # 记录交易结果
                enhanced_logger.log_trade_result(grid_id, 'BUY', True, price, qty_dec, current_trade_fees_usdc)
                
                print(now_str(), f"🎉 买入完全成交 {symbol}: 数量={qty_str}, 价格={price_str}。本次手续费: {current_trade_fees_usdc:.6f} USDC。积分: +{points_earned:.2f}。总成功买入次数: {success_buy}。")
                return True, res.get('id'), price, qty_dec 
            elif res.get('status') == 'New':
                print(now_str(), f"📝 买单已成功挂单 {symbol}: 数量={qty_str}, 价格={price_str}。订单ID: {res.get('id')}。等待成交。")
                return True, res.get('id'), None, None 
            elif res.get('status') == 'PartiallyFilled':
                executed_qty = decimal.Decimal(res.get('executedQuantity', '0'))
                executed_price = price 
                # 记录部分成交的积分
                trade_volume_usdc = executed_price * executed_qty
                points_earned = points_tracker.record_trade(trade_volume_usdc, is_maker=True)
                print(now_str(), f"⏳ 买单部分成交 {symbol}: 已成交数量={executed_qty}, 价格={executed_price}。积分: +{points_earned:.2f}。订单ID: {res.get('id')}。剩余部分继续等待。")
                return True, res.get('id'), executed_price, executed_qty 

            else:
                print(now_str(), f"步骤3.2：买入失败或未成交。响应: {res}")
                enhanced_logger.log_trade_result(grid_id, 'BUY', False, error_message=f"订单状态: {res.get('status', 'Unknown')}")
                return False, None, None, None 
        else:
            print(now_str(), f"步骤3.2：买入失败或未完全成交。响应: {res}")
            enhanced_logger.log_trade_result(grid_id, 'BUY', False, error_message=f"无效响应: {res}")
            return False, None, None, None 
    except Exception as e:
        print(now_str(), f"步骤3.3：执行买单时发生异常: {e}")
        
        # 使用错误处理器处理异常
        recovery_result = await error_handler.handle_error(e, {
            'grid_id': grid_id, 
            'action': 'BUY', 
            'symbol': symbol,
            'price': str(price),
            'quantity': str(qty_dec)
        }, 'execute_buy_order')
        
        enhanced_logger.log_error('TRADE_EXECUTION', str(e), {'grid_id': grid_id, 'action': 'BUY', 'symbol': symbol})
        enhanced_logger.log_trade_result(grid_id, 'BUY', False, error_message=str(e))
        
        # 根据恢复策略决定是否需要延迟
        if recovery_result.get('retry_after', 0) > 0:
            print(now_str(), f"错误恢复：等待 {recovery_result['retry_after']} 秒后继续")
            await asyncio.sleep(recovery_result['retry_after'])
        
        return False, None, None, None 
    finally:
        # 记录执行时间
        execution_time = time.time() - start_time
        performance_monitor.record_execution_time('execute_buy_order', execution_time)
        
        print(now_str(), f"--- 买入流程结束 (网格 {grid_id})：{symbol} ---")


async def execute_sell_order(client: Account, public_client: Public, symbol: str,
                             trade_pct: int, 
                             target_sell_price: decimal.Decimal, quantity_to_sell_dec: decimal.Decimal, 
                             quantity_decimals: dict, price_decimals: dict, grid_id: str):
    """执行卖出订单逻辑。"""
    global success_sell, total_fees_usdc

    start_time = time.time()  # 记录开始时间
    
    print(now_str(), f"--- 开始卖出流程 (网格 {grid_id})：尝试卖出 {symbol} ---")

    # 1. 取消现有挂单 (网格内只允许有一个挂单)
    print(now_str(), f"步骤1：检查 {symbol} 挂单 (网格 {grid_id})...")
    open_orders = client.get_open_orders(symbol=symbol) 
    if open_orders:
        print(now_str(), f"步骤1.1：发现 {len(open_orders)} 个 {symbol} 挂单，正在取消...")
        cancel_res = client.cancel_all_orders(symbol=symbol)
        print(now_str(), f"步骤1.2：取消订单结果: {cancel_res}")
        await asyncio.sleep(1)
    else:
        print(now_str(), "步骤1：无挂单需要取消。")

    # 2. 获取当前账户余额 (仅用于最终确认可用性，下单量直接用传入的)
    print(now_str(), "步骤2：获取账户余额和市场最新价格...")
    bal = client.get_balances() 
    if not isinstance(bal, dict):
        print(now_str(), f"步骤2.1：获取余额失败或格式错误: {bal}")
        return False, None, None 
    
    # 从 symbol 动态获取基础代币名称
    base_coin_symbol = symbol.split('_')[0] 
    coin_available_float = float(bal.get(base_coin_symbol, {}).get('available', 0)) # <--- 修正：使用 base_coin_symbol
    coin_available_dec = decimal.Decimal(str(coin_available_float)) 

    # 确保实际可用量满足要卖出的量
    final_quantity_to_sell_dec = min(quantity_to_sell_dec, coin_available_dec)
    
    # 定义最小可交易数量（这个值需要根据BPX交易所的实际 minQuantity 来设置！）
    # <--- 修正：使用 BASE_COIN_MIN_TRADE_QUANTITY 而不是 BTC
    MIN_TRADE_QUANTITY_BASE_COIN = decimal.Decimal('0.001') # SOL 最小交易数量
    # --- 修正结束 ---
    
    if final_quantity_to_sell_dec < MIN_TRADE_QUANTITY_BASE_COIN:
        print(now_str(), f"步骤2.4：{base_coin_symbol} 余额 {final_quantity_to_sell_dec:.6f} 小于最小交易数量 {MIN_TRADE_QUANTITY_BASE_COIN:.6f}，无法卖出。")
        return True, None, decimal.Decimal('0') 

    tickers = public_client.get_tickers()
    base_usdc_ticker = next((t for t in tickers if t.get('symbol') == symbol), None) # 使用 symbol 来查找 ticker
    
    if not base_usdc_ticker or 'lastPrice' not in base_usdc_ticker:
        print(now_str(), f"步骤2.2：未找到 {symbol} 的最新价格信息。")
        return False, None, None 
    
    current_price_float = float(base_usdc_ticker['lastPrice'])

    current_price_dec = decimal.Decimal(str(current_price_float))
    
    print(now_str(), f"步骤2.3：当前 {base_coin_symbol} 可用: {coin_available_dec:.6f}, 最新市场价: {current_price_dec}，目标卖出价: {target_sell_price}")


    # 3. 计算卖出数量 
    print(now_str(), "步骤3：计算卖出数量...")
    qty_decimal_places = quantity_decimals.get(symbol, 8)
    qty_dec = final_quantity_to_sell_dec.quantize(decimal.Decimal('1e-' + str(qty_decimal_places)), rounding=decimal.ROUND_DOWN)
    qty_str = "{:.{}f}".format(qty_dec, qty_decimal_places).rstrip('0').rstrip('.')

    if qty_dec <= decimal.Decimal('0'): 
        print(now_str(), f"步骤3.1：计算出的卖出数量 {qty_str} 无效（四舍五入后小于等于0）。")
        return True, None, decimal.Decimal('0') 
        
    print(now_str(), f"步骤3.2：计算得准备挂卖单 {symbol}: 数量={qty_str}, 目标卖出价={target_sell_price}")

    # 4. 执行卖单
    print(now_str(), "步骤4：执行卖单...")
    try:
        price_decimal_places = price_decimals.get(symbol, 2)
        price_str = "{:.{}f}".format(target_sell_price, price_decimal_places).rstrip('0').rstrip('.')
        
        res = client.execute_order(
            symbol=symbol,
            side='Ask',
            order_type=OrderTypeEnum.LIMIT,
            price=price_str,
            quantity=qty_str,
            time_in_force=TimeInForceEnum.GTC 
        )
        print(now_str(), f"步骤3.1：卖单请求响应: {res}")

        if isinstance(res, dict) and res.get('status') in ['Filled', 'New', 'PartiallyFilled']:
            # 显示详细的订单信息
            print(now_str(), f"📋 卖单详细信息 (网格 {grid_id}):")
            print(now_str(), f"  ├─ 订单ID: {res.get('id', 'N/A')}")
            print(now_str(), f"  ├─ 交易对: {symbol}")
            print(now_str(), f"  ├─ 订单类型: {res.get('orderType', 'N/A')}")
            print(now_str(), f"  ├─ 订单状态: {res.get('status', 'N/A')}")
            print(now_str(), f"  ├─ 订单价格: {price_str} USDC")
            print(now_str(), f"  ├─ 订单数量: {qty_str} {base_coin_symbol}")
            print(now_str(), f"  ├─ 订单金额: {float(price_str) * float(qty_str):.2f} USDC")
            
            # 如果有成交信息，显示成交详情
            if 'executedQuantity' in res and float(res.get('executedQuantity', '0')) > 0:
                executed_qty = res.get('executedQuantity', '0')
                executed_value = float(executed_qty) * float(price_str)
                print(now_str(), f"  ├─ 已成交数量: {executed_qty} {base_coin_symbol}")
                print(now_str(), f"  ├─ 已成交金额: {executed_value:.2f} USDC")
                
                # 显示剩余未成交部分
                if res.get('status') == 'PartiallyFilled':
                    remaining_qty = float(qty_str) - float(executed_qty)
                    remaining_value = remaining_qty * float(price_str)
                    print(now_str(), f"  ├─ 剩余数量: {remaining_qty:.6f} {base_coin_symbol}")
                    print(now_str(), f"  ├─ 剩余金额: {remaining_value:.2f} USDC")
            
            # 计算和显示手续费详情
            current_trade_fees_usdc = decimal.Decimal('0')
            if 'fills' in res and isinstance(res['fills'], list):
                print(now_str(), f"  ├─ 成交明细 ({len(res['fills'])} 笔):")
                for i, fill in enumerate(res['fills'], 1):
                    fill_qty = fill.get('quantity', '0')
                    fill_price = fill.get('price', '0')
                    fill_value = float(fill_qty) * float(fill_price)
                    fee_amount = decimal.Decimal(fill.get('fee', '0'))
                    fee_asset = fill.get('feeAsset', 'N/A')
                    
                    print(now_str(), f"  │  └─ 成交 {i}: {fill_qty} {base_coin_symbol} @ {fill_price} USDC = {fill_value:.2f} USDC")
                    print(now_str(), f"  │     └─ 手续费: {fee_amount} {fee_asset}")
                    
                    # 转换手续费为USDC
                    if fee_asset == 'USDC':
                        current_trade_fees_usdc += fee_amount
                    else:
                        # 尝试转换其他资产的手续费为USDC
                        all_tickers = public_client.get_tickers()
                        conversion_symbol = f"{fee_asset}_USDC"
                        conversion_ticker = next((t for t in all_tickers if t.get('symbol') == conversion_symbol), None)
                        if conversion_ticker and 'lastPrice' in conversion_ticker:
                            conversion_price = decimal.Decimal(str(conversion_ticker['lastPrice']))
                            fee_in_usdc = fee_amount * conversion_price
                            current_trade_fees_usdc += fee_in_usdc
                            print(now_str(), f"  │     └─ 手续费(USDC): {fee_in_usdc:.6f} USDC (按 {conversion_price} 汇率)")
                        else:
                            print(now_str(), f"  │     └─ 手续费转换失败: 无法获取 {conversion_symbol} 汇率")
            
            print(now_str(), f"  └─ 本次总手续费: {current_trade_fees_usdc:.6f} USDC")
            
            total_fees_usdc += current_trade_fees_usdc
            
            if res.get('status') == 'Filled':
                success_sell += 1
                # 记录积分 - 卖出订单通常是Maker订单（挂单）
                trade_volume_usdc = target_sell_price * qty_dec
                points_earned = points_tracker.record_trade(trade_volume_usdc, is_maker=True)
                print(now_str(), f"✅ 卖出完全成交 {symbol}: 数量={qty_str}, 价格={price_str}。本次手续费: {current_trade_fees_usdc:.6f} USDC。积分: +{points_earned:.2f}。总成功卖出次数: {success_sell}。")
                return True, res.get('id'), qty_dec 
            elif res.get('status') == 'New':
                print(now_str(), f"📝 卖单已成功挂单 {symbol}: 数量={qty_str}, 价格={price_str}。订单ID: {res.get('id')}。等待成交。")
                return True, res.get('id'), None 
            elif res.get('status') == 'PartiallyFilled':
                executed_qty = decimal.Decimal(res.get('executedQuantity', '0'))
                # 记录部分成交的积分
                trade_volume_usdc = target_sell_price * executed_qty
                points_earned = points_tracker.record_trade(trade_volume_usdc, is_maker=True)
                print(now_str(), f"⏳ 卖单部分成交 {symbol}: 已成交数量={executed_qty}。积分: +{points_earned:.2f}。订单ID: {res.get('id')}。剩余部分继续等待。")
                return True, res.get('id'), executed_qty 
            else:
                print(now_str(), f"步骤3.2：卖出失败或未成交。响应: {res}")
                return False, None, None 
        else:
            print(now_str(), f"步骤3.2：卖出失败或未完全成交。响应: {res}")
            return False, None, None 
    except Exception as e:
        print(now_str(), f"步骤3.3：执行卖单时发生异常: {e}")
        
        # 使用错误处理器处理异常
        recovery_result = await error_handler.handle_error(e, {
            'grid_id': grid_id, 
            'action': 'SELL', 
            'symbol': symbol,
            'price': str(target_sell_price),
            'quantity': str(quantity_to_sell_dec)
        }, 'execute_sell_order')
        
        enhanced_logger.log_error('TRADE_EXECUTION', str(e), {'grid_id': grid_id, 'action': 'SELL', 'symbol': symbol})
        enhanced_logger.log_trade_result(grid_id, 'SELL', False, error_message=str(e))
        
        # 根据恢复策略决定是否需要延迟
        if recovery_result.get('retry_after', 0) > 0:
            print(now_str(), f"错误恢复：等待 {recovery_result['retry_after']} 秒后继续")
            await asyncio.sleep(recovery_result['retry_after'])
        
        return False, None, None 
    finally:
        # 记录执行时间
        execution_time = time.time() - start_time
        performance_monitor.record_execution_time('execute_sell_order', execution_time)
        
        print(now_str(), f"--- 卖出流程结束 (网格 {grid_id})：{symbol} ---")


async def main_trading_loop():
    """主交易循环。"""
    # 声明 active_grids 为全局变量，因为它会在函数内部被修改
    global success_buy, success_sell, total_fees_usdc, active_grids,OUT_WANT 

    # 从配置文件获取API密钥
    credentials = config.get_api_credentials()
    API_KEY = credentials.get('api_key')
    API_SECRET = credentials.get('secret_key')

    if not API_KEY or not API_SECRET or not config.is_configured():
        print(now_str(), "错误: 未能从配置文件加载 API 密钥。请检查 config.json 配置。程序退出。")
        return

    client = Account(public_key=API_KEY, secret_key=API_SECRET)
    public_client = Public()

    print(now_str(), "--- 初始化机器人 ---")
    print(now_str(), "初始化步骤：获取市场信息以确定交易精度...")
    markets_info = public_client.get_markets()
    if not isinstance(markets_info, list):
        print(now_str(), f"初始化错误：获取市场信息失败或格式错误: {markets_info}。程序退出。")
        return
    
    quantity_decimals = {} 
    price_decimals = {}    

    for m in markets_info:
        symbol = m['symbol']
        if 'quantity' in m['filters'] and 'minQuantity' in m['filters']['quantity']:
            quantity_decimals[symbol] = get_decimal_places_from_tick_size(m['filters']['quantity']['minQuantity'])
        if 'price' in m['filters'] and 'tickSize' in m['filters']['price']:
            price_decimals[symbol] = get_decimal_places_from_tick_size(m['filters']['price']['tickSize'])

    print(now_str(), "初始化步骤：市场数量和价格精度初始化完成。")

    # 从配置文件加载交易参数
    TARGET_SYMBOL = config.get('trading_settings.target_symbol', 'SOL_USDC')
    BASE_COIN_SYMBOL = config.get('trading_settings.base_coin_symbol', 'SOL')
    TRADE_PCT = config.get('trading_settings.trade_pct', 100)
    DELAY_BETWEEN_OPERATIONS = config.get('trading_settings.delay_between_operations', 3)
    DELAY_BETWEEN_GRIDS = config.get('trading_settings.delay_between_grids', 1)
    
    DELAYS = list(range(DELAY_BETWEEN_OPERATIONS, DELAY_BETWEEN_OPERATIONS + 10)) 
    PCTS = list(range(90, 101)) 

    print(now_str(), f"--- 启动 {TARGET_SYMBOL} 循环交易机器人 ---")
    print(now_str(), f"策略配置：每次等待 {min(DELAYS)}-{max(DELAYS)} 秒。")
    print(now_str(), f"网格配置：{NUM_GRIDS} 个网格，每个网格价格区间 {GRID_PRICE_INTERVAL} USDC，每次下单金额 {GRID_USDC_PER_ORDER} USDC。")
    print(now_str(), f"目标利润：上次买入价的 0.1% (千分之一)。")

    # 日志文件头部写入
    with open(LOG_FILE_PATH, 'w', encoding='utf-8') as f:
        f.write(f"--- 交易机器人启动日志：{now_str()} ---\n")
        f.write("时间,总买入次数,总卖出次数,累计手续费(USDC),USDC可用,{base_coin}_可用,{base_coin}价值(USDC),{base_coin}当前价格,活跃网格状态\n".format(base_coin=BASE_COIN_SYMBOL)) # <--- 修正：日志头部动态代币
    
    # 初始化所有网格的状态
    initial_tickers = public_client.get_tickers()
    # 使用 TARGET_SYMBOL 来查找 ticker
    initial_base_usdc_ticker = next((t for t in initial_tickers if t.get('symbol') == TARGET_SYMBOL), None) 
    if not initial_base_usdc_ticker or 'lastPrice' not in initial_base_usdc_ticker:
        print(now_str(), f"初始化错误：无法获取初始 {TARGET_SYMBOL} 价格来构建网格。程序退出。") # <--- 修正日志
        return
    current_market_price_dec_at_init = decimal.Decimal(str(float(initial_base_usdc_ticker['lastPrice'])))
    
    # 重新计算 start_grid_floor 以便中间网格包含当前价格
    start_grid_floor_at_init = (current_market_price_dec_at_init // GRID_PRICE_INTERVAL) * GRID_PRICE_INTERVAL - (NUM_GRIDS // 2) * GRID_PRICE_INTERVAL
    
    for i in range(NUM_GRIDS):
        grid_floor = start_grid_floor_at_init + i * GRID_PRICE_INTERVAL
        grid_ceiling = grid_floor + GRID_PRICE_INTERVAL
        grid_id = f"{grid_floor:.0f}-{grid_ceiling:.0f}" 

        active_grids[grid_id] = {
            'status': 'buying', 
            'last_buy_price': None,
            'coin_qty': decimal.Decimal('0'), 
            'order_id': None, 
            'allocated_usdc': GRID_USDC_PER_ORDER 
        }
        print(now_str(), f"初始化：网格 {grid_id} (价格区间 {grid_floor}-{grid_ceiling}) 已创建，状态: buying。")

    while True:
        try:
            loop_start_time = time.time()  # 记录循环开始时间
            
            current_delay = random.choice(DELAYS)
            trade_pct = random.choice(PCTS) 
            
            print(f"\n{now_str()} --- 新一轮决策开始 ---")
            print(now_str(), f"总计：已买入成功: {success_buy} 次, 已卖出成功: {success_sell} 次。")
            print(now_str(), f"累计总手续费消耗: {total_fees_usdc:.6f} USDC。")
            
            # 显示积分统计
            points_summary = points_tracker.get_points_summary()
            print(now_str(), f"积分统计：预估积分: {points_summary['estimated_points']:.2f}, 周交易量: {points_summary['trading_volume_weekly']:.2f} USDC, Maker比例: {points_summary['maker_ratio']:.2%}")
            
            # 获取积分优化建议
            if 'sol_current_price_dec' in locals():
                optimization_suggestions = points_tracker.optimize_for_points(sol_current_price_dec, GRID_PRICE_INTERVAL)
                if optimization_suggestions['reasoning']:
                    print(now_str(), f"积分优化建议: {'; '.join(optimization_suggestions['reasoning'])}")

            print(now_str(), f"等待 {current_delay} 秒进行下一次决策...")
            await asyncio.sleep(current_delay)

            # 获取当前所有资产的余额和市值
            print(now_str(), "决策步骤：获取最新余额和行情...")
            
            # 记录API调用开始时间
            api_start_time = time.time()
            bal = client.get_balances()
            api_response_time = time.time() - api_start_time
            performance_monitor.record_api_response_time(api_response_time)
            
            if not isinstance(bal, dict):
                print(now_str(), f"决策步骤：获取余额失败或格式错误: {bal}，跳过本次循环。")
                await asyncio.sleep(5)
                continue

            usdc_available = decimal.Decimal(str(bal.get('USDC', {}).get('available', 0)))
            base_coin_available = decimal.Decimal(str(bal.get(BASE_COIN_SYMBOL, {}).get('available', 0)))

            # 记录获取行情数据的API调用时间
            api_start_time = time.time()
            tickers = public_client.get_tickers()
            api_response_time = time.time() - api_start_time
            performance_monitor.record_api_response_time(api_response_time)
            sol_usdc_ticker = next((t for t in tickers if t.get('symbol') == TARGET_SYMBOL), None)
            if not sol_usdc_ticker or 'lastPrice' not in sol_usdc_ticker:
                print(now_str(), f"决策步骤：无法获取 {TARGET_SYMBOL} 价格，跳过本次循环。")
                await asyncio.sleep(5)
                continue

            sol_current_price_dec = decimal.Decimal(str(float(sol_usdc_ticker['lastPrice'])))
            
            # 风险管理检查
            risk_manager.set_initial_balance(usdc_available, base_coin_available, sol_current_price_dec)
            risk_assessment = risk_manager.update_balance(usdc_available, base_coin_available, sol_current_price_dec)
            
            # 显示风险状态
            print(now_str(), f"风险状态：等级 {risk_assessment['risk_level']}, 总盈亏 {risk_assessment['total_pnl']:.2f} USDC ({risk_assessment['total_pnl_percentage']:.2f}%), 回撤 {risk_assessment['current_drawdown']:.2f}%")
            
            # 检查是否需要停止交易
            if risk_assessment['should_stop_trading']:
                print(now_str(), f"风险管理：触发停止交易条件！原因：{'; '.join(risk_assessment['risk_alerts'])}")
                if risk_assessment['emergency_stop']:
                    print(now_str(), "紧急停止交易！请检查风险状况后手动重启。")
                    break
                else:
                    print(now_str(), "暂停交易一轮，等待风险状况改善...")
                    await asyncio.sleep(current_delay * 2)
                    continue
            
            # 根据风险水平调整持仓大小
            should_reduce, position_ratio = risk_manager.should_reduce_position_size(risk_assessment['risk_level'])
            if should_reduce:
                adjusted_usdc_per_order = GRID_USDC_PER_ORDER * position_ratio
                print(now_str(), f"风险管理：调整持仓大小至 {position_ratio:.0%}，每网格订单金额调整为 {adjusted_usdc_per_order:.2f} USDC")
            else:
                adjusted_usdc_per_order = GRID_USDC_PER_ORDER

            usdc_available_float = float(usdc_available)
            base_coin_available_float = float(base_coin_available)
            sol_current_price_float = float(sol_current_price_dec)
            base_coin_current_value_in_usdc = base_coin_available_float * sol_current_price_float

            print(now_str(), f"决策步骤：当前总资产 - USDC 可用: {usdc_available_float:.2f}，{BASE_COIN_SYMBOL} 可用: {base_coin_available_float:.6f} (约 {base_coin_current_value_in_usdc:.2f} USDC)")
            print(now_str(), f"决策步骤：{BASE_COIN_SYMBOL} 当前市场价格: {sol_current_price_dec}")

            # 更新价格历史用于网格优化
            grid_optimizer.update_price_history(sol_current_price_dec)
            
            # 获取网格推荐
            grid_recommendations = grid_optimizer.get_grid_recommendations(sol_current_price_dec, NUM_GRIDS)
            
            # 显示网格优化信息
            print(now_str(), f"网格优化状态：")
            print(now_str(), f"  当前波动率: {grid_recommendations['current_volatility']:.4f} ({grid_recommendations['volatility_level']})")
            print(now_str(), f"  建议网格间距: {grid_recommendations['optimal_grid_interval']:.0f}")
            print(now_str(), f"  建议网格数量: {grid_recommendations['recommended_num_grids']}")
            print(now_str(), f"  订单金额调整系数: {grid_recommendations['order_size_multiplier']:.2f}")
            
            if grid_recommendations['should_adjust']:
                print(now_str(), f"  建议：考虑调整网格配置以优化性能")

            # 动态调整订单金额（结合风险管理和网格优化）
            grid_size_multiplier = decimal.Decimal(str(grid_recommendations['order_size_multiplier']))
            adjusted_usdc_per_order = adjusted_usdc_per_order * grid_size_multiplier

            # --- 动态网格调整逻辑 ---
            new_base_grid_floor_center = (sol_current_price_dec // GRID_PRICE_INTERVAL) * GRID_PRICE_INTERVAL
            new_start_grid_floor = new_base_grid_floor_center - (NUM_GRIDS // 2) * GRID_PRICE_INTERVAL
            
            lowest_active_grid_floor = decimal.Decimal('inf')
            highest_active_grid_ceiling = decimal.Decimal('-inf')
            if active_grids: 
                lowest_active_grid_floor = min([decimal.Decimal(k.split('-')[0]) for k in active_grids.keys()])
                highest_active_grid_ceiling = max([decimal.Decimal(k.split('-')[1]) for k in active_grids.keys()])

            should_realign_grids = False
            if not (sol_current_price_dec >= lowest_active_grid_floor and sol_current_price_dec < highest_active_grid_ceiling):
                if active_grids: 
                    print(now_str(), f"动态网格：市场价格 {sol_current_price_dec} 偏离当前网格范围 ({lowest_active_grid_floor}-{highest_active_grid_ceiling})。")
                    should_realign_grids = True
            elif new_start_grid_floor != lowest_active_grid_floor:
                 print(now_str(), f"动态网格：网格基准底部已从 {lowest_active_grid_floor} 变动到 {new_start_grid_floor}。")
                 should_realign_grids = True
            
            if should_realign_grids:
                print(now_str(), "动态网格：开始重新定位网格系统...")
                print(now_str(), "  动态网格：取消所有现有挂单...")
                all_open_orders = client.get_open_orders(symbol=TARGET_SYMBOL) 
                if all_open_orders:
                    cancel_all_res = client.cancel_all_orders(symbol=TARGET_SYMBOL)
                    print(now_str(), f"  动态网格：取消所有订单响应: {cancel_all_res}")
                    await asyncio.sleep(1) 
                else:
                    print(now_str(), "  动态网格：无挂单需要取消。")
                
                active_grids.clear() 
                print(now_str(), "  动态网格：已清空旧网格状态。")

                for i in range(NUM_GRIDS):
                    grid_floor = new_start_grid_floor + i * GRID_PRICE_INTERVAL
                    grid_ceiling = grid_floor + GRID_PRICE_INTERVAL
                    grid_id = f"{grid_floor:.0f}-{grid_ceiling:.0f}" 

                    active_grids[grid_id] = {
                        'status': 'buying', 
                        'last_buy_price': None,
                        'coin_qty': decimal.Decimal('0'), 
                        'order_id': None, 
                        'allocated_usdc': adjusted_usdc_per_order  # 使用调整后的订单金额
                    }
                    print(now_str(), f"  动态网格：已创建新网格 {grid_id} (价格区间 {grid_floor}-{grid_ceiling})，状态: buying。")
                print(now_str(), "动态网格：网格系统重新定位完成。")

                # 同步账户实际持仓到新的网格中
                print(now_str(), "动态网格：同步账户实际持仓到新网格...")
                current_bal_for_sync = client.get_balances()
                current_base_coin_available_for_sync = decimal.Decimal(str(float(current_bal_for_sync.get(BASE_COIN_SYMBOL, {}).get('available', 0))))
                
                market_info_for_target = next((m for m in markets_info if m['symbol'] == TARGET_SYMBOL), None)
                actual_min_trade_quantity = decimal.Decimal('0.000001')
                if market_info_for_target and 'quantity' in market_info_for_target['filters'] and 'minQuantity' in market_info_for_target['filters']['quantity']:
                    actual_min_trade_quantity = decimal.Decimal(market_info_for_target['filters']['quantity']['minQuantity'])
                
                if current_base_coin_available_for_sync >= actual_min_trade_quantity:
                    target_grid_for_holding_id = None
                    for grid_id_str_sync, grid_info_sync in active_grids.items():
                        grid_floor_sync, grid_ceiling_sync = decimal.Decimal(grid_id_str_sync.split('-')[0]), decimal.Decimal(grid_id_str_sync.split('-')[1])
                        if sol_current_price_dec >= grid_floor_sync and sol_current_price_dec < grid_ceiling_sync:
                            target_grid_for_holding_id = grid_id_str_sync
                            break
                    
                    if target_grid_for_holding_id:
                        target_grid_info = active_grids[target_grid_for_holding_id]
                        print(now_str(), f"  动态网格：检测到 {current_base_coin_available_for_sync:.6f} {BASE_COIN_SYMBOL} 持仓。将其分配到网格 {target_grid_for_holding_id}。")
                        target_grid_info['status'] = 'selling'
                        target_grid_info['last_buy_price'] = sol_current_price_dec 
                        target_grid_info['coin_qty'] = current_base_coin_available_for_sync
                        print(now_str(), f"  动态网格：网格 {target_grid_for_holding_id} 状态更新为 selling，持仓: {current_base_coin_available_for_sync:.6f} {BASE_COIN_SYMBOL}。")
                    else:
                        print(now_str(), f"  动态网格：检测到 {BASE_COIN_SYMBOL} 持仓，但当前价格不在任何一个新生成的网格区间内，无法分配。请手动处理。")
                else:
                    print(now_str(), f"  动态网格：账户无明显 {BASE_COIN_SYMBOL} 持仓需要同步或数量过小。")
                print(now_str(), "动态网格：持仓同步完成。")

            # --- 核心决策逻辑：遍历每个网格 ---
            for grid_id_str, grid_info in active_grids.items():
                grid_floor_str, grid_ceiling_str = grid_id_str.split('-')
                grid_floor = decimal.Decimal(grid_floor_str)
                grid_ceiling = decimal.Decimal(grid_ceiling_str)

                is_in_grid_range = (sol_current_price_dec >= grid_floor and sol_current_price_dec < grid_ceiling)
                
                print(now_str(), f"决策步骤：处理网格 {grid_id_str} (状态: {grid_info['status']})")

                if grid_info['status'] == 'buying' and grid_info['order_id'] is None:
                    if is_in_grid_range:
                        if usdc_available_float >= float(grid_info['allocated_usdc']):
                            print(now_str(), f"  网格 {grid_id_str}：满足买入条件 (价格在区间内且 USDC 充足)，尝试执行买入。")
                            
                            buy_price_for_order = sol_current_price_dec 
                            
                            # 检查持仓风险
                            position_risk = risk_manager.check_position_risk(grid_id_str, buy_price_for_order, sol_current_price_dec, adjusted_usdc_per_order / sol_current_price_dec)
                            if position_risk['risk_level'] == 'CRITICAL':
                                print(now_str(), f"  网格 {grid_id_str}：持仓风险过高，跳过买入。风险警告: {'; '.join(position_risk['alerts'])}")
                                continue
                            
                            success, order_id, filled_price, filled_qty = await execute_buy_order(
                                client, public_client, TARGET_SYMBOL, 
                                trade_pct, 
                                grid_info['allocated_usdc'], buy_price_for_order, 
                                quantity_decimals, price_decimals, grid_id_str
                            )
                            
                            if success:
                                grid_info['status'] = 'selling'
                                grid_info['last_buy_price'] = filled_price
                                grid_info['coin_qty'] = filled_qty
                                grid_info['order_id'] = None
                                success_buy += 1
                                
                                # 更新网格性能统计
                                grid_optimizer.update_grid_performance(grid_id_str, 'trade_completed')
                                
                                print(now_str(), f"  网格 {grid_id_str}：买入成功！状态转为 selling，买入价: {filled_price}, 持仓: {filled_qty:.6f}")
                            else:
                                grid_info['order_id'] = order_id if order_id else None
                                print(now_str(), f"  网格 {grid_id_str}：买入订单已提交，订单ID: {order_id}")
                        else:
                                print(now_str(), f"  网格 {grid_id_str}：USDC 余额不足，无法买入。需要: {grid_info['allocated_usdc']}, 可用: {usdc_available_float:.2f}")
                    else:
                        print(now_str(), f"  网格 {grid_id_str}：价格不在网格区间内，跳过买入。")

                elif grid_info['status'] == 'selling' and grid_info['order_id'] is None:
                    if grid_info['coin_qty'] > decimal.Decimal('0') and grid_info['last_buy_price'] is not None:
                        target_sell_price = grid_info['last_buy_price'] * (decimal.Decimal('1') + OUT_WANT)
                        
                        if sol_current_price_dec >= target_sell_price:
                            print(now_str(), f"  网格 {grid_id_str}：满足卖出条件 (价格达到目标)，尝试执行卖出。目标价: {target_sell_price}")
                            
                            # 检查卖出风险和记录盈亏
                            expected_pnl = (sol_current_price_dec - grid_info['last_buy_price']) * grid_info['coin_qty']
                            risk_manager.update_daily_pnl(expected_pnl)
                            
                            success, order_id, filled_price, filled_qty = await execute_sell_order(
                                client, public_client, TARGET_SYMBOL,
                                trade_pct, 
                                target_sell_price, grid_info['coin_qty'], 
                                quantity_decimals, price_decimals, grid_id_str
                            )
                            
                            if success:
                                # 计算利润
                                profit = (filled_price - grid_info['last_buy_price']) * filled_qty
                                
                                grid_info['status'] = 'buying'
                                grid_info['last_buy_price'] = None
                                grid_info['coin_qty'] = decimal.Decimal('0')
                                grid_info['order_id'] = None
                                success_sell += 1
                                
                                # 更新网格性能统计
                                grid_optimizer.update_grid_performance(grid_id_str, 'trade_completed', profit)
                                
                                print(now_str(), f"  网格 {grid_id_str}：卖出成功！状态转为 buying，卖出价: {filled_price}，利润: {profit:.6f} USDC")
                            else:
                                grid_info['order_id'] = order_id if order_id else None
                                print(now_str(), f"  网格 {grid_id_str}：卖出订单已提交，订单ID: {order_id}")
                        else:
                            print(now_str(), f"  网格 {grid_id_str}：价格未达到目标卖出价，继续持有。当前: {sol_current_price_dec}, 目标: {target_sell_price}")
                    else:
                        print(now_str(), f"  网格 {grid_id_str}：无持仓或买入价格缺失，状态异常。")

                elif grid_info['order_id'] is not None:
                    print(now_str(), f"  网格 {grid_id_str}：有未处理挂单 {grid_info['order_id']}，正在检查其状态...")
                    try:
                        # 记录订单状态查询的API调用时间
                        api_start_time = time.time()
                        order_status_res = client.get_open_order(symbol=TARGET_SYMBOL, order_id=grid_info['order_id'])
                        api_response_time = time.time() - api_start_time
                        performance_monitor.record_api_response_time(api_response_time)
                        
                        if isinstance(order_status_res, dict) and 'status' in order_status_res:
                            order_status = order_status_res.get('status')
                            
                            if order_status == 'Filled':
                                print(now_str(), f"  网格 {grid_id_str}：检测到旧订单 {grid_info['order_id']} 已完全成交。")
                                order_side = order_status_res.get('side')
                                executed_qty = decimal.Decimal(order_status_res.get('executedQuantity', '0'))
                                executed_price = decimal.Decimal(str(order_status_res.get('price', '0')))

                                if order_side == 'Bid': 
                                    grid_info['status'] = 'selling'
                                    grid_info['last_buy_price'] = executed_price 
                                    grid_info['coin_qty'] += executed_qty
                                    print(now_str(), f"  网格 {grid_id_str}：买单成交，状态转为 selling，买入价: {grid_info['last_buy_price']}, 持仓: {grid_info['coin_qty']:.6f}")
                                elif order_side == 'Ask': 
                                    grid_info['status'] = 'buying'
                                    grid_info['last_buy_price'] = None
                                    grid_info['coin_qty'] -= executed_qty 
                                    if grid_info['coin_qty'] < decimal.Decimal('0'): grid_info['coin_qty'] = decimal.Decimal('0')
                                    print(now_str(), f"  网格 {grid_id_str}：卖单成交，状态转为 buying，持仓清空。")
                                grid_info['order_id'] = None 

                            elif order_status == 'Canceled':
                                print(now_str(), f"  网格 {grid_id_str}：检测到旧订单 {grid_info['order_id']} 已被取消。")
                                grid_info['order_id'] = None 
                            
                            elif order_status == 'PartiallyFilled':
                                executed_qty = decimal.Decimal(order_status_res.get('executedQuantity', '0'))
                                print(now_str(), f"  网格 {grid_id_str}：旧订单 {grid_info['order_id']} 仍处于部分成交状态，已成交数量: {executed_qty}。")
                                order_side = order_status_res.get('side')
                                if order_side == 'Bid':
                                    grid_info['coin_qty'] = decimal.Decimal(str(order_status_res.get('executedQuantity', '0'))) 
                                    grid_info['last_buy_price'] = decimal.Decimal(str(order_status_res.get('price', '0'))) if grid_info['last_buy_price'] is None else grid_info['last_buy_price']
                                    if grid_info['coin_qty'] > decimal.Decimal('0'):
                                        grid_info['status'] = 'selling' 
                                elif order_side == 'Ask':
                                    pass 
                                print(now_str(), f"  网格 {grid_id_str}：持仓更新为: {grid_info['coin_qty']:.6f}。")
                                
                            elif order_status == 'New':
                                print(now_str(), f"  网格 {grid_id_str}：旧订单 {grid_info['order_id']} 仍处于 {order_status} 状态，继续等待。")
                            else:
                                print(now_str(), f"  网格 {grid_id_str}：旧订单 {grid_info['order_id']} 状态未知或异常: {order_status_res.get('status')}。完整响应: {order_status_res}")
                        
                        elif isinstance(order_status_res, list) and not order_status_res: # 订单不在开放订单列表
                            print(now_str(), f"  网格 {grid_id_str}：订单 {grid_info['order_id']} 已不在开放订单列表。尝试查询历史订单确认最终状态。")
                            history_orders = client.get_order_history(symbol=TARGET_SYMBOL, order_id=grid_info['order_id'])
                            
                            if isinstance(history_orders, list) and len(history_orders) > 0:
                                final_order_status = history_orders[0].get('status')
                                print(now_str(), f"  网格 {grid_id_str}：历史查询确认订单 {grid_info['order_id']} 最终状态为: {final_order_status}")
                                
                                if final_order_status == 'Filled':
                                    print(now_str(), f"  网格 {grid_id_str}：历史查询确认订单已完全成交。")
                                    order_side = history_orders[0].get('side')
                                    executed_qty = decimal.Decimal(history_orders[0].get('executedQuantity', '0'))
                                    executed_price = decimal.Decimal(str(history_orders[0].get('price', '0')))

                                    if order_side == 'Bid': 
                                        grid_info['status'] = 'selling'
                                        grid_info['last_buy_price'] = executed_price
                                        grid_info['coin_qty'] += executed_qty
                                        print(now_str(), f"  网格 {grid_id_str}：买单成交，状态转为 selling，买入价: {grid_info['last_buy_price']}, 持仓: {grid_info['coin_qty']:.6f}")
                                    elif order_side == 'Ask': 
                                        grid_info['status'] = 'buying'
                                        grid_info['last_buy_price'] = None
                                        grid_info['coin_qty'] -= executed_qty
                                        if grid_info['coin_qty'] < decimal.Decimal('0'): grid_info['coin_qty'] = decimal.Decimal('0')
                                        print(now_str(), f"  网格 {grid_id_str}：卖单成交，状态转为 buying，持仓清空。")
                                    grid_info['order_id'] = None 
                                
                                elif final_order_status == 'Canceled':
                                    print(now_str(), f"  网格 {grid_id_str}：历史查询确认订单已取消。")
                                    grid_info['order_id'] = None 
                                elif final_order_status == 'Rejected':
                                    print(now_str(), f"  网格 {grid_id_str}：历史查询确认订单被拒绝。")
                                    grid_info['order_id'] = None 
                                else:
                                    print(now_str(), f"  网格 {grid_id_str}：历史订单 {grid_info['order_id']} 状态 {final_order_status} 未知或异常。完整响应: {history_orders[0]}")
                            else:
                                print(now_str(), f"  网格 {grid_id_str}：历史订单 {grid_info['order_id']} 未在历史记录中找到。可能已过期或ID错误。")
                                grid_info['order_id'] = None 
                        else:
                            print(now_str(), f"  网格 {grid_id_str}：获取订单状态响应异常或为空: {order_status_res}")
                            grid_info['order_id'] = None 
                    except Exception as order_check_e:
                        print(now_str(), f"  网格 {grid_id_str}：检查旧订单状态时发生异常: {order_check_e}")

            # --- 核心决策逻辑：遍历每个网格 ---

        except Exception as e:
            print(now_str(), f"主循环发生未预期异常: {e}")
            
            # 使用错误处理器处理主循环异常
            recovery_result = await error_handler.handle_error(e, {
                'iteration': 'main_trading_loop',
                'timestamp': datetime.now().isoformat()
            }, 'main_trading_loop')
            
            enhanced_logger.log_error('MAIN_LOOP', str(e), {'iteration': 'main_trading_loop'})
            
            # 根据恢复策略决定下一步行动
            if recovery_result.get('action') == 'emergency_stop':
                print(now_str(), "错误处理器建议紧急停止交易")
                break
            elif recovery_result.get('action') == 'stop_trading':
                print(now_str(), f"错误处理器建议停止交易 {recovery_result.get('retry_after', 600)} 秒")
                await asyncio.sleep(recovery_result.get('retry_after', 600))
            else:
                print(now_str(), "程序将等待一段时间后尝试恢复...")
                await asyncio.sleep(recovery_result.get('retry_after', 5))
        finally:
            # 显示详细的网格状态总结
            print(now_str(), "📊 网格状态详细总结:")
            print(now_str(), "=" * 60)
            
            if 'active_grids' in locals() and active_grids:
                buying_grids = []
                selling_grids = []
                pending_order_grids = []
                
                for grid_id_str, grid_info in active_grids.items():
                    grid_floor_str, grid_ceiling_str = grid_id_str.split('-')
                    grid_floor = decimal.Decimal(grid_floor_str)
                    grid_ceiling = decimal.Decimal(grid_ceiling_str)
                    
                    # 判断当前价格是否在网格范围内
                    is_in_range = ""
                    if 'sol_current_price_dec' in locals():
                        if sol_current_price_dec >= grid_floor and sol_current_price_dec < grid_ceiling:
                            is_in_range = " 🎯"
                    
                    grid_summary = {
                        'id': grid_id_str,
                        'range': f"{grid_floor:.0f}-{grid_ceiling:.0f}",
                        'status': grid_info['status'],
                        'last_buy_price': grid_info['last_buy_price'],
                        'coin_qty': grid_info['coin_qty'],
                        'order_id': grid_info['order_id'],
                        'allocated_usdc': grid_info['allocated_usdc'],
                        'in_range': is_in_range
                    }
                    
                    if grid_info['status'] == 'buying':
                        buying_grids.append(grid_summary)
                    elif grid_info['status'] == 'selling':
                        selling_grids.append(grid_summary)
                    
                    if grid_info['order_id'] is not None:
                        pending_order_grids.append(grid_summary)
                
                # 显示买入状态的网格
                if buying_grids:
                    print(now_str(), f"🟢 买入状态网格 ({len(buying_grids)} 个):")
                    for grid in buying_grids:
                        order_status = f", 挂单: {grid['order_id']}" if grid['order_id'] else ", 无挂单"
                        print(now_str(), f"  ├─ {grid['range']}{grid['in_range']} | 分配资金: {grid['allocated_usdc']:.2f} USDC{order_status}")
                
                # 显示卖出状态的网格
                if selling_grids:
                    print(now_str(), f"🔴 卖出状态网格 ({len(selling_grids)} 个):")
                    for grid in selling_grids:
                        buy_price_str = f"{grid['last_buy_price']:.2f}" if grid['last_buy_price'] else "N/A"
                        order_status = f", 挂单: {grid['order_id']}" if grid['order_id'] else ", 无挂单"
                        potential_profit = ""
                        if grid['last_buy_price'] and 'sol_current_price_dec' in locals() and sol_current_price_dec is not None:
                            try:
                                profit_pct = ((sol_current_price_dec - grid['last_buy_price']) / grid['last_buy_price']) * 100
                                potential_profit = f", 潜在收益: {profit_pct:+.2f}%"
                            except (TypeError, ZeroDivisionError):
                                potential_profit = ""
                        print(now_str(), f"  ├─ {grid['range']}{grid['in_range']} | 持仓: {grid['coin_qty']:.6f} {BASE_COIN_SYMBOL} | 买入价: {buy_price_str} USDC{potential_profit}{order_status}")
                
                # 显示有挂单的网格
                if pending_order_grids:
                    print(now_str(), f"⏳ 有挂单的网格 ({len(pending_order_grids)} 个):")
                    for grid in pending_order_grids:
                        side = "买单" if grid['status'] == 'buying' else "卖单"
                        print(now_str(), f"  ├─ {grid['range']}{grid['in_range']} | {side} | 订单ID: {grid['order_id']}")
                
                # 显示网格分布统计
                total_allocated_usdc = sum(float(grid_info['allocated_usdc']) for grid_info in active_grids.values())
                total_holding_value = decimal.Decimal('0')
                if 'sol_current_price_dec' in locals():
                    total_holding_value = sum(grid_info['coin_qty'] * sol_current_price_dec for grid_info in active_grids.values())
                
                print(now_str(), f"📈 网格统计:")
                print(now_str(), f"  ├─ 总网格数: {len(active_grids)}")
                print(now_str(), f"  ├─ 买入状态: {len(buying_grids)} 个")
                print(now_str(), f"  ├─ 卖出状态: {len(selling_grids)} 个")
                print(now_str(), f"  ├─ 有挂单: {len(pending_order_grids)} 个")
                print(now_str(), f"  ├─ 分配资金总额: {total_allocated_usdc:.2f} USDC")
                print(now_str(), f"  └─ 持仓总价值: {total_holding_value:.2f} USDC")
                
                # 显示当前价格在网格中的位置
                if 'sol_current_price_dec' in locals():
                    current_grid = None
                    for grid_id_str, grid_info in active_grids.items():
                        grid_floor_str, grid_ceiling_str = grid_id_str.split('-')
                        grid_floor = decimal.Decimal(grid_floor_str)
                        grid_ceiling = decimal.Decimal(grid_ceiling_str)
                        if sol_current_price_dec >= grid_floor and sol_current_price_dec < grid_ceiling:
                            current_grid = grid_id_str
                            break
                    
                    if current_grid:
                        print(now_str(), f"🎯 当前价格 {sol_current_price_dec} USDC 位于网格: {current_grid}")
                    else:
                        print(now_str(), f"⚠️  当前价格 {sol_current_price_dec} USDC 不在任何网格范围内")
            else:
                print(now_str(), "⚠️  网格系统未初始化或无活跃网格")
            
            print(now_str(), "=" * 60)
            
            # 每轮循环结束时写入日志文件
            current_usdc_available = float(bal.get('USDC', {}).get('available', 0)) if 'bal' in locals() and isinstance(bal, dict) else 0.0
            current_base_coin_available = float(bal.get(BASE_COIN_SYMBOL, {}).get('available', 0)) if 'bal' in locals() and isinstance(bal, dict) else 0.0
            current_sol_price = float(sol_usdc_ticker['lastPrice']) if 'sol_usdc_ticker' in locals() and sol_usdc_ticker else 0.0 # 变量名改为sol_current_price
            current_sol_value = current_base_coin_available * current_sol_price # 用 base_coin_available
            
            # 记录余额更新
            total_value = current_usdc_available + current_sol_value
            enhanced_logger.log_balance_update(current_usdc_available, current_base_coin_available, total_value, current_sol_price)
            
            # 记录网格状态
            if 'active_grids' in locals() or 'active_grids' in globals(): # 确保 active_grids 存在
                enhanced_logger.log_grid_status(active_grids, current_sol_price)
                
                grid_states_for_log_final = []
                for grid_id_str_final, grid_info_final in active_grids.items():
                    last_buy_price_val_final = str(grid_info_final['last_buy_price']) if grid_info_final['last_buy_price'] is not None else 'N/A'
                    grid_states_for_log_final.append(f"{grid_id_str_final}:{grid_info_final['status']}:{last_buy_price_val_final}:{grid_info_final['coin_qty']:.6f}:{grid_info_final['order_id'] if grid_info_final['order_id'] else 'None'}")
            else:
                grid_states_for_log_final = ["Grid system not initialized."]
            
            active_grids_summary_final = "; ".join(grid_states_for_log_final)
            
            # 获取积分统计用于日志记录
            points_summary_for_log = points_tracker.get_points_summary()
            
            # 获取风险管理摘要用于日志记录
            risk_summary_for_log = risk_manager.get_risk_summary()
            
            # 获取网格优化摘要用于日志记录
            optimization_summary_for_log = grid_optimizer.get_optimization_summary()

            log_entry = (
                f"{now_str()},"
                f"{success_buy},{success_sell},{total_fees_usdc:.6f},"
                f"{current_usdc_available:.2f},{current_base_coin_available:.6f},{current_sol_value:.2f},"
                f"{current_sol_price},{active_grids_summary_final},"
                f"{points_summary_for_log['estimated_points']:.2f},{points_summary_for_log['trading_volume_weekly']:.2f},{points_summary_for_log['maker_ratio']:.2%},"
                f"{risk_summary_for_log['total_pnl']:.2f},{risk_summary_for_log['daily_pnl']:.2f},{risk_summary_for_log['max_drawdown']:.2f},"
                f"{optimization_summary_for_log['current_volatility']:.4f},{optimization_summary_for_log['success_rate']:.2%},{optimization_summary_for_log['avg_profit_per_trade']:.6f}"
            )
            write_to_log_file(log_entry)
            
            # 记录循环执行时间
            loop_execution_time = time.time() - loop_start_time
            performance_monitor.record_execution_time('main_trading_loop', loop_execution_time)
            
            print(now_str(), "--- 本轮决策结束 ---")

if __name__ == "__main__":
    asyncio.run(main_trading_loop())