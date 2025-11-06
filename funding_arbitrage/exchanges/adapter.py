import ccxt

def make_exchange(config: dict, proxies: dict | None = None) -> ccxt.Exchange:
    """根据配置创建并返回一个 ccxt 交易所实例。"""
    exchange_id = config.get('id')
    if not exchange_id:
        raise ValueError("Exchange 'id' not found in config")

    if not hasattr(ccxt, exchange_id):
        raise ValueError(f"Exchange '{exchange_id}' is not supported by ccxt")

    exchange_class = getattr(ccxt, exchange_id)
    
    # 准备 ccxt 初始化所需的参数
    ccxt_config = {
        'apiKey': config.get('apiKey'),
        'secret': config.get('secret'),
        'password': config.get('password'),
        'options': config.get('options', {}),
    }

    # 应用代理设置
    if proxies:
        ccxt_config['proxies'] = proxies

    # 移除值为 None 的键，避免 ccxt 出错
    ccxt_config = {k: v for k, v in ccxt_config.items() if v is not None}

    exchange = exchange_class(ccxt_config)
    
    # 设置超时
    # 注意：ccxt 的超时单位是毫秒
    timeout_sec = config.get('timeout_sec', 20)
    exchange.timeout = timeout_sec * 1000

    return exchange
