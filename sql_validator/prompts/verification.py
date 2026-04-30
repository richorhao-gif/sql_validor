"""
prompts/verification.py
────────────────────────
change_verifier 节点使用的 Prompt 模板。
"""

CHANGE_VERIFICATION_PROMPT = """\
你是一名数据仓库发版审核专家。请逐条对比变更说明与 SQL 脚本的实际数据库影响，
判断两者是否一致，并给出审核结论。

【本次发版变更说明】
{change_description}

【SQL 脚本实际数据库影响汇总】
{db_impact_summary}

【详细变更记录】
{changes_detail}

请逐一核对，按以下规则填写结果：

confirmed_items：变更说明中有明确对应脚本实现的条目，每条格式：
  "变更说明「...」→ 对应 [文件名] 中的 [操作]"

missing_items：变更说明提到但脚本中完全找不到对应实现的条目，每条格式：
  "变更说明提到「...」，但未在任何脚本中找到对应实现"

extra_items：脚本中存在但变更说明完全未提及的变更，每条格式：
  "[文件名] 中执行了 [操作]，变更说明未提及"

risk_items：所有高风险操作，每条格式：
  "🔴 [文件名]: [操作描述] — [风险说明]"

verdict 判定规则：
- PASS：confirmed_items 覆盖全部变更说明要点，missing_items 和 extra_items 为空或仅有无关紧要的差异
- WARN：存在少量 extra_items 或轻微描述不一致，但不影响发版安全性
- FAIL：存在任何 missing_items（说明里承诺的功能脚本没实现），或存在未说明的高危操作（DROP/TRUNCATE）

risk_level 判定参考：
- CRITICAL：有未说明的 DROP TABLE / TRUNCATE
- HIGH：有无 WHERE 条件的全表 UPDATE/DELETE
- MEDIUM：有 extra_items 或部分 missing_items
- LOW：全部对应，仅有轻微描述差异

confidence：你对本次审核结论的置信度，0-100 的整数。
analysis_notes：对比分析的详细说明文字，用中文描述核心发现。

请以 json 格式输出结果。
"""
