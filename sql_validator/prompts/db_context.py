"""
prompts/db_context.py
──────────────────────
db_context_agent 使用的 Prompt 模板。
"""

DB_SNAPSHOT_EXTRACTION_PROMPT = """\
根据以下数据库探查过程的对话记录，提取结构化的数据库快照信息。

对话记录：
{agent_conversation}

请将发现的所有数据库对象信息整理为结构化 json 格式。
对于每张表，包含：schema名、表名、列信息（名称/类型/是否可空/默认值）、
主键、外键约束、索引信息。
对于视图和函数，包含基本信息。

agent_query_notes 字段中记录：Agent 主动追查了哪些额外的依赖关系，
发现了哪些隐式依赖或潜在风险。
"""
