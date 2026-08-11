# 全量队列指令（一次粘贴）

> **给 CodeBuddy / 实现同学 · 整份复制到任务里即可**  
> **仓**：只改 `guess_you_like` · **禁止**改 fussball-bund 做产品  
> **产品转向**：世界杯专题 → **竞彩开售联赛**（见 `docs/PIVOT_JINGCAI_LEAGUES.md`）  
> **详细规格**：`docs/CODEBUDDY_MARKET_FORM_EV.md`  
> **日期**：2026-08-11  

---

## 产品一句话

**竞彩足球开售场/联赛** 的盘口工作台（非世界杯专题站）：  
欧赔 + 亚盘 + 欧亚分歧 + 必发 +（可选）竞彩 SP 对照  
+ 近 20～50 场总结、主近 20 主场 / 客近 20 客场（带赔率，联赛历史库）  
+ 去水隐含概率 + 勾选 2～3 场串关 EV + **同一结构化数据喂 AI**  

首页默认 **有竞彩编号或 SP 的场**；世界杯导航进「更多」。  
分析主轴不依赖世界杯数据；无 SP 仍可做欧亚赛果分析。

---

## 总顺序（严格）

```
[Q1-D0] 转向竞彩开售联赛（列表过滤/联赛映射/去 WC 主轴）
Q1 主路径（P0→P5→收尾）
  ↘ 途中阻塞：插入 Q3 基建
Q1 全绿后再做 Q2 模型增强（M1→M4，M5 可选）
永不做：文末「冻结」项
```

一条任务一个 PR，验过再开下一条。

---

## Q1-D0 · 世界杯 → 竞彩开售联赛（最先或与 P0 同 PR）

详见 `docs/PIVOT_JINGCAI_LEAGUES.md`。

- 主集合：jczq **match_num** 或 jingcai **SP**；配置 `FOCUS_JINGCAI_ONLY` 默认 true  
- poll 可仍抓窗口内盘口；**UI 默认只展示竞彩在售**  
- 战绩走 **联赛 football-data 映射**，不用 WC xlsx 主路径  
- 中文队名 → canonical 映射表  
- 导航/README/AI 默认 **profile=league**；`/worldcup*` 进更多  
- 世界杯若竞彩有开：当普通竞彩场，不进独立 WC 流水线  

验收：无世界杯赛程时首页仍有竞彩编号场；英超等竞彩场能分析且不提示依赖 WC。

---

## Q1 · 产品主路径（在 D0 后按序）

### Q1-P0 UI 减法
- 首页：主表 **选 | 比赛 | 去水倾向 | 亚盘 | 必发 | 规则 | 详情**；工具条只留刷新 + 勾选串关 EV  
- 导航主链：**首页 · 复盘**；世界杯・量化・Agent・Kelly… → 「更多」  
- 单场首屏 **仅 4 块按序**：①盘口 ②战绩 ③规则结论 ④AI；其余 details 默认折叠  
- 验收：窄屏首屏无 Agent/世界杯墙  

### Q1-P1 去水隐含概率统一
- `devig_1x2` → p 和=1 + overround；规则/EV/AI 全用 p_devig  
- UI：**隐含概率（去水）** + 抽水 %  

### Q1-P2 俱乐部战绩引擎（联赛向）
- `club_form`：20|30|50 + 主20主场 + 客20客场 + samples 赔率  
- `config/jingcai_league_map.yaml` + data/leagues；中文队名映射  
- **禁止** WC Excel 作主路径  

### Q1-P3 欧亚分歧 + 必发 → 规则 reasons  
### Q1-P4 勾选 2～3 场串关 EV（独立假设注明；SP优先否则欧赔）  
### Q1-P5 AI structured payload（**league profile**，禁默认出线/小组模板）  
### Q1-DONE 验收两份 doc + README/SCOPE 改「竞彩开售联赛」+ pytest  

---

## Q3 · 基建（阻塞插队）

- B1 单场补抓/空 tick  
- B2 context 回落与权重诚实  
- B3 比分 0% 禁显  
- B4 竞彩空 ≠ 无法分析  

---

## Q2 · 模型（Q1 全绿后）

- M1 Shin 去水  
- M2 p_model edge（**联赛历史** DC/Poisson+Elo）  
- M3 保守串关 EV  
- M4 赛后 Brier/CLV  
- M5 可选亚盘/大小球  

---

## 冻结

fussball-bund 产品；**新开世界杯专题**；保证收益；自动购彩；首页大 ML  

---

## 最短 ticket

```
[Q1-D0] 转向竞彩开售联赛
[Q1-P0] UI 减法
[Q1-P1] devig
[Q1-P2] 联赛战绩主客20
[Q1-P3] 分歧+必发
[Q1-P4] 串关 EV
[Q1-P5] AI league payload
[Q1-DONE] 验收文档
[Q3-B1]～[Q3-B4] 基建
[Q2-M1]～[Q2-M5] 模型后置
```

---

## 成功标准

用户打开 → **今天竞彩在售联赛场** → 去水盘口 + 联赛主客近 20 → 规则 → AI → 勾 2～3 场 EV；  
不依赖世界杯赛程；默认无 WC/Agent 噪音。
