"""
prompts/impact_analysis.py
───────────────────────────
dependency_analyzer 和 db_impact_analyzer 节点使用的 Prompt 模板。
"""

DEPENDENCY_ANALYSIS_PROMPT = """\
你是一名数据仓库架构师。以下是本次发版包含的 SQL 脚本文件解析摘要：

{scripts_summary}

代码层 dependency_analyzer 已基于对象引用关系计算出建议执行顺序：
{computed_order}

请综合判断并补充：
1. 是否认同计算出的执行顺序？如有异议请说明原因。
2. 是否存在代码层无法识别的隐式依赖（如通过动态 SQL、配置表跳转等）？
3. 如存在循环依赖，给出解决建议。

请在 analysis_notes 字段中用中文说明依赖关系分析结论（3-5句话）。
其余字段（execution_order、dependency_map 等）直接使用计算结果即可，如有修正请在对应字段中体现。

请以 json 格式输出结果。
"""

DB_IMPACT_PROMPT = """\
你是一名数据仓库专家。请根据以下信息，汇总本次发版对数据库的全局影响。

执行顺序：{execution_order}

各文件解析结果：
{scripts_summary}

数据库当前状态快照：
{db_snapshot_summary}

请分析：
1. 本次发版新增/修改/删除了哪些数据库对象？
2. 哪些表的数据会发生变化？变化的范围和方式？
3. 是否存在跨文件的逻辑依赖链（如 file1 创建的表被 file3 填充数据）？
4. 结合数据库当前状态，描述每个主要变更的"变更前 vs 变更后"。

输出字段说明（严格使用以下字段名，以 json 格式返回）：

changes 列表中每条 DBChange 必须包含：
  - source_file: 来源文件名（字符串）
  - object_full_name: schema.对象名 格式（如 public.dim_user_level）
  - object_type: TABLE / VIEW / INDEX / FUNCTION 等
  - operation: CREATE / ALTER / DROP / INSERT / UPDATE 等
  - before_state: 变更前状态描述（若对象不存在则填 null）
  - after_state: 变更后状态描述（字符串，必填）
  - impact_scope: 必须是 SCHEMA_ONLY / DATA_ONLY / SCHEMA_AND_DATA 之一
  - is_destructive: true/false，DROP 或 TRUNCATE 时为 true

顶层字段：
  - execution_sequence: 文件执行顺序列表（字符串数组，必填）
  - new_objects: 新增对象的全限定名列表
  - modified_objects: 修改对象的全限定名列表
  - removed_objects: 删除对象的全限定名列表
  - data_affected_tables: 有数据变动的表名列表
  - cross_file_dependencies: 跨文件依赖说明列表
  - schema_changes_summary: Schema 变更总结
  - data_changes_summary: 数据变更总结
  - overall_summary: 整体影响总结

对破坏性操作（DROP、TRUNCATE）必须标注 is_destructive=true。
请以 json 格式输出结果。
"""
