from __future__ import annotations

import json
from collections import deque
from typing import Any

SUPPORTED_NODES = {"input", "llm", "tool", "output"}
DEMO_TOOLS = {"text_summary", "json_validate"}

def validate_graph(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    node_ids = [node.get("id", "") for node in nodes]
    known = set(node_ids)
    if len(node_ids) != len(known):
        errors.append("节点 ID 必须唯一。")
    if not nodes:
        return [], [*errors, "流程至少需要一个节点。"]
    for node in nodes:
        if node.get("type") not in SUPPORTED_NODES:
            errors.append(f"节点 {node.get('id')} 使用了不支持的类型。")
        if node.get("type") == "tool":
            name = (node.get("config") or {}).get("tool_name", "text_summary")
            if name not in DEMO_TOOLS:
                errors.append(f"工具节点 {node.get('id')} 使用了未注册的工具 {name}。")
    input_ids = [node["id"] for node in nodes if node.get("type") == "input"]
    output_ids = [node["id"] for node in nodes if node.get("type") == "output"]
    if not input_ids:
        errors.append("流程至少需要一个输入节点。")
    if not output_ids:
        errors.append("流程至少需要一个输出节点。")

    indegree = {node_id: 0 for node_id in known}
    outgoing = {node_id: [] for node_id in known}
    incoming = {node_id: [] for node_id in known}
    seen_edges: set[tuple[str, str]] = set()
    for edge in edges:
        source, target = edge.get("source"), edge.get("target")
        if source not in known or target not in known:
            errors.append(f"连线 {edge.get('id')} 引用了不存在的节点。")
            continue
        if source == target:
            errors.append(f"节点 {source} 不能连接到自身。")
            continue
        if (source, target) in seen_edges:
            errors.append(f"节点 {source} 与 {target} 之间存在重复连线。")
            continue
        seen_edges.add((source, target))
        outgoing[source].append(target)
        incoming[target].append(source)
        indegree[target] += 1
    for node in nodes:
        node_id = node["id"]
        if node.get("type") == "input" and incoming[node_id]:
            errors.append("输入节点不能有入边。")
        if node.get("type") == "output" and outgoing[node_id]:
            errors.append("输出节点不能有出边。")

    order: list[str] = []
    queue = deque(node_id for node_id in node_ids if indegree[node_id] == 0)
    while queue:
        node_id = queue.popleft()
        order.append(node_id)
        for target in outgoing[node_id]:
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    if len(order) != len(node_ids):
        errors.append("流程中存在循环连线；第一版只支持 DAG 有向无环流程。")

    reachable: set[str] = set()
    stack = list(input_ids)
    while stack:
        current = stack.pop()
        if current in reachable:
            continue
        reachable.add(current)
        stack.extend(outgoing.get(current, []))
    disconnected = [node_id for node_id in node_ids if node_id not in reachable]
    if disconnected:
        errors.append(f"以下节点无法从任何输入节点到达：{', '.join(disconnected)}。")
    unreachable_outputs = [node_id for node_id in output_ids if node_id not in reachable]
    if unreachable_outputs:
        errors.append(f"以下输出节点无法从输入节点到达：{', '.join(unreachable_outputs)}。")
    for input_id in input_ids:
        branch_reachable: set[str] = set()
        branch_stack = [input_id]
        while branch_stack:
            current = branch_stack.pop()
            if current in branch_reachable:
                continue
            branch_reachable.add(current)
            branch_stack.extend(outgoing.get(current, []))
        if not any(output_id in branch_reachable for output_id in output_ids):
            errors.append(f"输入节点 {input_id} 无法到达任何输出节点。")
    if any(node.get("type") == "llm" and len(incoming.get(node.get("id"), [])) == 0 for node in nodes if node.get("type") != "input"):
        errors.append("LLM 节点必须连接上游输入。")
    return order, list(dict.fromkeys(errors))

def run_node(node: dict[str, Any], upstream: list[Any], task_title: str, task_description: str) -> Any:
    config = node.get("config") or {}
    if config.get("simulate_failure"):
        raise RuntimeError("节点配置为演示失败，用于展示失败状态。")
    kind = node["type"]
    if kind == "input":
        return {"title": task_title, "description": task_description}
    text = "\n".join(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False) for value in upstream)
    if kind == "llm":
        instruction = config.get("prompt_template") or "对输入进行清晰、简洁的整理"
        return {"text": f"演示模型输出（未调用真实模型）\n任务：{task_title}\n处理要求：{instruction}\n输入摘要：{text[:800]}"}
    if kind == "tool":
        name = config.get("tool_name", "text_summary")
        if name == "text_summary":
            return {"text": text[:600], "truncated": len(text) > 600}
        if name == "json_validate":
            parsed = json.loads(text)
            return {"valid": True, "value": parsed}
        raise RuntimeError(f"工具 {name} 未在演示工具白名单中注册。")
    if kind == "output":
        return {"result": text or task_title}
    raise RuntimeError(f"不支持的节点类型：{kind}")
