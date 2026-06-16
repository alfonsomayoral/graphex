"""Importance prior, score fusion, and Reciprocal Rank Fusion."""

from __future__ import annotations

from graphex.models import KnowledgeGraph, Node
from graphex.retrieval.fusion import fuse, importance_prior, reciprocal_rank_fusion


def test_importance_prior_god_node_on_top():
    g = KnowledgeGraph()
    g.add_node(Node(id="a", importance=2.0))
    g.add_node(Node(id="b", importance=5.0))
    g.add_node(Node(id="god", is_god=True))
    prior = importance_prior(g)
    assert prior["god"] == 1.0
    assert prior["b"] > prior["a"]
    assert 0.0 <= prior["a"] <= 1.0


def test_importance_prior_all_zero():
    g = KnowledgeGraph()
    g.add_node(Node(id="a"))
    g.add_node(Node(id="b"))
    assert all(v == 0.0 for v in importance_prior(g).values())


def test_fuse_ppr_dominates():
    ppr = {"a": 1.0, "b": 0.5}
    prior = {"a": 0.0, "b": 1.0}
    fused = fuse(ppr, prior, gamma=0.1)
    # Even with b's full prior, a's stronger PPR keeps it ahead at gamma=0.1.
    assert fused["a"] > fused["b"]


def test_rrf_combines_rankings():
    r1 = {"a": 0.9, "b": 0.1, "c": 0.05}
    r2 = {"b": 0.95, "a": 0.2, "c": 0.1}
    combined = reciprocal_rank_fusion([r1, r2])
    # a and b each top one ranking → both beat the consistently-last c.
    assert combined["c"] < combined["a"]
    assert combined["c"] < combined["b"]


def test_rrf_empty():
    assert reciprocal_rank_fusion([]) == {}
