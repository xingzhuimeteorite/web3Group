"""
增强的异常处理和错误恢复机制
Enhanced Exception Handling and Error Recovery Module
"""

import asyncio
import logging
import traceback
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Callable, List
from enum import Enum
import json
import os

class ErrorSeverity(Enum):
    """错误严重程度"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class ErrorType(Enum):
    """错误类型"""
    NETWORK = "network"
    API = "api"
    TRADING = "trading"
    BALANCE = "balance"
    ORDER = "order"
    SYSTEM = "system"
    CONFIGURATION = "configuration"

class BackpackErrorHandler:
    """Backpack交易系统错误处理器"""
    
    def __init__(self, config):
        self.config = config
        self.error_log_file = config.get('error_handling.error_log_file', 'logs/error_recovery.log')
        self.max_retry_attempts = config.get('error_handling.max_retry_attempts', 3)
        self.retry_delay_base = config.get('error_handling.retry_delay_base', 2)  # 基础重试延迟（秒）
        self.circuit_breaker_threshold = config.get('error_handling.circuit_breaker_threshold', 5)
        self.circuit_breaker_timeout = config.get('error_handling.circuit_breaker_timeout', 300)  # 5分钟
        
        # 错误统计
        self.error_counts = {}
        self.circuit_breakers = {}
        self.last_errors = {}
        
        # 恢复策略
        self.recovery_strategies = {
            ErrorType.NETWORK: self._handle_network_error,
            ErrorType.API: self._handle_api_error,
            ErrorType.TRADING: self._handle_trading_error,
            ErrorType.BALANCE: self._handle_balance_error,
            ErrorType.ORDER: self._handle_order_error,
            ErrorType.SYSTEM: self._handle_system_error,
            ErrorType.CONFIGURATION: self._handle_config_error
        }
        
        # 确保日志目录存在
        os.makedirs(os.path.dirname(self.error_log_file), exist_ok=True)
        
        # 设置日志记录器
        self.logger = logging.getLogger('BackpackErrorHandler')
        self.logger.setLevel(logging.INFO)
        
        # 文件处理器
        file_handler = logging.FileHandler(self.error_log_file)
        file_handler.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(formatter)
        self.logger.addHandler(file_handler)
    
    def classify_error(self, error: Exception, context: Dict[str, Any] = None) -> tuple:
        """分类错误并确定严重程度"""
        error_str = str(error).lower()
        error_type = str(type(error).__name__).lower()
        
        # 网络相关错误
        if any(keyword in error_str for keyword in ['connection', 'timeout', 'network', 'unreachable']):
            return ErrorType.NETWORK, ErrorSeverity.MEDIUM
        
        # API相关错误
        if any(keyword in error_str for keyword in ['api', 'unauthorized', 'forbidden', 'rate limit']):
            if 'rate limit' in error_str:
                return ErrorType.API, ErrorSeverity.HIGH
            return ErrorType.API, ErrorSeverity.MEDIUM
        
        # 交易相关错误
        if any(keyword in error_str for keyword in ['insufficient', 'balance', 'order', 'trade']):
            if 'insufficient' in error_str:
                return ErrorType.BALANCE, ErrorSeverity.HIGH
            return ErrorType.TRADING, ErrorSeverity.MEDIUM
        
        # 订单相关错误
        if any(keyword in error_str for keyword in ['order not found', 'invalid order', 'order failed']):
            return ErrorType.ORDER, ErrorSeverity.MEDIUM
        
        # 配置相关错误
        if any(keyword in error_str for keyword in ['config', 'setting', 'parameter']):
            return ErrorType.CONFIGURATION, ErrorSeverity.HIGH
        
        # 系统错误
        if error_type in ['keyerror', 'attributeerror', 'typeerror']:
            return ErrorType.SYSTEM, ErrorSeverity.HIGH
        
        # 默认分类
        return ErrorType.SYSTEM, ErrorSeverity.MEDIUM
    
    async def handle_error(self, error: Exception, context: Dict[str, Any] = None, 
                          operation: str = None) -> Dict[str, Any]:
        """处理错误并尝试恢复"""
        error_type, severity = self.classify_error(error, context)
        
        # 记录错误
        self._log_error(error, error_type, severity, context, operation)
        
        # 更新错误统计
        self._update_error_stats(error_type, operation)
        
        # 检查熔断器
        if self._is_circuit_breaker_open(error_type, operation):
            return {
                'success': False,
                'action': 'circuit_breaker_open',
                'message': f'Circuit breaker is open for {error_type.value}',
                'retry_after': self.circuit_breaker_timeout
            }
        
        # 执行恢复策略
        recovery_result = await self._execute_recovery_strategy(error, error_type, severity, context, operation)
        
        return recovery_result
    
    def _log_error(self, error: Exception, error_type: ErrorType, severity: ErrorSeverity,
                   context: Dict[str, Any], operation: str):
        """记录错误详情"""
        error_info = {
            'timestamp': datetime.now().isoformat(),
            'error_type': error_type.value,
            'severity': severity.value,
            'operation': operation,
            'error_message': str(error),
            'error_class': type(error).__name__,
            'context': context or {},
            'traceback': traceback.format_exc()
        }
        
        self.logger.error(json.dumps(error_info, indent=2))
    
    def _update_error_stats(self, error_type: ErrorType, operation: str):
        """更新错误统计"""
        key = f"{error_type.value}_{operation}" if operation else error_type.value
        
        if key not in self.error_counts:
            self.error_counts[key] = 0
        
        self.error_counts[key] += 1
        self.last_errors[key] = datetime.now()
    
    def _is_circuit_breaker_open(self, error_type: ErrorType, operation: str) -> bool:
        """检查熔断器是否开启"""
        key = f"{error_type.value}_{operation}" if operation else error_type.value
        
        # 检查错误次数是否超过阈值
        if self.error_counts.get(key, 0) >= self.circuit_breaker_threshold:
            # 检查是否在熔断时间内
            if key in self.circuit_breakers:
                if datetime.now() - self.circuit_breakers[key] < timedelta(seconds=self.circuit_breaker_timeout):
                    return True
                else:
                    # 熔断时间已过，重置计数器
                    self.error_counts[key] = 0
                    del self.circuit_breakers[key]
            else:
                # 首次触发熔断器
                self.circuit_breakers[key] = datetime.now()
                return True
        
        return False
    
    async def _execute_recovery_strategy(self, error: Exception, error_type: ErrorType,
                                       severity: ErrorSeverity, context: Dict[str, Any],
                                       operation: str) -> Dict[str, Any]:
        """执行恢复策略"""
        if error_type in self.recovery_strategies:
            return await self.recovery_strategies[error_type](error, severity, context, operation)
        else:
            return await self._default_recovery_strategy(error, severity, context, operation)
    
    async def _handle_network_error(self, error: Exception, severity: ErrorSeverity,
                                   context: Dict[str, Any], operation: str) -> Dict[str, Any]:
        """处理网络错误"""
        if severity == ErrorSeverity.CRITICAL:
            return {
                'success': False,
                'action': 'stop_trading',
                'message': 'Critical network error, stopping trading',
                'retry_after': 600  # 10分钟后重试
            }
        
        # 指数退避重试
        for attempt in range(self.max_retry_attempts):
            delay = self.retry_delay_base ** (attempt + 1)
            await asyncio.sleep(delay)
            
            # 这里可以添加网络连接测试
            # 如果网络恢复，返回成功
            
        return {
            'success': False,
            'action': 'retry_later',
            'message': f'Network error after {self.max_retry_attempts} attempts',
            'retry_after': 300
        }
    
    async def _handle_api_error(self, error: Exception, severity: ErrorSeverity,
                               context: Dict[str, Any], operation: str) -> Dict[str, Any]:
        """处理API错误"""
        error_str = str(error).lower()
        
        if 'rate limit' in error_str:
            return {
                'success': False,
                'action': 'rate_limit_wait',
                'message': 'Rate limit exceeded, waiting',
                'retry_after': 60  # 等待1分钟
            }
        
        if 'unauthorized' in error_str or 'forbidden' in error_str:
            return {
                'success': False,
                'action': 'check_credentials',
                'message': 'Authentication error, check API credentials',
                'retry_after': 0
            }
        
        return {
            'success': False,
            'action': 'retry_with_delay',
            'message': 'API error, retrying with delay',
            'retry_after': 30
        }
    
    async def _handle_trading_error(self, error: Exception, severity: ErrorSeverity,
                                   context: Dict[str, Any], operation: str) -> Dict[str, Any]:
        """处理交易错误"""
        return {
            'success': False,
            'action': 'skip_trade',
            'message': 'Trading error, skipping current trade',
            'retry_after': 10
        }
    
    async def _handle_balance_error(self, error: Exception, severity: ErrorSeverity,
                                   context: Dict[str, Any], operation: str) -> Dict[str, Any]:
        """处理余额错误"""
        return {
            'success': False,
            'action': 'refresh_balance',
            'message': 'Balance error, need to refresh balance',
            'retry_after': 5
        }
    
    async def _handle_order_error(self, error: Exception, severity: ErrorSeverity,
                                 context: Dict[str, Any], operation: str) -> Dict[str, Any]:
        """处理订单错误"""
        return {
            'success': False,
            'action': 'cancel_and_retry',
            'message': 'Order error, cancel and retry',
            'retry_after': 15
        }
    
    async def _handle_system_error(self, error: Exception, severity: ErrorSeverity,
                                  context: Dict[str, Any], operation: str) -> Dict[str, Any]:
        """处理系统错误"""
        if severity == ErrorSeverity.CRITICAL:
            return {
                'success': False,
                'action': 'emergency_stop',
                'message': 'Critical system error, emergency stop',
                'retry_after': 0
            }
        
        return {
            'success': False,
            'action': 'continue_with_caution',
            'message': 'System error, continuing with caution',
            'retry_after': 30
        }
    
    async def _handle_config_error(self, error: Exception, severity: ErrorSeverity,
                                  context: Dict[str, Any], operation: str) -> Dict[str, Any]:
        """处理配置错误"""
        return {
            'success': False,
            'action': 'reload_config',
            'message': 'Configuration error, need to reload config',
            'retry_after': 0
        }
    
    async def _default_recovery_strategy(self, error: Exception, severity: ErrorSeverity,
                                        context: Dict[str, Any], operation: str) -> Dict[str, Any]:
        """默认恢复策略"""
        if severity == ErrorSeverity.CRITICAL:
            return {
                'success': False,
                'action': 'emergency_stop',
                'message': 'Critical error, emergency stop',
                'retry_after': 0
            }
        
        return {
            'success': False,
            'action': 'retry_with_delay',
            'message': 'Unknown error, retrying with delay',
            'retry_after': 60
        }
    
    def get_error_statistics(self) -> Dict[str, Any]:
        """获取错误统计信息"""
        return {
            'error_counts': self.error_counts.copy(),
            'circuit_breakers': {k: v.isoformat() for k, v in self.circuit_breakers.items()},
            'last_errors': {k: v.isoformat() for k, v in self.last_errors.items()}
        }
    
    def reset_error_stats(self, error_type: str = None):
        """重置错误统计"""
        if error_type:
            if error_type in self.error_counts:
                del self.error_counts[error_type]
            if error_type in self.circuit_breakers:
                del self.circuit_breakers[error_type]
            if error_type in self.last_errors:
                del self.last_errors[error_type]
        else:
            self.error_counts.clear()
            self.circuit_breakers.clear()
            self.last_errors.clear()
    
    async def with_error_handling(self, func: Callable, *args, operation: str = None, **kwargs):
        """装饰器函数，为任何函数添加错误处理"""
        try:
            if asyncio.iscoroutinefunction(func):
                return await func(*args, **kwargs)
            else:
                return func(*args, **kwargs)
        except Exception as e:
            recovery_result = await self.handle_error(e, kwargs, operation)
            
            if recovery_result['action'] == 'emergency_stop':
                raise SystemExit("Emergency stop triggered by error handler")
            
            # 根据恢复策略决定是否重新抛出异常
            if recovery_result['retry_after'] > 0:
                await asyncio.sleep(recovery_result['retry_after'])
            
            # 重新抛出异常让调用者处理
            raise e