"""Fictional business requirements for the local DAG demonstration."""

DEMO_PREFIX = "【DAG演示"

SCENARIOS = [
    {
        "key": "launch",
        "name": "【DAG演示①】新品发布方案 · 三路并行汇合",
        "description": "虚拟需求：为轻舟知识助手策划新品发布，预算 30000 元，目标获取 1000 名试用用户。需求拆解后，用户画像、渠道创意、预算测算并行执行，最后汇总方案。使用本地模拟模型和虚拟数据，不联网、不发送通知、不产生外部业务操作。重新启动可观察三个分支同时运行。",
        "input": "请策划轻舟知识助手发布活动。预算 30000 元，目标 1000 名试用用户，筹备期 14 天。分别分析目标用户、推广渠道及预算，并汇总可执行方案。",
        "nodes": [
            {"id": "brief", "subject": "拆解发布需求", "description": "明确产品、预算、目标与筹备周期，输出项目约束。", "depends_on": [], "delay": 2},
            {"id": "audience", "subject": "分析目标用户", "description": "根据项目约束，独立分析用户画像、痛点和触达方式。此节点与渠道创意、预算测算并行。", "depends_on": ["brief"], "bindings": {"brief": "brief.data"}, "delay": 9},
            {"id": "creative", "subject": "设计渠道创意", "description": "根据项目约束，独立制定内容主题、渠道组合和活动节奏。", "depends_on": ["brief"], "bindings": {"brief": "brief.data"}, "delay": 11},
            {"id": "budget", "subject": "测算预算与指标", "description": "根据项目约束，独立分配预算并计算单个试用用户成本。", "depends_on": ["brief"], "bindings": {"brief": "brief.data"}, "delay": 7},
            {"id": "plan", "subject": "汇总发布执行方案", "description": "等待三个分支全部成功，结合用户画像、渠道创意和预算，形成最终发布方案。", "depends_on": ["audience", "creative", "budget"], "bindings": {"audience": "audience.data", "creative": "creative.data", "budget": "budget.data"}, "delay": 3},
        ],
    },
    {
        "key": "commerce",
        "name": "【DAG演示②】电商经营复盘 · 并行分析与人工审核",
        "description": "虚拟需求：分析一家文创商店的销售与库存。销售表现、库存风险并行计算，汇总后停在人工审核，点击通过才生成行动清单。所有金额与商品数据均为虚构，不会修改库存、下单或发送消息。",
        "input": "请复盘文创商店本周经营状况：同时分析销售收入、热销商品和缺货风险。给出复盘报告，等我审核通过后再生成下周行动清单。",
        "nodes": [
            {"id": "collect", "subject": "准备销售与库存数据", "description": "读取演示内置的三款文创商品销售记录及库存快照。", "depends_on": [], "delay": 2},
            {"id": "sales", "subject": "分析销售表现", "description": "从上游结构化数据计算总收入、总销量和热销商品。", "depends_on": ["collect"], "bindings": {"records": "collect.data.records"}, "delay": 8},
            {"id": "stock", "subject": "识别库存风险", "description": "从上游数据独立分析库存覆盖天数和需要补货的商品。", "depends_on": ["collect"], "bindings": {"records": "collect.data.records"}, "delay": 10},
            {"id": "review", "subject": "汇总复盘并等待审核", "description": "汇合销售与库存结论，生成复盘摘要。此节点需人工审核；审核通过前不会运行下游。", "depends_on": ["sales", "stock"], "bindings": {"sales": "sales.data", "stock": "stock.data"}, "human": "请查看销售收入和补货建议。点击通过后，系统会继续生成下周行动清单。", "delay": 3},
            {"id": "actions", "subject": "生成下周行动清单", "description": "仅在人工审核通过后，根据复盘结果生成负责人、优先级和期限清单。不会实际执行采购。", "depends_on": ["review"], "bindings": {"review": "review.data"}, "delay": 3},
        ],
    },
    {
        "key": "daily",
        "name": "【DAG演示③】数据日报 · 失败隔离与节点重试",
        "description": "虚拟需求：生成门店销售日报。数据校验与指标计算并行。首次校验会被模拟审核员以缺少金额字段为由拒绝（尝试上限 1），汇总节点被阻塞，指标分支仍可完成。点击校验节点的“只重试此节点”后，模拟器补齐字段并通过审核，原数据准备和指标计算节点保持一次执行。已预置失败记录及局部恢复成功记录各一份。",
        "input": "请生成虚拟门店销售日报，并演示失败隔离：第一次质量校验故意未通过，指标计算分支照常完成。人工点击节点重试后修复演示数据，并继续汇总报告。不要从头重跑整个任务。",
        "nodes": [
            {"id": "source", "subject": "准备门店销售数据", "description": "准备三条虚拟门店销售记录。首次快照故意缺少一项 paid_amount，用于演示质量审核失败。", "depends_on": [], "delay": 2},
            {"id": "quality", "subject": "校验数据完整性（首次故意失败）", "description": "检查金额字段；首次提交报告缺失字段，由演示审核员拒绝。收到上次失败反馈后，在新尝试中使用虚拟修复值补齐并重新提交。尝试上限为 1，方便观察手动局部重试。", "depends_on": ["source"], "bindings": {"records": "source.data.records"}, "max_attempts": 1, "agent_review": True, "delay": 6},
            {"id": "metrics", "subject": "计算可用数据指标", "description": "并行计算当前可用销售记录的金额和数量，明确缺失记录。此分支不会因为质量校验失败而重做。", "depends_on": ["source"], "bindings": {"records": "source.data.records"}, "delay": 10},
            {"id": "report", "subject": "汇总销售日报", "description": "等待质量校验与指标计算均成功。结合修复后的完整数据，重算最终收入并输出日报，同时保留原指标分支结果供对照。", "depends_on": ["quality", "metrics"], "bindings": {"quality": "quality.data", "metrics": "metrics.data"}, "delay": 3},
        ],
    },
]


def model_id(scenario, node_id):
    return f"dag-demo-{scenario}-{node_id}"


def find_node(model):
    for scenario in SCENARIOS:
        for node in scenario["nodes"]:
            if model == model_id(scenario["key"], node["id"]):
                return scenario["key"], node
    return None, None


def calculate(scenario, node, inputs, retry=False):
    """Use actual bound upstream outputs; never edit persisted run state."""
    key = (scenario, node)
    if key == ("launch", "brief"):
        return {"product": "轻舟知识助手", "budget_yuan": 30000, "target_trials": 1000, "preparation_days": 14}
    if key == ("launch", "audience"):
        return {"product": inputs["brief"]["product"], "segments": ["20–100 人研发团队", "需要统一知识库的客服团队"], "pain_points": ["文档分散", "新人查找答案耗时"], "message": "把团队知识变成可直接提问的助手"}
    if key == ("launch", "creative"):
        return {"product": inputs["brief"]["product"], "channels": ["技术社区案例文章", "线上产品公开课", "老用户邀请"], "schedule": ["第 1–5 天：案例预热", "第 6–10 天：公开课与试用", "第 11–14 天：答疑和复盘"]}
    if key == ("launch", "budget"):
        budget = inputs["brief"]["budget_yuan"]
        return {"total_yuan": budget, "items": {"内容制作": budget * .4, "公开课": budget * .3, "社区推广": budget * .2, "预备金": budget * .1}, "target_trials": inputs["brief"]["target_trials"], "cost_per_trial_yuan": budget / inputs["brief"]["target_trials"]}
    if key == ("launch", "plan"):
        return {"target_segments": inputs["audience"]["segments"], "channels": inputs["creative"]["channels"], "schedule": inputs["creative"]["schedule"], "budget_yuan": inputs["budget"]["total_yuan"], "cost_per_trial_yuan": inputs["budget"]["cost_per_trial_yuan"], "joined_branches": ["audience", "creative", "budget"]}
    if key == ("commerce", "collect"):
        return {"records": [{"product": "城市手账", "units": 120, "unit_price": 49, "stock": 40}, {"product": "创意贴纸", "units": 240, "unit_price": 12, "stock": 360}, {"product": "帆布袋", "units": 80, "unit_price": 39, "stock": 15}]}
    if key == ("commerce", "sales"):
        rows = inputs["records"]
        return {"revenue_yuan": sum(r["units"] * r["unit_price"] for r in rows), "units": sum(r["units"] for r in rows), "best_seller": max(rows, key=lambda r: r["units"])["product"]}
    if key == ("commerce", "stock"):
        return {"risks": [{"product": r["product"], "coverage_days": round(r["stock"] * 7 / r["units"], 1), "suggested_restock": max(0, r["units"] * 2 - r["stock"])} for r in inputs["records"] if r["stock"] * 7 / r["units"] < 5]}
    if key == ("commerce", "review"):
        return {**inputs, "recommendation": "优先补充城市手账与帆布袋；创意贴纸库存充足，维持当前投放。", "requires_human_approval": True}
    if key == ("commerce", "actions"):
        return {"reviewed_revenue_yuan": inputs["review"]["sales"]["revenue_yuan"], "actions": [{"task": "确认缺货商品补货计划", "owner": "采购负责人（虚拟）", "deadline": "2 个工作日", "priority": "高"}, {"task": "复盘创意贴纸推广素材", "owner": "运营负责人（虚拟）", "deadline": "下周一", "priority": "中"}], "executed_external_actions": False}
    if key == ("daily", "source"):
        return {"records": [{"store": "东城店", "paid_amount": 1280}, {"store": "西城店", "paid_amount": 960}, {"store": "南城店", "paid_amount": None}], "repair_value_yuan": 760}
    if key == ("daily", "quality"):
        rows = [dict(r) for r in inputs["records"]]
        if retry:
            for row in rows:
                if row["paid_amount"] is None:
                    row["paid_amount"] = 760
        return {"validation_status": "recovered" if retry else "missing_field", "records": rows, "missing_fields": [] if retry else ["南城店.paid_amount"], "note": "收到失败反馈后，使用虚拟金额 760 元修复。" if retry else "演示故障：南城店缺少金额字段，需手动重试校验节点。"}
    if key == ("daily", "metrics"):
        rows = inputs["records"]
        return {"available_revenue_yuan": sum(r["paid_amount"] or 0 for r in rows), "valid_records": sum(r["paid_amount"] is not None for r in rows), "missing_records": sum(r["paid_amount"] is None for r in rows), "note": "本分支使用初始快照成功完成，局部重试时保留结果。"}
    if key == ("daily", "report"):
        return {"final_revenue_yuan": sum(r["paid_amount"] for r in inputs["quality"]["records"]), "store_count": len(inputs["quality"]["records"]), "validation_status": inputs["quality"]["validation_status"], "preserved_metrics": inputs["metrics"], "note": "最终收入根据修复后的完整数据重新计算；无关成功分支未重跑。"}
    raise ValueError("Unsupported demo node")
