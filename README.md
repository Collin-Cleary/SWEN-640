# Research
## See Final Section for instructions




# STRATA — DC0: Repository & Database Setup

**STRATA (Software daTa Repository Analysis & Testing Architecture)**

Welcome to **DC0**, the very first "layer" of STRATA.  
In this assignment, you will set up your research pipeline foundation: repository posture, database connectivity, and automated testing in CI/CD.

This mirrors the setup assignment in SWEN-610 but adapted for **research methods**.

---

## Objectives

By the end of DC0, you will have:

- Initialized a structured project repository with required directories.  
- Connected to a PostgreSQL database using provided utilities.  
- Inserted and retrieve records from the database.  
- Used GitPython to mine commit metadata.  
- Run tests automatically in GitLab CI with **pytest**.

---

## Repository Structure

Your repo must follow this structure:

```
src/        # implementation code (db_utils.py, git_miner.py)
test/       # pytest tests + fixtures
data/       # SQL schema and future data
config/     # credentials (gitlab-credentials.yml -> copied to db.yml in CI)
requirements.txt
.gitlab-ci.yml
README.md
```

We provide you with:

- A `db_utils.py` for connecting to PostgreSQL and executing SQL.  
- A `git_miner.py` that uses GitPython to read the HEAD commit and insert into the DB.  
- A `schema.sql` file that defines a simple `commits` table.  
- Example pytest tests (`test_db_utils.py`, `test_git_miner.py`) and fixtures (`conftest.py`).  
- A GitLab CI file that runs PostgreSQL as a service, installs dependencies, and executes tests.

---

## Setup Instructions

0. **Create your GitLab repository** and **install postgresql 17 or 18**

* Now let's go and create our repository on GitLab. GitLab is a web application that allows you to have a remote Git repository, much like GitHub. RIT has its own installation of GitLab hosted on our GCCIS servers that we will be using for this course. Go to https://git.gccis.rit.edu/. Keep this link—you will NEED to use it to log in to GitLab. Do not google gitlab and try to access from there; it will not work.

* Sign into GitLab using your RIT (not SE) username and password.

* Create a new project and name it **swen-640**. Make sure the repository is private. Make sure the project name is **swen-640** exactly: same spelling, same capitalization, using a dash.

* Give Reporter permissions to your instructor and course assistant(s). You may need their usernames — be sure to ask if they have not provided them. To do this, open your project page; an easy way to ensure you have the right page open is to edit this link with your username: https://git.gccis.rit.edu/(YOUR_USERNAME_HERE)/swen-640. Then go to Manage -> Members on the left side of the project page and add ALL of your TAs and Instructor as members with the **Reporter** role.

* Make sure you completed the previous step (adding members with Reporter permission). If you are confused, ask your instructor or TAs for help.

* You should also set up [SSH keys](https://docs.gitlab.com/user/ssh/) if you have not done so in the past

* [Install postgresql 17 or 18](https://www.postgresql.org/download/)

* Using the PostgreSQL admin console (pgAdmin), create a user called swen640 with a password of your choosing. 

* Make sure you remember that password, because we’re about to put it in a file in a moment. Note: be sure to check the box for “User Can Login” on the Privileges tab. SWEN lab machines: this has been done for you. The password is salutecaptionearthyfight

* Still in pgAdmin, create a database also called swen640 and make the owner of it the user swen640.

1. **Clone your repo**

```shell
git clone <your-gitlab-repo-url>
cd <your-repo>
```

2. **Add provided scaffold**.  
   - [Download this file](/code/strata_starter.zip)
   - Copy the contents into the root of your repo. To do this, open the copyme directory and copy everything out of it (except the copyme directory) into the root of your repo.
   - Commit and push.

   

3. **Database Credentials.**  
     
   - In CI, `config/gitlab-credentials.yml` is copied to `config/db.yml` automatically.  
   - For local dev, create a `config/db.yml` with keys matching your own Postgres instance:

```
database: swen344
user: swen344
password: whowatchesthewatchmen
host: localhost
port: 5432
```

**GitHub Personal Access Token (PAT)**

Your workflow needs access to GitHub (for cloning private repositories and calling the GitHub API, etc), create a fine-grained personal access token following the official [GitHub guide](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens#creating-a-fine-grained-personal-access-token) 

After creating the token, set it in your environment as `GITHUB_TOKEN` so tools and CI can read it. For local shells you can run:

```shell
export GITHUB_TOKEN=<your-token-here>
```


4. **Install dependencies locally.**

```shell
pip install -r requirements.txt
```

5. **Initialize database schema.**  
   Use the helper in `db_utils.py`:

```py
python -c "from src import db_utils; db_utils.exec_sql_file('data/schema.sql')"

```

6. **Run pytest locally.**

```shell
pytest -q
```

   You should see all tests pass (including the Git miner test that creates a temporary repo and commits).

7. **Try it out on a real repository**
```shell
python main.py <user/repository_name>
```

   **Note** that you need to seed the database before you run on it on a real repo (per step #5). You could resolve this by modifying the code to run your data/schema.sql before it attempts to store anything on the db.

8. **Push to GitLab.**  
   On push, GitLab CI will:  
     
   - Spin up a Postgres service.  
   - Install requirements (psycopg2, PyYAML, GitPython, pytest).  
   - Run the test suite.  
   - Confirm Git → DB pipeline works.

---

## Deliverables

1. A correctly structured repo with all scaffold files.
2. Passing GitLab CI pipeline (all pytest tests green).
3. Tag your submission as DC0

---

## Tips

- If you see `Bad git executable` in CI, ensure your `.gitlab-ci.yml` includes the `apt-get install git` step (already provided).  
- On Windows, GitPython can hold file handles; our scaffold closes repos to avoid PermissionErrors.  
- Keep this structure intact-- future assignments (DC1, DI1, etc.) will build directly on top of it.

---

## Grading

You will be graded on:

- **Proper** repo structure (all required files present).  
- **CI pipeline** runs successfully.  
- **Tests** all pass.  
- **Database schema** is set up and accessible.
- Submission is **tagged** correctly

## DC1 additional tests

I didn't go for anything crazy for the two tests I needed to come up with.

my tests were test_change_in_count_after_new_commit and test_root_commit_as_A_in_commit_files

test_change_in_count_after_new_commit makes sure that changes to an existing repo show up after the mine_history is run a second time. Enforcing Idempotency would feel a little silly if changes weren't even possible when upserting, so I figure, why not. It reuses some logic given in conftest.py

test_root_commit_as_A_in_commit_files makes sure the fallback logic in the looping logic chain is actually reached so the root node detected as an orphan node has files showing up as new. It would be a shame to have the logic not work, especially since every repo has a root node, plus some null value would likely cause logic problems down the road. 

## DC2 additional tests

added tests were "test_upsert_updates_state_correctly" and "test_ci_jobs_null_handling"

the first test was meant to check the on conflict do update clause in the sql to make sure that the required changes were compatible with the idempotency which was already tested for

the second test is meant to make sure the ci_jobs logic properly handles the null or None values that we were trying to prepare it for

## DC2 how to run new methods

to run my main method I use something like the following

python main.py octocat/Spoon-Knife --issues --ci --ci-jobs --max-commits 10

--issues flag makes the main method fetch the issues from the specified repository

--prs fetches pull requests

--ci fetches workflow runs

--ci-jobs requires --ci and collects specific jobs from each pipeline found

## DI1 how to use new arguments/flags

the new flags are as follows:

--clean-issues: After mining the issues, the titles and author names will be normalized

--clean-commits: After mining the git history this will parse the commit messages into subject, body, type, scope, and breaking in accordance with conventional commits

If you wanted to use it in addition to the command provided above, it would look like this:

python main.py octocat/Spoon-Knife --issues --ci --ci-jobs --max-commits 10 --clean-issues --clean-commits

## DI2 how to use sampling flags

Used to extract subsets of data from the database for analysis. samples appear in the "samples" folder at the root level

Select which data types to sample:

    --sample-issues

    --sample-commits

    --sample-prs

    --sample-workflows (CI Pipelines)

    --sample-jobs (CI Jobs)

Control how the sample is selected:

    --sample-n <int>: Exact number of items to select (e.g., 50).

    --sample-frac <float>: Fraction of the population (e.g., 0.1 for 10%).

    --sample-step <int>: Step size for Systematic Sampling (e.g., every 5th item).

    --sample-seed <int>: Random seed for reproducibility.

    --sample-key <column>: Column to use for Stratified Sampling (e.g., author, state).

(unfortunately, you can't use multiple sampling methods in the same call)

Sampling Strategies

    Simple Random: Provide n or frac.

    Systematic: Provide step.

    Stratified: Provide key AND (n or frac).

    Auto-Calculation: Provide no params. The system calculates n based on a 95% confidence level / 5% margin of error.

here is an example call you can use to test:
python main.py octocat/Spoon-Knife --issues --prs --ci --ci-jobs --clean-issues --clean-prs --clean-commits --sample-issues --sample-commits --sample-prs --sample-workflows --sample-jobs --sample-n 50 --sample-seed 42


## DA1 how to use the srcml code

on the run where you want to use srcml to parse through a repo, you must mine that repo.

this will produce a csv file which can be found in the output folder. the csv will have one line for each file detailing this set of characteristics:
file_path,n_identifiers,avg_identifier_length,avg_tokens_per_identifier,vocab_size,vocab_diversity,pct_snake_case,pct_camel_case,pct_pascal_case

here is an example command to run the new code on a public repository containing java code:

python main.py google/gson --max-commits 10 --no-record-run --dump-identifiers

## DA2 commands:

python main.py junit-team/junit4 --mine-code-artifacts --depth 200 --file-limit 100 --clean-commits
python main.py analyze --output-dir output/ --clusters 5

## M1 commands:

python main.py predict --output-dir output/ --clusters 5
python main.py predict --model-type random_forest --max-depth 5


## research notes:

   before performing the following workflow, set up a python virtual environment and set the following variable
   $env:GITHUB_TOKEN="<your github personal access token here>"
   mining all commits takes roughly 20 minutes for Junit4 and around an hour for Flask

   process
   python main.py junit-team/junit4 --issues --max-commits 10
   python main.py junit-team/junit4
   python main.py junit-team/junit4 --clean-issues --max-commits 10
   python main.py junit-team/junit4 --sample-issues --sample-key labels --sample-seed 42 --max-commits 10
   python main.py research
