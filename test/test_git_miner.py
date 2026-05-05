from src import db_utils
from src.git_miner import mine_and_store, mine_history, validate_invariants, ingest_issues, ingest_pull_requests, ingest_ci
from git import Repo
import os
import pytest

def test_mine_and_store_inserts_head_commit(temp_git_repo):
    info = mine_and_store(temp_git_repo)
    assert 'hash' in info
    assert info['author_name'] == 'STRATA Student'

    row = db_utils.exec_get_one("SELECT commit_hash, author_name, message FROM commits ORDER BY id DESC LIMIT 1;")
    assert row[0] == info['hash']
    assert row[1] == 'STRATA Student'
    assert 'initial commit' in row[2]

def test_head_mining_compatibility(two_commit_seed_repo):
    info = mine_and_store(two_commit_seed_repo)
    assert info['author_name'] == 'STRATA Student'
    assert info['message'] == 'second commit'

    sql = """
    SELECT commit_hash, message
    FROM commits 
    WHERE commit_hash = %(hash)s;
    """
    params = {
        "hash": info['hash']
    }
    row = db_utils.exec_get_one(sql, params)
    assert row is not None
    assert row[1] == 'second commit'

def test_full_history_mining_populates_stats_and_files(two_commit_seed_repo):
    mine_history(two_commit_seed_repo)
    commit_count = db_utils.exec_get_one("SELECT COUNT (*) FROM commits;")[0]
    assert commit_count >= 2

    stats_count = db_utils.exec_get_one("SELECT COUNT (*) FROM commit_stats;")[0]
    assert stats_count == commit_count

    sql = """
    SELECT additions, deletions FROM commit_files
    WHERE file_path = 'hello.txt';
    """
    results = db_utils.exec_get_all(sql)
    assert len(results) > 0
    for result in results:
        assert result[0] >= 0
        assert result[1] >= 0

def test_idempotent_etl(two_commit_seed_repo):
    mine_history(two_commit_seed_repo)
    commit_count1 = db_utils.exec_get_one("SELECT COUNT(*) FROM commits;")[0]
    stats_count1 = db_utils.exec_get_one("SELECT COUNT(*) FROM commit_stats;")[0]
    files_count1 = db_utils.exec_get_one("SELECT COUNT(*) FROM commit_files;")[0]

    mine_history(two_commit_seed_repo)
    commit_count2 = db_utils.exec_get_one("SELECT COUNT(*) FROM commits;")[0]
    stats_count2 = db_utils.exec_get_one("SELECT COUNT(*) FROM commit_stats;")[0]
    files_count2 = db_utils.exec_get_one("SELECT COUNT(*) FROM commit_files;")[0]

    assert commit_count1 == commit_count2
    assert stats_count1 == stats_count2
    assert files_count1 == files_count2

def test_provenance_recorded_in_run_log(two_commit_seed_repo):
    repo = Repo(two_commit_seed_repo)
    expected_head_hash = repo.head.commit.hexsha
    repo.close()

    results = mine_history(two_commit_seed_repo, record_run=True)
    sql = """
    SELECT repo_path, head_hash, commit_count 
    FROM run_log 
    ORDER BY id dESC 
    LIMIT 1;
    """

    log = db_utils.exec_get_one(sql)

    assert two_commit_seed_repo in log[0]
    assert log[1] == expected_head_hash
    assert log[2] == results

def test_validation_invariants(two_commit_seed_repo):
    mine_history(two_commit_seed_repo)
    commit_count, stats_count, orphan_parent_count = validate_invariants()
    assert stats_count == commit_count
    assert orphan_parent_count == 0

def test_change_in_count_after_new_commit(two_commit_seed_repo):
    mine_history(two_commit_seed_repo)
    commit_count = db_utils.exec_get_one("SELECT COUNT(*) FROM commits")[0]
    files_count = db_utils.exec_get_one("SELECT COUNT(*) FROM commit_files;")[0]
    assert commit_count == 2
    assert files_count == 2

    repo = Repo(two_commit_seed_repo)
    new_fpath = os.path.join(two_commit_seed_repo, 'new_file.txt')
    with open(new_fpath, 'w') as f:
        f.write('Hey, how is it going?')
    repo.index.add([new_fpath])
    repo.index.commit('commit new file')
    repo.close()

    mine_history(two_commit_seed_repo)
    commit_count2 = db_utils.exec_get_one("SELECT COUNT(*) FROM commits")[0]
    files_count2 = db_utils.exec_get_one("SELECT COUNT(*) FROM commit_files;")[0]

    assert commit_count < commit_count2
    assert files_count < files_count2

def test_root_commit_as_A_in_commit_files(two_commit_seed_repo):
    mine_history(two_commit_seed_repo)
    root = db_utils.exec_get_one("SELECT id FROM commits ORDER BY id ASC LIMIT 1;")[0]
    sql = """
    SELECT change_type 
    FROM commit_files 
    WHERE commit_id = %(commit_id)s;
    """
    results = db_utils.exec_get_all(sql, {'commit_id': root})
    assert len(results) > 0
    for row in results:
        assert row[0] == 'A'

def test_issues_prs_upsert_idempotency():
    provider = "github"
    repo_name = "acme/widgets"

    issues_seed = [
        {"number": 1, "title": "Fix bug", "state": "open", "created_at": "2025-01-01T10:00:00Z", "author": "alice"},
        {"number": 2, "title": "Old bug", "state": "closed", "created_at": "2024-01-01T10:00:00Z", "closed_at": "2024-02-01T10:00:00Z", "author": "bob"}
    ]

    prs_seed = [
        {"number": 10, "title": "New Feat", "state": "open", "created_at": "2025-03-01T10:00:00Z", "author": "charlie"},
        {"number": 11, "title": "Merged Feat", "state": "merged", "created_at": "2025-03-02T10:00:00Z", "merged_at": "2025-03-03T10:00:00Z", "closed_at": "2025-03-03T10:00:00Z", "author": "dave"}
    ]

    ingest_issues(provider, repo_name, issues_seed)
    ingest_pull_requests(provider, repo_name, prs_seed)

    ingest_issues(provider, repo_name, issues_seed)
    ingest_pull_requests(provider, repo_name, prs_seed)

    issue_count = db_utils.exec_get_one("SELECT COUNT(*) FROM issues WHERE repo = %(repo)s", {"repo": repo_name})[0]
    pr_count = db_utils.exec_get_one("SELECT COUNT(*) FROM pull_requests WHERE repo = %(repo)s", {"repo": repo_name})[0]
    assert issue_count == 2
    assert pr_count == 2
    row_merged = db_utils.exec_get_one(
        "SELECT state FROM pull_requests WHERE repo=%(repo)s AND pr_number=11", 
        {"repo": repo_name}
    )
    assert row_merged[0] == "merged"

def test_ci_pipeline_and_jobs_upsert_idempotency_and_linkage(two_commit_seed_repo):
    mine_history(two_commit_seed_repo)
    
    repo = Repo(two_commit_seed_repo)
    head_sha = repo.head.commit.hexsha
    repo.close()

    provider = "github"
    repo_name = two_commit_seed_repo 

    pipelines = [{
        "pipeline_id": "1001",
        "sha": head_sha,
        "status": "success",
        "created_at": "2025-05-01T12:00:00Z",
        "updated_at": "2025-05-01T12:05:00Z"
    }]

    jobs_map = {
        "1001": [
            {"job_id": "2001", "pipeline_id": "1001", "name": "build", "status": "success", "started_at": "2025-05-01T12:00:00Z", "finished_at": "2025-05-01T12:02:00Z", "duration_seconds": 120},
            {"job_id": "2002", "pipeline_id": "1001", "name": "test", "status": "success", "started_at": "2025-05-01T12:02:00Z", "finished_at": "2025-05-01T12:05:00Z", "duration_seconds": 180}
        ]
    }

    ingest_ci(provider, repo_name, pipelines, jobs_map)
    ingest_ci(provider, repo_name, pipelines, jobs_map)

    p_count = db_utils.exec_get_one("SELECT COUNT(*) FROM ci_pipelines WHERE repo = %(repo)s", {"repo": repo_name})[0]
    j_count = db_utils.exec_get_one("SELECT COUNT(*) FROM ci_jobs WHERE repo = %(repo)s", {"repo": repo_name})[0]
    
    assert p_count == 1
    assert j_count == 2

    sql_link = """
    SELECT 1 FROM commits c
    JOIN ci_pipelines p ON c.commit_hash = p.sha
    WHERE p.pipeline_id = '1001';
    """
    row = db_utils.exec_get_one(sql_link)
    assert row is not None, "Pipeline SHA should match a mined commit hash"


def test_timestamp_robustness():
    """
    Requirement E: Timestamp coercion is robust.
    - Given ISO8601 timestamps with or without 'Z' and with/without fractional seconds.
    - Rows inserted with valid TIMESTAMP.
    """
    provider = "github"
    repo_name = "test/timestamps"
    
    issues = [

        {"number": 1, "title": "Z time", "state": "open", "created_at": "2025-01-01T12:00:00Z", "author": "a"},
        {"number": 2, "title": "Offset time", "state": "open", "created_at": "2025-01-01T12:00:00+00:00", "author": "b"},
        {"number": 3, "title": "Frac time", "state": "open", "created_at": "2025-01-01T12:00:00.123456Z", "author": "c"},
        {"number": 4, "title": "Naive time", "state": "open", "created_at": "2025-01-01T12:00:00", "author": "d"}
    ]

    ingest_issues(provider, repo_name, issues)
    count = db_utils.exec_get_one("SELECT COUNT(*) FROM issues WHERE repo=%(repo)s", {"repo": repo_name})[0]
    assert count == 4


def test_upsert_updates_state_correctly():
    provider = "github"
    repo = "acme/updating"
    issue_v1 = [{"number": 100, "title": "Flaky Bug", "state": "open", "created_at": "2025-01-01T10:00:00Z", "author": "tester"}]
    ingest_issues(provider, repo, issue_v1)

    status_1 = db_utils.exec_get_one("SELECT state FROM issues WHERE repo=%(repo)s AND issue_number=100", {"repo": repo})[0]
    assert status_1 == "open"

    issue_v2 = [{"number": 100, "title": "Flaky Bug", "state": "closed", "created_at": "2025-01-01T10:00:00Z", "closed_at": "2025-01-02T10:00:00Z", "author": "tester"}]
    ingest_issues(provider, repo, issue_v2)

    status_2 = db_utils.exec_get_one("SELECT state FROM issues WHERE repo=%(repo)s AND issue_number=100", {"repo": repo})[0]
    assert status_2 == "closed"


def test_ci_jobs_null_handling(two_commit_seed_repo):
    mine_history(two_commit_seed_repo)
    repo = Repo(two_commit_seed_repo)
    head_sha = repo.head.commit.hexsha
    repo.close()
    provider = "github"
    repo_name = two_commit_seed_repo
    pipeline_id = "999"

    pipelines = [{
        "pipeline_id": pipeline_id,
        "sha": head_sha,
        "status": "pending",
        "created_at": "2025-01-01T12:00:00Z",
        "updated_at": "2025-01-01T12:05:00Z"
    }]

    jobs_map = {
        pipeline_id: [
            {
                "job_id": "job_running",
                "pipeline_id": pipeline_id,
                "name": "long-process",
                "status": "running",
                "started_at": "2025-01-01T12:00:00Z",
                "finished_at": None,       
                "duration_seconds": None   
            }
        ]
    }

    ingest_ci(provider, repo_name, pipelines, jobs_map)
    stored_job = db_utils.exec_get_one(
        "SELECT finished_at, duration_seconds FROM ci_jobs WHERE job_id=%s", 
        ("job_running",)
    )

    assert stored_job is not None, "Job should be inserted successfully"
    assert stored_job[0] is None, f"finished_at should be NULL, got {stored_job[0]}"
    assert stored_job[1] is None, f"duration_seconds should be NULL, got {stored_job[1]}"