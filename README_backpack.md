# Backpack Exchange 网格交易策略

基于 [Backpack Exchange API](https://docs.backpack.exchange/) 开发的智能网格交易策略。

## 💡 网格交易设计思路

### 核心理念
我们的策略围绕**网格交易**和**积分获取**设计，通过在价格区间内设置多个买卖网格，捕捉市场波动获利，同时最大化 Backpack 积分收益。<mcreference link="https://support.backpack.exchange/exchange/programs/points" index="4">4</mcreference>

### 网格交易机制

#### 1. 网格布局策略
```python
# 网格参数配置
GRID_PRICE_INTERVAL = 40      # 每个网格价格区间 40 USDC
GRID_USDC_PER_ORDER = 50      # 每个网格下单金额 50 USDC  
NUM_GRIDS = 3                 # 总网格数量 3 个
OUT_WANT = 0.004              # 目标利润率 0.4%
```

#### 2. 动态网格定位
- **中心定位**: 以当前市价为中心，上下各布置网格
- **价格覆盖**: 确保网格覆盖合理的价格波动范围
- **自适应调整**: 根据市场价格动态调整网格位置

#### 3. 交易执行逻辑
```python
# 买入条件：价格跌入网格下沿
if current_price <= grid_floor:
    execute_buy_order()

# 卖出条件：价格涨至目标利润位
target_sell_price = last_buy_price * (1 + OUT_WANT)
if current_price >= target_sell_price:
    execute_sell_order()
```

### 手续费优化策略

#### 1. Backpack 手续费结构 <mcreference link="https://support.backpack.exchange/exchange/trading-fees" index="1">1</mcreference>
- **Maker 费率**: 0.085% (提供流动性)
- **Taker 费率**: 0.095% (消耗流动性)
- **VIP 等级**: 交易量越大，费率越低

#### 2. 费用计算与控制
```python
# 单次交易总成本估算
buy_fee = order_amount * 0.00095   # Taker 买入
sell_fee = order_amount * 0.00095  # Taker 卖出
total_fee = buy_fee + sell_fee     # 总手续费约 0.19%

# 确保利润覆盖手续费
min_profit_needed = total_fee + 0.001  # 额外缓冲
```

#### 3. 积分获取机制 <mcreference link="https://support.backpack.exchange/exchange/programs/points" index="4">4</mcreference>
- **交易量积分**: 每周根据交易活动分发积分
- **等级提升**: Bronze → Silver → Gold → Platinum → Diamond → Challenger
- **复合收益**: 交易利润 + 积分价值

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

#### 2. 配置 API 密钥
```bash
# 复制配置模板
cp backpack/config.json.template backpack/config.json

# 编辑配置文件
vim backpack/config.json
```

配置文件格式：
```json
{
    "api_key": "your_bpx_api_key_here",
    "secret_key": "your_bpx_secret_key_here",
    "base_url": "https://api.backpack.exchange",
    "testnet": false
}
```

### 策略运行

#### 1. 基础运行
```bash
# 进入策略目录
cd backpack

# 运行网格交易策略
python trade.py
```

#### 2. 参数配置

##### 网格策略设置
编辑 `config.json` 中的 `trading_settings` 部分：
```json
{
    "trading_settings": {
        "target_symbol": "ETH_USDC",        // 交易对
        "base_coin_symbol": "ETH",          // 基础币种
        "grid_price_interval": 40,          // 网格价格间隔
        "grid_usdc_per_order": 50,          // 每网格下单金额
        "num_grids": 3,                     // 网格数量
        "out_want": 0.004,                  // 目标利润率 0.4%
        "trade_pct": 100,                   // 交易百分比
        "delay_between_operations": 3,       // 操作间隔(秒)
        "delay_between_grids": 1            // 网格间隔(秒)
    }
}
```

##### 风险管理设置
```json
{
    "risk_management": {
        "max_loss_percentage": 5.0,         // 最大亏损百分比
        "stop_loss_enabled": true,          // 启用止损
        "max_position_size": 1000,          // 最大仓位
        "daily_loss_limit": 200             // 日亏损限制
    }
}
```

### 监控和控制

#### 1. 实时监控
策略运行时会显示：
- 网格状态和价格区间
- 买卖订单执行情况
- 账户余额变化
- 累计手续费统计
- 成功交易次数

#### 2. 日志记录
```bash
# 查看交易日志
tail -f trade_summary_log.txt

# 查看详细执行记录
cat trade_summary_log.txt | grep "成功"
```

#### 3. 安全退出
- 按 `Ctrl+C` 安全中断策略
- 自动保存当前网格状态
- 生成交易统计报告

### 高级功能

#### 1. 多网格管理
- **并行网格**: 同时运行多个价格区间的网格
- **状态跟踪**: 每个网格独立维护买卖状态
- **资金分配**: 智能分配资金到各个网格

#### 2. 动态调整
- **价格适应**: 根据市场波动调整网格间距
- **仓位控制**: 动态调整每网格的下单金额
- **风险管理**: 实时监控总仓位和风险敞口

#### 3. 积分优化 <mcreference link="https://support.backpack.exchange/exchange/programs/points" index="4">4</mcreference>
- **交易频率**: 保持适度交易频率获取积分
- **等级提升**: 通过交易量提升 VIP 等级
- **费率优化**: 利用等级优势降低交易成本

---

## 📊 策略优势

### 1. 市场适应性
- **震荡市场**: 网格策略在震荡市场中表现优异
- **趋势跟踪**: 动态调整网格位置跟踪趋势
- **风险分散**: 多网格分散单点风险

### 2. 资金效率 <mcreference link="https://support.backpack.exchange/exchange/trading-fees" index="1">1</mcreference>
- **低手续费**: Backpack 竞争性费率结构
- **高频交易**: 适合高频小额交易策略
- **复利效应**: 利润再投资实现复利增长

### 3. 技术优势
- **API 稳定**: 基于官方 API 确保稳定性
- **异步处理**: 高效的异步订单处理
- **错误恢复**: 完善的异常处理机制

---

## ⚠️ 风险提示

### 交易风险
- 网格交易在单边趋势市场中可能面临较大风险
- 建议在震荡或横盘市场中使用
- 设置合理的止损和仓位控制

### 技术风险
- 网络延迟可能影响订单执行
- API 限制可能影响高频交易
- 建议监控系统状态和网络连接

### 资金风险
- 确保账户有足够资金支持网格运行
- 避免过度杠杆和集中持仓
- 定期检查账户余额和风险敞口

---

## 📁 文件结构

```
backpack/
├── trade.py                    # 主策略文件
├── config_loader.py            # 配置加载器
├── config.json                 # API配置文件
├── config.json.template        # 配置模板
├── test.py                     # 测试文件
└── trade_summary_log.txt       # 交易日志
```

## 🔗 相关链接

- [Backpack Exchange 官网](https://backpack.exchange/) <mcreference link="https://backpack.exchange/" index="5">5</mcreference>
- [API 文档](https://docs.backpack.exchange/) <mcreference link="https://docs.backpack.exchange/" index="1">1</mcreference>
- [积分系统说明](https://support.backpack.exchange/exchange/programs/points) <mcreference link="https://support.backpack.exchange/exchange/programs/points" index="4">4</mcreference>
- [策略源码](./backpack/trade.py)

---

## 💰 积分获取指南

### Backpack 积分系统 <mcreference link="https://support.backpack.exchange/exchange/programs/points" index="4">4</mcreference>

#### 1. 积分分发机制
- **分发时间**: 每周五 02:00 UTC
- **计算周期**: 基于周四 00:00 UTC 结束的活动
- **分发标准**: 根据所有产品的用户活动

#### 2. 等级系统
- **Bronze** → **Silver** → **Gold** → **Platinum** → **Diamond** → **Challenger**
- 每个赛季重新开始，所有用户从零开始
- 等级越高，享受的优惠越多

#### 3. 特殊奖励
- **Legacy Drop**: 2025年3月20日快照，奖励历史用户
- **Bonus Drop**: 1000万积分奖励活跃用户
- **推荐奖励**: 推荐朋友可获得交易费用和积分分成

#### 4. 网格交易积分优化
- **高频交易**: 网格策略产生大量交易，有利于积分获取
- **持续活跃**: 保持交易活跃度，获得更多积分
- **交易量提升**: 增加交易量有助于等级提升和费率优化

---

⭐ 如果这个项目对您有帮助，请给我们一个星标！