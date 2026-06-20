"""Central tunables for matching, control, traps, confidence, and scores."""

# ── 样本门槛 ──────────────────────────────────────────
MIN_SAMPLES_FOR_PICK = 100
SCORE_POOL_TOP_N = 250
# ── 量化模型（免费层）────────────────────────────────
DIXON_COLES_RHO = -0.13
SCORE_MODEL_MAX_GOALS = 6
MC_SIMULATIONS = 3000
SCORE_RUNNER_MIN_RATE = 0.15  # 略降，历史比分轨更易带平局备选
HIST_EU_BLEND_MAX_WEIGHT_RATIO = 1.0  # 欧赔扩展样本最多与亚盘样本同权，避免大库压倒盘口匹配

# ── 历史匹配容差（predict.py CLI 可覆盖）──────────────
DEFAULT_LINE_TOL = 0.25
DEFAULT_WATER_TOL = 0.18
DEFAULT_EU_HOME_TOL = 0.30
DEFAULT_EU_DRAW_TOL = 0.40
DEFAULT_EU_AWAY_TOL = 0.50
RELAXED_LINE_TOL = 0.5
RELAXED_WATER_TOL = 0.25
RELAXED_EU_TOL = 0.45

# ── 控盘 → 初盘规律权重 ───────────────────────────────
PATTERN_WEIGHT = {"low": 1.0, "medium": 0.75, "high": 0.35}
CONTROL_INTENSITY_LOW = 0.25
CONTROL_INTENSITY_HIGH = 0.55
LIVE_SIGNAL_DAMPING = 0.65
LIVE_SIGNAL_MIN_SCALE = 0.15
LIVE_SIGNAL_ALLOW_HIGH_CONTROL_DIRECTION = False
LIVE_SIGNAL_SWITCH_MARGIN = 0.04

# ── 控盘强度计算（market_control）────────────────────
MOVE_WEIGHT_LINE = 0.35
MOVE_WEIGHT_WATER = 0.25
MOVE_WEIGHT_EU = 0.12
MOVE_NORM_LINE = 0.5
MOVE_NORM_WATER = 0.15
MOVE_NORM_EU_RATIO = 0.08
MOVE_NORM_EU_FLOOR = 0.05

# ── 欧转亚 / 亚转欧 一致性 ─────────────────────────────
EU_AH_LINE_GAP_TOL = 0.25          # 实际盘口与欧赔隐含盘口差 ≤ 此值视为一致
EU_AH_ODDS_GAP = 0.15              # 亚转欧粗推 vs 实际欧赔主胜差
EU_AH_DIVERGENCE_NOTICE_SCORE = 30   # 轻度分歧
EU_AH_DIVERGENCE_MIN_SCORE = 45      # 列表默认筛选：明显分歧
EU_AH_DIVERGENCE_HUGE_SCORE = 62     # 巨大分歧
PATTERN_PENALTY_TRAP_HOME = 0.88     # 套路标记诱主时再扣
PATTERN_PENALTY_TRAP_AWAY = 0.88

# ── 欧赔隐含概率和 (100/odds 三项之和) ─────────────────
# 正常博彩公司 raw sum 约 102%–110%；去水后 fair sum = 100%
EU_IMPLIED_SUM_OK_MIN = 99.0
EU_IMPLIED_SUM_OK_MAX = 110.0
EU_IMPLIED_SUM_WARN_MAX = 115.0
EU_IMPLIED_PEER_SUM_DEV_PP = 4.0     # 与同业隐含和中位偏差 ≥4pp 记异动
EU_IMPLIED_SCORE_PENALTY = 1.0       # daily_picks 轻量降权（非否决）

# ── 服务赛程窗口（poll / 整点分析 / 首页展示）────────────────
SERVICE_WITHIN_DAYS = 7.0            # 世界杯小组赛程跨度大，默认 7 天

# ── 定时 AI 节流（整点任务：距上次 AI 不足此间隔则跳过）────
AI_AUTO_ENABLED = False             # False=仅手动触发 AI；True=整点任务可自动跑 AI
AI_INTERVAL_MINUTES = 150            # 自动 AI 时约 2.5h 一次（AI_AUTO_ENABLED=True 时生效）
# AI 模型注册表：data/ai_providers.example.json → 复制为 data/ai_providers.json
# 或运行时 output/service/ai_config.json（POST /api/ai/config 写入）

# ── 异动 / 诱盘惩罚（乘在有效概率上，0.85=扣15%）──────
TRAP_PENALTY_LINE_UP_WATER_DOWN = 0.85      # 升盘+上盘降水 → 诱上盘/主胜
TRAP_PENALTY_LINE_DOWN_WATER_DOWN = 0.85    # 降盘+下盘降水 → 诱下盘/客胜
TRAP_PENALTY_LINE_EU_CONFLICT = 0.90        # 盘口与欧赔方向矛盾
TRAP_PENALTY_EU_AH_DIVERGE = 0.92           # 欧赔大变、亚盘不动
TRAP_PENALTY_DRAW_STEAM = 1.0               # 仅标注，不惩罚；见 TRAP_DRAW_STEAM_NOTE
TRAP_PENALTY_SEVERE_FLUCTUATION = 0.90      # 高震荡：全方向轻扣
TRAP_EXTRA_ON_FLAGGED_HIGH_CONTROL = 0.50   # 高控盘时诱盘方向再打5折

LINE_MOVE_EPS = 0.01
WATER_MOVE_EPS = 0.03
EU_ODDS_MOVE_EPS = 0.02
EU_IMPLIED_MOVE_EPS = 0.008
EU_DIVERGE_INTENSITY = 0.40                   # 欧赔异动而亚盘几乎不动的门槛
DRAW_STEAM_DROP = 0.03                        # 平赔显著下调视为平局资金
DRAW_STEAM_RESPECT_OPEN_HIST = True           # 初盘单项明确时，不因平赔下调改推平局

# ── 世界杯小组战意（R2/R3 以风险提示为主，避免过度改判平局）──
GROUP_STAGE_BIAS_SCALE = 0.35                 # 战意 bias 计入综合概率时的缩放
GROUP_STAGE_MAX_DRAW_NUDGE = 0.04             # 战意最多抬平这么多（绝对值）
GROUP_STAGE_MAX_SIDE_NUDGE = 0.03             # 主/客战意 bias 上限
GROUP_STAGE_DRAW_FLIP_MIN_LEAD = 0.06         # 非初盘锁定时，平局需领先次选至少此值才改判
OPEN_HIST_LOCK_MIN_RATE = 0.50                # 初盘单项最高至少此概率
OPEN_HIST_LOCK_MIN_MARGIN = 0.08                # 且领先次选至少此差距 → 禁止战意/临盘改推平局
KNOCKOUT_DRAW_BIAS_SCALE = 0.40               # 淘汰赛挑对手时的平局抬升缩放

# ── 参考研判（欧赔/亚盘/历史，不含竞彩）────────────────────
ODDS_FIRST_ENABLED = True
ODDS_W_LIVE_EU = 0.40
ODDS_W_OPEN_EU = 0.15
ODDS_W_AH = 0.18
ODDS_W_HIST = 0.27
ODDS_FIRST_TRAP_SCALE = 0.45

# ── 竞彩（最终可购口径）──────────────────────────────────
JINGCAI_REFERENCE_DIVERGENCE_PP = 0.08       # SP隐含与参考方向差≥8pp → 标注分歧

# ── 出线场次 · 欧亚分歧标注 ───────────────────────────────
QUALIFICATION_DIVERGENCE_MIN_SCORE = 30       # 小组出线/战意场，≥此分特殊标注

# ── 高控盘决策 ────────────────────────────────────────
HIGH_CONTROL_TRAP_INTENSITY = 0.55
HIGH_CONTROL_MARGIN_FOR_SWITCH = 0.02           # 扣分后Top2差距小于此 → 改推次选

# ── 置信度 ────────────────────────────────────────────
CONF_MIN_TOP_RATE = 0.42
CONF_HIGH_MARGIN = 0.12
CONF_MED_MARGIN = 0.06
CONF_HIGH_SAMPLE = 300

# ── 大小球 ────────────────────────────────────────────
OU_OVER_THRESHOLD = 2.65
OU_UNDER_THRESHOLD = 2.35

# ── 亚盘 ──────────────────────────────────────────────
AH_EFFECTIVE_THRESHOLD = 0.08
AH_EFFECTIVE_THRESHOLD_STRONG = 0.06
AH_SKIP_SIGNAL_SCALE = 0.35
AH_STRONG_BIAS = 0.05

# ── 1X2 与亚盘联动 ────────────────────────────────────
AH_CONFLICT_FORCE_SKIP_ON_HIGH_CONTROL = True
AH_CONFLICT_DOWNGRADE_CONFIDENCE = True

# ── 相似度加权（比分）────────────────────────────────
SCORE_SIMILARITY_DECAY = 2.5

# ── 双方近期状态（国际赛/预选赛）──────────────────────
TEAM_FORM_DAYS = 365
TEAM_FORM_MAX_MATCHES = 8

# ── 球风相克（轻量代理，权重低，仅防一手）────────────
STYLE_CLASH_MIN_MATCHES = 3
STYLE_CLASH_UPSET_BOOST = 2.0       # daily_picks upset 分 +N（high 档）
STYLE_CLASH_SAFE_PENALTY = 1.0      # 热门遇相克时 safe 分 -N

# ── 每日 2串1 选场 ─────────────────────────────────────
DAILY_PICKS_SP_PREFERRED = True   # 优先胜平负；仅让球默认不进池，极高置信例外
DAILY_PICKS_SP_ONLY = DAILY_PICKS_SP_PREFERRED  # 兼容旧名
DAILY_PICKS_RQSP_SCORE_PENALTY = 5  # 让球场次入选后评分扣分（仍弱于胜平负）
