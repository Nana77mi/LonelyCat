"""
Execution Similarity Engine - Phase 2.4-D

Provides similarity search for executions based on:
- Error messages (text similarity)
- Affected file paths (Jaccard similarity)
- Changeset content (future: vector embeddings)

Philosophy:
- Lightweight: No heavy ML models (TF-IDF for text, set operations for paths)
- Fast: In-memory computation, cached embeddings
- Deterministic: Same inputs → same similarity scores

Use Cases:
- Find similar failures when execution fails
- Suggest repairs from historical fixes
- Debug by finding "what worked last time"
"""

import re
import math
from typing import List, Dict, Tuple, Optional, Set
from dataclasses import dataclass
from collections import Counter


@dataclass
class SimilarityScore:
    """Similarity score between two executions."""
    execution_id: str
    total_score: float  # 0.0 to 1.0
    error_similarity: float  # Text similarity of error messages
    path_similarity: float  # Jaccard similarity of affected paths
    status_match: bool  # Same status (completed, failed, rolled_back)
    verdict_match: bool  # Same verdict (allow, deny)


class TextVectorizer:
    """
    Simple TF-IDF vectorizer for error messages.

    Why not use sklearn? Keep dependencies minimal for core package.
    """

    def __init__(self):
        """Initialize vectorizer."""
        self.idf: Dict[str, float] = {}  # term -> inverse document frequency
        self.doc_count: int = 0

    def tokenize(self, text: str) -> List[str]:
        """
        Tokenize text into terms.

        Strategy:
        - Lowercase
        - Remove non-alphanumeric (keep spaces)
        - Split on whitespace
        - Remove common stop words
        """
        if not text:
            return []

        # Lowercase and clean
        text = text.lower()
        text = re.sub(r'[^a-z0-9\s]', ' ', text)

        # Split and filter
        tokens = text.split()

        # Remove common stop words (minimal set)
        stop_words = {'the', 'a', 'an', 'in', 'on', 'at', 'to', 'for', 'of', 'and', 'or', 'but'}
        tokens = [t for t in tokens if t not in stop_words and len(t) > 1]

        return tokens

    def compute_tf(self, tokens: List[str]) -> Dict[str, float]:
        """
        Compute term frequency (TF).

        TF(term) = count(term) / total_terms
        """
        if not tokens:
            return {}

        term_counts = Counter(tokens)
        total = len(tokens)

        return {term: count / total for term, count in term_counts.items()}

    def vectorize(self, text: str) -> Dict[str, float]:
        """
        Convert text to TF vector (no IDF yet, computed on corpus).

        Returns:
            term -> TF score
        """
        tokens = self.tokenize(text)
        return self.compute_tf(tokens)

    def cosine_similarity(self, vec1: Dict[str, float], vec2: Dict[str, float]) -> float:
        """
        Compute cosine similarity between two TF vectors.

        cos(A, B) = dot(A, B) / (||A|| * ||B||)

        Returns:
            Similarity score (0.0 to 1.0)
        """
        if not vec1 or not vec2:
            return 0.0

        # Compute dot product
        common_terms = set(vec1.keys()) & set(vec2.keys())
        dot_product = sum(vec1[term] * vec2[term] for term in common_terms)

        # Compute magnitudes
        mag1 = math.sqrt(sum(v * v for v in vec1.values()))
        mag2 = math.sqrt(sum(v * v for v in vec2.values()))

        if mag1 == 0 or mag2 == 0:
            return 0.0

        return dot_product / (mag1 * mag2)


class PathSimilarity:
    """
    File path similarity using Jaccard index.

    Jaccard(A, B) = |A ∩ B| / |A ∪ B|
    """

    @staticmethod
    def normalize_path(path: str) -> str:
        """
        Normalize file path for comparison.

        Strategy:
        - Convert backslashes to forward slashes (Windows compatibility)
        - Lowercase
        - Remove leading/trailing slashes
        """
        path = path.replace('\\', '/')
        path = path.lower()
        path = path.strip('/')
        return path

    @staticmethod
    def jaccard_similarity(paths1: List[str], paths2: List[str]) -> float:
        """
        Compute Jaccard similarity between two path lists.

        Returns:
            Similarity score (0.0 to 1.0)
        """
        if not paths1 and not paths2:
            return 1.0  # Both empty = identical

        if not paths1 or not paths2:
            return 0.0  # One empty = no overlap

        # Normalize paths
        set1 = {PathSimilarity.normalize_path(p) for p in paths1}
        set2 = {PathSimilarity.normalize_path(p) for p in paths2}

        # Jaccard index
        intersection = set1 & set2
        union = set1 | set2

        if not union:
            return 0.0

        return len(intersection) / len(union)

    @staticmethod
    def path_overlap_count(paths1: List[str], paths2: List[str]) -> int:
        """
        Count number of overlapping paths.

        Returns:
            Number of paths in common
        """
        set1 = {PathSimilarity.normalize_path(p) for p in paths1}
        set2 = {PathSimilarity.normalize_path(p) for p in paths2}

        return len(set1 & set2)


class SimilarityEngine:
    """
    Main similarity engine for execution comparison.

    Combines multiple similarity signals:
    - Error message similarity (text)
    - Affected paths similarity (Jaccard)
    - Status/verdict matching (categorical)
    """

    def __init__(self, error_weight: float = 0.5, path_weight: float = 0.3, meta_weight: float = 0.2):
        """
        Initialize similarity engine.

        Args:
            error_weight: Weight for error message similarity
            path_weight: Weight for path similarity
            meta_weight: Weight for metadata matching (status, verdict)
        """
        self.error_weight = error_weight
        self.path_weight = path_weight
        self.meta_weight = meta_weight

        self.vectorizer = TextVectorizer()
        self.path_sim = PathSimilarity()

    def compute_similarity(
        self,
        exec1_error: Optional[str],
        exec1_paths: List[str],
        exec1_status: str,
        exec1_verdict: str,
        exec2_error: Optional[str],
        exec2_paths: List[str],
        exec2_status: str,
        exec2_verdict: str
    ) -> Tuple[float, float, float, bool, bool]:
        """
        Compute similarity between two executions.

        Args:
            exec1_error: Error message of execution 1
            exec1_paths: Affected paths of execution 1
            exec1_status: Status of execution 1
            exec1_verdict: Verdict of execution 1
            exec2_error: Error message of execution 2
            exec2_paths: Affected paths of execution 2
            exec2_status: Status of execution 2
            exec2_verdict: Verdict of execution 2

        Returns:
            Tuple of (total_score, error_sim, path_sim, status_match, verdict_match)
        """
        # Error similarity (text)
        error_sim = 0.0
        if exec1_error and exec2_error:
            vec1 = self.vectorizer.vectorize(exec1_error)
            vec2 = self.vectorizer.vectorize(exec2_error)
            error_sim = self.vectorizer.cosine_similarity(vec1, vec2)
        elif exec1_error or exec2_error:
            # One has error, one doesn't = dissimilar
            error_sim = 0.0
        else:
            # Both have no error = similar (no error is good!)
            error_sim = 1.0

        # Path similarity (Jaccard)
        path_sim = self.path_sim.jaccard_similarity(exec1_paths, exec2_paths)

        # Metadata matching
        status_match = (exec1_status == exec2_status)
        verdict_match = (exec1_verdict == exec2_verdict)

        meta_score = 0.0
        if status_match:
            meta_score += 0.5
        if verdict_match:
            meta_score += 0.5

        # Weighted total score
        total_score = (
            self.error_weight * error_sim +
            self.path_weight * path_sim +
            self.meta_weight * meta_score
        )

        return total_score, error_sim, path_sim, status_match, verdict_match

    def compute_similarity_score(
        self,
        target_execution_id: str,
        target_error: Optional[str],
        target_paths: List[str],
        target_status: str,
        target_verdict: str,
        candidate_execution_id: str,
        candidate_error: Optional[str],
        candidate_paths: List[str],
        candidate_status: str,
        candidate_verdict: str
    ) -> SimilarityScore:
        """
        Compute similarity score object between target and candidate execution.

        Returns:
            SimilarityScore object with detailed breakdown
        """
        total, error_sim, path_sim, status_match, verdict_match = self.compute_similarity(
            target_error, target_paths, target_status, target_verdict,
            candidate_error, candidate_paths, candidate_status, candidate_verdict
        )

        return SimilarityScore(
            execution_id=candidate_execution_id,
            total_score=total,
            error_similarity=error_sim,
            path_similarity=path_sim,
            status_match=status_match,
            verdict_match=verdict_match
        )


# ==================== Utility Functions ====================

def extract_error_keywords(error_message: str) -> List[str]:
    """
    Extract key terms from error message for quick filtering.

    Examples:
        "FileNotFoundError: file.txt not found" -> ["filenotfounderror", "file", "txt", "not", "found"]
    """
    vectorizer = TextVectorizer()
    return vectorizer.tokenize(error_message)


def compute_path_signature(paths: List[str]) -> str:
    """
    Compute a signature for a set of paths (sorted, concatenated).

    Useful for quick lookups of exact path matches.

    Example:
        ["src/app.py", "src/utils.py"] -> "src/app.py|src/utils.py"
    """
    normalized = [PathSimilarity.normalize_path(p) for p in paths]
    return "|".join(sorted(normalized))


if __name__ == "__main__":
    # Quick test
    engine = SimilarityEngine()

    # Test error similarity
    error1 = "FileNotFoundError: config.json not found"
    error2 = "FileNotFoundError: settings.json not found"
    error3 = "ValueError: invalid configuration"

    vec1 = engine.vectorizer.vectorize(error1)
    vec2 = engine.vectorizer.vectorize(error2)
    vec3 = engine.vectorizer.vectorize(error3)

    sim_12 = engine.vectorizer.cosine_similarity(vec1, vec2)
    sim_13 = engine.vectorizer.cosine_similarity(vec1, vec3)

    print(f"Similarity (error1, error2): {sim_12:.3f}")  # Should be high (similar errors)
    print(f"Similarity (error1, error3): {sim_13:.3f}")  # Should be lower (different errors)

    # Test path similarity
    paths1 = ["src/app.py", "src/config.py"]
    paths2 = ["src/app.py", "src/utils.py"]
    paths3 = ["tests/test_app.py"]

    jaccard_12 = PathSimilarity.jaccard_similarity(paths1, paths2)
    jaccard_13 = PathSimilarity.jaccard_similarity(paths1, paths3)

    print(f"Path similarity (paths1, paths2): {jaccard_12:.3f}")  # Should be 0.333 (1/3 overlap)
    print(f"Path similarity (paths1, paths3): {jaccard_13:.3f}")  # Should be 0.0 (no overlap)

    # Test combined similarity
    total, error_sim, path_sim, status_match, verdict_match = engine.compute_similarity(
        error1, paths1, "failed", "allow",
        error2, paths2, "failed", "allow"
    )

    print(f"\nCombined similarity:")
    print(f"  Total: {total:.3f}")
    print(f"  Error: {error_sim:.3f}")
    print(f"  Paths: {path_sim:.3f}")
    print(f"  Status match: {status_match}")
    print(f"  Verdict match: {verdict_match}")
