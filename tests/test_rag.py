from pathlib import Path
from rag import retrieve_context


def test_retrieve_context_returns_relevant_note():
    knowledge = Path(__file__).parents[1] / "knowledge"
    result = retrieve_context("Jenkins pipeline stages and build tests", knowledge)
    assert "Jenkins" in result or "pipeline" in result.lower()
