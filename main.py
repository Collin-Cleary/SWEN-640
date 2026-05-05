import argparse
import os
import sys
import tempfile
import shutil
from git import Repo
import subprocess
from src import git_miner
from src import db_utils
from src import qual_clean
from src import sampling_algorithms
import stat
import xml.etree.ElementTree as ET
from collections import Counter
from src import research_modeling

def main(argv=None):
    argv = argv or sys.argv[1:]

    if argv and argv[0] == "analyze":
        p_analyze = argparse.ArgumentParser(description="Run DA2 vocabulary analysis")
        p_analyze.add_argument("command", help="Command to run (analyze)")
        p_analyze.add_argument("--output-dir", type=str, default="output/", help="Directory to save plots and report")
        p_analyze.add_argument("--clusters", type=int, default=5, help="Number of clusters (k) for k-means")
        p_analyze.add_argument("--commit-limit", type=int, default=None, help="Limit commits for quick testing")
        p_analyze.add_argument("--file-limit", type=int, default=None, help="Limit files for quick testing")

        args = p_analyze.parse_args(argv)
        cmd_analyze(args)
        return
    
    if argv and argv[0] == "predict":
        p_predict = argparse.ArgumentParser(description="Train commit-type classifier and write evaluation outputs (M1)")
        p_predict.add_argument("command", help="Command to run (predict)")
        p_predict.add_argument("--output-dir", default="output")
        p_predict.add_argument("--clusters", "-k", type=int, default=5)
        p_predict.add_argument("--model-type", default="decision_tree", choices=["decision_tree", "random_forest"])
        p_predict.add_argument("--max-depth", type=int, default=None)
        p_predict.add_argument("--commit-limit", type=int, default=None)
        
        args = p_predict.parse_args(argv)
        cmd_predict(args)
        return
    
    if argv and argv[0] == "research":
        research = argparse.ArgumentParser(description="Train issue resolution efficiency classifier (RQ1/RQ2)")
        research.add_argument("command", help="Command to run (research)")
        research.add_argument("--output-dir", default="output")
        research.add_argument("--model-type", default="decision_tree", choices=["decision_tree", "random_forest"])
        research.add_argument("--max-depth", type=int, default=None)
        research.add_argument("--issue-limit", type=int, default=None)
        research.add_argument("--sample-csv", type=str, default="samples/sampled_issues.csv", help="Path to sampled issues CSV (default: samples/sampled_issues.csv)")

        args = research.parse_args(argv)
        cmd_rq(args)
        return

    p = argparse.ArgumentParser(description="Clone a repository (or use local path) and run git_miner")
    p.add_argument("owner_repo", help="owner/repo (e.g. octocat/Hello-World) or local repo path")
    p.add_argument("--token", help="GitHub token (or set GITHUB_TOKEN) for private repo cloning")
    p.add_argument("--depth", type=int, default=None, help="Perform a shallow clone of a specific depth")
    p.add_argument("--max-commits", type=int, default=None, help="Stop after this many commits (optional)")
    p.add_argument("--no-record-run", action="store_true", help="Do not write a run_log entry")

    # Mining Flags
    p.add_argument("--issues", action="store_true", help="Mine GitHub Issues")
    p.add_argument("--prs", action="store_true", help="Mine GitHub Pull Requests")
    p.add_argument("--ci", action="store_true", help="Mine GitHub Actions Pipelines")
    p.add_argument("--ci-jobs", action="store_true", help="If mining CI, also fetch Jobs (API intensive)")

    # Cleaning Flags
    p.add_argument("--clean-issues", action="store_true", help="Normalize Issue titles and authors in DB")
    p.add_argument("--clean-prs", action="store_true", help="Normalize PR titles and authors in DB")
    p.add_argument("--clean-commits", action="store_true", help="Parse and normalize Commit messages in DB")
    p.add_argument("--clean-limit", type=int, default=None, help="Limit number of rows to clean (for testing)")

    # Sampling Flags (What to sample)
    p.add_argument("--sample-issues", action="store_true", help="Generate sample CSV for Issues")
    p.add_argument("--sample-commits", action="store_true", help="Generate sample CSV for Commits")
    p.add_argument("--sample-prs", action="store_true", help="Generate sample CSV for Pull Requests")
    p.add_argument("--sample-workflows", action="store_true", help="Generate sample CSV for CI Pipelines")
    p.add_argument("--sample-jobs", action="store_true", help="Generate sample CSV for CI Jobs")

    # Sampling Parameters (How to sample)
    p.add_argument("--sample-n", type=int, default=None, help="Exact number of items to sample")
    p.add_argument("--sample-frac", type=float, default=None, help="Fraction of items to sample (0.0 - 1.0)")
    p.add_argument("--sample-step", type=int, default=None, help="Step size for systematic sampling")
    p.add_argument("--sample-seed", type=int, default=None, help="Random seed for reproducibility")
    p.add_argument("--sample-key", type=str, default=None, help="Column name to stratify by (e.g., 'author', 'state')")

    p.add_argument("--dump-identifiers", action="store_true", help="Dump all raw parsed identifiers to a CSV")

    p.add_argument("--mine-code-artifacts", action="store_true", help="Run srcML to extract and store itentifiers and comments to the Database")
    p.add_argument("--file-limit", type=int, default=None, help="determine the number of files from which srcml stores comments and identifiers")

    args = p.parse_args(argv)

    token = args.token or os.environ.get("GITHUB_TOKEN")
    owner_repo = args.owner_repo

    tmp_repo_dir = None
    repo_path = owner_repo

    # 1. MINING PHASE
    try:
        if "/" in owner_repo and not os.path.isdir(owner_repo):
            tmp_repo_dir = tempfile.mkdtemp(prefix="gitminer_")
            if token:
                clone_url = f"https://{token}@github.com/{owner_repo}.git"
            else:
                clone_url = f"https://github.com/{owner_repo}.git"
            print(f"Cloning {owner_repo} into {tmp_repo_dir}...")
            #Repo.clone_from(clone_url, tmp_repo_dir)
            clone_cmd = ["git", "clone"]
            
            if args.depth:
                clone_cmd.extend(["--depth", str(args.depth)])
            else:
                clone_cmd.append("--filter=blob:none")
                
            clone_cmd.extend([clone_url, tmp_repo_dir])
            
            subprocess.run(clone_cmd, check=True)
            repo_path = tmp_repo_dir

        print(f"Mining repository at {repo_path}...")
        safe_max = args.max_commits
        if args.depth:
            limit = args.depth - 1
            if safe_max is None or safe_max > limit:
                safe_max = limit
        n = git_miner.mine_history(repo_path, max_commits=safe_max, record_run=(not args.no_record_run))
        head = git_miner.extract_head_commit(repo_path)
        print(f"Mined {n} commits; HEAD {head.get('hash')} by {head.get('author_name')} at {head.get('timestamp')}")

        if getattr(args, 'mine_code_artifacts', False):
            print("\nStarting Code Artifact Mining (Identifiers and Comments)...")

            def remove_readonly(func, path, _):
                os.chmod(path, stat.S_IWRITE)
                func(path)

            git_dir = os.path.join(repo_path, ".git")
            if os.path.exists(git_dir):
                shutil.rmtree(git_dir, onerror=remove_readonly)

            supported_exts = ('.c', '.cpp', '.cxx', '.cs', '.java')
            for root, dirs, files in os.walk(repo_path):
                for file in files:
                    if not file.endswith(supported_exts):
                        try:
                            file_path = os.path.join(root, file)
                            os.chmod(file_path, stat.S_IWRITE)
                            os.remove(file_path)
                        except Exception:
                            pass

            _mine_code_artifacts(repo_path, int(args.file_limit))

        if getattr(args, 'dump_identifiers', False):
            from src.da1_identifiers import export_dataset_to_csv
            
            repo_name = owner_repo.split('/')[-1] if '/' in owner_repo else os.path.basename(os.path.abspath(repo_path))
            out_filename = f"{repo_name}_file_dataset.csv"
            
            print(f"\nStarting dataset generation for {repo_name}...")
            export_dataset_to_csv(repo_path, commit_hash="HEAD", output_csv=out_filename)
            
    except Exception as e:
        print(f"Error mining git history: {e}", file=sys.stderr)
        raise
    finally:
        if tmp_repo_dir:
            try:
                shutil.rmtree(tmp_repo_dir)
            except Exception:
                pass


    # 2. ECOSYSTEM PHASE
    if (args.issues or args.prs or args.ci) and "/" in owner_repo and not os.path.isdir(owner_repo):
        print("Starting Ecosystem Mining...")
        provider = "github"

        if args.issues:
            print(f"  > Collecting Issues for {owner_repo}...")
            try:
                issue_gen = git_miner.collect_github_issues(owner_repo, token=token, per_page=100, max_pages=100)
                count = git_miner.ingest_issues(provider, owner_repo, issue_gen)
                print(f"  > Ingested {count} issues.")
            except Exception as e:
                print(f"  > Error collecting issues: {e}", file=sys.stderr)

        if args.prs:
            print(f"  > Collecting Pull Requests for {owner_repo}...")
            try:
                pr_gen = git_miner.collect_github_pulls(owner_repo, token=token)
                count = git_miner.ingest_pull_requests(provider, owner_repo, pr_gen)
                print(f"  > Ingested {count} pull requests.")
            except Exception as e:
                print(f"  > Error collecting PRs: {e}", file=sys.stderr)

        if args.ci:
            print(f"  > Collecting CI Pipelines for {owner_repo}...")
            try:
                pipelines = list(git_miner.collect_github_actions_runs(owner_repo, token=token))
                print(f"  > Found {len(pipelines)} pipelines. Processing...")
                
                jobs_map = {}
                if args.ci_jobs:
                    print(f"  > Fetching jobs for {len(pipelines)} pipelines (API intensive)...")
                    for pipe in pipelines:
                        p_id = str(pipe["pipeline_id"])
                        jobs = list(git_miner.collect_github_actions_jobs(owner_repo, p_id, token=token))
                        if jobs:
                            jobs_map[p_id] = jobs
                
                count = git_miner.ingest_ci(provider, owner_repo, pipelines, jobs_by_pipeline=jobs_map)
                print(f"  > Ingested {count} pipelines (with jobs).")
            except Exception as e:
                print(f"  > Error collecting CI: {e}", file=sys.stderr)
                
    elif (args.issues or args.prs or args.ci):
        print("Warning: Ecosystem mining skipped. It requires an 'owner/repo' string, not a local path.")

    # 3. CLEANING PHASE
    if args.clean_issues or args.clean_prs or args.clean_commits:
        print("Starting Data Cleaning & Normalization...")

        if args.clean_issues:
            print("  > Normalizing Issues (titles, authors)...")
            try:
                n = qual_clean.clean_issues_db(limit=args.clean_limit)
                print(f"  > Cleaned {n} issues.")
            except Exception as e:
                print(f"  > Error cleaning issues: {e}", file=sys.stderr)

        if args.clean_prs:
            print("  > Normalizing Pull Requests (titles, authors)...")
            try:
                n = qual_clean.clean_prs_db(limit=args.clean_limit)
                print(f"  > Cleaned {n} pull requests.")
            except Exception as e:
                print(f"  > Error cleaning PRs: {e}", file=sys.stderr)

        if args.clean_commits:
            print("  > Normalizing Commit Messages (structured parsing)...")
            try:
                n = qual_clean.clean_commits_db(limit=args.clean_limit)
                print(f"  > Cleaned {n} commits.")
            except Exception as e:
                print(f"  > Error cleaning commits: {e}", file=sys.stderr)

    # 4. SAMPLING PHASE
    any_sampling = (args.sample_issues or args.sample_commits or args.sample_prs 
                    or args.sample_workflows or args.sample_jobs)
    
    if any_sampling:
        print("Starting Sampling Phase...")
        try:
            sampling_algorithms.run_sampling(
                sample_issues=args.sample_issues,
                sample_commits=args.sample_commits,
                sample_prs=args.sample_prs,
                sample_workflows=args.sample_workflows,
                sample_jobs=args.sample_jobs,
                n=args.sample_n,
                frac=args.sample_frac,
                step=args.sample_step,
                seed=args.sample_seed,
                key=args.sample_key
            )
            print("  > Sampling complete. Check 'samples/' directory.")
        except Exception as e:
            print(f"  > Error during sampling: {e}", file=sys.stderr)

def _mine_code_artifacts(repo_path: str, file_limit: int = None) -> None:
    """Run srcML on the entire cloned repo directory, then store identifiers
    and comments to the DB.

    Must be called *before* the temp directory is cleaned up.  Clears existing
    rows first so re-running mine is idempotent.

    Silently exits if srcML is not installed rather than failing the whole
    mine stage.
    """
    from src import db_utils, srcml_runner
    from src import da1_identifiers
    from src import da2_vocabulary

    # Ensure new tables exist (idempotent)
    #db_utils.exec_sql_file('data/schema.sql')

    # Clear previous run's data -- REMOVE IF YOU DO NOT WANT IT
    db_utils.exec_commit("TRUNCATE code_identifiers, code_comments;")

    # Single srcML call on the whole directory
    print("  Running srcML on repository directory...")
    try:
        dir_xml = srcml_runner.run_srcml_on_directory(repo_path)
    except RuntimeError as exc:
        print(f"  Warning: srcML unavailable - skipping code artifact mining ({exc})",
              file=sys.stderr)
        return
    except Exception as exc:
        print(f"  Warning: srcML failed - {exc}", file=sys.stderr)
        return

    # Parse the multi-unit document; each child <unit> is one source file
    try:
        root = ET.fromstring(dir_xml.encode("utf-8"))
    except ET.ParseError as exc:
        print(f"  Warning: could not parse srcML output - {exc}", file=sys.stderr)
        return

    units = [c for c in root if c.tag.split('}')[-1] == 'unit']
    if file_limit:
        units = units[:file_limit]

    print(f"  Processing {len(units)} source files...")

    id_rows = []
    cm_rows = []

    for unit in units:
        rel_path = unit.get('filename', '')
        unit_xml = ET.tostring(unit, encoding='unicode')

        # DA1 - identifiers
        try:
            for row in da1_identifiers.extract_identifiers_dom(unit_xml):
                id_rows.append({"fp": rel_path, "name": row["name"], "kind": row["kind"]})
        except Exception:
            pass

        # DA2 - comments
        try:
            for text in da2_vocabulary.extract_comments_from_srcml(unit_xml):
                if text.strip():
                    cm_rows.append({"fp": rel_path, "ct": text})
        except Exception:
            pass

    # Batch insert
    db_utils.exec_many(
        "INSERT INTO code_identifiers (file_path, name, kind) VALUES (%(fp)s, %(name)s, %(kind)s);",
        id_rows,
    )
    db_utils.exec_many(
        "INSERT INTO code_comments (file_path, comment_text) VALUES (%(fp)s, %(ct)s);",
        cm_rows,
    )

    print(f"    -> {len(id_rows)} identifiers, {len(cm_rows)} comments from {len(units)} files")


def cmd_analyze(args) -> None:
    """Run DA2 vocabulary analysis from DB. No network calls.

    Produces:
      <output_dir>/commit_clusters.png      k-means scatter (commit vocab)
      <output_dir>/identifier_clusters.png  k-means scatter (identifier vocab)
      <output_dir>/comment_clusters.png     k-means scatter (comment vocab)
      <output_dir>/alignment_report.txt     cluster inspection + alignment metrics
    """
    from src import da2_vocabulary
    import os

    out = args.output_dir
    os.makedirs(out, exist_ok=True)
    k = args.clusters

    # 1. Build vocabulary dataset from DB
    print("Building vocabulary dataset from DB...")
    dataset = da2_vocabulary.build_vocabulary_dataset(
        commit_limit=args.commit_limit,
        file_limit=args.file_limit,
    )

    commit_tokens     = dataset["commit_tokens"]
    identifier_tokens = dataset["identifier_tokens"]
    comment_tokens    = dataset["comment_tokens"]

    print(f"  commit tokens:     {len(commit_tokens)}")
    print(f"  identifier tokens: {len(identifier_tokens)}")
    print(f"  comment tokens:    {len(comment_tokens)}")

    # 2. k-means clustering + scatter plots
    sources = [
        ("commit",     commit_tokens,     "Commit Message Vocabulary"),
        ("identifier", identifier_tokens, "Code Identifier Vocabulary"),
        ("comment",    comment_tokens,    "Code Comment Vocabulary"),
    ]

    kmeans_labels = {}
    cluster_inspection = {}  # name -> {cluster_id: [top tokens]}
    for name, tokens, title in sources:
        if not tokens:
            print(f"  [{name}] no tokens – skipping k-means")
            kmeans_labels[name] = None
            cluster_inspection[name] = {}
            continue
        print(f"  Clustering {name} tokens (k={k})...")
        labels, vectors, _ = da2_vocabulary.cluster_vocabulary(tokens, k=k)
        kmeans_labels[name] = labels
        cluster_inspection[name] = da2_vocabulary.inspect_clusters(tokens, labels, top_n=10)
        coords = da2_vocabulary.reduce_dimensions(vectors, method="pca")
        da2_vocabulary.visualize_clusters(
            coords, labels, tokens,
            title=f"{title} – k-means (k={k})",
            output_path=os.path.join(out, f"{name}_clusters.png"),
        )
        print(f"    → {out}/{name}_clusters.png")

    # 3. Alignment metrics + report
    alignment = dataset.get("alignment", {})

    report_lines = ["VOCABULARY ALIGNMENT REPORT", "=" * 40, ""]

    source_titles = {
        "commit":     "Commit Message Vocabulary",
        "identifier": "Code Identifier Vocabulary",
        "comment":    "Code Comment Vocabulary",
    }
    for name, title in source_titles.items():
        clusters = cluster_inspection.get(name, {})
        if not clusters:
            continue
        report_lines += [f"{title} Clusters", "-" * 36]
        for cluster_id, top_tokens in sorted(clusters.items()):
            report_lines.append(f"  Cluster {cluster_id}: {', '.join(top_tokens)}")
        report_lines.append("")

    report_lines += ["Alignment Metrics", "=" * 40, ""]

    pair_names = {
        "commits_identifiers":  ("commit",     "identifier"),
        "commits_comments":     ("commit",     "comment"),
        "identifiers_comments": ("identifier", "comment"),
    }
    for key, (a, b) in pair_names.items():
        m = alignment.get(key)
        if not m:
            report_lines.append(f"{a} ↔ {b}: no data")
            continue
        report_lines += [
            f"{a} ↔ {b}",
            f"  Vocabulary overlap (Jaccard): {m['vocab_overlap']:.1%}",
            f"  Shared vocabulary size:       {m['shared_vocab_size']}",
            f"  Cluster similarity (ARI):     {m['cluster_similarity']:.3f}",
            "",
        ]

    report_path = os.path.join(out, "alignment_report.txt")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))
    print(f"  → {report_path}")

    for line in report_lines:
        print(line)


def cmd_predict(args) -> None:
    """Train a commit-type classifier from DB data and write evaluation outputs.

    No network calls.  Reads commits, identifiers, and comments from the DB
    (populated by 'mine'), then runs the full M1 pipeline.

    Produces:
      <output_dir>/feature_importance.png   — which features matter most
      <output_dir>/confusion_matrix.png     — where the model gets confused
      <output_dir>/model_report.txt         — accuracy, per-class F1, interpretation

    Usage:
        python main.py predict
        python main.py predict --output-dir output/ --clusters 5
        python main.py predict --model-type random_forest --max-depth 5
    """
    from src import m1_modeling, da2_vocabulary
    import os
    from src import db_utils # Ensuring this is available for the DB query

    out = args.output_dir
    os.makedirs(out, exist_ok=True)
    k = args.clusters

    # 1. Load commit records from DB
    print("Loading commit data from DB...")
    commit_records = m1_modeling.load_commit_data(
        commit_limit=getattr(args, "commit_limit", None)
    )
    print(f"  {len(commit_records)} commits loaded")

    if not commit_records:
        print("No commits found. Run 'mine' first.")
        return

    # 2. (Optional) Load identifier and comment tokens for overlap features
    try:
        id_rows = db_utils.exec_get_all("SELECT name FROM code_identifiers;")
        identifier_tokens = da2_vocabulary.extract_vocabulary(
            [r[0] for r in id_rows if r[0]]
        )
        cm_rows = db_utils.exec_get_all("SELECT comment_text FROM code_comments;")
        comment_tokens = da2_vocabulary.extract_vocabulary(
            [r[0] for r in cm_rows if r[0]]
        )
    except Exception as e:
        print(f"  Warning: could not load identifier/comment tokens: {e}")
        identifier_tokens = []
        comment_tokens = []

    # 3. Build feature matrix
    print(f"Building feature matrix (k={k})...")
    X, y, feature_names = m1_modeling.build_feature_matrix(
        commit_records,
        k=k,
        identifier_tokens=identifier_tokens,
        comment_tokens=comment_tokens,
    )
    print(f"  X shape: {X.shape}")
    print(f"  Label distribution: {dict(Counter(y))}")

    if len(set(y)) < 2:
        print("Only one label class found — model cannot be trained.")
        return

    # 4. Train/test split
    X_train, X_test, y_train, y_test = m1_modeling.split_dataset(
        X, y, test_size=0.2
    )

    # 5. Train
    model_type = getattr(args, "model_type", "decision_tree")
    print(f"Training {model_type}...")
    model = m1_modeling.train_classifier(X_train, y_train, model_type=model_type)

    # 6. Evaluate
    from sklearn.metrics import classification_report as sk_clf_report

    results = m1_modeling.evaluate_model(model, X_test, y_test)
    clf_report_text = sk_clf_report(
        y_test, results["y_pred"],
        labels=results["class_names"],
        zero_division=0,
    )
    print(f"  Accuracy: {results['accuracy']:.1%}")
    print()
    print("Classification report:")
    print(clf_report_text)

    # 7. Plots — wrapped in try/except so one failure doesn't block the report
    fi_path = os.path.join(out, "feature_importance.png")
    cm_path = os.path.join(out, "confusion_matrix.png")

    try:
        m1_modeling.plot_feature_importance(model, feature_names, output_path=fi_path)
        print(f"  -> {fi_path}")
    except Exception as exc:
        print(f"  Warning: could not save feature_importance.png: {exc}")

    try:
        m1_modeling.plot_confusion_matrix(
            y_test, results["y_pred"], results["class_names"], output_path=cm_path
        )
        print(f"  -> {cm_path}")
    except Exception as exc:
        print(f"  Warning: could not save confusion_matrix.png: {exc}")

    # 8. Write model report
    report_lines = [
        "M1 MODEL REPORT",
        "=" * 40,
        "",
        f"Model type:  {model_type}",
        f"Features:    {len(feature_names)}",
        f"Train size:  {len(X_train)}",
        f"Test size:   {len(X_test)}",
        f"Accuracy:    {results['accuracy']:.1%}",
        "",
        "Classification report (test set):",
        "-" * 36,
        clf_report_text,
        "Feature importances (descending):",
        "-" * 36,
    ]
    importances = model.feature_importances_
    ranked = sorted(zip(feature_names, importances), key=lambda x: -x[1])
    for name, imp in ranked:
        report_lines.append(f"  {name:<25} {imp:.4f}")
    report_lines += [
        "",
        "Interpretation:",
        "  [TODO: Write 2-3 sentences interpreting your results here]",
        "  Which clusters are most predictive? What does the confusion",
        "  matrix tell you about which commit types are hardest to classify?",
    ]

    report_path = os.path.join(out, "model_report.txt")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))
    for line in report_lines:
        print(line)
    print(f"  -> {report_path}")


def cmd_rq(args) -> None:
    from src import research_modeling as rq_modeling
    from sklearn.metrics import classification_report as sk_clf_report
    import os

    out = args.output_dir
    os.makedirs(out, exist_ok=True)

    # 1. Load data
    print("Loading issue data from DB...")
    issue_records = rq_modeling.load_issue_data(
        issue_limit=getattr(args, "issue_limit", None),
        sample_csv=getattr(args, "sample_csv", "samples/sampled_issues.csv")
    )
    print(f"  {len(issue_records)} closed issues loaded")

    if not issue_records:
        print("No closed issues found. Run 'mine --issues' first.")
        return

    # 2. Build feature matrix
    print("Building feature matrix...")
    X, y, feature_names = rq_modeling.build_feature_matrix(issue_records)
    print(f"  X shape: {X.shape}")
    print(f"  Label distribution: {dict(Counter(y))}")

    if len(set(y)) < 2:
        print("Only one efficiency class found — model cannot be trained.")
        return

    # 3. Split
    X_train, X_test, y_train, y_test = rq_modeling.split_dataset(X, y)

    # 4. Train
    model_type = getattr(args, "model_type", "decision_tree")
    print(f"Training {model_type}...")
    model = rq_modeling.train_classifier(
        X_train, y_train,
        model_type=model_type,
        max_depth=getattr(args, "max_depth", None)
    )

    # 5. Evaluate
    results = rq_modeling.evaluate_model(model, X_test, y_test)
    clf_report_text = sk_clf_report(
        y_test, results["y_pred"],
        labels=results["class_names"],
        zero_division=0,
    )
    print(f"  Accuracy: {results['accuracy']:.1%}")
    print()
    print("Classification report:")
    print(clf_report_text)

    # 6. Plots
    fi_path = os.path.join(out, "rq_feature_importance.png")
    cm_path = os.path.join(out, "rq_confusion_matrix.png")

    try:
        rq_modeling.plot_feature_importance(model, feature_names, output_path=fi_path)
        print(f"  -> {fi_path}")
    except Exception as exc:
        print(f"  Warning: could not save rq_feature_importance.png: {exc}")

    try:
        rq_modeling.plot_confusion_matrix(
            y_test, results["y_pred"], results["class_names"], output_path=cm_path
        )
        print(f"  -> {cm_path}")
    except Exception as exc:
        print(f"  Warning: could not save rq_confusion_matrix.png: {exc}")

    # 7. Report
    report_lines = [
        "RQ MODEL REPORT",
        "=" * 40,
        "",
        f"Model type:  {model_type}",
        f"Features:    {len(feature_names)}",
        f"Train size:  {len(X_train)}",
        f"Test size:   {len(X_test)}",
        f"Accuracy:    {results['accuracy']:.1%}",
        "",
        "Classification report (test set):",
        "-" * 36,
        clf_report_text,
        "Feature importances (descending):",
        "-" * 36,
    ]
    importances = model.feature_importances_
    ranked = sorted(zip(feature_names, importances), key=lambda x: -x[1])
    for name, imp in ranked:
        report_lines.append(f"  {name:<25} {imp:.4f}")

    report_path = os.path.join(out, "rq_report.txt")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))
    print(f"  -> {report_path}")

if __name__ == "__main__":
    main()