from datetime import datetime, timezone
from typing import Optional, Iterable, Tuple, Dict, Any
from git import Repo
from . import db_utils
from git.exc import GitCommandError

def _strip_nul(s) -> str:
    """Remove null bytes that PostgreSQL cannot store."""
    if not s:
        return ""
    return s.replace("\x00", "")

def extract_head_commit(repo_path: str = "."):
    repo = Repo(repo_path)
    try:
        head = repo.head.commit
        return {
            "hash": head.hexsha,
            "author_name": head.author.name or "unknown",
            "message": head.message.strip(),
            "timestamp": datetime.fromtimestamp(head.committed_date),
        }
    finally:
        # Important on Windows to release file handles
        repo.close()

def insert_commit_record(commit_info: dict):
    sql = """
    INSERT INTO commits (commit_hash, author_name, message, commit_ts)
    VALUES (%(hash)s, %(author_name)s, %(message)s, %(timestamp)s);
    """
    db_utils.exec_commit(sql, commit_info)

def mine_and_store(repo_path: str = "."):
    info = extract_head_commit(repo_path)
    insert_commit_record(info)
    return info


def upsert_commit(repo_commit) -> int:
  """Insert commit if missing and return its DB primary-key id.
  
  Behavior:
  - Build a dict with `hash`, `author_name`, `message`, `timestamp`.
  - INSERT ... ON CONFLICT DO NOTHING RETURNING id; if no row is
    returned, SELECT id FROM commits WHERE commit_hash=%(hash)s.
  - Return the integer id;
  """
  
  params = {
     "hash": repo_commit.hexsha,
     "author_name": repo_commit.author.name or "unknown",
     "message": repo_commit.message.strip(),
     "timestamp": datetime.fromtimestamp(repo_commit.committed_date),
  }

  sql = """
  INSERT INTO commits (commit_hash, author_name, message, commit_ts)
  VALUES (%(hash)s, %(author_name)s, %(message)s, %(timestamp)s)
  ON CONFLICT DO NOTHING
  RETURNING id;
  """

  rowid = db_utils.exec_commit_get_one(sql, params)

  if rowid is not None:
     return rowid[0]
  
  sql = """
  SELECT id FROM commits WHERE commit_hash = %(hash)s;
  """
  rowid = db_utils.exec_get_one(sql, params)
  return rowid[0]



def insert_parents(commit_id: int, parents: Iterable[str]) -> None:
  """Record parent links for `commit_id`.

  Insert rows into `commit_parents(commit_id, parent_hash)` using
  `ON CONFLICT DO NOTHING` to keep the operation idempotent.
  """

  sql = """
  INSERT INTO commit_parents (commit_id, parent_hash)
  VALUES (%(commit_id)s, %(parent_hash)s)
  ON CONFLICT DO NOTHING;
  """
  for parent_hash in parents:
     params = {
        "commit_id": commit_id,
        "parent_hash": parent_hash
     }
     db_utils.exec_commit(sql, params)

def insert_stats(commit_id: int, repo_commit) -> None:
  """Insert aggregate stats for a commit.

  Use `repo_commit.stats.total` (or default zeros) and write into
  `commit_stats(commit_id, files_changed, insertions, deletions)` with
  `ON CONFLICT (commit_id) DO NOTHING`.
  """

  sql = """
  INSERT INTO commit_stats (commit_id, files_changed, insertions, deletions)
  VALUES (%(commit_id)s, %(files_changed)s, %(insertions)s, %(deletions)s)
  ON CONFLICT (commit_id) DO NOTHING;
  """

  try: 
     total = getattr(repo_commit.stats, "total", {}) or {}
  except GitCommandError:
     total = {}

  params = {
     "commit_id": commit_id,
     "files_changed": int(total.get("files", 0)),
     "insertions": int(total.get("insertions", 0)),
     "deletions": int(total.get("deletions", 0))
  }

  db_utils.exec_commit(sql, params)

def insert_files(commit_id: int, repo_commit) -> None:
  """Insert per-file change rows for a commit.

  General structure (implement this pattern):

  - Obtain per-file stats dict:
    files = getattr(repo_commit.stats, 'files', {}) or {}

  - Attempt to infer change types via a diff to the parent commit:
    change_types = {}
    try:
      parent = repo_commit.parents[0] if repo_commit.parents else None
      if parent is not None:
        for diff in parent.diff(repo_commit):
          # set change_types[diff.b_path or diff.a_path]
          # to diff.change_type.upper() (A/M/D/R/T)
          # Note: `diff.b_path` is the path in the new commit (useful for
          # additions/renames); `diff.a_path` is the path in the parent (useful
          # for deletions). Preferring `b_path` records the post-change path,
          # while falling back to `a_path` preserves the old path when the file
          # was removed.
      else:
        # root commit: mark all paths in `files` as 'A'
        for path in files.keys():
          change_types[path] = 'A'
    except Exception:
      # If diffing fails, fall back to a conservative default
      # (e.g. treat unknown files as 'M') and continue.
      pass

  - For each (path, data) in `files.items()`:
    # compute additions = int(data.get('insertions', 0))
    # compute deletions = int(data.get('deletions', 0))
    # choose change_type = change_types.get(path, 'M')
    # INSERT into `commit_files(commit_id, file_path, change_type, additions, deletions)`
    # using `ON CONFLICT DO NOTHING` keyed by (commit_id, file_path).

  The goal is to be best-effort and idempotent; tests will assert
  that rows exist with non-negative additions/deletions and reasonable
  change_type values.
  """
  try:
    files = getattr(repo_commit.stats, "files", {}) or {}
  except GitCommandError:
     files = {}

  change_types = {}
  try:
    parent = repo_commit.parents[0] if repo_commit.parents else None
    if parent is not None:
      for diff in parent.diff(repo_commit):
        path = diff.b_path or diff.a_path
        if path:
          change_types[path] = (diff.change_type or "M").upper()
    else:
       for path in files.keys():
          change_types[path] = "A"
  except Exception:
     for path in files.keys():
        change_types[path] = "M"

  sql = """
  INSERT INTO commit_files (commit_id, file_path, change_type, additions, deletions)
  VALUES (%(commit_id)s, %(file_path)s, %(change_type)s, %(additions)s, %(deletions)s)
  ON CONFLICT DO NOTHING;
  """

  for path, data in files.items():
     additions = int(data.get("insertions", 0))
     deletions = int(data.get("deletions", 0))
     change_type = change_types.get(path, "M")

     params = {
        "commit_id": commit_id,
        "file_path": path,
        "change_type": change_type,
        "additions": additions,
        "deletions": deletions,
     }

     db_utils.exec_commit(sql, params)
     


def insert_run_log(repo_path: str, head_hash: str, commit_count: int) -> None:
  """Append a provenance row to `run_log`.

  Write `repo_path`, `head_hash`, and `commit_count`. `started_at` can
  be a DB default of `now()`.

  Motivation: when mining software repositories for research it's
  important to record provenance for reproducibility, auditing, and
  debugging. Recording the `repo_path`, the `head_hash` observed after a
  run, and the `commit_count` lets future analysts tie database rows to a
  specific repository state (commit SHA) and run. This supports:
  - reproducing results by checking out the recorded `head_hash`;
  - detecting incomplete runs or partial replays by comparing counts;
  - auditing which repository snapshot produced the stored facts.
  """

  sql = """
  INSERT INTO run_log (repo_path, head_hash, commit_count)
  VALUES (%(repo_path)s, %(head_hash)s, %(commit_count)s)
  """

  params = {
     "repo_path": repo_path, 
     "head_hash": head_hash,
     "commit_count": commit_count,
  }

  db_utils.exec_commit(sql,params)

def validate_invariants() -> Tuple[int, int, int]:
  """Return (n_commits, n_stats, n_orphan_parents).

  Tests use this to assert `n_stats == n_commits` and `n_orphan_parents == 0`. Example of how to do orphans below.
  n_orphan_parents = db_utils.exec_get_one(
    "SELECT COUNT(*) FROM commit_parents cp WHERE NOT EXISTS (SELECT 1 FROM commits c WHERE c.commit_hash = cp.parent_hash);"
)[0]
  """

  n_commits = db_utils.exec_get_one("SELECT COUNT(*) FROM commits;")[0]
  n_stats = db_utils.exec_get_one("SELECT COUNT(*) FROM commit_stats;")[0]
  n_orphan_parents = db_utils.exec_get_one(
     "SELECT COUNT(*) FROM commit_parents cp WHERE NOT EXISTS (SELECT 1 FROM commits c WHERE c.commit_hash = cp.parent_hash);"
  )[0]

  return(n_commits, n_stats, n_orphan_parents)   


def mine_history(repo_path: str = ".", max_commits: Optional[int] = None, record_run: bool = True) -> int:
  """Traverse commit history and persist commits, stats, files, and parents.

  Processing order: oldest -> newest so the HEAD commit receives the highest id.
  Idempotent: uses unique(commit_hash) and ON CONFLICT safeguards.
  Returns: number of commits traversed this call (not newly inserted).
  """
  with Repo(repo_path) as repo:
    commits = list(repo.iter_commits("HEAD"))  # newest -> oldest
    commits.reverse()  # oldest -> newest
    count = 0
    for c in commits:
      cid = upsert_commit(c)
      insert_parents(cid, [p.hexsha for p in c.parents])
      insert_stats(cid, c)
      insert_files(cid, c)
      count += 1
      if max_commits is not None and count >= max_commits:
        break
    if record_run:
      head_hash = repo.head.commit.hexsha  # capture after processing
      insert_run_log(repo_path, head_hash, count)
    return count


# =============================
# DC2: Ecosystem Artifacts
# =============================

def _normalize_timestamp_to_utc(value: Any) -> datetime:
    """Coerce timestamps to timezone-aware UTC datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        # If already datetime, ensure it's UTC-aware
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    
    # Parse string timestamp
    v = str(value)
    
    # Try common formats with explicit UTC 'Z' suffix
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            dt = datetime.strptime(v, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    
    # Try formats without timezone (assume UTC)
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(v, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    
    # Fallback: fromisoformat
    try:
        dt = datetime.fromisoformat(v.replace('Z', '+00:00'))
        return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        raise ValueError(f"Unrecognized timestamp: {value}")

# ---- Issues ----

def upsert_issue(provider: str, repo: str, issue: Dict[str, Any]) -> int:
    """Insert/update a single issue idempotently; return db id.
    
    Implementation guidance:
    - Build an INSERT ... ON CONFLICT (provider, repo, issue_number) DO UPDATE statement.
    - Extract: provider, repo, issue["number"], issue["title"], issue["author"], 
      issue["state"], issue["created_at"], issue["closed_at"].
    - Use _normalize_timestamp_to_utc() for timestamp fields.
    - ON UPDATE: set title=EXCLUDED.title, state=EXCLUDED.state,
      author=COALESCE(EXCLUDED.author, issues.author),
      created_at=LEAST(issues.created_at, EXCLUDED.created_at),
      closed_at=COALESCE(EXCLUDED.closed_at, issues.closed_at).
    - Use RETURNING id to get the row id.
    - If no rows returned (shouldn't happen with RETURNING), fallback SELECT.
    """
    sql = """
    INSERT INTO issues (provider, repo, issue_number, title, body, author, state, state_reason, comments_count, labels, created_at, closed_at)
    VALUES (%(provider)s, %(repo)s, %(issue_number)s, %(title)s, %(body)s, %(author)s, %(state)s, %(state_reason)s, %(comments_count)s, %(labels)s, %(created_at)s, %(closed_at)s)
        ON CONFLICT (provider, repo, issue_number) DO UPDATE SET
        title = EXCLUDED.title,
        body = EXCLUDED.body,
        state = EXCLUDED.state,
        state_reason = EXCLUDED.state_reason,
        comments_count = EXCLUDED.comments_count,
        labels = EXCLUDED.labels,
        author = EXCLUDED.author,
        created_at = LEAST(issues.created_at, EXCLUDED.created_at),
        closed_at = COALESCE(EXCLUDED.closed_at, issues.closed_at)
    RETURNING id;
    """

    params = {
       "provider": provider,
       "repo": repo,
       "issue_number": issue["number"],
       "title": issue["title"],
       "body": issue.get("body", ""),
       "author": issue.get("author"),
       "state": issue["state"],
       "state_reason": issue.get("state_reason"),
       "comments_count": issue.get("comments_count", 0),
       "labels": issue.get("labels", ""),
       "created_at": _normalize_timestamp_to_utc(issue.get("created_at")),
       "closed_at": _normalize_timestamp_to_utc(issue.get("closed_at")),
    }

    row = db_utils.exec_commit_get_one(sql,params)
    if row:
       return row[0]
    
    sql_fallback = "SELECT id FROM issues WHERE provider=%(provider)s AND repo=%(repo)s AND issue_number=%(issue_number)s"
    row = db_utils.exec_get_one(sql_fallback, params)
    return row[0]

def ingest_issues(provider: str, repo: str, issues: Iterable[Dict[str, Any]]) -> int:
    """Ingest multiple issues; return count processed.
    
    Implementation guidance:
    - Loop over issues iterable.
    - Call upsert_issue(provider, repo, issue) for each.
    - Return total count processed.
    """
    count = 0
    for issue in issues:
       upsert_issue(provider, repo, issue)
       count+=1
    return count

# ---- Pull Requests ----

def upsert_pull_request(provider: str, repo: str, pr: Dict[str, Any]) -> int:
    """Insert/update a single pull/merge request idempotently; return db id.
    
    Implementation guidance:
    - Similar to upsert_issue, but for pull_requests table.
    - Extract: provider, repo, pr["number"], pr["title"], pr["author"],
      pr["state"], pr["created_at"], pr["merged_at"], pr["closed_at"].
    - Use _normalize_timestamp_to_utc() for timestamp fields.
    - ON CONFLICT (provider, repo, pr_number) DO UPDATE with similar COALESCE/LEAST logic.
    - Use RETURNING id; fallback SELECT if needed.
    """
    sql = """
    INSERT INTO pull_requests (provider, repo, pr_number, title, author, state, created_at, merged_at, closed_at)
    VALUES (%(provider)s, %(repo)s, %(pr_number)s, %(title)s, %(author)s, %(state)s, %(created_at)s, %(merged_at)s, %(closed_at)s)
    ON CONFLICT (provider, repo, pr_number) DO UPDATE SET
        title = EXCLUDED.title,
        state = EXCLUDED.state,
        author = EXCLUDED.author,
        created_at = LEAST(pull_requests.created_at, EXCLUDED.created_at),
        merged_at = COALESCE (EXCLUDED.merged_at, pull_requests.merged_at),
        closed_at = COALESCE(EXCLUDED.closed_at, pull_requests.closed_at)
    RETURNING id;
    """

    params = {
       "provider": provider,
       "repo": repo,
       "pr_number": pr["number"],
       "title": pr["title"],
       "author": pr.get("author"),
       "state": pr["state"],
       "created_at": _normalize_timestamp_to_utc(pr.get("created_at")),
       "merged_at": _normalize_timestamp_to_utc(pr.get("merged_at")),
       "closed_at": _normalize_timestamp_to_utc(pr.get("closed_at")),
    }

    row = db_utils.exec_commit_get_one(sql,params)
    if row:
       return row[0]
    
    sql_fallback = "SELECT id FROM pull_requests WHERE provider=%(provider)s AND repo=%(repo)s AND pr_number=%(pr_number)s"
    row = db_utils.exec_get_one(sql_fallback, params)
    return row[0]

def ingest_pull_requests(provider: str, repo: str, prs: Iterable[Dict[str, Any]]) -> int:
    """Ingest multiple pull requests; return count processed.
    
    Implementation guidance:
    - Loop over prs iterable.
    - Call upsert_pull_request(provider, repo, pr) for each.
    - Return total count processed.
    """
    count = 0
    for pr in prs:
       upsert_pull_request(provider, repo, pr)
       count += 1
    return count

# ---- CI Pipelines & Jobs ----

def upsert_ci_pipeline(provider: str, repo: str, pipe: Dict[str, Any]) -> int:
    """Insert/update a CI pipeline idempotently; return db id.
    
    Implementation guidance:
    - INSERT into ci_pipelines with fields: provider, repo, pipeline_id,
      status, created_at, updated_at, sha.
    - Use str(pipe["pipeline_id"]) to handle large integers.
    - Use _normalize_timestamp_to_utc() for timestamp fields.
    - ON CONFLICT (provider, repo, pipeline_id) DO UPDATE:
      status=EXCLUDED.status,
      created_at=LEAST(ci_pipelines.created_at, EXCLUDED.created_at),
      updated_at=COALESCE(EXCLUDED.updated_at, ci_pipelines.updated_at),
      sha=COALESCE(EXCLUDED.sha, ci_pipelines.sha).
    - Use RETURNING id; fallback SELECT if needed.
    """
    sql = """
    INSERT INTO ci_pipelines (provider, repo, pipeline_id, status, created_at, updated_at, sha)
    VALUES (%(provider)s, %(repo)s, %(pipeline_id)s, %(status)s, %(created_at)s, %(updated_at)s, %(sha)s)
    ON CONFLICT (provider, repo, pipeline_id) DO UPDATE SET
        status = EXCLUDED.status,
        created_at = LEAST(ci_pipelines.created_at, EXCLUDED.created_at),
        updated_at = COALESCE(EXCLUDED.updated_at, ci_pipelines.updated_at),
        sha = COALESCE(EXCLUDED.sha, ci_pipelines.sha)
    returning id;
    """

    params = {
       "provider": provider,
       "repo": repo,
       "pipeline_id": str(pipe["pipeline_id"]),
       "status": pipe["status"],
       "created_at": _normalize_timestamp_to_utc(pipe.get("created_at")),
       "updated_at": _normalize_timestamp_to_utc(pipe.get("updated_at")),
       "sha": pipe.get("sha"),
    }

    row = db_utils.exec_commit_get_one(sql, params)
    if row:
       return row[0]
    
    sql_fallback = "SELECT id FROM ci_pipelines WHERE provider=%(provider)s AND repo=%(repo)s AND pipeline_id=%(pipeline_id)s"
    row = db_utils.exec_get_one(sql_fallback, params)
    return row[0]

def upsert_ci_job(provider: str, repo: str, job: Dict[str, Any]) -> int:
    """Insert/update a CI job idempotently; return db id.
    
    Implementation guidance:
    - INSERT into ci_jobs with fields: provider, repo, pipeline_id, job_id,
      name, status, started_at, finished_at, duration_seconds.
    - Convert job_id and pipeline_id to strings.
    - Use _normalize_timestamp_to_utc() for timestamp fields (if not None).
    - For duration_seconds: int(job.get("duration_seconds", 0)) if not None else None.
    - ON CONFLICT (provider, repo, job_id) DO UPDATE with COALESCE logic.
    - Use RETURNING id; fallback SELECT if needed.
    """
    
    sql = """
    INSERT INTO ci_jobs (provider, repo, pipeline_id, job_id, name, status, started_at, finished_at, duration_seconds)
    VALUES (%(provider)s, %(repo)s, %(pipeline_id)s, %(job_id)s, %(name)s, %(status)s, %(started_at)s, %(finished_at)s, %(duration_seconds)s)
    ON CONFLICT (provider, repo, job_id) DO UPDATE SET
        status = EXCLUDED.status,
        started_at = COALESCE(EXCLUDED.started_at, ci_jobs.started_at),
        finished_at = COALESCE(EXCLUDED.finished_at, ci_jobs.finished_at),
        duration_seconds = COALESCE(EXCLUDED.duration_seconds, ci_jobs.duration_seconds)
        RETURNING id;
    """

    if job.get("duration_seconds") is not None:
       duration = int(job.get("duration_seconds", 0))
    else:
       duration = None

    params = {
       "provider": provider,
        "repo": repo,
        "pipeline_id": str(job["pipeline_id"]),
        "job_id": str(job["job_id"]),
        "name": job.get("name"),
        "status": job.get("status"),
        "started_at": _normalize_timestamp_to_utc(job.get("started_at")),
        "finished_at": _normalize_timestamp_to_utc(job.get("finished_at")),
        "duration_seconds": duration
    }

    row = db_utils.exec_commit_get_one(sql, params)
    if row:
       return row[0]
    
    sql_get = "SELECT id FROM ci_jobs WHERE provider=%(provider)s AND repo=%(repo)s AND job_id=%(job_id)s"
    row = db_utils.exec_get_one(sql_get, params)
    return row[0]

def ingest_ci(provider: str, repo: str, pipelines: Iterable[Dict[str, Any]], 
              jobs_by_pipeline: Optional[Dict[str, Iterable[Dict[str, Any]]]] = None) -> int:
    """Ingest pipelines and their jobs. Returns number of pipelines processed.
    
    Implementation guidance:
    - Loop over pipelines iterable.
    - For each pipeline, call upsert_ci_pipeline(provider, repo, pipe).
    - If jobs_by_pipeline is provided:
      - Get pipeline_id as str(pipe["pipeline_id"]).
      - For each job in jobs_by_pipeline.get(pipeline_id, []):
        - Ensure job has "pipeline_id" set
        - Call upsert_ci_job(provider, repo, job).
    - Return total count of pipelines processed.
    """
    count = 0
    jobs_map = jobs_by_pipeline or {}

    for pipe in pipelines:
       upsert_ci_pipeline(provider, repo, pipe)
       pipeline_id = str(pipe["pipeline_id"])
       if pipeline_id in jobs_map:
          for job in jobs_map[pipeline_id]:
             job["pipeline_id"] = pipeline_id
             upsert_ci_job(provider, repo, job)
       count += 1
    return count

# ---------------------------------------------
# Helper Functions -- some are provided, others are stubbed; you can implement them or decide on your own way of providing similar functionality
# ---------------------------------------------

import requests

def fetch_json(url: str, headers: Optional[Dict[str, str]] = None, 
               params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Lightweight GET JSON wrapper."""
    resp = requests.get(url, headers=headers or {}, params=params or {}, timeout=30)
    resp.raise_for_status()
    return resp.json()

def collect_github_issues(owner_repo: str, state: str = "all", 
                          token: Optional[str] = None, 
                          per_page: int = 100, max_pages: int = 1) -> Iterable[Dict[str, Any]]:
    """Generator yielding normalized issue dicts from GitHub REST v3."""
    owner, repo = owner_repo.split("/", 1)
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = f"https://api.github.com/repos/{owner}/{repo}/issues"
    page = 1
    while page <= max_pages:
        data = fetch_json(url, headers=headers, params={"state": state, "per_page": per_page, "page": page})
        if not data:
            break
        for it in data:
            if "pull_request" in it:
                # skip PRs here; use collect_github_pulls for PR details
                continue
            labels_list = it.get("labels", [])
            labels_str = ",".join([lbl.get("name", "") for lbl in labels_list if isinstance(lbl, dict)])
            yield {
                "number": it["number"],
                "title": _strip_nul(it.get("title", "")),
                "body": _strip_nul(it.get("body") or ""),
                "author": (it.get("user") or {}).get("login"),
                "state": it.get("state", "open"),
                "state_reason": it.get("state_reason"),
                "comments_count": it.get("comments", 0),
                "labels": labels_str,
                "created_at": it.get("created_at"),
                "closed_at": it.get("closed_at"),
            }
        page += 1

def collect_github_pulls(owner_repo: str, state: str = "all", 
                        token: Optional[str] = None, 
                        per_page: int = 100, max_pages: int = 1) -> Iterable[Dict[str, Any]]:
    """Generator yielding normalized pull request dicts from GitHub REST v3.
    
    Implementation guidance:
    - URL: https://api.github.com/repos/{owner}/{repo}/pulls
    - Headers: Accept: application/vnd.github+json, Authorization if token provided
    - Query params: state={state}, per_page={per_page}, page={page}
    - Normalize state: if pr.get("merged_at") then state="merged", else pr.get("state", "open")
    - Yield dict with: number, title, author (from user.login), state, 
      created_at, merged_at, closed_at
    """
    owner, repo = owner_repo.split("/", 1)
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls"
    page = 1
    
    while page <= max_pages:
        params = {"state": state, "per_page": per_page, "page": page}
        data = fetch_json(url, headers=headers, params=params)
        
        if not data:
            break
            
        for pr in data:
            normalized_state = pr.get("state", "open")
            if pr.get("merged_at"):
                normalized_state = "merged"
                
            yield {
                "number": pr["number"],
                "title": pr.get("title", ""),
                "author": (pr.get("user") or {}).get("login"),
                "state": normalized_state,
                "created_at": pr.get("created_at"),
                "merged_at": pr.get("merged_at"),
                "closed_at": pr.get("closed_at"),
            }
        page += 1

def collect_github_actions_runs(owner_repo: str, token: Optional[str] = None, 
                                per_page: int = 100, max_pages: int = 1) -> Iterable[Dict[str, Any]]:
    """Yield pipelines from GitHub Actions workflow runs.
    
    Implementation guidance:
    - URL: https://api.github.com/repos/{owner}/{repo}/actions/runs
    - Headers: Accept: application/vnd.github+json, Authorization if token provided
    - Response is a dict with "workflow_runs" key containing array
    - For each run r, yield dict with:
      pipeline_id: r["id"]
      status: r.get("conclusion") or r.get("status") or "unknown"
      created_at: r.get("created_at")
      updated_at: r.get("updated_at")
      sha: r.get("head_sha")
    """
    owner, repo = owner_repo.split("/", 1)
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
        
    url = f"https://api.github.com/repos/{owner}/{repo}/actions/runs"
    page = 1
    
    while page <= max_pages:
        params = {"per_page": per_page, "page": page}
        resp = fetch_json(url, headers=headers, params=params)
        runs = resp.get("workflow_runs", [])
        
        if not runs:
            break
            
        for r in runs:
            yield {
                "pipeline_id": str(r["id"]),
                "status": r.get("conclusion") or r.get("status") or "unknown",
                "created_at": r.get("created_at"),
                "updated_at": r.get("updated_at"),
                "sha": r.get("head_sha"),
            }
        page += 1

def collect_github_actions_jobs(owner_repo: str, run_id: str, 
                                token: Optional[str] = None, 
                                per_page: int = 100, max_pages: int = 1) -> Iterable[Dict[str, Any]]:
    """Yield jobs for a specific GitHub Actions run.
    
    Implementation guidance:
    - URL: https://api.github.com/repos/{owner}/{repo}/actions/runs/{run_id}/jobs
    - Headers: Accept: application/vnd.github+json, Authorization if token provided
    - Response is a dict with "jobs" key containing array
    - For each job j, yield dict with:
      pipeline_id: str(run_id)
      job_id: j["id"]
      name: j.get("name")
      status: j.get("conclusion") or j.get("status")
      started_at: j.get("started_at")
      finished_at: j.get("completed_at")
      duration_seconds: j.get("duration_ms", 0) // 1000 if j.get("duration_ms") else None
    """
    owner, repo = owner_repo.split("/", 1)
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
        
    url = f"https://api.github.com/repos/{owner}/{repo}/actions/runs/{run_id}/jobs"
    page = 1
    
    while page <= max_pages:
        params = {"per_page": per_page, "page": page}
        resp = fetch_json(url, headers=headers, params=params)
        jobs = resp.get("jobs", [])
        
        if not jobs:
            break
            
        for j in jobs:
            duration_ms = j.get("duration_ms")
            duration_seconds = (duration_ms // 1000) if duration_ms is not None else None
            
            yield {
                "pipeline_id": str(run_id),
                "job_id": str(j["id"]),
                "name": j.get("name"),
                "status": j.get("conclusion") or j.get("status"),
                "started_at": j.get("started_at"),
                "finished_at": j.get("completed_at"),
                "duration_seconds": duration_seconds,
            }
        page += 1