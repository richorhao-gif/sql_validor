"""
fetcher.py
───────────
通过 CODING OpenAPI 按 Coding 编号获取发版脚本内容。

流程：
  1. 调用 DescribeGitTree 列出"发版脚本"下的日期子目录
  2. 对每个子目录再次调用 DescribeGitTree 列出 .sql 文件名
  3. 用编号正则过滤，对匹配文件调用 DescribeGitFile 获取 base64 文件内容
  4. 解码后返回，全程无磁盘写入

CODING OpenAPI 文档：https://coding.net/help/openapi
"""
from __future__ import annotations

import base64
import json
import re
import urllib.error
import urllib.request
from typing import NamedTuple

from sql_validator.utils import parse_developer_from_filename

# "发版脚本"在仓库中的顶层目录名
_DEPLOY_FOLDER = "发版脚本"

# 从文件名中提取 Coding 编号，兼容 _#2590_ 和 coding#5151 两种格式
_CODING_RE = re.compile(r"(?:_#|[Cc]oding#?)(\d+)")


class FetchedFile(NamedTuple):
    """从仓库抓取到的单个 SQL 文件信息。"""
    filename: str       # 完整文件名（含 .sql 后缀，不含路径）
    content: str        # 文件文本内容
    developer: str      # 从文件名解析的开发者姓名
    coding_number: str  # 带 # 前缀，如 "#2590"
    date_folder: str    # 所在日期文件夹名，如 "20260422"


def fetch_scripts_by_coding(
    repo_url: str,
    branch: str,
    token: str,
    coding_numbers: list[str],
) -> dict[str, list[FetchedFile]]:
    """
    通过 CODING OpenAPI 搜索并返回匹配 Coding 编号的发版脚本。

    Args:
        repo_url      : 仓库 URL，格式 https://e.coding.net/{team}/{project}/{repo}
        branch        : 分支名，如 "develop"
        token         : CODING Personal Access Token
        coding_numbers: Coding 编号列表，支持带或不带 # 前缀

    Returns:
        按日期文件夹分组：{date_folder_name: [FetchedFile, ...]}

    Raises:
        ValueError       : 编号为空 / 未找到匹配文件
        FileNotFoundError: 仓库中不存在"发版脚本"目录
        RuntimeError     : API 调用失败
    """
    bare_numbers = [n.lstrip("#").strip() for n in coding_numbers if n.strip()]
    if not bare_numbers:
        raise ValueError("Coding 编号列表不能为空")

    # 兼容 _#2590_ 和 coding#5151 / coding5151 两种命名风格
    number_re = re.compile(
        r"(?:_#|[Cc]oding#?)(" + "|".join(re.escape(n) for n in bare_numbers) + r")"
    )

    team, project, repo = _parse_repo_url(repo_url)
    api_base = f"https://{team}.coding.net/open-api"

    # 获取仓库 DepotId
    depot_id = _get_depot_id(api_base, token, repo)

    # 列出"发版脚本"下的所有日期子目录
    date_items = _list_tree(api_base, token, project, depot_id, branch, _DEPLOY_FOLDER)
    if date_items is None:
        raise FileNotFoundError(
            f'仓库中未找到"{_DEPLOY_FOLDER}"目录，请确认分支和仓库路径是否正确'
        )
    date_dirs = sorted(
        _basename(item["Path"]) for item in date_items
        if item.get("Type") == "tree" and _basename(item["Path"]) != _DEPLOY_FOLDER
    )

    results: dict[str, list[FetchedFile]] = {}
    for date_name in date_dirs:
        folder_path = f"{_DEPLOY_FOLDER}/{date_name}"
        items = _list_tree(api_base, token, project, depot_id, branch, folder_path)
        if not items:
            continue

        files: list[FetchedFile] = []
        for item in sorted(items, key=lambda x: x.get("Path", "")):
            if item.get("Type") != "blob":
                continue
            name: str = _basename(item["Path"])
            if not name.lower().endswith(".sql"):
                continue
            if not number_re.search(name):
                continue

            content = _get_file(
                api_base, token, project, depot_id, branch,
                f"{folder_path}/{name}",
            )
            m = _CODING_RE.search(name)
            files.append(FetchedFile(
                filename=name,
                content=content,
                developer=parse_developer_from_filename(name),
                coding_number=f"#{m.group(1)}" if m else "",
                date_folder=date_name,
            ))

        if files:
            results[date_name] = files

    if not results:
        raise ValueError(
            f'在"{_DEPLOY_FOLDER}"目录下未找到匹配指定 Coding 编号的 .sql 文件'
        )

    return results


# ─────────────────────────────────────────────────────────────────────────────
# 内部实现
# ─────────────────────────────────────────────────────────────────────────────

def _basename(path: str) -> str:
    """取路径最后一段，如 '发版脚本/20260422发版/foo.sql' → 'foo.sql'。"""
    return path.rstrip("/").rsplit("/", 1)[-1]


def _parse_repo_url(repo_url: str) -> tuple[str, str, str]:
    """
    从 https://e.coding.net/{team}/{project}/{repo} 解析三元组。

    Returns:
        (team, project, repo)
    """
    url = repo_url.rstrip("/").removesuffix(".git")
    # 支持 https://e.coding.net/team/project/repo 格式
    m = re.match(r"https?://(?:e\.coding\.net|[^/]+)/([^/]+)/([^/]+)/([^/]+)", url)
    if not m:
        raise ValueError(
            f"无法从 repo_url 解析 team/project/repo，请确认格式为 "
            f"https://e.coding.net/{{team}}/{{project}}/{{repo}}，当前值：{repo_url!r}"
        )
    return m.group(1), m.group(2), m.group(3)


def _get_depot_id(api_base: str, token: str, repo_name: str) -> int:
    """
    通过 DescribeTeamDepots 查询仓库名对应的 DepotId。

    Raises:
        FileNotFoundError: 仓库不存在
    """
    resp = _api_call(api_base, token, {"Action": "DescribeTeamDepots", "PageSize": 100, "Page": 1})
    depots = resp.get("Data", {}).get("DepotList", [])
    for d in depots:
        if d.get("Name") == repo_name:
            return int(d["Id"])
    raise FileNotFoundError(
        f'在团队仓库列表中未找到名为 "{repo_name}" 的仓库，'
        f'已有仓库：{[d.get("Name") for d in depots]}'
    )


def _api_call(api_base: str, token: str, payload: dict) -> dict:
    """
    向 CODING OpenAPI 发送 POST 请求，返回解析后的响应 dict。

    Raises:
        RuntimeError: HTTP 错误或 API 返回 Response.Error
    """
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        api_base,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"CODING API HTTP 错误 {exc.code}: {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"CODING API 网络错误: {exc.reason}") from exc

    if data.get("Response", {}).get("Error"):
        err = data["Response"]["Error"]
        raise RuntimeError(
            f"CODING API 返回错误 [{err.get('Code')}]: {err.get('Message')}"
        )
    return data.get("Response", {})


def _list_tree(
    api_base: str, token: str,
    project: str, depot_id: int, ref: str, path: str,
) -> list[dict] | None:
    """
    列出指定 path 下的目录树（非递归）。
    path 为目录名时 API 需加尾部 '/'，根目录传空字符串。

    Returns:
        文件/目录信息列表；若路径不存在返回 None。
    """
    query_path = path.rstrip("/") + "/" if path else ""
    try:
        resp = _api_call(api_base, token, {
            "Action": "DescribeGitTree",
            "ProjectName": project,
            "DepotId": depot_id,
            "Ref": ref,
            "Path": query_path,
            "Recursive": False,
        })
    except RuntimeError as exc:
        if "not found" in str(exc).lower() or "404" in str(exc) or "仓库不存在" in str(exc):
            return None
        raise
    return resp.get("Trees", []) or []


def _get_file(
    api_base: str, token: str,
    project: str, depot_id: int, ref: str, path: str,
) -> str:
    """
    获取单个文件内容（API 返回 base64，此处解码为 UTF-8 字符串）。
    """
    resp = _api_call(api_base, token, {
        "Action": "DescribeGitFile",
        "ProjectName": project,
        "DepotId": depot_id,
        "Ref": ref,
        "Path": path,
    })
    encoded: str = resp.get("GitFile", {}).get("Content", "")
    return base64.b64decode(encoded).decode("utf-8", errors="replace")
