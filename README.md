# Aster Finance API 测试脚本

基于 [Aster Finance 期货API文档](https://github.com/asterdex/api-docs/blob/master/aster-finance-futures-api_CN.md) 开发的Python测试脚本。

## 功能特性

- ✅ 完整的API客户端实现
- ✅ 支持公开API（无需密钥）
- ✅ 支持私有API（需要密钥）
- ✅ 安全的配置管理
- ✅ 详细的错误处理
- ✅ 签名验证机制

## 文件结构

```
├── aster_api_client.py      # API客户端核心类
├── config_loader.py         # 配置加载器
├── config.json.template     # 配置文件模板
├── test_aster_api.py        # 完整测试脚本
├── test_public_api.py       # 公开API测试脚本
├── requirements.txt         # 依赖包列表
└── README.md               # 说明文档
```

## 快速开始

### 1. 安装依赖

```bash
# 激活虚拟环境
source venv/bin/activate

# 安装依赖（可选，项目使用内置模块）
pip install -r requirements.txt
```

### 2. 配置API密钥（可选）

```bash
# 复制配置模板
cp aster/config.json.template aster/config.json

# 编辑配置文件，填入您的API密钥
vim aster/config.json
```

### 3. 运行测试

```bash
# 运行公开API测试（无需API密钥）
python -m aster.test_public_api

# 运行完整测试（需要API密钥）
python -m aster.test_aster_api
```

## API客户端使用示例

### 基本使用

```python
from aster import AsterFinanceClient

# 创建客户端（公开API）
client = AsterFinanceClient()

# 测试连通性
result = client.ping()
print(result)

# 获取服务器时间
time_info = client.get_server_time()
print(f"服务器时间: {time_info['serverTime']}")

# 获取交易对信息
exchange_info = client.get_exchange_info()
print(f"交易对数量: {len(exchange_info['symbols'])}")
```

### 使用API密钥

```python
from aster import AsterFinanceClient, ConfigLoader

# 加载配置
config = ConfigLoader()
credentials = config.get_api_credentials()

# 创建客户端
client = AsterFinanceClient(**credentials)

# 获取账户信息
account_info = client.get_account_info()
print(f"账户余额: {account_info['totalWalletBalance']}")

# 获取持仓信息
positions = client.get_position_risk()
print(f"持仓数量: {len(positions)}")
```

## 支持的API接口

### 公开接口（无需API密钥）

- `ping()` - 测试连通性
- `get_server_time()` - 获取服务器时间
- `get_exchange_info()` - 获取交易规则
- `get_depth(symbol, limit)` - 获取深度信息
- `get_recent_trades(symbol, limit)` - 获取近期成交
- `get_klines(symbol, interval, limit)` - 获取K线数据
- `get_24hr_ticker(symbol)` - 获取24小时价格变动
- `get_ticker_price(symbol)` - 获取最新价格

### 私有接口（需要API密钥）

- `get_account_info()` - 获取账户信息
- `get_position_risk()` - 获取持仓风险
- `place_order()` - 下单

## 安全说明

- ⚠️ 请妥善保管您的API密钥
- ⚠️ 不要将包含密钥的配置文件提交到版本控制
- ⚠️ 建议使用只读权限的API密钥进行测试
- ⚠️ 生产环境请使用环境变量存储密钥

## 错误处理

脚本包含完整的错误处理机制：

- 网络连接错误
- API密钥格式错误
- 签名验证失败
- 请求频率限制
- 服务器错误

## 注意事项

1. 请遵守API访问频率限制
2. 测试环境和生产环境使用不同的API密钥
3. 定期检查API文档更新
4. 建议先在测试网络上验证功能

## 相关链接

- [Aster Finance 官网](https://asterdex.com)
- [API文档](https://github.com/asterdex/api-docs/blob/master/aster-finance-futures-api_CN.md)
- [Python requests 文档](https://docs.python-requests.org/)