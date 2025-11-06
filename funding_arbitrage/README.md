# 资金费套利（Funding Rate Arbitrage）蓝图

目标：以最小复杂度建立“严格对冲、低成本执行、可回测可监控”的资金费套利模块，优先支持同平台（现货+永续）与跨平台（永续+现货/期货）两种路径，基于 `ccxt` 快速落地。

## 设计原则
- 简洁：组件职责单一、依赖最少、首版以观察者模式上线。
- 安全：以 delta-neutral 为首要目标，严格风控与熔断；默认先不下单。
- 可扩展：模块化适配交易所行情/资金费差异，逐步增强自动化。
- 透明：所有收益用“资金费 – 成本 – 滑点”模型实时核算与记录。

## 目录结构（规划）
- `funding_arbitrage/`
  - `README.md`：本蓝图与实现指导
  - `config/`：配置文件（密钥、交易参数、阈值、成本）
  - `exchanges/`：`ccxt` 交易所适配层（统一行情、资金费、下单接口）
  - `strategy/`：资金费监控、开/平仓对冲、再平衡与退出逻辑
  - `risk/`：风控与熔断器（保证金健康度、价格跳变、API故障）
  - `accounting/`：成本与收益核算、资金与仓位状态管理
  - `notifier/`：告警与日报（可选：飞书/邮件）
  - `scripts/`：`observer.py`（不下单只评估）、`live.py`（最小实盘）
  - `logs/`：运行日志与净值快照

## 配置示例（最小可行）
```json
{
  "mode": "observer", // observer | live
  "symbols": ["BTC/USDT"],
  "exchanges": {
    "perp": {"id": "binance", "type": "future", "apiKey": "...", "secret": "..."},
    "spot": {"id": "binance", "type": "spot", "apiKey": "...", "secret": "..."}
  },
  "position": {
    "notional_usd": 50000,
    "futures_margin_leverage": 3,
    "deltaTarget": 0.0,
    "rebalanceThreshold": 0.002 // 0.2%
  },
  "thresholds": {
    "dailyFundingMin": 0.0002, // 日资金费最低阈值（0.02%）
    "flipExit": true,
    "flipToleranceHours": 2
  },
  "costs": {
    "taker": 0.0005,
    "maker": 0.0002,
    "borrowRateDaily": 0.0001,
    "transferFixed": 5
  },
  "monitor": {
    "intervalSec": 30,
    "snapshotEveryMin": 5
  }
}
```

## 核心组件与职责
- `observer.py`
  - **职责**：项目主入口。负责加载配置、初始化交易所、并启动无限循环来持续监控资金费套利机会。
  - **状态**：已实现。

- `exchanges/adapter.py`
  - **职责**：初始化 `ccxt` 客户端（spot、perp），为上层逻辑提供统一的交易所接口。
  - **状态**：已实现。

- `strategy/monitor.py`
  - **职责**：定时拉取资金费与价格，进行初步计算。
  - **状态**：已实现。

- `accounting/pnl.py`
  - **职责**：提供成本模型计算，如往返成本、盈亏平衡天数等。
  - **状态**：已实现。

- `utils/`
  - `config_loader.py`: **职责**：安全地加载 `config.json` 文件。
  - `logger.py`: **职责**：配置全局日志记录器，输出到控制台和 `logs/observer.log`。
  - `recorder.py`: **职责**：将结构化数据（如套利机会）写入 `logs/funding_opportunities.csv`。
  - **状态**：已实现。

- `risk/manager.py` （规划中）
  - **职责**：监控保证金健康度、价格跳变、API故障等，并在超出阈值时执行熔断。

- `notifier/feishu.py`（规划中）
  - **职责**：当发现机会或触发风控时，发送告警与日报。

## 运行流程（MVP）
- 观察者模式
  - 启动 -> 加载配置 -> 初始化交易所 -> 定时拉取资金费与价格。
  - 计算净值：`dailyFunding - taker/maker - borrow - slippage - transfer/hold`。
  - 满足阈值则记录“可开仓信号”，但不实际下单；生成日报。

- 实盘模式（最小）
  - 开仓：当信号满足 -> `open_perp_short + buy_spot` 或反向（负资金费）。
  - 维护：监控资金费翻转、仓位偏离、保证金健康度；必要时再平衡或退出。
  - 退出：资金费低于阈值或连续翻转、风控触发、系统异常。

## 关键 API（以 ccxt 为主，示例伪代码）
```python
import ccxt

exchange = ccxt.binance({"apiKey": "...", "secret": "..."})
exchange.set_sandbox_mode(False)

# 获取价格
price = exchange.fetch_ticker("BTC/USDT")['last']

# 获取资金费（不同交易所支持度不同，需做兼容）
# 优先使用统一方法 fetchFundingRate / fetchFundingHistory，否则走自定义端点
funding = getattr(exchange, 'fetch_funding_rate', None)
if callable(funding):
    fr = exchange.fetch_funding_rate("BTC/USDT")['fundingRate']  # 8小时费率
else:
    # 回退：自定义请求或通过 perp 标记价与资金费端点解析（因所而异）
    fr = None

# 下单（永续做空 + 现货做多），建议限价或 maker 方式
# exchange.create_order(symbol, type, side, amount, price, params)
```

## 风险与保护
- 资金费翻转：设定容忍时长与自动退出/反向逻辑。
- 强平与保证金：健康度阈值与降仓策略；永续杠杆不要过高。
- 执行与系统：API 故障、滑点超阈值、下单失败要熔断并告警。
- 跨平台：转账与借贷利率不确定性；优先同平台以降低复杂度。

## MVP 里程碑
- M1 观察者上线：完成 `adapter + monitor + pnl + logs`，连续 14–30 天评估。
- M2 单平台实盘：`hedger + risk` 最小对冲；可平稳运行不少于 2 周。
- M3 增强自动化：资金费翻转自切换、再平衡优化、返佣与费率动态管理。

## 下一步建议
- 建立 `config/example.json` 与 `scripts/observer.py` 雏形，跑数据不下单。
- 明确目标交易所与费率结构（maker/taker、返佣、借贷），校验成本模型。
- 若需要，我会基于此蓝图补齐 `adapter` 与 `observer` 的代码框架。

## 资金费日化与阈值建议
- 结算周期差异：常见为 8 小时（Binance/Bybit/OKX），也有 1 小时或自定义。
- 统一口径：`dailyFunding = fundingRate * (24 / intervalHours)`；以日化统一做筛选与核算。
- 开仓阈值：建议 `dailyFunding ≥ 0.0002`（日化 0.02%）且连续 ≥ 3 个周期为正，再考虑持有；结合你的费率与返佣微调。
- 持有与退出：当日化资金费显著下降或翻转，进入观察或退出；若翻转持续 ≥ 2 小时，执行退出或反向。
- 合约与计价一致性：优先 U 本位永续与同标的现货/指数，避免币本位或计价不一致引入隐性基差。

## 状态机与回滚流程（孤儿单保护）
- 状态流：`IDLE → OPENING → ACTIVE → CLOSING`，所有开/平动作都在状态机内执行。
- OPENING 监控：两腿下单后持续轮询成交；若第二腿未成交或超时（如 10 秒），立刻回滚孤儿腿（市价平掉已成交的一腿），状态回到 `IDLE` 并告警。
- ACTIVE 维护：监控资金费方向、仓位 delta 偏离（`rebalanceThreshold`）、保证金健康度；必要时再平衡。
- CLOSING 异常：若一腿平仓失败，优先恢复原对冲（例如重新开回合约腿），保持 `ACTIVE`，避免裸腿暴露。
- 告警与日志：记录每次状态转移、回滚原因、成交明细与耗时，用于复盘与优化。

## 成本模型与告警阈值
- 日净值估算：`netDaily = dailyFunding * notional_usd - fees - borrow - slippage - transfer/hold`。
- 滑点成本：将滑点视作固定成本（每腿 `slippage_bps × notional_usd`），在观察者模式中按盘口深度或经验值设定并扣除。
- 手续费：按 taker/maker bps 分别计入；下单风格调整（maker 优先）可显著改善净值。
- 再平衡成本：每次再平衡付双边费用与滑点，需单独累计并在日报中展示占比；建议当 24h 再平衡成本占净值 ≥ 30% 时告警，提示提高 `rebalanceThreshold`。
- 借贷/资金占用：按日利率或固定费用计入；跨平台转账时加入固定转账成本与时间窗风险。

## 配置字段说明（严谨版）
- `position.notional_usd`：名义本金；开多现货与开空合约都以此金额为基准，组合有效杠杆 ≈ 1x。
- `position.futures_margin_leverage`：永续的保证金杠杆，提高资金效率，不改变组合总杠杆的目标（仍以 1x 为准）。
- `position.deltaTarget`：目标 delta；通常为 0；允许轻微偏离以控制再平衡频率。
- `position.rebalanceThreshold`：当价格波动或仓位偏离比例超过该阈值时触发再平衡；与成本模型联动。
- `thresholds.dailyFundingMin`：按日化资金费筛选的最低阈值；与手续费/滑点/借贷成本共同决定是否开仓。
- `thresholds.flipToleranceHours`：资金费翻转容忍时长；超过即退出或反向。
- `timeouts.open_timeout_sec`：OPENING 超时；两腿未在此时间内全部成交则回滚孤儿腿。

## 跨所执行注意事项
- 账户与划转：不同交易所的资金账户/交易账户/合约账户层级不同，开仓前需确保资金在对应账户并可用。
- 保证金模式：`cross` 与 `isolated` 的爆仓规则不同；建议按策略统一设定与校验，便于风控计算。
- 标记价与计价单位：统一用 USD-M 永续与同标的现货，避免币本位或奇异标记价导致 delta 不中性。

## 参考流派与知识点速查（浓缩）
- `@moncici_is_girl`：资金费率 + 现货搬砖；要点：费率实时 API、防滑点撤单重挂、多所统一风控。
- `@0xKaKa03`：Lead-Lag 跨所 + MEV 三角；要点：延迟测速、并发下单、Jito/Flashbots Bundle。
- `@DongLius`：全门派综述 + 安全警告；要点：钓鱼识别、API Key 最小权限、资金分仓。
- `@lnkybtc`：跨系统贸易；要点：多链钱包、跨链桥 Gas 模型、周期切换策略。
- `@moodylu6`：意图引擎 + 路由竞价；要点：CCTP 原生 USDC、Solver 竞价、失败退款机制。
- `@Moon1ightSt`：统一账户手动搬砖；要点：CrossEx 保证金共享、手动对冲表、止损脚本。
- `@LZYH88`：做市商对冲 + 负手续费；要点：负 Maker 费率谈判、Delta Neutral、资金费对冲计算器。
- `@warley1993`：借贷-跨链-结算闭环；要点：Flashloan 启动、zkKYC 返现卡、空投迁移奖励。

## 0 → 1 行动清单（观察者优先）
- 第 0–1 周：只跑观察者；采集日化资金费与价格、估算净值（含滑点与费用），累计 14 天评估。
- 第 2–3 周：单平台最小实盘；状态机管控开/平与回滚；名义本金 500–1000 USDT，阈值与风控保守。
- 第 4 周：跨所与返佣优化；maker 路径与返佣谈判，逐步提升成本优势后再扩仓。

## Bitget 接入指南（ccxt）
- 交易所 ID：`bitget`，在 ccxt 中为 `ccxt.bitget`。
- 市场类型：`spot`（现货）、`swap`（永续，建议 USDT 线性合约用于对冲）。
- 必填凭证：`apiKey`、`secret`、`password`（API Passphrase，不可缺省）。
- 推荐选项：
  - `options.defaultType = 'swap'`（默认走永续端）；
  - `options.defaultSubType = 'USDT'`（选择 USDT 线性）；
  - 统一符号：现货 `BTC/USDT`，永续 `BTC/USDT:USDT`（后缀不可漏）。
- 保证金/仓位模式（视 ccxt 版本与交易所端支持）：
  - `set_margin_mode('cross'|'isolated', {symbol})` 固定保证金模式；
  - `set_leverage(leverage, symbol, params={'marginMode': 'cross'})` 设置杠杆；
  - `set_position_mode(True|False)` 是否对冲/双向持仓模式（对冲建议开启）。
- 资金费统一口径：
  - 结算周期通常 8 小时，以交易所返回为准；
  - `dailyFunding = fundingRate * (24 / intervalHours)`；若无 `fetch_funding_rate`，用 `fetch_funding_history` 最近一条换算；
  - 开仓阈值建议 `dailyFunding ≥ 0.0002` 且连续 ≥ 3 个周期。
- 常见坑：
  - 忘记 `:USDT` 后缀导致走错市场；
  - 未提供 `password`（Passphrase）鉴权失败；
  - 保证金/仓位模式未设置，风控计算与实际不一致；
  - 账户层级（资金/交易/合约）未划转到位，造成可用余额不足。

示例配置片段（仅文档，便于你填值）：
```json
{
  "exchanges": {
    "perp": { "id": "bitget", "type": "swap", "apiKey": "<填>", "secret": "<填>", "password": "<填>" },
    "spot": { "id": "bitget", "type": "spot", "apiKey": "<填>", "secret": "<填>", "password": "<填>" }
  },
  "symbols": ["BTC/USDT"],
  "position": {
    "notional_usd": 1000,
    "futures_margin_leverage": 3,
    "deltaTarget": 0.0,
    "rebalanceThreshold": 0.002
  },
  "thresholds": { "dailyFundingMin": 0.0002, "flipExit": true, "flipToleranceHours": 2 },
  "timeouts": { "open_timeout_sec": 10, "poll_interval_sec": 0.5 },
  "costs": { "taker_bps": 5, "maker_bps": 2, "slippage_bps": 5, "borrowRateDaily": 0.001 }
}
```

执行建议：
- 早期同平台对冲（Bitget 现货 + USDT 永续），避免跨所转账复杂度；
- 保持 USD-M（USDT 线性）与现货计价一致，减少隐性基差；
- 观察者阶段先验证日化资金费稳定性与真实成本，再切入最小实盘。