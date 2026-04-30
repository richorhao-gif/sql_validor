"""
core/dependency.py
───────────────────
纯函数层：根据各文件的"创建对象"与"读写对象"集合，
构建文件间依赖关系图并做拓扑排序（Kahn 算法）。

无 LLM、无 DB 连接。
"""
from __future__ import annotations

from collections import defaultdict, deque
from typing import Any


def build_dependency_graph(parsed_scripts: list[dict[str, Any]]) -> dict[str, Any]:
    """
    根据 ParsedScript.model_dump() 列表构建依赖图。

    依赖规则：
      若文件 B 读取或写入的对象中有任一是文件 A 新建的对象，则 B 依赖 A
      （B 必须在 A 之后执行）。

    Returns:
        dict，结构与 DependencyGraph Pydantic 模型一致
    """
    all_files: list[str] = [s["filename"] for s in parsed_scripts]

    # 每个文件创建了哪些对象
    file_creates: dict[str, set[str]] = {}
    # 每个文件读写了哪些对象（读 + 写，排除自己创建的）
    file_uses: dict[str, set[str]] = {}

    for script in parsed_scripts:
        fn = script["filename"]
        created = set(script.get("objects_created", []))
        reads = set(script.get("objects_read", []))
        written = set(script.get("objects_written", []))
        file_creates[fn] = created
        # 使用集合 = 读 + 写 - 自身创建（自建自用不算外部依赖）
        file_uses[fn] = (reads | written) - created

    # 构建依赖边：dep_map[B] = [A, ...] 表示 B 依赖 A
    dep_map: dict[str, list[str]] = {fn: [] for fn in all_files}

    for file_b in all_files:
        for file_a in all_files:
            if file_a == file_b:
                continue
            # 若 B 使用了 A 创建的对象，则 B 依赖 A
            if file_creates[file_a] & file_uses[file_b]:
                if file_a not in dep_map[file_b]:
                    dep_map[file_b].append(file_a)

    # 拓扑排序
    execution_order, has_cycles, cycle_paths = _topological_sort(all_files, dep_map)

    # 反向索引
    reverse_map: dict[str, list[str]] = {fn: [] for fn in all_files}
    for fn, deps in dep_map.items():
        for dep in deps:
            if fn not in reverse_map[dep]:
                reverse_map[dep].append(fn)

    return {
        "execution_order": execution_order,
        "dependency_map": dep_map,
        "reverse_map": reverse_map,
        "has_cycles": has_cycles,
        "cycle_paths": cycle_paths,
        "analysis_notes": "",  # 由 LLM 填充
    }


def _topological_sort(
    nodes: list[str],
    dep_map: dict[str, list[str]],
) -> tuple[list[str], bool, list[list[str]]]:
    """
    Kahn 算法拓扑排序。

    dep_map[B] = [A] 表示 B 依赖 A，即图中存在边 A → B（A 先于 B 执行）。

    Returns:
        (execution_order, has_cycles, cycle_paths)
    """
    # adj[A] = [B, ...] 表示 A 执行完才能执行 B
    adj: dict[str, list[str]] = defaultdict(list)
    in_degree: dict[str, int] = {n: 0 for n in nodes}

    for node, deps in dep_map.items():
        for dep in deps:
            adj[dep].append(node)
            in_degree[node] = in_degree.get(node, 0) + 1

    # 修正：确保所有节点都在 in_degree 中
    for node in nodes:
        if node not in in_degree:
            in_degree[node] = 0

    queue: deque[str] = deque(n for n in nodes if in_degree[n] == 0)
    order: list[str] = []

    while queue:
        node = queue.popleft()
        order.append(node)
        for dependent in adj[node]:
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)

    has_cycles = len(order) < len(nodes)
    cycle_paths: list[list[str]] = []

    if has_cycles:
        remaining = set(nodes) - set(order)
        cycle_paths = [list(remaining)]
        # 循环依赖节点排在末尾，不阻断流程
        order.extend(sorted(remaining))

    return order, has_cycles, cycle_paths
