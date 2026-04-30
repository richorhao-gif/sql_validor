"""
tests/integration/test_graph.py
────────────────────────────────
集成测试：需要真实 DB 连接和 LLM API Key。
通过 pytest.mark.integration 标记，默认不在 CI 中运行。

运行方式：
    uv run pytest tests/integration -m integration
"""
from __future__ import annotations

import pytest


@pytest.mark.integration
def test_full_graph_smoke(tmp_path):
    """
    完整图冒烟测试：验证图能正常跑通并产出两份 MD 文件。
    需要 .env 配置 LLM_API_KEY 和 POSTGRES_DSN。
    """
    from sql_validator.entrypoint import run_validation
    from sql_validator.schemas.inputs import SQLFile, ValidationRequest

    request = ValidationRequest(
        sql_files=[
            SQLFile(
                filename="01_create_dim_user_level.sql",
                content=(
                    "CREATE TABLE IF NOT EXISTS public.dim_user_level (\n"
                    "    level_id   SERIAL PRIMARY KEY,\n"
                    "    level_name VARCHAR(50) NOT NULL,\n"
                    "    min_score  INT NOT NULL DEFAULT 0,\n"
                    "    max_score  INT NOT NULL DEFAULT 100,\n"
                    "    created_at TIMESTAMP DEFAULT NOW()\n"
                    ");\n"
                ),
            ),
            SQLFile(
                filename="02_insert_dim_user_level.sql",
                content=(
                    "INSERT INTO public.dim_user_level (level_name, min_score, max_score)\n"
                    "VALUES\n"
                    "    ('普通用户', 0,   59),\n"
                    "    ('银牌用户', 60,  79),\n"
                    "    ('金牌用户', 80,  99),\n"
                    "    ('钻石用户', 100, 999);\n"
                ),
            ),
        ],
        change_description=(
            "本次发版新增用户分层维度表 dim_user_level，"
            "包含4个分层（普通/银牌/金牌/钻石），并插入初始化数据。"
        ),
    )

    result = run_validation(request)

    assert result.verdict in ("PASS", "WARN", "FAIL")
    assert result.risk_level in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    assert result.change_report_path.endswith(".md")
    assert result.syntax_report_path.endswith(".md")
