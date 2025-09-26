# Web3 Trading Group

🚀 基于区块链技术的智能交易策略集合

## 📋 项目概述

目前主要包含基于Aster Finance的SOL双向交易策略。

## 📚 策略文档

### Aster Finance SOL双向交易策略

详细的策略设计、使用说明和配置指南，请查看：

📖 **[Aster Finance SOL双向交易策略文档](./README_aster.md)**



## 📁 项目结构

```
web3Group/
├── README.md                 # 主文档（本文件）
├── README_aster.md          # Aster策略详细文档
├── requirements.txt         # Python依赖
├── .gitignore              # Git忽略文件
└── aster/                  # Aster Finance策略模块
    ├── __init__.py
    ├── aster_api_client.py    # API客户端
    ├── config_loader.py       # 配置加载器
    ├── sol_long_strategy.py   # SOL双向交易策略
    ├── points_monitor.py      # 积分监控系统
    ├── test_account.py        # 账户测试
    └── config.json.template   # 配置模板
```

## 🔧 主要组件

### 交易策略
- **SOL双向交易**: 基于技术指标的自动化交易
- **风险控制**: 动态止盈止损机制
- **手续费优化**: 最小化交易成本

### 监控系统
- **实时监控**: 价格、持仓、盈亏实时跟踪
- **数据分析**: 交易数据统计和分析

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