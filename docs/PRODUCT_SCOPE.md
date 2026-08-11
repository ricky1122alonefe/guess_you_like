# Product scope — guess_you_like（冻结）

> 主交付仓：**本仓库 `guess_you_like`**。  
> **fussball-bund 停止产品改造**（科研/历史实验可自用，不再交叉扩需求、不再救 bund Web）。  
> 最后更新：2026-08-10

## 决策记录（2026-08-10 反转）

此前一度决定「交付 `fussball-bund`、`guess_you_like` 只读对照」，派工见
`fussball-bund/docs/JINGCAI_IMPLEMENTATION_ORDERS.md` 与 `PRODUCT_WEB_PLAN.md`。
**该方向作废**。产品回归 **本仓库**，理由：主路径（poll → serve → 竞彩列表/详情）
在 gyl 已跑通，无需在 bund 重建；两边同时加功能只会稀释焦点。

> 本仓 `docs/JINGCAI_ONLY_ORDERS.md` 是该旧指令的残留，已标记作废，以本文为准。

## 一句话

本地 **500 竞彩 / 在售足球** 工作台：定时抓盘 → 看板 → 单场 → 推荐 /（可选）AI。

## 主路径（只保证这 3 步好用）

```bash
guess-you-like poll --days 7          # 默认：时间窗内全部联赛；竞彩在售优先
guess-you-like serve --host 127.0.0.1 --port 8765
# 浏览器 http://127.0.0.1:8765 → 竞彩列表 → 单场详情
```

展开（首次或 Docker）：

```bash
docker compose up -d db               # 或本地 PG
guess-you-like poll --interval 300 --days 7
guess-you-like serve --host 127.0.0.1 --port 8765
```

## 默认产品规则

| 规则 | 说明 |
|------|------|
| 数据源 | live/odds 500 + 竞彩 SP 上下文（jingcai） |
| 首页默认 | **优先展示有竞彩编号或可售 SP 的场**；全联赛 poll 噪音场默认折叠/过滤 |
| 推荐 | 绑定竞彩 SP；无 SP → 观望/不可购 |
| 世界杯专题 | **次导航 / 赛季能力**，不抢首页主叙事 |
| AI | 可选；无 key 规则仍能用 |

## 明确不做（本阶段）

- 两边同时加功能（gyl 与 bund 并行迭代）
- 再救 fussball-bund Web（对标 bund Web、在 bund 重建 serve）
- 把 fussball-bund 接进本仓当双产品
- 五大联赛历史 CSV 科研流水线当主功能
- 保证盈利、自动购彩
- 无限加 Agent / FIFA 预览 等未验收主链

## 收口优先级（改 gyl 时按这个）

1. **P0** 首页（`/` 与 `/daily`）：竞彩优先过滤 + **poll 状态可见**（最近成功时间、场数、错误）
2. **P0** README 置顶改成「竞彩工作台」三行命令（世界杯当附录）
3. **P1** 导航减法：世界杯/quant/Kelly 等二次入口，主链 3 个入口
4. **P1** poll 稳定性（失败可观测、不静默）
5. **P2** `web_ui.py` / `serve.py` 按路由拆文件（不影响功能时再拆）

## 与 bund 关系

- **不**再提「对标 bund Web」
- bund 代码 **可只读抄思路**；功能迭代 **只在 gyl 合 PR**
- bund 现有科研 CLI（Poisson/DC/walk-forward）保留自用，不产品化、不接 Web

## 验收

- [ ] 新人按 README 30 分钟内看到 **带编号的竞彩场 + SP + 推荐/观望**
- [ ] 重启 poll 后首页能说明「上次抓取结果」
- [ ] 无 DEEPSEEK key 仍可用主路径
