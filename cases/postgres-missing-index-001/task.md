# OpsBench Task: Slow Order History Query

The order history workload for a PostgreSQL-backed service is slower than expected. Your goal is to diagnose and repair the environment so the final verifier passes.

You may change the database, service files, configuration, or scripts inside this case environment. The benchmark will judge the final behavior, not a specific patch.

## Useful Context

- Database service: `db`
- Database name: `opsbench`
- Database user: `opsbench`
- Database password: `opsbench`
- Docker Compose is managed by the runner with `OPSBENCH_COMPOSE_PROJECT`.
- You can inspect PostgreSQL with:

```bash
docker compose -p "$OPSBENCH_COMPOSE_PROJECT" -f docker-compose.yaml exec -T db \
  psql -U opsbench -d opsbench
```

## Success Criteria

The verifier checks that the database remains healthy, the order-history query returns correct data, and the measured PostgreSQL execution time for the workload is below the benchmark thresholds.
