# SQL 脚本变更说明对比报告

| 字段 | 值 |
|---|---|
| 生成时间 | 2026-04-29 14:32:18 |
| SQL 文件数 | 1 |
| 总体判定 | ✅ **PASS** |
| 风险等级 | 🟢 LOW |
| LLM 置信度 | 92% |

---

## 执行概要

本次发版包含 1 个 SQL 脚本文件，整体方向为**新增用户分层维度表并完成初始化数据写入**。  
变更说明中提及的所有事项均在脚本中找到对应实现，执行顺序合理，无高风险操作。

> 建议正常发版。

---

## 变更覆盖情况

### ✅ 已确认（3 项）

| 变更说明要点 | 对应实现 |
|---|---|
| 表包含 4 个分层（普通 / 银牌 / 金牌 / 钻石） | `02_insert_dim_user_level.sql` — INSERT 4 条初始化记录 |
| 插入初始化数据 | `02_insert_dim_user_level.sql` — `INSERT INTO ... VALUES (...)` |

### ❌ 遗漏（0 项）

无遗漏项。

### ⚠️ 额外变更（0 项）

无额外变更。

---

## 🔴 高风险操作清单

无高风险操作。

---

## 数据库变更影响详情

### 新增对象（1 个）

| 对象类型 | Schema | 对象名 | 所在文件 |
|---|---|---|---|


**新增表结构：**

```sql
CREATE TABLE IF NOT EXISTS public.dim_user_level (
    level_id   SERIAL PRIMARY KEY,
    level_name VARCHAR(50) NOT NULL,
    min_score  INT NOT NULL DEFAULT 0,
    max_score  INT NOT NULL DEFAULT 100,
    created_at TIMESTAMP DEFAULT NOW()
);
```

### 修改对象（0 个）

无。

### 删除对象（0 个）

无。

### DML 数据影响

| 表名 | 操作 | 影响行数估算 | 所在文件 |
|---|---|---|---|
| `public.dim_user_level` | INSERT | 4 行（初始化数据） | `02_insert_dim_user_level.sql` |

---

## 审核结论

> **✅ 审核结论：建议正常发版**
>
> 变更说明与脚本实现完全吻合，逻辑清晰，无遗漏，无高风险操作。执行顺序已经过依赖分析确认。

---

*本报告由 SQL 变更校验智能体自动生成*
