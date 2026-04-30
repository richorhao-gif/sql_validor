"""
prompts/file_analysis.py
─────────────────────────
file_analyzer 节点使用的 Prompt 模板。
LLM 只负责填充 intent_summary，其余字段已由 sqlglot 填充。
"""

FILE_INTENT_PROMPT = """\
你是一名数据仓库专家。以下是对一个 SQL 文件的结构化解析结果，
请根据这些信息提炼该文件的业务意图。

文件名：{filename}

操作摘要：
- 新建对象: {objects_created}
- 修改对象: {objects_altered}
- 删除对象: {objects_dropped}
- DML 写入: {objects_written}
- SELECT 读取: {objects_read}

语句列表（前10条）：
{statements_preview}

数据库上下文（相关对象当前状态）：
{db_context}

请用 **简洁中文** 描述：
1. 本文件的核心业务目的（1-2句话）
2. 主要操作类型（如：建表初始化、历史数据迁移、新增字段、索引优化、数据刷新等）
3. 与数据仓库哪一层相关（ODS/DWD/DWS/ADS/维度表，如无法判断可注明）

返回不超过 150 字的意图描述。
"""
