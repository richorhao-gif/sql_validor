"""
report_writer.py
─────────────────
Markdown 报告生成模块。

对外暴露两个公开函数：
  write_change_report(report, sql_files, output_dir)  ->  str (报告路径)
  write_syntax_report(report, sql_files, output_dir)  ->  str (报告路径)

变更报告新增【发版人员概览】矩阵（按发版者汇总），并在详情区按发版者分组展示问题。
语法报告同样在文件概览表中注明发版者。

"有问题"判定标准：
  变更报告  —— 该文件有任意 severity 为 CRITICAL / HIGH / MEDIUM 的 Finding
  语法报告  —— 该文件的 error_count > 0 或 warning_count > 0
"""
from __future__ import annotations

import os
from datetime import datetime

from sql_validator.schemas.report import Finding, ValidationReport
from sql_validator.schemas.syntax_report import SyntaxFinding, SyntaxReport
from sql_validator.utils import parse_developer_from_filename

# ─────────────────────────────────────────────────────────────────────────────
# 内部工具
# ─────────────────────────────────────────────────────────────────────────────

_SEV_ICON = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🔵", "INFO": "⚪"}


def _get_developer(f: dict) -> str:
    """从 SQLFile dict 取开发者；若为空则尝试从文件名解析，最终兜底为"未知开发者"。"""
    dev = (f.get("developer") or "").strip()
    if not dev:
        dev = parse_developer_from_filename(f.get("filename", ""))
    return dev or "未知开发者"


def _file_has_change_issues(filename: str, findings: list[Finding]) -> bool:
    """变更报告：是否有 CRITICAL/HIGH/MEDIUM 级别 Finding。"""
    return any(
        f.file in (filename, "all") and f.severity in ("CRITICAL", "HIGH", "MEDIUM")
        for f in findings
    )


def _file_has_syntax_issues(filename: str, file_results) -> bool:
    """语法报告：是否有 ERROR 或 WARNING 问题。"""
    for fr in file_results:
        if fr.filename == filename:
            return fr.error_count > 0 or fr.warning_count > 0
    return False


def _group_by_developer(sql_files: list[dict]) -> dict[str, list[str]]:
    """返回 {developer: [filename, ...]} 有序映射（按首次出现顺序）。"""
    result: dict[str, list[str]] = {}
    for f in sql_files:
        dev = _get_developer(f)
        result.setdefault(dev, []).append(f["filename"])
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 变更报告
# ─────────────────────────────────────────────────────────────────────────────

def write_change_report(
    report: ValidationReport,
    sql_files: list[dict],
    output_dir: str,
) -> str:
    """
    将 ValidationReport 写成 Markdown，返回文件路径。

    Args:
        report    : Agent 产出的结构化报告
        sql_files : ValidationRequest.sql_files 转换的 dict 列表
                    （必须含 filename；可选含 developer）
        output_dir: 输出目录
    """
    os.makedirs(output_dir, exist_ok=True)
    ts_file    = datetime.now().strftime("%Y%m%d_%H%M%S")
    ts_display = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    path       = os.path.join(output_dir, f"change_report_{ts_file}.md")

    verdict_icon = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}.get(report.verdict, "")
    risk_icon    = {"LOW": "🟢", "MEDIUM": "🟡", "HIGH": "🟠", "CRITICAL": "🔴"}.get(report.risk_level, "")
    confidence_str = f"{report.confidence}%" if report.confidence else "—"

    conclusion_label = {
        "PASS": "✅ 审核结论：建议正常发版",
        "WARN": "⚠️ 审核结论：建议审查高风险项后再发版",
        "FAIL": "❌ 审核结论：存在阻断性风险，暂不建议发版",
    }.get(report.verdict, report.verdict)

    callout_type = {"PASS": "TIP", "WARN": "WARNING", "FAIL": "CAUTION"}.get(report.verdict, "NOTE")

    lines: list[str] = [
        "# SQL 脚本变更说明对比报告",
        "",
        "| 字段 | 值 |",
        "|:---|:---|",
        f"| 📅 生成时间 | {ts_display} |",
        f"| 📁 SQL 文件数 | {len(sql_files)} |",
        f"| 🏁 总体判定 | {verdict_icon} **{report.verdict}** |",
        f"| {risk_icon} 风险等级 | **{report.risk_level}** |",
        f"| 🤖 LLM 置信度 | {confidence_str} |",
        "",
        "---",
        "",
    ]

    if report.execution_order:
        lines += [
            "> **推荐执行顺序：** " + " → ".join(f"`{f}`" for f in report.execution_order),
            "",
        ]

    # ── 发版人员概览矩阵 ──────────────────────────────────────────────────────
    dev_files_map = _group_by_developer(sql_files)
    lines += ["## 本次发版人员概览", ""]
    lines += [
        "| 开发者 | 文件数 | 文件名 | ✅ 无问题 | ❌ 有问题 |",
        "|:---|:---:|:---|:---:|:---:|",
    ]
    total_ok = 0
    total_bad = 0
    for dev, filenames in dev_files_map.items():
        bad = [fn for fn in filenames if _file_has_change_issues(fn, report.findings)]
        ok  = [fn for fn in filenames if fn not in bad]
        total_ok  += len(ok)
        total_bad += len(bad)
        fname_md = "<br>".join(f"`{fn}`" for fn in filenames)
        lines.append(
            f"| {dev} | {len(filenames)} | {fname_md} | {len(ok)} | {len(bad)} |"
        )
    lines.append(
        f"| **合计** | **{len(sql_files)}** | — | **{total_ok}** | **{total_bad}** |"
    )
    lines += [""]
    summary_status = (
        f"✅ {total_ok} 个文件无问题，❌ {total_bad} 个文件有问题。"
        if total_bad
        else f"✅ 全部 {total_ok} 个文件无问题。"
    )
    lines += [
        f"> 本次发版共 **{len(sql_files)}** 个文件，涉及 **{len(dev_files_map)}** 位开发者。{summary_status}",
        "",
        "---",
        "",
    ]

    # ── 审核结论 ──────────────────────────────────────────────────────────────
    lines += [
        "## 审核结论",
        "",
        f"> [!{callout_type}]",
        f"> **{conclusion_label}**",
        ">",
        f"> {report.summary}",
        "",
    ]

    # ── 执行概要 ──────────────────────────────────────────────────────────────
    if report.execution_overview or report.summary:
        lines += ["## 执行概要", ""]
        lines += [report.execution_overview or report.summary, "", "---", ""]

    # ── 按发版者详情 ──────────────────────────────────────────────────────────
    lines += ["## 发版人员详情", ""]
    for dev, filenames in dev_files_map.items():
        dev_findings = [
            f for f in report.findings
            if f.file in filenames or f.file == "all"
        ]
        lines += [f"### 👤 {dev}（{len(filenames)} 个文件）", ""]
        for fname in filenames:
            file_findings = [f for f in report.findings if f.file == fname]
            bad = _file_has_change_issues(fname, report.findings)
            status_icon = "❌ 有问题" if bad else "✅ 无问题"
            finding_cnt = len(file_findings)
            lines += [f"#### 📄 `{fname}` — {status_icon}", ""]
            if not file_findings:
                lines += ["该文件无发现问题。", ""]
            else:
                lines += [
                    "| # | 严重度 | 类别 | 描述 |",
                    "|:---:|:---:|:---|:---|",
                ]
                for i, ff in enumerate(file_findings, 1):
                    icon = _SEV_ICON.get(ff.severity, "")
                    desc_short = ff.description[:100] + ("…" if len(ff.description) > 100 else "")
                    lines.append(f"| {i} | {icon} {ff.severity} | {ff.category} | {desc_short} |")
                lines.append("")
                for i, ff in enumerate(file_findings, 1):
                    lines += [
                        f"**F{i} · [{ff.severity}] {ff.category}**",
                        "",
                        ff.description,
                    ]
                    if ff.suggestion:
                        lines += ["", f"> [!TIP]", f"> **建议：** {ff.suggestion}"]
                    lines.append("")

        # 文件级 "all" 通用问题挂在该开发者的最后一个文件后面
        # （若已在 per-file 里展示则不重复）
        lines += [""]

    lines += ["---", ""]

    # ── 变更覆盖情况 ──────────────────────────────────────────────────────────
    confirmed_n = len(report.confirmed_changes)
    missing_n   = len(report.missing_changes)
    extra_n     = len(report.extra_changes)

    lines += [
        "## 变更覆盖情况",
        "",
        "| 类别 | 数量 |",
        "|:---|:---:|",
        f"| ✅ 已确认 | {confirmed_n} |",
        f"| ❌ 遗漏 | {missing_n} |",
        f"| ⚠️ 额外变更 | {extra_n} |",
        "",
    ]

    lines += [f"### ✅ 已确认（{confirmed_n} 项）", ""]
    if report.confirmed_changes:
        lines += ["| # | 变更说明要点 | 对应实现 |", "|:---:|:---|:---|"]
        for i, c in enumerate(report.confirmed_changes, 1):
            lines.append(f"| {i} | {c.point} | {c.implementation} |")
    else:
        lines.append("_无已确认变更。_")
    lines.append("")

    lines += [f"### ❌ 遗漏（{missing_n} 项）", ""]
    if report.missing_changes:
        for c in report.missing_changes:
            lines.append(f"- ❌ {c}")
    else:
        lines.append("_无遗漏项。_")
    lines.append("")

    lines += [f"### ⚠️ 额外变更（{extra_n} 项）", ""]
    if report.extra_changes:
        for c in report.extra_changes:
            lines.append(f"- ⚠️ {c}")
    else:
        lines.append("_无额外变更。_")
    lines += ["", "---", ""]

    # ── 高风险操作 ────────────────────────────────────────────────────────────
    lines += ["## 🔴 高风险操作清单", ""]
    if report.high_risk_operations:
        lines += ["| # | 操作描述 |", "|:---:|:---|"]
        for i, op in enumerate(report.high_risk_operations, 1):
            lines.append(f"| {i} | {op} |")
    else:
        lines += ["> [!TIP]", "> 无高风险操作，本次变更较为安全。"]
    lines += ["", "---", ""]

    # ── 数据库变更影响详情 ────────────────────────────────────────────────────
    new_n     = len(report.new_objects)
    altered_n = len(report.altered_objects)
    dropped_n = len(report.dropped_objects)
    dml_n     = len(report.dml_changes)

    lines += [
        "## 数据库变更影响详情",
        "",
        "| 类别 | 数量 |",
        "|:---|:---:|",
        f"| 🆕 新增对象 | {new_n} |",
        f"| ✏️ 修改对象 | {altered_n} |",
        f"| 🗑️ 删除对象 | {dropped_n} |",
        f"| 📝 DML 操作 | {dml_n} |",
        "",
    ]

    def _obj_table(objs):
        lines.append("| 对象类型 | Schema | 对象名 | 所在文件 | 备注 |")
        lines.append("|:---|:---|:---|:---|:---|")
        for o in objs:
            lines.append(
                f"| `{o.object_type}` | `{o.schema_name}` | `{o.object_name}` | `{o.file}` | {o.notes} |"
            )

    lines += [f"### 🆕 新增对象（{new_n} 个）", ""]
    if report.new_objects:
        _obj_table(report.new_objects)
    else:
        lines.append("_无。_")
    lines.append("")

    lines += [f"### ✏️ 修改对象（{altered_n} 个）", ""]
    if report.altered_objects:
        _obj_table(report.altered_objects)
    else:
        lines.append("_无。_")
    lines.append("")

    lines += [f"### 🗑️ 删除对象（{dropped_n} 个）", ""]
    if report.dropped_objects:
        _obj_table(report.dropped_objects)
    else:
        lines.append("_无。_")
    lines.append("")

    lines += ["### 📝 DML 数据影响", ""]
    if report.dml_changes:
        lines += ["| 表名 | 操作 | 影响行数估算 | 所在文件 |", "|:---|:---:|:---|:---|"]
        for d in report.dml_changes:
            lines.append(
                f"| `{d.table}` | `{d.operation}` | {d.estimated_rows} | `{d.file}` |"
            )
    else:
        lines.append("_无 DML 操作。_")
    lines += [
        "",
        "---",
        "",
        "<sub>🤖 本报告由 SQL 变更校验智能体自动生成</sub>",
    ]

    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))

    return path


# ─────────────────────────────────────────────────────────────────────────────
# 语法报告
# ─────────────────────────────────────────────────────────────────────────────

def write_syntax_report(
    report: SyntaxReport,
    sql_files: list[dict],
    output_dir: str,
) -> str:
    """
    将 SyntaxReport 写成 Markdown，返回文件路径。

    Args:
        report    : Syntax Agent 产出的结构化报告
        sql_files : ValidationRequest.sql_files 转换的 dict 列表
        output_dir: 输出目录
    """
    os.makedirs(output_dir, exist_ok=True)
    ts_file    = datetime.now().strftime("%Y%m%d_%H%M%S")
    ts_display = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    path       = os.path.join(output_dir, f"syntax_report_{ts_file}.md")

    errors   = [f for f in report.findings if f.severity == "ERROR"]
    warnings = [f for f in report.findings if f.severity == "WARNING"]
    infos    = [f for f in report.findings if f.severity == "INFO"]

    score = report.quality_score
    score_icon    = "🟢" if score >= 85 else ("🟡" if score >= 60 else "🔴")
    score_callout = "TIP" if score >= 85 else ("WARNING" if score >= 60 else "CAUTION")

    lines: list[str] = [
        "# SQL 脚本语法与质量分析报告",
        "",
        "| 字段 | 值 |",
        "|:---|:---|",
        f"| 📅 生成时间 | {ts_display} |",
        f"| 📁 分析文件数 | {len(report.file_results)} |",
        f"| {score_icon} 综合质量评分 | **{score} / 100** |",
        f"| 🔴 ERROR 数 | **{len(errors)}** |",
        f"| 🟡 WARNING 数 | **{len(warnings)}** |",
        f"| 🔵 INFO 数 | {len(infos)} |",
        "",
        "---",
        "",
        "## 质量结论",
        "",
        f"> [!{score_callout}]",
        f"> **综合质量评分：{score_icon} {score} / 100**",
        ">",
    ]

    if report.improvement_suggestions:
        lines += ["> **最优先改进项：**", ">"]
        for s in report.improvement_suggestions[:3]:
            lines.append(f"> - {s}")
    else:
        lines.append("> 本次脚本质量良好，无重大改进建议。")

    lines += ["", "---", ""]

    # ── 发版人员文件概览 ──────────────────────────────────────────────────────
    dev_files_map = _group_by_developer(sql_files)
    lines += ["## 本次发版人员概览", ""]
    lines += [
        "| 开发者 | 文件名 | ✅ 无问题 | ❌ 有问题 |",
        "|:---|:---|:---:|:---:|",
    ]
    for dev, filenames in dev_files_map.items():
        bad = [fn for fn in filenames if _file_has_syntax_issues(fn, report.file_results)]
        ok  = [fn for fn in filenames if fn not in bad]
        fname_md = "<br>".join(f"`{fn}`" for fn in filenames)
        lines.append(f"| {dev} | {fname_md} | {len(ok)} | {len(bad)} |")
    lines += ["", "---", ""]

    # ── 各文件质量概览 ────────────────────────────────────────────────────────
    lines += ["## 各文件质量概览", ""]
    lines += [
        "| 文件名 | 开发者 | 🔴 ERROR | 🟡 WARNING | 🔵 INFO | 主要问题摘要 |",
        "|:---|:---|:---:|:---:|:---:|:---|",
    ]
    # 构建 filename→developer map
    fn_dev = {f["filename"]: _get_developer(f) for f in sql_files}
    for fr in report.file_results:
        dev = fn_dev.get(fr.filename, "—")
        e_cell = f"**{fr.error_count}**" if fr.error_count else "—"
        w_cell = f"**{fr.warning_count}**" if fr.warning_count else "—"
        i_cell = str(fr.info_count) if fr.info_count else "—"
        lines.append(
            f"| `{fr.filename}` | {dev} | {e_cell} | {w_cell} | {i_cell} | {fr.main_issues} |"
        )
    lines += ["", "---", ""]

    # ── ERROR ─────────────────────────────────────────────────────────────────
    lines += [f"## 🔴 ERROR 级问题（{len(errors)} 项）", ""]
    if errors:
        for i, f in enumerate(errors, 1):
            dev = fn_dev.get(f.filename, "—")
            lines += [
                f"### E{i} · `{f.filename}` [{dev}] — `{f.rule}`",
                "",
                f"**描述：** {f.description}",
            ]
            if f.sql_snippet:
                lines += ["", "**涉及片段：**", f"```sql\n{f.sql_snippet}\n```"]
            if f.suggestion:
                lines += ["", "> [!TIP]", f"> **建议：** {f.suggestion}"]
            lines.append("")
    else:
        lines += ["> [!TIP]", "> 本次发版无 ERROR 级语法问题。"]
    lines += ["", "---", ""]

    # ── WARNING ───────────────────────────────────────────────────────────────
    lines += [f"## 🟡 WARNING 级问题（{len(warnings)} 项）", ""]
    if warnings:
        for i, f in enumerate(warnings, 1):
            dev = fn_dev.get(f.filename, "—")
            lines += [
                f"### W{i} · `{f.filename}` [{dev}] — `{f.rule}`",
                "",
                f"**描述：** {f.description}",
            ]
            if f.sql_snippet:
                lines += ["", "**涉及片段：**", f"```sql\n{f.sql_snippet}\n```"]
            if f.suggestion:
                lines += ["", "> [!TIP]", f"> **建议：** {f.suggestion}"]
            lines.append("")
    else:
        lines += ["> [!TIP]", "> 本次发版无 WARNING 级问题。"]
    lines += ["", "---", ""]

    # ── INFO ──────────────────────────────────────────────────────────────────
    lines += [f"## 🔵 INFO 级问题（{len(infos)} 项）", ""]
    if infos:
        lines += ["| # | 文件 | 开发者 | 规则 | 描述 |", "|:---:|:---|:---|:---|:---|"]
        for i, f in enumerate(infos, 1):
            dev = fn_dev.get(f.filename, "—")
            desc_short = f.description[:80] + ("…" if len(f.description) > 80 else "")
            lines.append(f"| {i} | `{f.filename}` | {dev} | `{f.rule}` | {desc_short} |")
    else:
        lines.append("_无 INFO 级问题。_")
    lines += ["", "---", ""]

    # ── 专项安全分析 ──────────────────────────────────────────────────────────
    lines += [
        "## 专项分析",
        "",
        "### 🛡️ 安全风险",
        "",
        "| 风险类型 | 数量 | 状态 |",
        "|:---|:---:|:---|",
        f"| 无 WHERE 的 DELETE | {report.no_where_deletes} | {'🔴 需关注' if report.no_where_deletes else '✅ 无'} |",
        f"| 无 WHERE 的 UPDATE | {report.no_where_updates} | {'🔴 需关注' if report.no_where_updates else '✅ 无'} |",
        f"| TRUNCATE 操作 | {report.truncates} | {'🟡 需确认' if report.truncates else '✅ 无'} |",
        f"| DROP 操作 | {report.drops} | {'🟡 需确认' if report.drops else '✅ 无'} |",
        "",
        "### ⚡ 性能规范",
        "",
        "| 问题类型 | 数量 | 状态 |",
        "|:---|:---:|:---|",
        f"| SELECT * 用法 | {report.select_stars} | {'🟡 建议明确列名' if report.select_stars else '✅ 无'} |",
        "",
        "---",
        "",
    ]

    # ── 改进建议 ──────────────────────────────────────────────────────────────
    lines += ["## 改进建议", ""]
    if report.improvement_suggestions:
        for i, s in enumerate(report.improvement_suggestions, 1):
            lines.append(f"{i}. {s}")
    else:
        lines.append("_暂无改进建议。_")
    lines += [
        "",
        "---",
        "",
        "<sub>🤖 本报告由 SQL 语法审查智能体自动生成</sub>",
    ]

    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))

    return path
