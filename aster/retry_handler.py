#!/usr/bin/env python3
"""
智能重试处理器
提供重试装饰器、熔断器机制和错误分类处理
"""

import time
import logging
from functools import wraps
from typing import Callable, Any, Dict, List, Optional
from datetime import datetime, timedelta
import urllib.error
import ssl
import json

logger = logging.getLogger(__name__)

class CircuitBreaker:
    """熔断器机制"""
    
    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 300, half_open_max_calls: int = 3):
        """
        初始化熔断器
        
        Args:
            failure_threshold: 连续失败阈值
            recovery_timeout: 恢复超时时间（秒）
            half_open_max_calls: 半开状态最大调用次数
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls
        
        self.failure_count = 0
        self.last_failure_time = None
        self.state = 'CLOSED'  # CLOSED, OPEN, HALF_OPEN
        self.half_open_calls = 0
        
    def call(self, func: Callable, *args, **kwargs) -> Any:
        """执行函数调用，应用熔断器逻辑"""
        
        if self.state == 'OPEN':
            if self._should_attempt_reset():
                self.state = 'HALF_OPEN'
                self.half_open_calls = 0
                logger.info("🔄 熔断器进入半开状态，尝试恢复")
            else:
                raise Exception(f"熔断器开启中，距离下次尝试还有 {self._time_until_retry():.0f} 秒")
        
        if self.state == 'HALF_OPEN':
            if self.half_open_calls >= self.half_open_max_calls:
                raise Exception("熔断器半开状态调用次数已达上限")
        
        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise e
    
    def _should_attempt_reset(self) -> bool:
        """检查是否应该尝试重置熔断器"""
        if self.last_failure_time is None:
            return True
        return datetime.now() - self.last_failure_time > timedelta(seconds=self.recovery_timeout)
    
    def _time_until_retry(self) -> float:
        """计算距离下次重试的时间"""
        if self.last_failure_time is None:
            return 0
        elapsed = datetime.now() - self.last_failure_time
        return max(0, self.recovery_timeout - elapsed.total_seconds())
    
    def _on_success(self):
        """成功时的处理"""
        if self.state == 'HALF_OPEN':
            self.half_open_calls += 1
            if self.half_open_calls >= self.half_open_max_calls:
                self.state = 'CLOSED'
                self.failure_count = 0
                logger.info("✅ 熔断器已关闭，服务恢复正常")
        else:
            self.failure_count = 0
    
    def _on_failure(self):
        """失败时的处理"""
        self.failure_count += 1
        self.last_failure_time = datetime.now()
        
        if self.state == 'HALF_OPEN':
            self.state = 'OPEN'
            logger.warning(f"⚠️ 熔断器重新开启，连续失败 {self.failure_count} 次")
        elif self.failure_count >= self.failure_threshold:
            self.state = 'OPEN'
            logger.warning(f"🚨 熔断器开启！连续失败 {self.failure_count} 次，暂停 {self.recovery_timeout} 秒")

class ErrorClassifier:
    """错误分类器"""
    
    # 临时性错误 - 可以重试
    TEMPORARY_ERRORS = [
        'timeout',
        'connection',
        'ssl',
        'eof',
        'network',
        'temporary',
        '400',  # Bad Request (在加密货币交易中有时是临时的)
        '502',  # Bad Gateway
        '503',  # Service Unavailable
        '504',  # Gateway Timeout
        '429',  # Too Many Requests
    ]
    
    # 永久性错误关键词
    PERMANENT_ERRORS = [
        '401',  # Unauthorized (API密钥错误)
        '403',  # Forbidden (权限不足)
        '404',  # Not Found
        '422',  # Unprocessable Entity
    ]
    
    @classmethod
    def is_retryable(cls, error: Exception) -> bool:
        """判断错误是否可重试"""
        error_str = str(error).lower()
        
        # 检查是否为永久性错误
        for permanent_error in cls.PERMANENT_ERRORS:
            if permanent_error in error_str:
                return False
        
        # 检查是否为临时性错误
        for temp_error in cls.TEMPORARY_ERRORS:
            if temp_error in error_str:
                return True
        
        # 特殊处理SSL和网络错误
        if isinstance(error, (urllib.error.URLError, ssl.SSLError, OSError)):
            return True
        
        # 默认认为可重试（保守策略）
        return True
    
    @classmethod
    def get_error_type(cls, error: Exception) -> str:
        """获取错误类型"""
        if cls.is_retryable(error):
            return "TEMPORARY"
        else:
            return "PERMANENT"

def smart_retry(max_retries: int = 5, 
                base_delay: float = 1.0, 
                max_delay: float = 60.0, 
                exponential_base: float = 2.0,
                use_circuit_breaker: bool = True):
    """
    智能重试装饰器
    
    Args:
        max_retries: 最大重试次数
        base_delay: 基础延迟时间（秒）
        max_delay: 最大延迟时间（秒）
        exponential_base: 指数退避基数
        use_circuit_breaker: 是否使用熔断器
    """
    
    # 全局熔断器实例
    if not hasattr(smart_retry, 'circuit_breaker'):
        smart_retry.circuit_breaker = CircuitBreaker()
    
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    # 如果使用熔断器，通过熔断器调用
                    if use_circuit_breaker:
                        return smart_retry.circuit_breaker.call(func, *args, **kwargs)
                    else:
                        return func(*args, **kwargs)
                        
                except Exception as e:
                    last_exception = e
                    
                    # 检查是否为永久性错误
                    if not ErrorClassifier.is_retryable(e):
                        logger.error(f"❌ 永久性错误，不重试: {e}")
                        raise e
                    
                    # 如果是最后一次尝试，直接抛出异常
                    if attempt == max_retries:
                        logger.error(f"❌ 重试 {max_retries} 次后仍失败: {e}")
                        raise e
                    
                    # 计算延迟时间（指数退避）
                    delay = min(base_delay * (exponential_base ** attempt), max_delay)
                    
                    error_type = ErrorClassifier.get_error_type(e)
                    logger.warning(f"⚠️ {error_type}错误 (尝试 {attempt + 1}/{max_retries + 1}): {e}")
                    logger.info(f"⏰ 等待 {delay:.1f} 秒后重试...")
                    
                    time.sleep(delay)
            
            # 如果所有重试都失败了
            if last_exception:
                raise last_exception
                
        return wrapper
    return decorator

def reset_circuit_breaker():
    """重置熔断器状态"""
    if hasattr(smart_retry, 'circuit_breaker'):
        smart_retry.circuit_breaker.state = 'CLOSED'
        smart_retry.circuit_breaker.failure_count = 0
        smart_retry.circuit_breaker.last_failure_time = None
        logger.info("🔄 熔断器已手动重置")

def get_circuit_breaker_status() -> Dict[str, Any]:
    """获取熔断器状态"""
    if hasattr(smart_retry, 'circuit_breaker'):
        cb = smart_retry.circuit_breaker
        return {
            'state': cb.state,
            'failure_count': cb.failure_count,
            'last_failure_time': cb.last_failure_time.isoformat() if cb.last_failure_time else None,
            'time_until_retry': cb._time_until_retry() if cb.state == 'OPEN' else 0
        }
    return {'state': 'NOT_INITIALIZED'}

# 预定义的重试装饰器
network_retry = smart_retry(max_retries=3, base_delay=2.0, max_delay=30.0)
api_retry = smart_retry(max_retries=5, base_delay=1.0, max_delay=60.0)
critical_retry = smart_retry(max_retries=8, base_delay=0.5, max_delay=120.0)