"""Read-only PostgreSQL/MySQL diagnostics via remote CLI tools.
Credentials should be provisioned in the remote user's .pgpass or MySQL option file.
"""
import re
import shlex
from .host_manager import connect_active_host

DB_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,63}$")

def _run(command: str, timeout=30) -> str:
    client = connect_active_host()
    try:
        _, stdout, stderr = client.exec_command(command, timeout=timeout)
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
        code = stdout.channel.recv_exit_status()
        return out if code == 0 else f"Command failed ({code}): {err or out}"
    finally:
        client.close()

def postgres_version() -> str:
    return _run("psql -X -A -t -c 'SELECT version();'")

def postgres_activity() -> str:
    sql = ("SELECT pid, usename, datname, state, wait_event_type, "
           "now()-query_start AS query_age, left(query,160) "
           "FROM pg_stat_activity WHERE pid <> pg_backend_pid() "
           "ORDER BY query_start NULLS LAST LIMIT 50;")
    return _run("psql -X -P pager=off -c " + shlex.quote(sql))

def postgres_database_sizes() -> str:
    sql = "SELECT datname, pg_size_pretty(pg_database_size(datname)) FROM pg_database ORDER BY pg_database_size(datname) DESC;"
    return _run("psql -X -P pager=off -c " + shlex.quote(sql))

def postgres_long_queries(min_seconds: int = 30) -> str:
    if not isinstance(min_seconds, int) or not 1 <= min_seconds <= 86400:
        raise ValueError("min_seconds must be 1..86400.")
    sql = ("SELECT pid, usename, datname, now()-query_start AS duration, "
           "left(query,300) FROM pg_stat_activity "
           "WHERE state='active' AND now()-query_start > interval '" +
           str(min_seconds) + " seconds' ORDER BY query_start;")
    return _run("psql -X -P pager=off -c " + shlex.quote(sql))

def mysql_version() -> str:
    return _run("mysql --batch --skip-column-names -e 'SELECT VERSION();'")

def mysql_processlist() -> str:
    return _run("mysql --table -e 'SHOW FULL PROCESSLIST;'")

def mysql_database_sizes() -> str:
    sql = ("SELECT table_schema, ROUND(SUM(data_length+index_length)/1024/1024,2) AS size_mb "
           "FROM information_schema.tables GROUP BY table_schema ORDER BY size_mb DESC;")
    return _run("mysql --table -e " + shlex.quote(sql))

def mysql_slow_query_settings() -> str:
    return _run("mysql --table -e \"SHOW VARIABLES LIKE 'slow_query_log%'; SHOW VARIABLES LIKE 'long_query_time';\"")

# These tools require psql/mysql client authentication to be configured on the remote account.
# Do not pass database passwords as MCP tool arguments.
