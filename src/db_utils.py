import psycopg2
import yaml
import os

def connect():
    config = {}
    yml_path = os.path.join(os.path.dirname(__file__), '../config/db.yml')
    with open(yml_path, 'r') as file:
        config = yaml.load(file, Loader=yaml.FullLoader)
    return psycopg2.connect(dbname=config['database'],
                            user=config['user'],
                            password=config['password'],
                            host=config['host'],
                            port=config['port'])

def exec_sql_file(path):
    full_path = os.path.join(os.path.dirname(__file__), f'../{path}')
    conn = connect()
    cur = conn.cursor()
    with open(full_path, 'r') as file:
        cur.execute(file.read())
    conn.commit()
    conn.close()

def exec_get_one(sql, args={}):
    conn = connect()
    cur = conn.cursor()
    cur.execute(sql, args)
    one = cur.fetchone()
    conn.close()
    return one

def exec_get_all(sql, args={}):
    conn = connect()
    cur = conn.cursor()
    cur.execute(sql, args)
    list_of_tuples = cur.fetchall()
    conn.close()
    return list_of_tuples

def exec_commit(sql, args={}):
    conn = connect()
    cur = conn.cursor()
    result = cur.execute(sql, args)
    conn.commit()
    conn.close()
    return result

def exec_commit_get_one(sql, args={}):
    conn = connect()
    cur = conn.cursor()
    cur.execute(sql, args)
    one = cur.fetchone()
    conn.commit()
    conn.close()
    return one


def exec_query(query: str, args={}):
    """
    Routes the query to the correct function based on whether it is 
    fetching data (SELECT) or modifying data (INSERT/UPDATE/DELETE).
    """
    clean_query = query.strip().upper()
    
    if clean_query.startswith("SELECT"):
        return exec_get_all(query, args)
    else:
        return exec_commit(query, args)

def exec_many(sql, args_list):
    """Execute a parameterised statement once per row using executemany().

    Much faster than calling exec_commit() in a loop because it reuses a
    single connection and cursor for the entire batch.

    Parameters:
    - sql: parameterised SQL with %(name)s placeholders
    - args_list: iterable of dicts, one per row
    """
    items = list(args_list)
    if not items:
        return
    conn = connect()
    cur = conn.cursor()
    cur.executemany(sql, items)
    conn.commit()
    conn.close()