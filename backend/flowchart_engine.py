"""
Flowchart Engine
Parses Python and Java source code structurally into flowchart nodes and edges.
Provides hierarchical layout computation and strict data validation for flowcharts.
"""

import ast
import re
import uuid

ALLOWED_SHAPES = {
    "start", "end", "process", "decision", "inputoutput",
    "document", "subroutine", "connector", "database", "note"
}

DEFAULT_NODE_WIDTH = 160
DEFAULT_NODE_HEIGHT = 70


def generate_node_id(prefix="node"):
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def generate_edge_id(prefix="edge"):
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


# ==================================================================== #
#                   HIERARCHICAL GRAPH LAYOUT ENGINE                   #
# ==================================================================== #

def calculate_hierarchical_layout(nodes, edges, direction="TB"):
    """
    Computes professional hierarchical coordinates (Sugiyama-style) for nodes.
    Supports Top-to-Bottom ('TB') and Left-to-Right ('LR') layouts.
    Preserves all node properties while updating 'x' and 'y'.
    """
    if not nodes:
        return nodes

    node_map = {n["id"]: n for n in nodes}
    in_edges = {n["id"]: [] for n in nodes}
    out_edges = {n["id"]: [] for n in nodes}

    for e in edges:
        s = e.get("source")
        t = e.get("target")
        if s in node_map and t in node_map and s != t:
            out_edges[s].append(t)
            in_edges[t].append(s)

    # 1. Detect and break cycles using DFS
    visited = {}
    acyclic_out = {n["id"]: [] for n in nodes}

    def dfs_cycle(curr_id, path_set):
        visited[curr_id] = True
        path_set.add(curr_id)
        for neighbor in out_edges[curr_id]:
            if neighbor not in path_set:
                acyclic_out[curr_id].append(neighbor)
                if neighbor not in visited:
                    dfs_cycle(neighbor, path_set)
        path_set.remove(curr_id)

    # Find root nodes (in-degree == 0, or type == 'start')
    roots = [n["id"] for n in nodes if n.get("type") == "start" or len(in_edges[n["id"]]) == 0]
    if not roots:
        roots = [nodes[0]["id"]]

    for r in roots:
        if r not in visited:
            dfs_cycle(r, set())
    for n in nodes:
        if n["id"] not in visited:
            dfs_cycle(n["id"], set())

    # 2. Assign ranks using longest path on acyclic graph
    ranks = {n["id"]: 0 for n in nodes}
    # Topological sort
    in_degree = {n["id"]: 0 for n in nodes}
    for u in nodes:
        for v in acyclic_out[u["id"]]:
            in_degree[v] += 1

    queue = [n["id"] for n in nodes if in_degree[n["id"]] == 0]
    if not queue:
        queue = [roots[0]]

    topo_order = []
    while queue:
        curr = queue.pop(0)
        topo_order.append(curr)
        for nxt in acyclic_out[curr]:
            in_degree[nxt] -= 1
            if in_degree[nxt] == 0:
                queue.append(nxt)

    # In case there are remaining nodes not in topo_order:
    for n in nodes:
        if n["id"] not in topo_order:
            topo_order.append(n["id"])

    for u in topo_order:
        curr_rank = ranks[u]
        for v in acyclic_out[u]:
            if ranks[v] < curr_rank + 1:
                ranks[v] = curr_rank + 1

    # Put 'end' nodes at the maximum rank if appropriate
    max_rank = max(ranks.values()) if ranks else 0
    for n in nodes:
        if n.get("type") == "end" and ranks[n["id"]] < max_rank:
            ranks[n["id"]] = max_rank

    # Group nodes by rank
    rank_groups = {}
    for n_id, r in ranks.items():
        rank_groups.setdefault(r, []).append(n_id)

    sorted_ranks = sorted(rank_groups.keys())

    # 3. Position assignment
    node_w = DEFAULT_NODE_WIDTH
    node_h = DEFAULT_NODE_HEIGHT
    gap_x = 80
    gap_y = 90
    margin_top = 80
    margin_left = 100

    # Max layer width calculation to center layers
    max_count = max(len(grp) for grp in rank_groups.values()) if rank_groups else 1
    total_max_span = max_count * node_w + (max_count - 1) * gap_x

    positioned_nodes = []
    for rank_idx, r in enumerate(sorted_ranks):
        layer_nodes = rank_groups[r]
        layer_count = len(layer_nodes)

        # Center this layer relative to total_max_span
        layer_span = layer_count * node_w + (layer_count - 1) * gap_x
        start_offset = (total_max_span - layer_span) / 2

        for i, n_id in enumerate(layer_nodes):
            node = dict(node_map[n_id])
            w = node.get("width", node_w)
            h = node.get("height", node_h)

            if direction == "TB":
                x = margin_left + start_offset + i * (node_w + gap_x)
                y = margin_top + rank_idx * (node_h + gap_y)
            else:  # 'LR'
                x = margin_left + rank_idx * (node_w + gap_x + 30)
                y = margin_top + start_offset + i * (node_h + gap_y)

            node["x"] = round(x)
            node["y"] = round(y)
            node["width"] = w
            node["height"] = h
            positioned_nodes.append(node)

    return positioned_nodes


# ==================================================================== #
#                   PYTHON AST TO FLOWCHART PARSER                     #
# ==================================================================== #

def parse_python_code(code_str):
    """
    Parses Python code structurally using python's built-in ast module.
    Never executes user code. Converts statements, if/else conditions,
    loops (while, for), functions, returns, break, and continue into
    flowchart nodes and connected edges.
    """
    if not code_str or not code_str.strip():
        raise ValueError("Provided Python code is empty.")

    if len(code_str) > 25000:
        raise ValueError("Code exceeds maximum supported length (25,000 characters).")

    try:
        tree = ast.parse(code_str)
    except SyntaxError as se:
        raise ValueError(f"Python Syntax Error at line {se.lineno}, col {se.offset}: {se.msg}")
    except Exception as e:
        raise ValueError(f"Failed to parse Python code: {str(e)}")

    nodes = []
    edges = []

    def make_node(node_type, label, width=DEFAULT_NODE_WIDTH, height=DEFAULT_NODE_HEIGHT, extra_style=None):
        n_id = generate_node_id(node_type)
        style = {
            "fill": "#ffffff",
            "stroke": "#3b82f6" if node_type == "process" else ("#10b981" if node_type in ["start", "end"] else "#f59e0b"),
            "strokeWidth": 2,
            "textColor": "#1e293b",
            "fontSize": 13,
            "textAlign": "center"
        }
        if extra_style:
            style.update(extra_style)

        node = {
            "id": n_id,
            "type": node_type,
            "label": label,
            "width": width,
            "height": height,
            "style": style
        }
        nodes.append(node)
        return n_id

    def make_edge(src, tgt, label="", edge_type="orthogonal"):
        e_id = generate_edge_id()
        edge = {
            "id": e_id,
            "source": src,
            "target": tgt,
            "label": label,
            "type": edge_type,
            "style": {
                "stroke": "#64748b",
                "strokeWidth": 2,
                "markerEnd": "arrow"
            }
        }
        edges.append(edge)
        return e_id

    # Create root Start node
    start_id = make_node("start", "Start", extra_style={"fill": "#ecfdf5", "stroke": "#10b981"})

    def format_expr(node):
        try:
            return ast.unparse(node).strip()
        except Exception:
            return "expr"

    # Context structure for loops and functions
    # Returns (first_node_id, [exit_node_ids])
    def process_statements(stmt_list, loop_ctx=None):
        if not stmt_list:
            return None, []

        first_id = None
        prev_exits = []

        for stmt in stmt_list:
            step_first, step_exits = process_single_statement(stmt, loop_ctx)
            if not step_first:
                continue

            if first_id is None:
                first_id = step_first

            if prev_exits:
                for exit_id in prev_exits:
                    make_edge(exit_id, step_first)

            prev_exits = step_exits

        return first_id, prev_exits

    def process_single_statement(stmt, loop_ctx=None):
        # 1. Assignment / AugAssign
        if isinstance(stmt, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            lbl = format_expr(stmt)
            nid = make_node("process", lbl)
            return nid, [nid]

        # 2. Expression / Call (print, input, or generic)
        elif isinstance(stmt, ast.Expr):
            val = stmt.value
            if isinstance(val, ast.Call) and isinstance(val.func, ast.Name):
                fname = val.func.id
                if fname == "print":
                    args_str = ", ".join(format_expr(a) for a in val.args)
                    nid = make_node("inputoutput", f"Print: {args_str}", extra_style={"fill": "#eff6ff", "stroke": "#3b82f6"})
                    return nid, [nid]
                elif fname == "input":
                    prompt_str = format_expr(val.args[0]) if val.args else ""
                    nid = make_node("inputoutput", f"Read Input: {prompt_str}".strip(), extra_style={"fill": "#eff6ff", "stroke": "#3b82f6"})
                    return nid, [nid]
            lbl = format_expr(stmt)
            nid = make_node("process", lbl)
            return nid, [nid]

        # 3. If / Elif / Else condition
        elif isinstance(stmt, ast.If):
            test_str = format_expr(stmt.test)
            decision_id = make_node("decision", f"{test_str} ?", width=170, height=75, extra_style={"fill": "#fffbeb", "stroke": "#f59e0b"})

            # True branch
            true_first, true_exits = process_statements(stmt.body, loop_ctx)
            if true_first:
                make_edge(decision_id, true_first, label="Yes")
            else:
                true_exits = [decision_id]

            # False / Else branch
            false_exits = []
            if stmt.orelse:
                false_first, false_exits = process_statements(stmt.orelse, loop_ctx)
                if false_first:
                    make_edge(decision_id, false_first, label="No")
            else:
                false_exits = [decision_id]

            combined_exits = []
            combined_exits.extend(true_exits)
            combined_exits.extend(false_exits)
            return decision_id, combined_exits

        # 4. While loop
        elif isinstance(stmt, ast.While):
            test_str = format_expr(stmt.test)
            loop_decision_id = make_node("decision", f"{test_str} ?", width=170, height=75, extra_style={"fill": "#fffbeb", "stroke": "#f59e0b"})

            curr_loop_ctx = {
                "condition_id": loop_decision_id,
                "break_exits": []
            }

            body_first, body_exits = process_statements(stmt.body, curr_loop_ctx)
            if body_first:
                make_edge(loop_decision_id, body_first, label="True")
                for be in body_exits:
                    make_edge(be, loop_decision_id, label="Loop")
            else:
                make_edge(loop_decision_id, loop_decision_id, label="Loop")

            exits = [loop_decision_id]  # False branch exits loop
            exits.extend(curr_loop_ctx["break_exits"])
            return loop_decision_id, exits

        # 5. For loop
        elif isinstance(stmt, ast.For):
            target_str = format_expr(stmt.target)
            iter_str = format_expr(stmt.iter)
            for_decision_id = make_node("decision", f"For {target_str} in {iter_str}", width=180, height=75, extra_style={"fill": "#fffbeb", "stroke": "#f59e0b"})

            curr_loop_ctx = {
                "condition_id": for_decision_id,
                "break_exits": []
            }

            body_first, body_exits = process_statements(stmt.body, curr_loop_ctx)
            if body_first:
                make_edge(for_decision_id, body_first, label="Next")
                for be in body_exits:
                    make_edge(be, for_decision_id, label="Next item")
            else:
                make_edge(for_decision_id, for_decision_id, label="Next")

            exits = [for_decision_id]  # Done branch exits loop
            exits.extend(curr_loop_ctx["break_exits"])
            return for_decision_id, exits

        # 6. Function definition
        elif isinstance(stmt, ast.FunctionDef):
            args_list = [a.arg for a in stmt.args.args]
            func_id = make_node("subroutine", f"def {stmt.name}({', '.join(args_list)})", extra_style={"fill": "#faf5ff", "stroke": "#8b5cf6"})
            body_first, body_exits = process_statements(stmt.body, loop_ctx)
            if body_first:
                make_edge(func_id, body_first)
            return func_id, body_exits

        # 7. Return statement
        elif isinstance(stmt, ast.Return):
            val_str = format_expr(stmt.value) if stmt.value else "None"
            ret_id = make_node("inputoutput", f"Return {val_str}", extra_style={"fill": "#fdf4ff", "stroke": "#c084fc"})
            return ret_id, [ret_id]

        # 8. Break statement
        elif isinstance(stmt, ast.Break):
            break_id = make_node("process", "Break", width=110, height=50)
            if loop_ctx:
                loop_ctx["break_exits"].append(break_id)
            return break_id, []

        # 9. Continue statement
        elif isinstance(stmt, ast.Continue):
            cont_id = make_node("process", "Continue", width=110, height=50)
            if loop_ctx:
                make_edge(cont_id, loop_ctx["condition_id"], label="Continue")
            return cont_id, []

        # Fallback generic statement
        else:
            lbl = format_expr(stmt)
            nid = make_node("process", lbl)
            return nid, [nid]

    first_stmt_id, final_exits = process_statements(tree.body)

    if first_stmt_id:
        make_edge(start_id, first_stmt_id)
    else:
        # Empty body
        final_exits = [start_id]

    end_id = make_node("end", "End", extra_style={"fill": "#ecfdf5", "stroke": "#10b981"})
    for fe in final_exits:
        # Avoid self-edge to end
        if fe != end_id:
            make_edge(fe, end_id)

    # Apply auto layout
    positioned_nodes = calculate_hierarchical_layout(nodes, edges, direction="TB")
    return {
        "nodes": positioned_nodes,
        "edges": edges,
        "title": "Python Code Flowchart"
    }


# ==================================================================== #
#                   JAVA STRUCTURAL CODE PARSER                        #
# ==================================================================== #

def parse_java_code(code_str):
    """
    Parses Java source code structurally without execution.
    Extracts methods, sequential statements, if/else conditions,
    while/for loops, return, break, continue, and System.out calls.
    """
    if not code_str or not code_str.strip():
        raise ValueError("Provided Java code is empty.")

    if len(code_str) > 25000:
        raise ValueError("Code exceeds maximum supported length (25,000 characters).")

    # Clean comments
    cleaned = re.sub(r'//.*?\n', '\n', code_str)
    cleaned = re.sub(r'/\*.*?\*/', '', cleaned, flags=re.DOTALL)

    # Strip package and import lines
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    code_lines = []
    for line in lines:
        if line.startswith("package ") or line.startswith("import "):
            continue
        code_lines.append(line)

    clean_code = " ".join(code_lines)

    # If wrapped in a class or main method, extract inner block
    class_match = re.search(r'class\s+[\w$]+\s*\{([\s\S]*)\}\s*$', clean_code)
    if class_match:
        clean_code = class_match.group(1).strip()

    main_match = re.search(r'(?:public\s+static\s+void\s+main|public\s+[\w$<>\[\]]+\s+[\w$]+)\s*\([^\)]*\)\s*\{([\s\S]*)\}\s*$', clean_code)
    if main_match:
        clean_code = main_match.group(1).strip()

    nodes = []
    edges = []

    def make_node(node_type, label, width=DEFAULT_NODE_WIDTH, height=DEFAULT_NODE_HEIGHT, extra_style=None):
        n_id = generate_node_id(node_type)
        style = {
            "fill": "#ffffff",
            "stroke": "#3b82f6" if node_type == "process" else ("#10b981" if node_type in ["start", "end"] else "#f59e0b"),
            "strokeWidth": 2,
            "textColor": "#1e293b",
            "fontSize": 13,
            "textAlign": "center"
        }
        if extra_style:
            style.update(extra_style)

        node = {
            "id": n_id,
            "type": node_type,
            "label": label,
            "width": width,
            "height": height,
            "style": style
        }
        nodes.append(node)
        return n_id

    def make_edge(src, tgt, label=""):
        e_id = generate_edge_id()
        edge = {
            "id": e_id,
            "source": src,
            "target": tgt,
            "label": label,
            "type": "orthogonal",
            "style": {
                "stroke": "#64748b",
                "strokeWidth": 2,
                "markerEnd": "arrow"
            }
        }
        edges.append(edge)
        return e_id

    start_id = make_node("start", "Start (Java)", extra_style={"fill": "#ecfdf5", "stroke": "#10b981"})

    # Simple lexical statement extractor for Java
    def extract_blocks_and_statements(code_text):
        items = []
        i = 0
        n = len(code_text)

        while i < n:
            while i < n and code_text[i].isspace():
                i += 1
            if i >= n:
                break

            # Check for if statement
            if code_text[i:].startswith("if"):
                match = re.match(r'if\s*\((.*?)\)\s*\{', code_text[i:])
                if match:
                    cond = match.group(1).strip()
                    i += match.end()
                    # Find closing brace
                    depth = 1
                    start_body = i
                    while i < n and depth > 0:
                        if code_text[i] == '{': depth += 1
                        elif code_text[i] == '}': depth -= 1
                        i += 1
                    true_body = code_text[start_body:i-1].strip()

                    # Check for else
                    else_body = ""
                    rest = code_text[i:].strip()
                    if rest.startswith("else"):
                        else_match = re.match(r'else\s*\{', rest)
                        if else_match:
                            i += len(code_text[i:]) - len(rest) + else_match.end()
                            depth = 1
                            start_else = i
                            while i < n and depth > 0:
                                if code_text[i] == '{': depth += 1
                                elif code_text[i] == '}': depth -= 1
                                i += 1
                            else_body = code_text[start_else:i-1].strip()

                    items.append({"type": "if", "cond": cond, "true_body": true_body, "else_body": else_body})
                    continue

            # Check for while loop
            if code_text[i:].startswith("while"):
                match = re.match(r'while\s*\((.*?)\)\s*\{', code_text[i:])
                if match:
                    cond = match.group(1).strip()
                    i += match.end()
                    depth = 1
                    start_body = i
                    while i < n and depth > 0:
                        if code_text[i] == '{': depth += 1
                        elif code_text[i] == '}': depth -= 1
                        i += 1
                    body = code_text[start_body:i-1].strip()
                    items.append({"type": "while", "cond": cond, "body": body})
                    continue

            # Check for for loop
            if code_text[i:].startswith("for"):
                match = re.match(r'for\s*\((.*?)\)\s*\{', code_text[i:])
                if match:
                    header = match.group(1).strip()
                    i += match.end()
                    depth = 1
                    start_body = i
                    while i < n and depth > 0:
                        if code_text[i] == '{': depth += 1
                        elif code_text[i] == '}': depth -= 1
                        i += 1
                    body = code_text[start_body:i-1].strip()
                    items.append({"type": "for", "header": header, "body": body})
                    continue

            # Standard statement ending in ';'
            end_stmt = code_text.find(';', i)
            if end_stmt != -1:
                stmt = code_text[i:end_stmt].strip()
                if stmt:
                    items.append({"type": "stmt", "code": stmt})
                i = end_stmt + 1
            else:
                remaining = code_text[i:].strip()
                if remaining and remaining != "}":
                    items.append({"type": "stmt", "code": remaining})
                break

        return items

    def process_java_items(items):
        if not items:
            return None, []

        first_id = None
        prev_exits = []

        for item in items:
            itype = item["type"]
            step_first = None
            step_exits = []

            if itype == "stmt":
                raw = item["code"]
                # System.out.println
                if "System.out.print" in raw:
                    print_match = re.search(r'System\.out\.println?\s*\((.*)\)', raw)
                    arg = print_match.group(1) if print_match else raw
                    step_first = make_node("inputoutput", f"Print: {arg}", extra_style={"fill": "#eff6ff", "stroke": "#3b82f6"})
                    step_exits = [step_first]
                elif "return" in raw:
                    ret_val = re.sub(r'^\s*return\s*', '', raw)
                    step_first = make_node("inputoutput", f"Return: {ret_val}", extra_style={"fill": "#fdf4ff", "stroke": "#c084fc"})
                    step_exits = [step_first]
                elif raw == "break":
                    step_first = make_node("process", "Break", width=110, height=50)
                    step_exits = [step_first]
                elif raw == "continue":
                    step_first = make_node("process", "Continue", width=110, height=50)
                    step_exits = [step_first]
                else:
                    step_first = make_node("process", raw)
                    step_exits = [step_first]

            elif itype == "if":
                cond = item["cond"]
                step_first = make_node("decision", f"{cond} ?", width=175, height=75, extra_style={"fill": "#fffbeb", "stroke": "#f59e0b"})
                true_sub_items = extract_blocks_and_statements(item["true_body"])
                t_first, t_exits = process_java_items(true_sub_items)
                if t_first:
                    make_edge(step_first, t_first, label="Yes")
                else:
                    t_exits = [step_first]

                f_exits = []
                if item["else_body"]:
                    false_sub_items = extract_blocks_and_statements(item["else_body"])
                    f_first, f_exits = process_java_items(false_sub_items)
                    if f_first:
                        make_edge(step_first, f_first, label="No")
                else:
                    f_exits = [step_first]

                step_exits = t_exits + f_exits

            elif itype == "while":
                cond = item["cond"]
                step_first = make_node("decision", f"{cond} ?", width=175, height=75, extra_style={"fill": "#fffbeb", "stroke": "#f59e0b"})
                body_sub_items = extract_blocks_and_statements(item["body"])
                b_first, b_exits = process_java_items(body_sub_items)
                if b_first:
                    make_edge(step_first, b_first, label="True")
                    for be in b_exits:
                        make_edge(be, step_first, label="Loop")
                step_exits = [step_first]

            elif itype == "for":
                hdr = item["header"]
                step_first = make_node("decision", f"For ({hdr})", width=180, height=75, extra_style={"fill": "#fffbeb", "stroke": "#f59e0b"})
                body_sub_items = extract_blocks_and_statements(item["body"])
                b_first, b_exits = process_java_items(body_sub_items)
                if b_first:
                    make_edge(step_first, b_first, label="Next")
                    for be in b_exits:
                        make_edge(be, step_first, label="Next item")
                step_exits = [step_first]

            if not step_first:
                continue

            if first_id is None:
                first_id = step_first

            if prev_exits:
                for pe in prev_exits:
                    make_edge(pe, step_first)

            prev_exits = step_exits

        return first_id, prev_exits

    top_items = extract_blocks_and_statements(clean_code)
    first_stmt_id, final_exits = process_java_items(top_items)

    if first_stmt_id:
        make_edge(start_id, first_stmt_id)
    else:
        final_exits = [start_id]

    end_id = make_node("end", "End", extra_style={"fill": "#ecfdf5", "stroke": "#10b981"})
    for fe in final_exits:
        if fe != end_id:
            make_edge(fe, end_id)

    positioned_nodes = calculate_hierarchical_layout(nodes, edges, direction="TB")
    return {
        "nodes": positioned_nodes,
        "edges": edges,
        "title": "Java Code Flowchart"
    }


# ==================================================================== #
#                   DATA VALIDATION & SANITIZATION                     #
# ==================================================================== #

def validate_diagram_data(data):
    """
    Validates diagram JSON before saving or returning.
    Enforces maximum limits, valid shape types, and proper edge references.
    Returns (is_valid: bool, sanitized_data: dict, error_msg: str)
    """
    if not isinstance(data, dict):
        return False, None, "Invalid data payload: expected JSON object."

    title = str(data.get("title") or "Untitled Flowchart").strip()[:120]
    if not title:
        title = "Untitled Flowchart"

    description = str(data.get("description") or "").strip()[:500]

    raw_nodes = data.get("nodes", [])
    raw_edges = data.get("edges", [])

    if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
        return False, None, "'nodes' and 'edges' must be arrays."

    if len(raw_nodes) > 200:
        return False, None, "Diagram exceeds maximum allowed node limit (200 nodes)."

    if len(raw_edges) > 300:
        return False, None, "Diagram exceeds maximum allowed edge limit (300 edges)."

    sanitized_nodes = []
    node_ids = set()

    for idx, n in enumerate(raw_nodes):
        if not isinstance(n, dict):
            continue
        n_id = str(n.get("id") or f"node_{idx}").strip()
        if not n_id:
            n_id = f"node_{idx}"
        node_ids.add(n_id)

        shape_type = str(n.get("type") or "process").lower().strip()
        if shape_type not in ALLOWED_SHAPES:
            shape_type = "process"

        label = str(n.get("label") or "").strip()[:400]
        try:
            x = float(n.get("x", 100))
            y = float(n.get("y", 100))
            w = float(n.get("width", DEFAULT_NODE_WIDTH))
            h = float(n.get("height", DEFAULT_NODE_HEIGHT))
        except (ValueError, TypeError):
            x, y, w, h = 100.0, 100.0, float(DEFAULT_NODE_WIDTH), float(DEFAULT_NODE_HEIGHT)

        style = n.get("style", {})
        if not isinstance(style, dict):
            style = {}

        sanitized_style = {
            "fill": str(style.get("fill") or "#ffffff")[:30],
            "stroke": str(style.get("stroke") or "#3b82f6")[:30],
            "strokeWidth": int(style.get("strokeWidth", 2)) if str(style.get("strokeWidth", "")).isdigit() else 2,
            "textColor": str(style.get("textColor") or "#1e293b")[:30],
            "fontSize": int(style.get("fontSize", 13)) if str(style.get("fontSize", "")).isdigit() else 13,
            "textAlign": str(style.get("textAlign") or "center")[:20]
        }

        sanitized_nodes.append({
            "id": n_id,
            "type": shape_type,
            "label": label,
            "x": round(x, 1),
            "y": round(y, 1),
            "width": max(40, min(600, round(w, 1))),
            "height": max(30, min(500, round(h, 1))),
            "style": sanitized_style
        })

    sanitized_edges = []
    for idx, e in enumerate(raw_edges):
        if not isinstance(e, dict):
            continue
        e_id = str(e.get("id") or f"edge_{idx}").strip()
        src = str(e.get("source") or "").strip()
        tgt = str(e.get("target") or "").strip()

        # Enforce that source and target must exist in sanitized_nodes
        if src in node_ids and tgt in node_ids:
            label = str(e.get("label") or "").strip()[:80]
            edge_type = str(e.get("type") or "orthogonal").lower()
            if edge_type not in ["orthogonal", "straight", "curved"]:
                edge_type = "orthogonal"

            e_style = e.get("style", {})
            if not isinstance(e_style, dict):
                e_style = {}

            sanitized_edges.append({
                "id": e_id,
                "source": src,
                "target": tgt,
                "label": label,
                "type": edge_type,
                "style": {
                    "stroke": str(e_style.get("stroke") or "#64748b")[:30],
                    "strokeWidth": int(e_style.get("strokeWidth", 2)) if str(e_style.get("strokeWidth", "")).isdigit() else 2,
                    "markerEnd": str(e_style.get("markerEnd") or "arrow")[:20]
                }
            })

    sanitized = {
        "title": title,
        "description": description,
        "nodes": sanitized_nodes,
        "edges": sanitized_edges,
        "viewport": data.get("viewport", {"x": 0, "y": 0, "zoom": 1.0}),
        "layout": data.get("layout", {"direction": "TB", "grid": "dots", "gridSize": 20})
    }
    return True, sanitized, ""
