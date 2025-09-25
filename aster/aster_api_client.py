import hashlib
import hmac
import time
import json
import urllib.request
import urllib.parse
import urllib.error
import ssl
from typing import Dict, Any, Optional


class AsterFinanceClient:
    """
    Aster Finance 期货API客户端
    """
    
    def __init__(self, api_key: str = "", secret_key: str = "", base_url: str = "https://fapi.asterdex.com"):
        """
        初始化客户端
        
        Args:
            api_key: API密钥
            secret_key: 密钥
            base_url: API基础URL
        """
        self.api_key = api_key
        self.secret_key = secret_key
        self.base_url = base_url
        
        # 设置默认请求头
        self.headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'X-MBX-APIKEY': self.api_key,
            'User-Agent': 'AsterFinance-Python-Client/1.0'
        }
    
    def _generate_signature(self, params: Dict[str, Any]) -> str:
        """
        生成签名
        
        Args:
            params: 请求参数
            
        Returns:
            签名字符串
        """
        query_string = urllib.parse.urlencode(params)
        return hmac.new(
            self.secret_key.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
    
    def _request(self, method: str, endpoint: str, params: Dict[str, Any] = None, signed: bool = False) -> Dict[str, Any]:
        """
        发送HTTP请求
        
        Args:
            method: HTTP方法
            endpoint: API端点
            params: 请求参数
            signed: 是否需要签名
            
        Returns:
            响应数据
        """
        if params is None:
            params = {}
        
        url = f"{self.base_url}{endpoint}"
        
        # 如果需要签名，添加时间戳和签名
        if signed:
            params['timestamp'] = int(time.time() * 1000)
            params['signature'] = self._generate_signature(params)
        
        try:
            if method.upper() == 'GET':
                if params:
                    query_string = urllib.parse.urlencode(params)
                    url = f"{url}?{query_string}"
                
                req = urllib.request.Request(url, headers=self.headers)
                
            elif method.upper() == 'POST':
                data = urllib.parse.urlencode(params).encode('utf-8')
                req = urllib.request.Request(url, data=data, headers=self.headers)
                
            elif method.upper() == 'DELETE':
                if params:
                    query_string = urllib.parse.urlencode(params)
                    url = f"{url}?{query_string}"
                
                req = urllib.request.Request(url, headers=self.headers)
                req.get_method = lambda: 'DELETE'
                
            else:
                raise ValueError(f"不支持的HTTP方法: {method}")
            
            # 创建SSL上下文，忽略证书验证（仅用于测试）
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            
            with urllib.request.urlopen(req, timeout=30, context=ssl_context) as response:
                response_data = response.read().decode('utf-8')
                return json.loads(response_data)
                
        except urllib.error.HTTPError as e:
            error_msg = e.read().decode('utf-8')
            print(f"HTTP错误 {e.code}: {error_msg}")
            try:
                error_data = json.loads(error_msg)
                print(f"错误详情: {error_data}")
            except:
                pass
            raise Exception(f"HTTP {e.code}: {error_msg}")
            
        except urllib.error.URLError as e:
            print(f"网络错误: {e}")
            raise
            
        except json.JSONDecodeError as e:
            print(f"JSON解析错误: {e}")
            raise
            
        except Exception as e:
            print(f"请求错误: {e}")
            raise
    
    # 公开接口 - 不需要API密钥
    def ping(self) -> Dict[str, Any]:
        """测试服务器连通性"""
        return self._request('GET', '/fapi/v1/ping')
    
    def get_server_time(self) -> Dict[str, Any]:
        """获取服务器时间"""
        return self._request('GET', '/fapi/v1/time')
    
    def get_exchange_info(self) -> Dict[str, Any]:
        """获取交易规则和交易对信息"""
        return self._request('GET', '/fapi/v1/exchangeInfo')
    
    def get_depth(self, symbol: str, limit: int = 100) -> Dict[str, Any]:
        """
        获取深度信息
        
        Args:
            symbol: 交易对符号
            limit: 返回的深度数量
        """
        params = {'symbol': symbol, 'limit': limit}
        return self._request('GET', '/fapi/v1/depth', params)
    
    def get_recent_trades(self, symbol: str, limit: int = 500) -> Dict[str, Any]:
        """
        获取近期成交
        
        Args:
            symbol: 交易对符号
            limit: 返回的成交数量
        """
        params = {'symbol': symbol, 'limit': limit}
        return self._request('GET', '/fapi/v1/trades', params)
    
    def get_klines(self, symbol: str, interval: str, limit: int = 500) -> Dict[str, Any]:
        """
        获取K线数据
        
        Args:
            symbol: 交易对符号
            interval: 时间间隔
            limit: 返回的K线数量
        """
        params = {'symbol': symbol, 'interval': interval, 'limit': limit}
        return self._request('GET', '/fapi/v1/klines', params)
    
    def get_24hr_ticker(self, symbol: str = None) -> Dict[str, Any]:
        """
        获取24小时价格变动情况
        
        Args:
            symbol: 交易对符号，如果为空则返回所有交易对
        """
        params = {}
        if symbol:
            params['symbol'] = symbol
        return self._request('GET', '/fapi/v1/ticker/24hr', params)
    
    def get_ticker_price(self, symbol: str = None) -> Dict[str, Any]:
        """
        获取最新价格
        
        Args:
            symbol: 交易对符号，如果为空则返回所有交易对
        """
        params = {}
        if symbol:
            params['symbol'] = symbol
        return self._request('GET', '/fapi/v1/ticker/price', params)
    
    # 需要签名的接口
    def get_account_info(self) -> Dict[str, Any]:
        """获取账户信息"""
        return self._request('GET', '/fapi/v2/account', signed=True)
    
    def get_position_risk(self) -> Dict[str, Any]:
        """获取用户持仓风险"""
        return self._request('GET', '/fapi/v2/positionRisk', signed=True)
    
    def place_order(self, symbol: str, side: str, order_type: str, quantity: float, 
                   price: float = None, **kwargs) -> Dict[str, Any]:
        """
        下单
        
        Args:
            symbol: 交易对符号
            side: 买卖方向 BUY/SELL
            order_type: 订单类型 LIMIT/MARKET等
            quantity: 数量
            price: 价格（限价单必填）
            **kwargs: 其他参数
        """
        params = {
            'symbol': symbol,
            'side': side,
            'type': order_type,
            'quantity': quantity
        }
        
        if price is not None:
            params['price'] = price
            
        params.update(kwargs)
        return self._request('POST', '/fapi/v1/order', params, signed=True)