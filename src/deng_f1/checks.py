"""Data checks shared by every stage, in one report format.

A failed `error` check blocks the stage from publishing its output; a `warn` check is only
reported. Each stage runs its checks on the data *before* writing it (write → audit → publish).
"""

from typing import NamedTuple


class Check(NamedTuple):
    name: str
    failures: int
    detail: str = ""
    severity: str = "error"  # or "warn"


def sql_check(spark, name: str, query: str, severity: str = "error") -> Check:
    """`query` returns one row: (number of failures, detail text)."""
    failures, detail = spark.sql(query).first()
    return Check(name, int(failures or 0), str(detail or ""), severity)


def duplicates(spark, view: str, key: str) -> Check:
    """One row per `key` (Delta does not enforce primary keys)."""
    return sql_check(
        spark,
        f"{view}: one row per ({key})",
        f"""
        SELECT count(*), concat_ws('; ', slice(collect_list(k), 1, 5))
        FROM (
            SELECT concat_ws('/', {key}) AS k FROM {view}
            GROUP BY {key} HAVING count(*) > 1
        )
        """,
    )


def report(context: str, checks: list[Check]) -> int:
    """Print one line per check; returns the number of failed error checks."""
    errors = 0
    for check in checks:
        if not check.failures:
            status = "PASS"
        elif check.severity == "error":
            status = "FAIL"
            errors += 1
        else:
            status = "WARN"
        detail = f"  ({check.failures}: {check.detail})" if check.failures else ""
        print(f"{status}  {context}: {check.name}{detail}")
    return errors
