"""
Tests for Similarity Engine - Phase 2.4-D

Validates:
- Text vectorization and similarity
- Path similarity (Jaccard index)
- Combined similarity scoring
- find_similar_executions() query
- find_similar_by_error() query
- find_similar_by_paths() query
"""

import pytest
import tempfile
from pathlib import Path

# Add packages to path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "packages"))

from executor import (
    ExecutionStore,
    init_executor_db,
    SimilarityEngine,
    TextVectorizer,
    PathSimilarity
)


@pytest.fixture
def temp_workspace():
    """Create temporary workspace with database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        db_path = workspace / ".lonelycat" / "executor.db"
        init_executor_db(db_path)
        yield workspace


@pytest.fixture
def execution_store(temp_workspace):
    """Create ExecutionStore."""
    return ExecutionStore(temp_workspace)


# ========== Test 1: Text Similarity ==========

def test_text_vectorizer_tokenization():
    """Test text tokenization."""
    vectorizer = TextVectorizer()

    text = "FileNotFoundError: config.json not found in /etc/app"
    tokens = vectorizer.tokenize(text)

    # Should lowercase, remove punctuation, filter stop words
    assert "filenotfounderror" in tokens
    assert "config" in tokens
    assert "json" in tokens
    assert "found" in tokens
    assert "etc" in tokens
    assert "app" in tokens

    # Should remove stop words
    assert "in" not in tokens
    assert "the" not in tokens

    print(f"[OK] Tokens: {tokens}")


def test_text_similarity_same_error_type():
    """Test similarity between same error types."""
    vectorizer = TextVectorizer()

    error1 = "FileNotFoundError: config.json not found"
    error2 = "FileNotFoundError: settings.json not found"

    vec1 = vectorizer.vectorize(error1)
    vec2 = vectorizer.vectorize(error2)

    similarity = vectorizer.cosine_similarity(vec1, vec2)

    # Should be high similarity (same error type)
    assert similarity > 0.5
    print(f"[OK] Same error type similarity: {similarity:.3f}")


def test_text_similarity_different_error_type():
    """Test similarity between different error types."""
    vectorizer = TextVectorizer()

    error1 = "FileNotFoundError: config.json not found"
    error2 = "ValueError: invalid configuration value"

    vec1 = vectorizer.vectorize(error1)
    vec2 = vectorizer.vectorize(error2)

    similarity = vectorizer.cosine_similarity(vec1, vec2)

    # Should be low similarity (different error types)
    assert similarity < 0.5
    print(f"[OK] Different error type similarity: {similarity:.3f}")


# ========== Test 2: Path Similarity ==========

def test_path_similarity_identical():
    """Test Jaccard similarity for identical paths."""
    paths1 = ["src/app.py", "src/config.py"]
    paths2 = ["src/app.py", "src/config.py"]

    similarity = PathSimilarity.jaccard_similarity(paths1, paths2)

    assert similarity == 1.0
    print(f"[OK] Identical paths similarity: {similarity:.3f}")


def test_path_similarity_partial_overlap():
    """Test Jaccard similarity for partial overlap."""
    paths1 = ["src/app.py", "src/config.py", "src/utils.py"]
    paths2 = ["src/app.py", "tests/test_app.py"]

    similarity = PathSimilarity.jaccard_similarity(paths1, paths2)

    # Intersection: {src/app.py}
    # Union: {src/app.py, src/config.py, src/utils.py, tests/test_app.py}
    # Jaccard: 1/4 = 0.25
    assert similarity == 0.25
    print(f"[OK] Partial overlap similarity: {similarity:.3f}")


def test_path_similarity_no_overlap():
    """Test Jaccard similarity for no overlap."""
    paths1 = ["src/app.py", "src/config.py"]
    paths2 = ["tests/test_app.py", "tests/test_config.py"]

    similarity = PathSimilarity.jaccard_similarity(paths1, paths2)

    assert similarity == 0.0
    print(f"[OK] No overlap similarity: {similarity:.3f}")


def test_path_normalization():
    """Test path normalization (Windows/Unix compatibility)."""
    paths1 = ["src\\app.py", "SRC\\CONFIG.PY"]
    paths2 = ["src/app.py", "src/config.py"]

    similarity = PathSimilarity.jaccard_similarity(paths1, paths2)

    # Should normalize to same paths
    assert similarity == 1.0
    print(f"[OK] Path normalization works: {similarity:.3f}")


# ========== Test 3: Combined Similarity ==========

def test_combined_similarity_engine():
    """Test combined similarity scoring."""
    engine = SimilarityEngine()

    # Similar executions (same error, overlapping paths, same status)
    total, error_sim, path_sim, status_match, verdict_match = engine.compute_similarity(
        "FileNotFoundError: config.json not found",
        ["src/app.py", "src/config.py"],
        "failed",
        "allow",
        "FileNotFoundError: settings.json not found",
        ["src/app.py", "src/utils.py"],
        "failed",
        "allow"
    )

    # Should have high error similarity
    assert error_sim > 0.5

    # Should have some path overlap
    assert path_sim > 0.0

    # Should match metadata
    assert status_match is True
    assert verdict_match is True

    # Total should be weighted combination
    assert 0.0 <= total <= 1.0

    print(f"[OK] Combined similarity: total={total:.3f}, error={error_sim:.3f}, path={path_sim:.3f}")


def test_similarity_no_error_match():
    """Test similarity when both have no errors (should be high)."""
    engine = SimilarityEngine()

    total, error_sim, path_sim, status_match, verdict_match = engine.compute_similarity(
        None,  # No error
        ["src/app.py"],
        "completed",
        "allow",
        None,  # No error
        ["src/app.py"],
        "completed",
        "allow"
    )

    # No error + no error = similar (both succeeded)
    assert error_sim == 1.0
    assert total > 0.5

    print(f"[OK] No error match: error_sim={error_sim:.3f}, total={total:.3f}")


# ========== Test 4: find_similar_executions ==========

def test_find_similar_executions(execution_store, temp_workspace):
    """Test finding similar executions."""
    # Create target execution (failed with error)
    execution_store.record_execution_start(
        execution_id="exec_target",
        plan_id="plan_1",
        changeset_id="cs_1",
        decision_id="dec_1",
        checksum="sum_1",
        verdict="allow",
        risk_level="medium",
        affected_paths=["src/app.py", "src/config.py"],
        artifact_path=str(temp_workspace / "exec_target")
    )
    execution_store.record_execution_end(
        "exec_target",
        status="failed",
        duration_seconds=1.0,
        files_changed=0,
        verification_passed=False,
        health_checks_passed=False,
        rolled_back=False,
        error_message="FileNotFoundError: config.json not found",
        error_step="apply"
    )

    # Create similar execution (same error type, overlapping paths)
    execution_store.record_execution_start(
        execution_id="exec_similar1",
        plan_id="plan_2",
        changeset_id="cs_2",
        decision_id="dec_2",
        checksum="sum_2",
        verdict="allow",
        risk_level="medium",
        affected_paths=["src/app.py", "src/utils.py"],
        artifact_path=str(temp_workspace / "exec_similar1")
    )
    execution_store.record_execution_end(
        "exec_similar1",
        status="failed",
        duration_seconds=1.0,
        files_changed=0,
        verification_passed=False,
        health_checks_passed=False,
        rolled_back=False,
        error_message="FileNotFoundError: settings.json not found",
        error_step="apply"
    )

    # Create dissimilar execution (different error, different paths)
    execution_store.record_execution_start(
        execution_id="exec_different",
        plan_id="plan_3",
        changeset_id="cs_3",
        decision_id="dec_3",
        checksum="sum_3",
        verdict="allow",
        risk_level="low",
        affected_paths=["tests/test_app.py"],
        artifact_path=str(temp_workspace / "exec_different")
    )
    execution_store.record_execution_end(
        "exec_different",
        status="failed",
        duration_seconds=1.0,
        files_changed=0,
        verification_passed=False,
        health_checks_passed=False,
        rolled_back=False,
        error_message="ValueError: invalid configuration",
        error_step="verify"
    )

    # Find similar executions
    similar = execution_store.find_similar_executions(
        "exec_target",
        limit=5,
        min_similarity=0.3
    )

    # Should find exec_similar1 but not exec_different (or it should rank lower)
    assert len(similar) > 0

    # First result should be exec_similar1 (highest similarity)
    top_result = similar[0]
    assert top_result[0].execution_id == "exec_similar1"
    assert top_result[1].total_score > 0.3

    print(f"[OK] Found {len(similar)} similar execution(s)")
    print(f"[OK] Top match: {top_result[0].execution_id} with score {top_result[1].total_score:.3f}")


def test_find_similar_executions_exclude_correlation(execution_store, temp_workspace):
    """Test excluding same correlation chain."""
    # Create root execution
    execution_store.record_execution_start(
        execution_id="exec_root",
        plan_id="plan_1",
        changeset_id="cs_1",
        decision_id="dec_1",
        checksum="sum_1",
        verdict="allow",
        risk_level="medium",
        affected_paths=["src/app.py"],
        artifact_path=str(temp_workspace / "exec_root"),
        correlation_id="corr_123"
    )
    execution_store.record_execution_end("exec_root", status="failed", duration_seconds=1.0, files_changed=0, verification_passed=False, health_checks_passed=False, rolled_back=False, error_message="Error A", error_step="apply")

    # Create retry in same correlation (should be excluded)
    execution_store.record_execution_start(
        execution_id="exec_retry",
        plan_id="plan_2",
        changeset_id="cs_2",
        decision_id="dec_2",
        checksum="sum_2",
        verdict="allow",
        risk_level="medium",
        affected_paths=["src/app.py"],
        artifact_path=str(temp_workspace / "exec_retry"),
        correlation_id="corr_123",  # Same correlation
        parent_execution_id="exec_root"
    )
    execution_store.record_execution_end("exec_retry", status="failed", duration_seconds=1.0, files_changed=0, verification_passed=False, health_checks_passed=False, rolled_back=False, error_message="Error A", error_step="apply")

    # Create unrelated execution (different correlation)
    execution_store.record_execution_start(
        execution_id="exec_other",
        plan_id="plan_3",
        changeset_id="cs_3",
        decision_id="dec_3",
        checksum="sum_3",
        verdict="allow",
        risk_level="medium",
        affected_paths=["src/app.py"],
        artifact_path=str(temp_workspace / "exec_other"),
        correlation_id="corr_456"  # Different correlation
    )
    execution_store.record_execution_end("exec_other", status="failed", duration_seconds=1.0, files_changed=0, verification_passed=False, health_checks_passed=False, rolled_back=False, error_message="Error A", error_step="apply")

    # Find similar (exclude same correlation)
    similar = execution_store.find_similar_executions(
        "exec_root",
        limit=5,
        min_similarity=0.3,
        exclude_same_correlation=True
    )

    # Should find exec_other but NOT exec_retry
    exec_ids = [record.execution_id for record, score in similar]

    assert "exec_other" in exec_ids
    assert "exec_retry" not in exec_ids

    print(f"[OK] Excluded same correlation: found {exec_ids}")


# ========== Test 5: find_similar_by_error ==========

def test_find_similar_by_error(execution_store, temp_workspace):
    """Test finding executions by error message."""
    # Create executions with errors
    errors = [
        ("exec_1", "FileNotFoundError: config.json not found"),
        ("exec_2", "FileNotFoundError: settings.json not found"),
        ("exec_3", "ValueError: invalid configuration")
    ]

    for exec_id, error in errors:
        execution_store.record_execution_start(
            execution_id=exec_id,
            plan_id=f"plan_{exec_id}",
            changeset_id=f"cs_{exec_id}",
            decision_id=f"dec_{exec_id}",
            checksum=f"sum_{exec_id}",
            verdict="allow",
            risk_level="medium",
            affected_paths=["src/app.py"],
            artifact_path=str(temp_workspace / exec_id)
        )
        execution_store.record_execution_end(exec_id, status="failed", duration_seconds=1.0, files_changed=0, verification_passed=False, health_checks_passed=False, rolled_back=False, error_message=error, error_step="apply")

    # Search for similar errors
    similar = execution_store.find_similar_by_error(
        "FileNotFoundError: data.json not found",
        limit=5,
        min_similarity=0.3
    )

    # Should find exec_1 and exec_2 (both FileNotFoundError)
    exec_ids = [record.execution_id for record, score in similar]

    assert "exec_1" in exec_ids
    assert "exec_2" in exec_ids
    # exec_3 may or may not appear depending on threshold

    print(f"[OK] Found similar errors: {exec_ids}")


# ========== Test 6: find_similar_by_paths ==========

def test_find_similar_by_paths(execution_store, temp_workspace):
    """Test finding executions by affected paths."""
    # Create executions with different paths
    path_sets = [
        ("exec_1", ["src/app.py", "src/config.py"]),
        ("exec_2", ["src/app.py", "src/utils.py"]),
        ("exec_3", ["tests/test_app.py", "tests/test_config.py"])
    ]

    for exec_id, paths in path_sets:
        execution_store.record_execution_start(
            execution_id=exec_id,
            plan_id=f"plan_{exec_id}",
            changeset_id=f"cs_{exec_id}",
            decision_id=f"dec_{exec_id}",
            checksum=f"sum_{exec_id}",
            verdict="allow",
            risk_level="medium",
            affected_paths=paths,
            artifact_path=str(temp_workspace / exec_id)
        )
        execution_store.record_execution_end(exec_id, status="completed", duration_seconds=1.0, files_changed=len(paths), verification_passed=True, health_checks_passed=True, rolled_back=False)

    # Search for similar paths
    similar = execution_store.find_similar_by_paths(
        ["src/app.py", "src/models.py"],
        limit=5,
        min_similarity=0.25  # At least 25% overlap
    )

    # Should find exec_1 and exec_2 (both contain src/app.py)
    exec_ids = [record.execution_id for record, score in similar]

    assert "exec_1" in exec_ids or "exec_2" in exec_ids

    print(f"[OK] Found similar paths: {exec_ids}")


# ========== Run All Tests ==========

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
