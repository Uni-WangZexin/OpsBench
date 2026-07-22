# OpsBench Task: Slow Order History Query

The order history workload for a PostgreSQL-backed service is slower than expected. Your goal is to diagnose and repair the environment so the final verifier passes.

Diagnose the live database and apply the smallest database repair needed. The benchmark will judge the final service behavior, not a specific SQL statement.

## Useful Context

- Database service: `db`
- Database name: `opsbench`
- Database user: `opsbench`
- Database password: `opsbench`
- The agent runs in an isolated container on the same network as the database.
- Structured database inspection, SQL execution, and EXPLAIN tools are
  available. The `psql` client remains available through the audited shell
  fallback:

```bash
psql -h db -U opsbench -d opsbench
```

## Success Criteria

The verifier checks that the database remains healthy, the order-history query returns correct data, and the measured PostgreSQL execution time for the workload is below the benchmark thresholds.
