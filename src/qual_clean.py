from typing import Any, Dict, Optional, Tuple
from src import db_utils
import re

# ---- User Canonicalization ----

def canonicalize_user(login: Optional[str]) -> Tuple[str, bool]:
    """Canonicalize a user login and detect bot accounts.

    Why this matters for MSR:
    - Contributors appear with inconsistent casing ("Alice" vs "alice")
    - Bot accounts should often be filtered from human contributor analysis
    - Consistent formats enable accurate contributor metrics

    Parameters:
    - login: raw login string (may be None or empty)

    Returns:
    - (login_norm, is_bot) tuple where:
      - login_norm: lowercase, stripped login (empty string for falsy inputs)
      - is_bot: True if login matches common bot patterns

    Bot detection hints - look for these patterns:
    - "[bot]" suffix (e.g., "dependabot[bot]")
    - Known names: "dependabot", "renovate", "github-actions", "gitlab-ci"

    Examples:
    >>> canonicalize_user("Alice")
    ('alice', False)
    >>> canonicalize_user("dependabot[bot]")
    ('dependabot[bot]', True)
    >>> canonicalize_user(None)
    ('', False)
    """
    if login:
        login_norm = login.strip().lower()
    else: login_norm = ""

    is_bot = "[bot]" in login_norm or "bot" in login_norm or "renovate" in login_norm or "github-actions" in login_norm or "gitlab-ci" in login_norm
    return (login_norm, is_bot)

# ---- Text Normalization ----

def normalize_text(md: Optional[str]) -> str:
    """Convert Markdown-like text into clean plain text for analysis.

    Why this matters for MSR:
    - Issue/PR bodies contain Markdown that obscures actual content
    - Code blocks should be preserved but marked for analysis
    - Consistent whitespace enables text comparison and NLP

    Parameters:
    - md: raw text that may contain Markdown (None returns empty string)

    Returns:
    - Cleaned text with these transformations:
      - Fenced code blocks (```...```) → <CODE>...</CODE>
      - Inline code (`...`) → <CODE>...</CODE>
      - Heading markers (e.g., "## ") removed
      - List bullets (e.g., "- ", "* ", "1. ") removed
      - Windows/Mac newlines → Unix \\n
      - Runs of 3+ blank lines → 2 blank lines
      - Runs of 2+ spaces/tabs → 1 space
      - ASCII control characters removed (except newlines)
      - URLs preserved as-is

    Examples:
    >>> normalize_text("# Hello World")
    'Hello World'
    >>> normalize_text("Use `print()` to debug")
    'Use <CODE>print()</CODE> to debug'
    >>> normalize_text(None)
    ''

    Implementation hints:
    - Use re.compile() for regex patterns
    - Process fenced code blocks BEFORE inline code (order matters!)
    - re.DOTALL makes . match newlines
    - re.MULTILINE makes ^ match line starts
    """

    if not md:
        return ""
    
    text = md

    patterns = [
        (re.compile(r"```(?:[^\n]*)(.*?)```", flags=re.DOTALL), r"<CODE>\1</CODE>"),
        (re.compile(r"`(.*?)`", flags=re.DOTALL), r"<CODE>\1</CODE>"),
        (re.compile(r"#"), ""),
        (re.compile(r"^\s*(?:[-*+]|\d+\.)"), ""),
        (re.compile(r"\r\n|\r"), "\n"),
        (re.compile(r"[\n]{3,}"), "\n\n"),
        (re.compile(r"[ \t]{2,}"), " "),
        (re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]"), "")
    ]

    for pattern, replacement in patterns:
        text = pattern.sub(replacement, text)

    return text

# ---- Commit Message Parsing ----

def split_commit_message(msg: Optional[str]) -> Dict[str, Any]:
    """Parse a commit message into Conventional Commit components.

    Why this matters for MSR:
    - Conventional Commits provide semantic meaning (feat, fix, etc.)
    - Enables automated analysis of development practices
    - Breaking changes can be systematically identified

    Conventional Commits format: <type>[optional scope][!]: <subject>
    Examples:
    - "feat(parser): add array support" → type=feat, scope=parser
    - "fix: correct typo" → type=fix, scope=None
    - "feat!: breaking API change" → type=feat, breaking=True

    Parameters:
    - msg: raw commit message (subject + optional body). None treated as empty.

    Returns:
    - dict with keys: subject, body, type, scope, breaking
      - subject: first line (or CC description if CC format)
      - body: everything after first line, stripped
      - type: CC type lowercase (e.g., 'feat', 'fix') or None
      - scope: CC scope if present, or None
      - breaking: True if '!' indicates breaking change

    Examples:
    >>> split_commit_message("fix(auth): resolve login bug")
    {'subject': 'resolve login bug', 'body': '', 'type': 'fix', 'scope': 'auth', 'breaking': False}

    >>> split_commit_message("Update readme\\n\\nMore details here")
    {'subject': 'Update readme', 'body': 'More details here', 'type': None, 'scope': None, 'breaking': False}

    >>> split_commit_message(None)
    {'subject': '', 'body': '', 'type': None, 'scope': None, 'breaking': False}

    Implementation hints:
    - First normalize newlines and split into subject (line 1) and body
    - Use a regex to match CC pattern: type(scope)!: subject
    - Remember to lowercase the type in output
    """
    result = {
        "subject": "",
        "body": "",
        "type": None,
        "scope": None,
        "breaking": False
    }

    if not msg:
        return result
    
    clean_msg = msg.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not clean_msg:
        return result
    
    parts = clean_msg.split("\n", 1)
    subject_raw = parts[0]
    body_raw = parts[1].strip() if len(parts) > 1 else ""
    result["subject"] = subject_raw
    result["body"] = normalize_text(body_raw)

    PATTERN = re.compile(
        r"^(?P<type>\w+)(?:\((?P<scope>[^)]+)\))?(?P<breaking>!)?:\s+(?P<subject>.*)$"
    )

    match = PATTERN.match(subject_raw)
    if match:
        groups = match.groupdict()
        result["type"] = groups["type"].lower()
        result["scope"] = groups["scope"]
        result["breaking"] = bool(groups["breaking"])
        result["subject"] = groups["subject"]
    return result




# ---------------------------------------------------------------------------
# Database helpers - Modify if you need to, but most likely you do not.
# ---------------------------------------------------------------------------

def ensure_columns():
    """
    Create normalized columns on database tables if they don't exist.
    Idempotent - safe to run multiple times.
    """
    if db_utils is None:
        return
    stmts = [
        "ALTER TABLE issues ADD COLUMN IF NOT EXISTS title_clean TEXT;",
        "ALTER TABLE issues ADD COLUMN IF NOT EXISTS author_norm TEXT;",
        "ALTER TABLE issues ADD COLUMN IF NOT EXISTS is_bot BOOLEAN DEFAULT FALSE;",

        "ALTER TABLE pull_requests ADD COLUMN IF NOT EXISTS title_clean TEXT;",
        "ALTER TABLE pull_requests ADD COLUMN IF NOT EXISTS author_norm TEXT;",
        "ALTER TABLE pull_requests ADD COLUMN IF NOT EXISTS is_bot BOOLEAN DEFAULT FALSE;",

        "ALTER TABLE commits ADD COLUMN IF NOT EXISTS subject TEXT;",
        "ALTER TABLE commits ADD COLUMN IF NOT EXISTS body TEXT;",
        "ALTER TABLE commits ADD COLUMN IF NOT EXISTS cc_type TEXT;",
        "ALTER TABLE commits ADD COLUMN IF NOT EXISTS cc_scope TEXT;",
        "ALTER TABLE commits ADD COLUMN IF NOT EXISTS cc_breaking BOOLEAN DEFAULT FALSE;",
    ]
    for s in stmts:
        db_utils.exec_commit(s)


def clean_issues_db(limit: Optional[int] = None) -> int:
    """
    Apply normalization to issues table. Returns count of rows processed.
    """
    if db_utils is None:
        return 0
    ensure_columns()
    rows = db_utils.exec_query(
        "SELECT id, title, author FROM issues"
        + (f" LIMIT {int(limit)}" if limit else "")
        + ";"
    )
    count = 0
    for (iid, title, author) in rows:
        title_clean = normalize_text(title or "")
        author_norm, is_bot = canonicalize_user(author)
        db_utils.exec_commit(
            """
            UPDATE issues SET
                title_clean=%(title_clean)s,
                author_norm=%(author_norm)s,
                is_bot=%(is_bot)s
            WHERE id=%(id)s;
            """,
            {
                "title_clean": title_clean,
                "author_norm": author_norm,
                "is_bot": is_bot,
                "id": iid,
            }
        )
        count += 1
    return count


def clean_prs_db(limit: Optional[int] = None) -> int:
    """
    Apply normalization to pull_requests table. Returns count of rows processed.
    """
    if db_utils is None:
        return 0
    ensure_columns()
    rows = db_utils.exec_query(
        "SELECT id, title, author FROM pull_requests"
        + (f" LIMIT {int(limit)}" if limit else "")
        + ";"
    )
    count = 0
    for (pid, title, author) in rows:
        title_clean = normalize_text(title or "")
        author_norm, is_bot = canonicalize_user(author)
        db_utils.exec_commit(
            """
            UPDATE pull_requests SET
                title_clean=%(title_clean)s,
                author_norm=%(author_norm)s,
                is_bot=%(is_bot)s
            WHERE id=%(id)s;
            """,
            {
                "title_clean": title_clean,
                "author_norm": author_norm,
                "is_bot": is_bot,
                "id": pid,
            }
        )
        count += 1
    return count


def clean_commits_db(limit: Optional[int] = None) -> int:
    """
    Apply commit message parsing to commits table. Returns count of rows processed.
    """
    if db_utils is None:
        return 0
    ensure_columns()
    rows = db_utils.exec_query(
        "SELECT id, message FROM commits"
        + (f" LIMIT {int(limit)}" if limit else "")
        + ";"
    )
    count = 0
    for (cid, message) in rows:
        parts = split_commit_message(message or "")
        db_utils.exec_commit(
            """
            UPDATE commits SET
                subject=%(subject)s,
                body=%(body)s,
                cc_type=%(cc_type)s,
                cc_scope=%(cc_scope)s,
                cc_breaking=%(cc_breaking)s
            WHERE id=%(id)s;
            """,
            {
                "subject": parts["subject"],
                "body": parts["body"],
                "cc_type": parts["type"],
                "cc_scope": parts["scope"],
                "cc_breaking": parts["breaking"],
                "id": cid,
            }
        )
        count += 1
    return count