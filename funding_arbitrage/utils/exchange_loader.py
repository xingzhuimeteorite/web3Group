import ccxt

def get_exchange_from_config(config):
    """从配置中获取并初始化永续合约交易所实例。"""
    try:
        exchange_id = config['exchanges']['perp']['id']
        api_key = config['exchanges']['perp']['apiKey']
        secret = config['exchanges']['perp']['secret']
        password = config['exchanges']['perp'].get('password')

        exchange_class = getattr(ccxt, exchange_id)
        exchange = exchange_class({
            'apiKey': api_key,
            'secret': secret,
            'password': password,
            'options': {
                'defaultType': 'swap',
            },
        })

        # 设置代理
        if config.get('network') and config['network'].get('proxies'):
            exchange.proxies = config['network']['proxies']

        return exchange

    except KeyError as e:
        print(f"配置错误：缺少关键字段 {e}")
        return None
    except AttributeError:
        print(f"配置错误：不支持的交易所 ID '{exchange_id}'")
        return None
    except Exception as e:
        print(f"初始化交易所时发生未知错误: {e}")
        return None