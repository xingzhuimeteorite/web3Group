# Web3 Trading Group

🚀 基于区块链技术的智能交易策略集合

## 📋 项目概述

智能交易策略集合，包含两个主要交易平台的自动化策略：
- **Aster Finance**: SOL双向交易策略，专注积分获取和手续费优化
- **Backpack Exchange**: 网格交易策略，捕捉市场波动获利

### 🆕 最新功能更新
- **到期时间显示**: 新增持仓到期时间实时显示功能，帮助用户更好地把握交易时机
- **策略文件统一**: 将主策略文件统一命名为 `trade.py`，提升项目一致性
- **参数优化**: 优化了止盈止损参数和最小持仓时间，提高策略效率

## 📚 策略文档

### Aster Finance SOL双向交易策略

详细的策略设计、使用说明和配置指南，请查看：

📖 **[Aster Finance SOL双向交易策略文档](./docs/README_aster.md)**

### Backpack Exchange 网格交易策略

基于网格交易的智能策略，详细文档请查看：

📖 **[Backpack Exchange 网格交易策略文档](./docs/README_backpack.md)**



## 📁 项目结构

```
web3Group/
├── README.md                 # 主文档（本文件）
├── README_aster.md          # Aster策略详细文档
├── README_backpack.md       # Backpack策略详细文档
├── requirements.txt         # Python依赖
├── .gitignore              # Git忽略文件
├── aster/                  # Aster Finance策略模块
│   ├── __init__.py
│   ├── aster_api_client.py    # API客户端
│   ├── config_loader.py       # 配置加载器
│   ├── trade.py               # SOL双向交易策略
│   ├── points_monitor.py      # 积分监控系统
│   ├── test_account.py        # 账户测试
│   └── config.json.template   # 配置模板
└── backpack/               # Backpack Exchange策略模块
    ├── trade.py               # 网格交易策略
    ├── config_loader.py       # 配置加载器
    ├── test.py                # 测试文件
    ├── config.json.template   # 配置模板
    └── trade_summary_log.txt  # 交易日志
```

## ▶️ 运行入口（已归档至 scripts/）

- `python scripts/trade_2.py`：实盘动态对冲策略（Aster空单 + Backpack多单）
- `python scripts/trade_any_2.py`：多币种动态对冲策略（含波动性筛选）
- `python scripts/trade_find.py`：两平台共同交易对的波动率分析与推荐
- `python scripts/quick_close_test.py`：快速平仓逻辑验证（极小阈值）
- `python scripts/trade_test.py`：交易流程与策略测试入口

文档已归档至 `docs/` 目录，主文档仍为根目录的 `README.md`。

## 🔧 主要组件

### 交易策略
- **SOL双向交易**: 基于技术指标的自动化交易（Aster Finance）
- **网格交易**: 捕捉价格波动的网格策略（Backpack Exchange）
- **风险控制**: 动态止盈止损机制
- **手续费优化**: 最小化交易成本

### 监控系统
- **实时监控**: 价格、持仓、盈亏实时跟踪
- **到期时间提醒**: 显示最小持仓时间的到期时刻，优化交易时机
- **数据分析**: 交易数据统计和分析
- **积分追踪**: 自动追踪平台积分获取情况

## ⚠️ 风险提示

- 本项目仅供学习和研究使用
- 数字货币交易存在高风险，请谨慎投资
- 使用前请充分了解相关风险
- 建议先在测试环境中验证策略

## 📞 支持与反馈

如有问题或建议，请通过以下方式联系：

- 📧 提交Issue
- 💬 参与讨论
- 🔧 贡献代码

## 📄 许可证

本项目采用 MIT 许可证 - 详见 [LICENSE](LICENSE) 文件

---

⭐ 如果这个项目对您有帮助，请给我们一个星标！