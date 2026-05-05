from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from collections import Counter
import os
import numpy as np
import matplotlib.pyplot as plt
from sklearn.tree import DecisionTreeClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
)

from src import db_utils

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MINUTE = 60
_HOUR   = 60 * _MINUTE
_DAY    = 24 * _HOUR
_WEEK   = 7  * _DAY
_MONTH  = 30 * _DAY

FEATURE_LABELS = {
    "enhancement", "feature", "feature request", "feature-request",
    "type: feature", "type:feature", "kind/feature", "new feature",
}

EFFICIENCY_CLASSES = ["minutes", "hours", "days", "weeks", "months"]

# ---------------------------------------------------------------------------
# Binning helper
# ---------------------------------------------------------------------------

def bin_resolution_time(seconds: float) -> str:
    if seconds < _HOUR:
        return "minutes"
    if seconds < _DAY:
        return "hours"
    if seconds < _WEEK:
        return "days"
    if seconds < _MONTH:
        return "weeks"
    return "months"


# ---------------------------------------------------------------------------
# Feature helpers
# ---------------------------------------------------------------------------

def _is_feature_request(labels_str: Optional[str]) -> int:
    if not labels_str:
        return 0
    for lbl in labels_str.split(","):
        if lbl.strip().lower() in FEATURE_LABELS:
            return 1
    return 0


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_issue_data(issue_limit: Optional[int] = None, sample_csv: Optional[str] = "samples/sampled_issues.csv") -> List[Dict[str, Any]]:
    sampled_numbers = None
    if sample_csv and os.path.exists(sample_csv):
        try:
            import csv
            with open(sample_csv, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                sampled_numbers = [int(row["issue_number"]) for row in reader]
            print(f"  Filtering to {len(sampled_numbers)} sampled issues from {sample_csv}")
        except Exception as exc:
            print(f"  Warning: could not read sample CSV, using full issue set: {exc}")

    if sampled_numbers:
        placeholders = ",".join(str(n) for n in sampled_numbers)
        query = f"""
            SELECT
                issue_number,
                body,
                comments_count,
                labels,
                created_at,
                closed_at
            FROM issues
            WHERE closed_at IS NOT NULL
              AND created_at IS NOT NULL
              AND issue_number IN ({placeholders})
        """
    else:
        query = """
            SELECT
                issue_number,
                body,
                comments_count,
                labels,
                created_at,
                closed_at
            FROM issues
            WHERE closed_at IS NOT NULL
              AND created_at IS NOT NULL
        """

    if issue_limit:
        query += f" LIMIT {int(issue_limit)}"
    query += ";"

    try:
        rows = db_utils.exec_get_all(query)
    except Exception as exc:
        print(f"[load_issue_data] DB query failed: {exc}")
        return []

    cols = ["issue_number", "body", "comments_count",
            "labels", "created_at", "closed_at"]
    return [dict(zip(cols, row)) for row in rows]


def _load_commit_timestamps() -> List[Any]:
    global _COMMIT_TS_CACHE
    if _COMMIT_TS_CACHE is not None:
        return _COMMIT_TS_CACHE

    try:
        rows = db_utils.exec_get_all(
            "SELECT commit_ts FROM commits WHERE commit_ts IS NOT NULL ORDER BY commit_ts ASC;"
        )
        _COMMIT_TS_CACHE = [row[0] for row in rows]
    except Exception as exc:
        print(f"[_load_commit_timestamps] DB query failed: {exc}")
        _COMMIT_TS_CACHE = []

    return _COMMIT_TS_CACHE

_COMMIT_TS_CACHE = None  # module-level cache


def _count_commits_in_window(
    commit_timestamps: List[Any],
    start: Any,
    end: Any,
) -> int:
    import bisect
    lo = bisect.bisect_left(commit_timestamps, start)
    hi = bisect.bisect_right(commit_timestamps, end)
    return hi - lo


# ---------------------------------------------------------------------------
# Feature engineering
# ---------------------------------------------------------------------------

def build_issue_features(issue: Dict[str, Any],
                         commit_timestamps: List[Any]) -> np.ndarray:
    body = issue.get("body") or ""
    description_length = len(body)

    comment_count = int(issue.get("comments_count") or 0)

    created_at = issue["created_at"]
    closed_at  = issue["closed_at"]

    window_commits = _count_commits_in_window(
        commit_timestamps, created_at, closed_at
    )
    concurrent_commits  = window_commits
    commits_in_lifespan = window_commits

    is_feature = _is_feature_request(issue.get("labels"))

    return np.array([
        description_length,
        comment_count,
        concurrent_commits,
        is_feature,
        commits_in_lifespan,
    ], dtype=float)


FEATURE_NAMES = [
    "description_length",
    "comment_count",
    "concurrent_commits",
    "is_feature_request",
    "commits_in_lifespan",
]


# ---------------------------------------------------------------------------
# Matrix builder
# ---------------------------------------------------------------------------

def build_feature_matrix(
    issue_records: List[Dict[str, Any]],
) -> Tuple[np.ndarray, List[str], List[str]]:
    commit_timestamps = _load_commit_timestamps()

    X_rows: List[np.ndarray] = []
    y: List[str] = []

    skipped = 0
    for issue in issue_records:
        created_at = issue.get("created_at")
        closed_at  = issue.get("closed_at")

        if created_at is None or closed_at is None:
            skipped += 1
            continue

        try:
            lifespan_seconds = (closed_at - created_at).total_seconds()
        except TypeError:
            skipped += 1
            continue

        if lifespan_seconds < 0:
            skipped += 1
            continue

        label = bin_resolution_time(lifespan_seconds)
        features = build_issue_features(issue, commit_timestamps)

        X_rows.append(features)
        y.append(label)

    if skipped:
        print(f"  [build_feature_matrix] Skipped {skipped} issues "
              f"(missing/invalid timestamps).")

    if not X_rows:
        return np.zeros((0, len(FEATURE_NAMES))), [], FEATURE_NAMES

    return np.array(X_rows), y, FEATURE_NAMES


# ---------------------------------------------------------------------------
# Train / evaluate (like m1 kinda')
# ---------------------------------------------------------------------------

def split_dataset(
    X: np.ndarray,
    y: List[str],
    test_size: float = 0.2,
    random_state: int = 42,
) -> Tuple[np.ndarray, np.ndarray, List[str], List[str]]:
    class_counts = Counter(y)
    can_stratify = all(count >= 2 for count in class_counts.values())

    if not can_stratify:
        print("  Warning: One or more efficiency classes has < 2 samples. "
              "Falling back to non-stratified split.")
        stratify_param = None
    else:
        stratify_param = y

    return train_test_split(
        X, y,
        test_size=test_size,
        random_state=random_state,
        stratify=stratify_param,
    )


def train_classifier(
    X_train: np.ndarray,
    y_train: List[str],
    model_type: str = "decision_tree",
    max_depth: Optional[int] = None,
) -> Any:
    if model_type == "decision_tree":
        clf = DecisionTreeClassifier(max_depth=max_depth, random_state=42)
    elif model_type == "random_forest":
        clf = RandomForestClassifier(
            n_estimators=100, max_depth=max_depth, random_state=42
        )
    else:
        raise ValueError(
            f"Unsupported model_type '{model_type}'. "
            "Choose 'decision_tree' or 'random_forest'."
        )
    clf.fit(X_train, y_train)
    return clf


def evaluate_model(
    model: Any,
    X_test: np.ndarray,
    y_test: List[str],
) -> Dict[str, Any]:
    y_pred = model.predict(X_test)
    class_names = sorted(set(y_test), key=lambda c: EFFICIENCY_CLASSES.index(c)
                         if c in EFFICIENCY_CLASSES else 99)

    return {
        "accuracy": float(accuracy_score(y_test, y_pred)),
        "classification_report": classification_report(
            y_test, y_pred,
            labels=class_names,
            output_dict=True,
            zero_division=0,
        ),
        "confusion_matrix": confusion_matrix(
            y_test, y_pred, labels=class_names
        ),
        "class_names": class_names,
        "y_pred": y_pred,
    }


# ---------------------------------------------------------------------------
# Plotting (like m1 kinda')
# ---------------------------------------------------------------------------

def plot_feature_importance(
    model: Any,
    feature_names: List[str],
    output_path: Optional[str] = None,
) -> None:
    """Bar chart of feature importances, sorted descending."""
    importances = model.feature_importances_
    indices = np.argsort(importances)[::-1]

    plt.figure(figsize=(9, 5))
    plt.bar(
        range(len(importances)),
        importances[indices],
        color="steelblue",
        edgecolor="black",
        linewidth=0.5,
    )
    plt.xticks(
        range(len(importances)),
        [feature_names[i] for i in indices],
        rotation=35,
        ha="right",
        fontsize=9,
    )
    plt.xlabel("Feature", fontsize=12)
    plt.ylabel("Importance", fontsize=12)
    plt.title("Feature Importances — Issue Resolution Efficiency",
              fontsize=13, fontweight="bold")
    plt.grid(axis="y", alpha=0.3)
    plt.tight_layout()

    if output_path:
        plt.savefig(output_path, dpi=300, bbox_inches="tight")
        plt.close()
    else:
        plt.show()


def plot_confusion_matrix(
    y_true: List[str],
    y_pred: Any,
    class_names: List[str],
    output_path: Optional[str] = None,
) -> None:
    """Annotated heatmap of predicted vs. true efficiency classes."""
    cm = confusion_matrix(y_true, y_pred, labels=class_names)

    plt.figure(figsize=(8, 6))
    im = plt.imshow(cm, interpolation="nearest", cmap="Blues")
    plt.colorbar(im, label="Count")
    plt.title("Confusion Matrix — Issue Resolution Efficiency",
              fontsize=13, fontweight="bold")
    plt.xlabel("Predicted Label", fontsize=12)
    plt.ylabel("True Label", fontsize=12)

    tick_marks = np.arange(len(class_names))
    plt.xticks(tick_marks, class_names, rotation=45, ha="right", fontsize=9)
    plt.yticks(tick_marks, class_names, fontsize=9)

    thresh = cm.max() / 2.0
    for i in range(cm.shape[0]):
        for j in range(cm.shape[1]):
            plt.text(
                j, i, str(cm[i, j]),
                ha="center", va="center",
                color="white" if cm[i, j] > thresh else "black",
                fontsize=10,
            )

    plt.tight_layout()
    if output_path:
        plt.savefig(output_path, dpi=300, bbox_inches="tight")
        plt.close()
    else:
        plt.show()
