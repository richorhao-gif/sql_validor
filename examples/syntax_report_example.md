# SQL 脚本语法与质量分析报告

| 字段 | 值 |
|---|---|
| 生成时间 | 2026-04-29 14:32:18 |
| 分析文件数 | 1 |
| 综合质量评分 | 🟢 **91 / 100** |
| ERROR 数 | 0 |
| WARNING 数 | 2 |
| INFO 数 | 1 |

---

## 各文件质量概览

| 文件名 | ERROR | WARNING | INFO | 主要问题摘要 |
|---|---|---|---|---|
| `02_insert_dim_user_level.sql` | 0 | 0 | 1 |  |

---

## 🔴 ERROR 级问题（0 项）

本次发版无 ERROR 级语法问题。

---

## 🟡 WARNING 级问题（2 项）

### W1 · `02_insert_dim_user_level.sql` — SELECT_STAR

**规则：** `SELECT_STAR`  
**严重度：** WARNING  
**描述：** 子查询中使用了 `SELECT *`，建议改为明确列名，避免因源表结构变更导致隐性错误。

**涉及片段：**
```sql
INSERT INTO dim_user_level
SELECT * FROM staging_dim_user_level;
```

**建议：** 将 `SELECT *` 替换为明确列名：
```sql
INSERT INTO dim_user_level (level_name, min_score, max_score)
SELECT level_name, min_score, max_score FROM staging_dim_user_level;
```

---

### W2 · `02_insert_dim_user_level.sql` — TRUNCATE_TABLE

**规则：** `TRUNCATE_TABLE`  
**严重度：** WARNING  
**描述：** 脚本中包含 TRUNCATE 操作，属不可逆的破坏性操作，执行前须确认备份策略。

**涉及片段：**
```sql
TRUNCATE TABLE staging_dim_user_level;
```

**建议：** 确认已备份 `staging_dim_user_level`，并在变更说明中明确说明此操作的必要性。

---

## 🔵 INFO 级问题（2 项）

| # | 文件 | 规则 | 描述 |
|---|---|---|---|
| 1 | `02_insert_dim_user_level.sql` | `DML_TARGET_NOT_IN_DB` | 写入目标 `public.dim_user_level` 在快照采集时不存在（由同批次 01 文件创建，属正常情况） |

---

## 专项分析

### 🛡️ 安全风险

| 风险类型 | 数量 | 详情 |
|---|---|---|
| 无 WHERE 的 DELETE | 0 | — |
| 无 WHERE 的 UPDATE | 0 | — |
| TRUNCATE 操作 | 1 | `02_insert_dim_user_level.sql` |
| DROP 操作 | 0 | — |

### ⚡ 性能规范

| 问题类型 | 数量 | 详情 |
|---|---|---|
| SELECT * | 1 | 见 W1 |
| 大表全量扫描（无 LIMIT） | 0 | — |
| 缺失索引建议 | 0 | — |

---

## 改进建议

1. **明确 INSERT 列名**（高优先）：将 `INSERT INTO ... SELECT *` 替换为明确列名，提升可维护性与安全性。
2. **TRUNCATE 前确认备份**（中优先）：对 `staging_dim_user_level` 的 TRUNCATE，建议在 CI/CD 流水线中添加备份检查步骤。
3. **添加脚本头部注释**（低优先）：建议在每个脚本开头添加注释说明作者、日期、关联变更说明编号，提升可追溯性。
4. **统一命名规范**（信息）：当前命名格式 `序号_操作类型_对象名.sql` 符合规范，请继续保持。

---

*本报告由 SQL 变更校验智能体自动生成*
