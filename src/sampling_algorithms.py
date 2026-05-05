from __future__ import annotations

from math import ceil
from typing import Any, Callable, Dict, List, Optional, Sequence, TypeVar
import random
from src import db_utils
import csv
import os

T = TypeVar("T")


# ---- Uniform Sampling ----

def sample_uniform(items: Sequence[T], k: int, seed: Optional[int] = None) -> List[T]:
    """Draw k items uniformly at random without replacement.

    Why this matters for MSR:
    - Random sampling is the foundation of statistical inference
    - Reproducibility requires deterministic seeds for replication studies
    - Many research tasks need unbiased subsets of large datasets

    Parameters:
    - items: the population to sample from
    - k: number of items to select
    - seed: random seed for reproducibility (None = non-deterministic)

    Returns:
    - List of k sampled items (or all items if k >= len(items))

    Behavior:
    - If k >= len(items), return a shallow copy of all items
    - When seed is provided, the same seed must produce identical results

    Examples:
    >>> sample_uniform([1, 2, 3, 4, 5], k=3, seed=42)
    [4, 5, 2]  # deterministic with seed=42
    >>> sample_uniform([1, 2], k=5, seed=0)
    [1, 2]  # k > len, returns all

    Implementation hints:
    - Use random.Random(seed) to create an isolated RNG instance
    - The random module's .sample() method does sampling without replacement
    """
    
    if k >= len(items):
        return list(items)
    
    rng = None

    if seed:
        rng = random.Random(seed)
    else:
        rng = random.Random()

    return rng.sample(list(items), k)


# ---- Stratified Sampling ----

def sample_stratified(
    items: Sequence[T],
    key: Callable[[T], Any],
    *,
    n: Optional[int] = None,
    frac: Optional[float] = None,
    seed: Optional[int] = None,
) -> List[T]:
    """Stratified sampling by key(item).

    Why this matters for MSR:
    - Ensures representation across groups (languages, authors, time periods)
    - Reduces variance when strata are internally homogeneous
    - Prevents dominant groups from overwhelming the sample

    Parameters:
    - items: the population to sample from
    - key: function that returns the stratum/group for each item 
      (Using a callable instead of a string allows grouping by computed values 
      and supports any data type, similar to Python's `sorted`)
    - n: exact number of samples per stratum (**mutually exclusive** with frac)
    - frac: fraction of each stratum to sample (**mutually exclusive** with n)
    - seed: random seed for reproducibility
    - * means that every parameter that comes after (to the right) must be named explicitly (frac=.5, seed=1, etc).

    Returns:
    - List of sampled items from all strata combined

    Behavior:
    - Exactly one of `n` or `frac` must be provided (raise ValueError otherwise)
    - For small strata, return up to the available members (don't error)
    - When frac > 0 but would yield 0 items, return at least 1 item
    - Selection must be reproducible with the same seed

    Examples:
    >>> items = [('py', 1), ('py', 2), ('js', 3), ('js', 4)]
    >>> sample_stratified(items, key=lambda x: x[0], n=1, seed=0)
    [('py', 2), ('js', 4)]  # 1 from each stratum

    >>> sample_stratified(items, key=lambda x: x[0], frac=0.5, seed=0)
    [('py', 1), ('js', 3)]  # 50% from each stratum

    Implementation hints:
    - Group items by key(item) into a dictionary
    - Sample within each group independently
    - For reproducibility, derive per-group seeds from the main seed
      (e.g., hash((group_key, seed)) to get consistent sub-seeds)
    """
    
    if (n is None and frac is None) or (n is not None and frac is not None):
        raise ValueError("Exactly one of variables 'n' or 'frac' must be provided")
    
    groups: Dict[Any, List[T]] = {}

    for item in items:
        group_key = key(item)
        if group_key not in groups:
            groups[group_key] = []
        groups[group_key].append(item)
    
    result = []

    try:
        sorted_keys = sorted(groups.keys())
    except TypeError:
        sorted_keys = list(groups.keys())

    for g_key in sorted_keys:
        group_items = groups[g_key]
        if n is not None:
            k = min(n, len(group_items))
        else:
            if frac <= 0:
                k = 0
            else:
                calculated_size = ceil(len(group_items) * frac)
                if len(group_items) > 0 and calculated_size == 0:
                    k = 1
                else: 
                    k = calculated_size

        group_seed = None
        if seed is not None:
            group_seed = hash((g_key, seed))
        sampled_group = sample_uniform(group_items, k, seed=group_seed)
        result.extend(sampled_group)

    return result


# ---- Systematic Sampling ----

def sample_systematic(items: Sequence[T], step: int, seed: Optional[int] = None) -> List[T]:
    """Systematic sampling: random start, then every step-th item.

    Why this matters for MSR:
    - Efficient for large ordered populations (e.g., commit history)
    - Simpler than full random sampling for streaming data
    - Approximates uniform sampling when population is randomly ordered

    Parameters:
    - items: the population to sample from (order matters)
    - step: interval between selected items (must be >= 1)
    - seed: random seed for reproducibility of starting position

    Returns:
    - List of sampled items

    Behavior:
    - Choose a random start position in [0, step-1]
    - Select every step-th item from that starting point
    - Raise ValueError if step <= 0

    Examples:
    >>> sample_systematic(list(range(20)), step=5, seed=0)
    [3, 8, 13, 18]  # start=3 with seed=0, then +5 each time

    Implementation hints:
    - Use random.Random(seed).randrange(step) for the start position
    - Iterate with idx += step until idx >= len(items)
    """
    if step <= 0:
        raise ValueError("Step must be >= 1")
    
    rng = random.Random(seed)
    start_index = rng.randrange(step)
    return list(items[start_index::step])


# ---- Sample Size for Proportions ----

def sample_size_proportion(
    N: Optional[int], p: float = 0.5, margin: float = 0.05, z: float = 1.96
) -> int:
    """Compute required sample size to estimate a proportion.

    Why this matters for MSR:
    - Answers: "How many commits must I label to estimate the bug rate?"
    - Ensures statistical validity of research findings
    - Finite population correction prevents over-sampling small repos

    Parameters:
    - N: population size (None = infinite population, no FPC)
    - p: expected proportion (0.5 is most conservative when unknown)
    - margin: desired margin of error (e.g., 0.05 = ±5%)
    - z: z-score for confidence level (1.96 = 95% confidence)

    Returns:
    - Required sample size as an integer (ceiling), capped at N if provided

    Formulas:
    - Baseline (infinite population): n0 = z² * p * (1-p) / margin²
    - With FPC: n = n0 / (1 + (n0 - 1) / N)

    Examples:
    >>> sample_size_proportion(None, p=0.5, margin=0.05, z=1.96)
    385  # classic value for 95% CI, ±5%

    >>> sample_size_proportion(500, p=0.5, margin=0.05, z=1.96)
    218  # FPC reduces required sample for small population

    Implementation hints:
    - Validate that margin > 0 and p is in valid range
    - Apply ceiling (math.ceil) to get integer
    - Cap result at N when N is provided
    """
    
    if margin <= 0:
        raise ValueError("Margin must be > 0")
    if not (0 <= p <= 1):
        raise ValueError("p must be between 0 and 1")
    
    n0 = (z**2 * p * (1-p)) / (margin**2)

    if N is None:
        return ceil(n0)
    else:
        n = n0 / (1 + (n0 - 1) / N)
        result = ceil(n)
        return min(result, N)


# ---- Sample Size for Means ----

def sample_size_mean(
    sigma: float, margin: float = 0.05, z: float = 1.96, N: Optional[int] = None
) -> int:
    """Compute required sample size to estimate a mean.

    Why this matters for MSR:
    - Answers: "How many files must I measure to estimate average complexity?"
    - Requires an estimate of population standard deviation

    Parameters:
    - sigma: known or estimated population standard deviation
    - margin: desired margin of error (same units as sigma)
    - z: z-score for confidence level (1.96 = 95% confidence)
    - N: population size (None = infinite population, no FPC)

    Returns:
    - Required sample size as an integer (ceiling), capped at N if provided

    Formulas:
    - Baseline: n0 = z² * σ² / margin²
    - With FPC: n = n0 / (1 + (n0 - 1) / N)

    Examples:
    >>> sample_size_mean(sigma=1.0, margin=0.1, z=1.96)
    385  # same as proportion with p=0.5 when units align

    Implementation hints:
    - Validate that sigma > 0 and margin > 0
    - Same FPC formula as sample_size_proportion
    """
    
    if margin <= 0:
        raise ValueError("Margin must be > 0")
    if sigma <= 0:
        raise ValueError("Sigma must be > 0")
    
    n0 = (z**2 * sigma**2) / (margin**2)

    if N is None:
        return ceil(n0)
    else:
        n = n0 / (1 + (n0 - 1) / N)
        result = ceil(n)
        return min(result, N)

# ---------------------------------------------------------------------------
# Helper methods
# ---------------------------------------------------------------------------



def _fetch_as_dicts(query: str) -> List[Dict[str, Any]]:
    """Helper to run a query and map tuple results to a list of dictionaries."""
    if db_utils is None:
        return []
    
    rows = db_utils.exec_query(query)
    if not rows:
        return []
    
    return rows 

def _write_csv(filename: str, rows: List[Dict[str, Any]]):
    """Writes a list of dicts to CSV."""
    if not rows:
        return
    if not os.path.exists("samples"):
        os.makedirs("samples")
    
    filepath = os.path.join("samples", filename)
    headers = list(rows[0].keys())
    
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)
    print(f"  > Wrote {len(rows)} samples to {filepath}")


def _apply_sampling_logic(
    items: List[Dict[str, Any]], 
    n: Optional[int], 
    frac: Optional[float], 
    step: Optional[int], 
    seed: Optional[int], 
    key: Optional[str]
) -> List[Dict[str, Any]]:
    population_size = len(items)
    if population_size == 0:
        return []

    if n is None and frac is None and step is None:
        calc_n = sample_size_proportion(N=population_size, p=0.5, margin=0.05)
        if key: 
            frac = calc_n / population_size
        else:
            n = calc_n
        print(f"    (Auto-calculated sample size: {calc_n} from population {population_size})")

    if key:
        print(f"    - Strategy: Stratified Sampling (by '{key}')")
        if key not in items[0]:
            print(f"    ! Warning: Key '{key}' not found in data. Falling back to Uniform.")
            return sample_uniform(items, k=(n or len(items)), seed=seed)
        
        return sample_stratified(
            items, 
            key=lambda x: x.get(key), 
            n=n, 
            frac=frac, 
            seed=seed
        )

    if step:
        print(f"    - Strategy: Systematic Sampling (step={step})")
        return sample_systematic(items, step=step, seed=seed)

    if n is None and frac is not None:
        n = ceil(population_size * frac)
        
    print(f"    - Strategy: Uniform Random Sampling (n={n})")
    return sample_uniform(items, k=n, seed=seed)


def run_sampling(
    sample_issues: bool = False,
    sample_commits: bool = False,
    sample_prs: bool = False,
    sample_workflows: bool = False,
    sample_jobs: bool = False,
    n: Optional[int] = None,
    frac: Optional[float] = None,
    step: Optional[int] = None,
    seed: Optional[int] = None,
    key: Optional[str] = None
):
    """
    Main entry point called by main.py. 
    Fetches data, applies logic, saves CSV.
    """
    if db_utils is None:
        print("Error: DB connection missing.")
        return

    # --- 1. ISSUES ---
    if sample_issues:
        print("\nSampling Issues...")
        has_clean = False
        try:
            db_utils.exec_query("SELECT title_clean FROM issues LIMIT 1;")
            has_clean = True
        except: pass

        cols = ["issue_number", "state", "created_at", "author", "title", "labels"]
        if has_clean: cols += ["title_clean", "author_norm", "is_bot"]
    
        query = f"SELECT {', '.join(cols)} FROM issues ORDER BY id ASC;" 
        rows = db_utils.exec_query(query)
        data = [dict(zip(cols, row)) for row in rows]
        
        samples = _apply_sampling_logic(data, n, frac, step, seed, key)
        _write_csv("sampled_issues.csv", samples)

    # --- 2. COMMITS ---
    if sample_commits:
        print("\nSampling Commits...")
        cols = ["commit_hash", "author_name", "commit_ts", "message"]
        query = f"SELECT {', '.join(cols)} FROM commits ORDER BY commit_ts DESC;"
        rows = db_utils.exec_query(query)
        data = [dict(zip(cols, row)) for row in rows]
        
        samples = _apply_sampling_logic(data, n, frac, step, seed, key)
        _write_csv("sampled_commits.csv", samples)

    # --- 3. PULL REQUESTS ---
    if sample_prs:
        print("\nSampling Pull Requests...")
        has_clean = False
        try:
            db_utils.exec_query("SELECT title_clean FROM pull_requests LIMIT 1;")
            has_clean = True
        except: pass

        cols = ["pr_number", "state", "created_at", "merged_at", "author", "title"]
        if has_clean: cols += ["title_clean", "author_norm", "is_bot"]

        query = f"SELECT {', '.join(cols)} FROM pull_requests ORDER BY id ASC;"
        rows = db_utils.exec_query(query)
        data = [dict(zip(cols, row)) for row in rows]

        samples = _apply_sampling_logic(data, n, frac, step, seed, key)
        _write_csv("sampled_prs.csv", samples)

    # --- 4. WORKFLOWS (CI Pipelines) ---
    if sample_workflows:
        print("\nSampling CI Pipelines...")
        cols = ["pipeline_id", "status", "created_at", "updated_at", "sha"]
        query = f"SELECT {', '.join(cols)} FROM ci_pipelines ORDER BY created_at DESC;"
        rows = db_utils.exec_query(query)
        data = [dict(zip(cols, row)) for row in rows]

        samples = _apply_sampling_logic(data, n, frac, step, seed, key)
        _write_csv("sampled_workflows.csv", samples)

    # --- 5. CI JOBS ---
    if sample_jobs:
        print("\nSampling CI Jobs...")
        cols = ["job_id", "name", "status", "started_at", "duration_seconds"]
        query = f"SELECT {', '.join(cols)} FROM ci_jobs ORDER BY started_at DESC;"
        rows = db_utils.exec_query(query)
        data = [dict(zip(cols, row)) for row in rows]

        samples = _apply_sampling_logic(data, n, frac, step, seed, key)
        _write_csv("sampled_jobs.csv", samples)