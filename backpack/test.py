import asyncio
from datetime import datetime
import os # 导入 os 模块来访问环境变量
from dotenv import load_dotenv # 导入 load_dotenv 函数

# 导入 BPX 客户端 (根据你的实际安装或源码来)
from bpx.account import Account
from bpx.public import Public

# 在代码最前面加载 .env 文件中的环境变量
load_dotenv()

def now_str():
    """返回当前时间戳的格式化字符串。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

async def test_bpx_api_from_env(): # 新的函数名
    """
    测试 BPX API 客户端的基本功能，从 .env 文件加载密钥。
    """
    # 从环境变量中获取 API Key 和 Secret Key
    # 使用 os.getenv() 来安全地获取环境变量
    API_KEY = os.getenv("BPX_API_KEY") 
    API_SECRET = os.getenv("BPX_API_SECRET")

    print(now_str(), "开始测试 BPX API (从 .env 文件加载密钥)...")

    try:
        # --- 1. 测试公共 API ---
        print(now_str(), "测试公共 API: 获取服务器时间...")
        public_client = Public()
        server_time =  public_client.get_time()
        print(now_str(), f"服务器时间获取成功: {server_time}")

        print(now_str(), "测试公共 API: 获取市场列表...")
        markets =  public_client.get_markets()
        print(now_str(), f"市场数量获取成功: {len(markets)} 个市场")
        if markets:
            print(now_str(), f"部分市场示例: {markets[0]['symbol']}, {markets[1]['symbol']}...")
        else:
            print(now_str(), "未获取到任何市场信息。")

        print(now_str(), "测试公共 API: 获取所有 tickers (行情)...")
        tickers =  public_client.get_tickers()
        print(now_str(), f"Tickers 数量获取成功: {len(tickers)}")
        if tickers:
            btc_usdc_ticker = next((t for t in tickers if t.get('symbol') == 'BTC_USDC'), None)
            if btc_usdc_ticker:
                print(now_str(), f"BTC_USDC 最新价格: {btc_usdc_ticker.get('lastPrice')}")
            else:
                print(now_str(), "未找到 BTC_USDC 的 ticker 信息。")
        else:
            print(now_str(), "未获取到任何 ticker 信息。")


        # --- 2. 测试账户 API (需要有效的 API_KEY 和 API_SECRET) ---
        # 检查是否成功从 .env 文件加载了密钥
        if not API_KEY or not API_SECRET:
            print(now_str(), "警告: 未能从 .env 文件加载 API 密钥。跳过账户 API 测试。")
            print(now_str(), "请确保 .env 文件存在且格式正确，并且密钥名称与代码中一致。")
        else:
            print(now_str(), "测试账户 API: 初始化 Account 客户端...")
            # 根据你提供的 Account 类源码，这里使用 public_key 和 secret_key
            account_client = Account(public_key=API_KEY, secret_key=API_SECRET) 

            print(now_str(), "测试账户 API: 获取余额 (get_balances)...")
            balance =  account_client.get_balances() 
            if isinstance(balance, dict):
                print(now_str(), "账户余额获取成功:")
                for asset, info in balance.items():
                    print(f"  {asset}: 可用={info.get('available', 'N/A')}, 冻结={info.get('onHold', 'N/A')}")
            else:
                print(now_str(), f"获取余额失败或返回格式非字典: {balance}")

            print(now_str(), "测试账户 API: 获取未完成订单 (get_open_orders)...")
            open_orders =  account_client.get_open_orders(symbol='BTC_USDC') 
            if isinstance(open_orders, list):
                print(now_str(), f"BTC_USDC 未完成订单数量: {len(open_orders)} 个订单")
                if open_orders:
                    print(now_str(), f"首个未完成订单示例: {open_orders[0]}")
            else:
                print(now_str(), f"获取未完成订单失败或返回格式非列表: {open_orders}")

        print(now_str(), "BPX API 基本测试完成。")

    except Exception as e:
        print(now_str(), f"测试过程中发生错误: {e}")
        print(now_str(), "请检查：")
        print("  1. 网络连接是否稳定。")
        print("  2. `bpx-api-client` 库是否已正确安装 (`pip install bpx-api-client`)。")
        print("  3. `.env` 文件是否存在于与脚本相同的目录中，并且其中的 API 密钥是否正确且有效。")
        print("  4. 你的 IP 地址是否在交易所的白名单中（如果设置了）。")
        print("  5. `bpx-api-client` 库的版本，因为不同版本的方法名和参数可能有所不同。")


if __name__ == "__main__":
    asyncio.run(test_bpx_api_from_env())