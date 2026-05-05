import os
import tempfile
import pytest
from git import Repo
from src import db_utils

@pytest.fixture(scope="function", autouse=True)
def ensure_schema():
    # Ensure the commits table exists before any tests run
    db_utils.exec_sql_file('data/schema.sql')

@pytest.fixture
def temp_git_repo():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Repo.init(tmp)
        try:
            with repo.config_writer() as cw:
                cw.set_value('user', 'name', 'STRATA Student')
                cw.set_value('user', 'email', 'student@example.com')

            fpath = os.path.join(tmp, 'hello.txt')
            with open(fpath, 'w') as f:
                f.write('hello strata')
            repo.index.add([fpath])
            repo.index.commit('initial commit')

            yield tmp
        finally:
            # Make sure GitPython releases all file handles
            repo.close()

@pytest.fixture
def two_commit_seed_repo():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Repo.init(tmp)
        try:
            with repo.config_writer() as cw:
                cw.set_value('user', 'name', 'STRATA Student')
                cw.set_value('user', 'email', 'student@example.com')

            fpath = os.path.join(tmp, 'hello.txt')
            with open(fpath, 'w') as f:
                f.write('hello strata')
            repo.index.add([fpath])
            repo.index.commit('initial commit')

            with open(fpath, 'a') as  f:
                f.write('goodbye strata')
            repo.index.add([fpath])
            repo.index.commit('second commit')

            yield tmp
        finally:
            repo.close()