"""Selection + honest token accounting, including the never-overflow invariant."""

from __future__ import annotations

from pathlib import Path

import pytest

from graphex.budget import _NODE_OVERHEAD_TOKENS, count_tokens, select_subgraph
from graphex.models import Edge, KnowledgeGraph, Node


def _chain_graph(n: int = 12) -> KnowledgeGraph:
    g = KnowledgeGraph()
    for i in range(n):
        g.add_node(
            Node(
                id=f"n{i}",
                label=f"node{i}",
                type="function",
                file_type="code",
                description=f"does thing number {i} with widgets and gadgets",
                community=i % 3,
            )
        )
    for i in range(n - 1):
        g.add_edge(Edge(source=f"n{i}", target=f"n{i+1}", relation="calls"))
    return g


def test_count_tokens_basic():
    assert count_tokens("") == 0
    assert count_tokens("hello world") > 0


def test_never_exceeds_budget():
    g = _chain_graph(20)
    scores = {nid: 1.0 - i * 0.01 for i, nid in enumerate(g.node_ids)}
    for budget in (10, 25, 50, 100, 300, 1000):
        _sub, stats = select_subgraph(g, scores, budget=budget)
        assert stats["tokens_used"] <= budget, f"overflow at budget={budget}"
        assert stats["tokens_budget"] == budget


def test_empty_and_degenerate():
    empty = KnowledgeGraph()
    sub, stats = select_subgraph(empty, {}, budget=100)
    assert stats["nodes_selected"] == 0 and len(sub) == 0

    g = _chain_graph(3)
    _sub, stats = select_subgraph(g, {n: 1.0 for n in g.node_ids}, budget=0)
    assert stats["nodes_selected"] == 0


def test_min_score_filters_candidates():
    g = _chain_graph(6)
    scores = {nid: (0.9 if i < 2 else 0.01) for i, nid in enumerate(g.node_ids)}
    sub, _stats = select_subgraph(g, scores, budget=10_000, min_score=0.5)
    assert set(sub.node_ids) <= {"n0", "n1"}


def test_higher_scores_preferred_under_tight_budget():
    g = _chain_graph(10)
    # n7 is by far the most relevant; a tight budget should still include it.
    scores = {nid: 0.1 for nid in g.node_ids}
    scores["n7"] = 1.0
    sub, _stats = select_subgraph(
        g, scores, budget=40, redundancy_weight=0.0, connectivity_bonus=0.0
    )
    assert "n7" in sub.node_ids


def test_selected_subgraph_is_induced():
    g = _chain_graph(8)
    scores = {nid: 1.0 for nid in g.node_ids}
    sub, stats = select_subgraph(g, scores, budget=120)
    # Every edge in the subgraph connects two selected nodes.
    keep = set(sub.node_ids)
    for u, v in sub.digraph.edges:
        assert u in keep and v in keep
    assert stats["coverage_pct"] == round(len(keep) / 8 * 100, 1)


def test_inject_code_counted_in_budget(tmp_path: Path):
    src = tmp_path / "mod.py"
    src.write_text(
        "def big_function():\n" + "".join(f"    x{i} = {i}\n" for i in range(40)),
        encoding="utf-8",
    )
    g = KnowledgeGraph()
    g.add_node(
        Node(
            id="mod_big_function",
            label="big_function",
            type="function",
            file_type="code",
            description="a large function",
            source_file="mod.py",
            source_location="L1",
        )
    )
    scores = {"mod_big_function": 1.0}

    # With code injected, the body is large; a tiny budget must reject it honestly
    # rather than render 40 lines of code for "free".
    plain_cost = (
        count_tokens("mod_big_function big_function (function) a large function")
        + _NODE_OVERHEAD_TOKENS
    )
    sub, stats = select_subgraph(
        g, scores, budget=plain_cost + 5, inject_code=True, project_root=tmp_path
    )
    assert stats["nodes_selected"] == 0  # code body doesn't fit → not selected

    sub, stats = select_subgraph(g, scores, budget=10_000, inject_code=True, project_root=tmp_path)
    assert stats["tokens_used"] <= 10_000
    assert "code_block" in sub.digraph.nodes["mod_big_function"]


def test_exact_strategy_matches_or_beats_greedy_on_relevance():
    g = _chain_graph(10)
    scores = {nid: (i + 1) / 10 for i, nid in enumerate(g.node_ids)}
    sub_g, stats_g = select_subgraph(g, scores, budget=120, strategy="greedy")
    sub_e, stats_e = select_subgraph(g, scores, budget=120, strategy="exact")
    val_g = sum(scores[n] for n in sub_g.node_ids)
    val_e = sum(scores[n] for n in sub_e.node_ids)
    assert stats_e["tokens_used"] <= 120
    # Exact maximises pure relevance, so it can never be beaten on that metric.
    assert val_e >= val_g - 1e-9


@pytest.mark.parametrize("strategy", ["greedy", "exact"])
def test_strategies_respect_budget(strategy):
    g = _chain_graph(15)
    scores = {nid: 1.0 for nid in g.node_ids}
    _sub, stats = select_subgraph(g, scores, budget=200, strategy=strategy)
    assert stats["tokens_used"] <= 200
