# Aster Finance SOL双向交易策略

基于 [Aster Finance 期货API](https://github.com/asterdex/api-docs/blob/master/aster-finance-futures-api_CN.md) 开发的SOL智能交易策略。

## 💡 手续费设计思路

### 核心理念
我们的策略围绕**手续费优化**和**积分获取**设计，通过精确的手续费计算和持仓时间控制，实现盈利最大化。

### 手续费计算机制

#### 1. 双重手续费考虑
```python
# 开仓手续费
open_fee = trade_amount * 0.0005  # 0.05%

# 平仓手续费  
close_fee = trade_amount * 0.0005  # 0.05%

# 总手续费成本
total_fee = open_fee + close_fee  # 约0.1%
```

#### 2. 盈利阈值设计
- **止盈阈值**: 1.5% (覆盖手续费后仍有1.4%净利润)
- **止损阈值**: 1.0% (控制最大损失)
- **最小盈利**: 必须覆盖双向手续费成本

#### 3. 积分优化策略
- **最小持仓时间**: 1小时 (获得5倍积分)
- **时间vs收益**: 平衡快速止盈和积分获取
- **复合收益**: 积分价值 + 交易盈利

### 风险控制逻辑

#### 1. 动态止盈止损
```python
# 多单
take_profit = entry_price * (1 + 0.015)  # +1.5%
stop_loss = entry_price * (1 - 0.01)    # -1.0%

# 空单  
take_profit = entry_price * (1 - 0.015)  # -1.5%
stop_loss = entry_price * (1 + 0.01)    # +1.0%
```

#### 2. 手续费覆盖检查
```python
# 确保盈利能覆盖手续费
min_profit_needed = total_fee + 0.001  # 额外0.1%缓冲
if current_profit >= min_profit_needed:
    # 执行止盈
```

#### 3. 时间加权决策
- 持仓 < 1小时: 需要更高盈利才止盈
- 持仓 ≥ 1小时: 达到最小盈利即可止盈
- 积分价值计入总收益考量

---

## 🚀 使用方法

### 环境准备

#### 1. 安装依赖
```bash
# 进入项目目录
cd /Users/solwhite/web3/web3Group

# 激活虚拟环境（如果有）
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

#### 2. 配置API密钥
```bash
# 复制配置模板
cp aster/config.json.template aster/config.json

# 编辑配置文件
vim aster/config.json
```

配置文件格式：
```json
{
    "api_key": "your_api_key_here",
    "secret_key": "your_secret_key_here", 
    "base_url": "https://api.asterdex.com"
}
```

### 策略运行

#### 1. 基础运行
```bash
# 进入策略目录
cd aster

# 运行双向交易策略
python sol_long_strategy.py
```

#### 2. 参数配置

##### 开仓次数设置
编辑 `sol_long_strategy.py` 第704行：
```python
max_loops = 100  # 修改为你想要的开仓次数
```

##### 交易方向设置  
编辑 `sol_long_strategy.py` 第712行：
```python
strategy_direction = "auto"  # 自动检测方向
# strategy_direction = "long"   # 只做多
# strategy_direction = "short"  # 只做空
```

##### 策略参数调整
编辑策略类初始化参数（第44-50行）：
```python
self.position_size = 50.0        # 每次开仓金额(USDT)
self.leverage = 5                # 杠杆倍数
self.fee_rate = 0.0005          # 手续费率 0.05%
self.profit_threshold = 0.015    # 止盈阈值 1.5%
self.stop_loss_threshold = 0.01  # 止损阈值 1.0%
self.min_holding_time = 3600     # 最小持仓时间(秒)
```

### 监控和控制

#### 1. 实时监控
策略运行时会显示：
- 当前轮次进度
- 账户余额变化
- 持仓状态和盈亏
- 手续费计算
- 积分获取情况

#### 2. 安全退出
- 按 `Ctrl+C` 安全中断策略
- 自动检查当前持仓状态
- 生成最终交易报告

#### 3. 日志查看
```bash
# 查看策略日志
tail -f sol_strategy.log

# 查看详细运行记录
cat sol_strategy.log | grep "盈亏"
```

### 高级功能

#### 1. 自动方向检测
- **时间策略**: 奇数小时做多，偶数小时做空
- **可扩展**: 支持添加技术指标判断
- **智能切换**: 根据市场情况自动调整

#### 2. 风险管理
- **余额检查**: 每轮开始前检查资金充足性
- **最大循环**: 防止无限循环运行
- **异常处理**: 网络错误、API错误自动恢复

#### 3. 性能优化
- **批量处理**: 减少API调用频率
- **缓存机制**: 避免重复数据请求
- **异步执行**: 提高响应速度

### 注意事项

#### ⚠️ 风险提示
- 期货交易存在爆仓风险，请合理控制仓位
- 建议先在测试环境验证策略效果
- 密切关注市场波动，及时调整参数

#### 💡 最佳实践
- **小额测试**: 先用小资金测试策略
- **参数调优**: 根据市场情况调整止盈止损
- **定期检查**: 监控策略表现和资金安全
- **备份配置**: 保存有效的参数配置

#### 📊 性能评估
- 关注胜率和盈亏比
- 计算年化收益率
- 评估最大回撤风险
- 对比基准收益

---

## 📁 文件结构

```
aster/
├── sol_long_strategy.py         # 主策略文件
├── aster_api_client.py          # API客户端
├── config_loader.py             # 配置加载器
├── config.json                  # API配置文件
├── points_monitor.py            # 积分监控
├── test_account.py              # 账户测试
└── sol_strategy.log             # 策略日志
```

## 🔗 相关链接

- [Aster Finance 官网](https://asterdex.com)
- [API文档](https://github.com/asterdex/api-docs)
- [策略源码](./aster/sol_long_strategy.py)