"""Airflow DAG — GADM Administrative Boundaries Sync.

Runs weekly (Sunday 01:00 IST) since GADM releases are infrequent.
Downloads GADM level 1 (states) and level 2 (districts) shapefiles.
Each level is a separate task.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timedelta, timezone

from airflow import DAG
from airflow.operators.python import PythonOperator

default_args = {
    "owner": "gsip",
    "retries": 1,
    "retry_delay": timedelta(minutes=30),
    "email_on_failure": False,
}


def _run_gadm(level: int, **context: object) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "app.tasks.ingest_gadm", "--level", str(level), "--download"],
        capture_output=True,
        text=True,
        cwd="/opt/airflow/gsip_backend",
    )
    if result.returncode != 0:
        raise RuntimeError(f"ingest_gadm level {level} failed:\n{result.stderr}")


with DAG(
    dag_id="gsip_ingest_gadm",
    description="Weekly GADM administrative boundary sync (states + districts)",
    default_args=default_args,
    schedule="30 19 * * 0",  # Sunday 01:00 IST = Sunday 19:30 UTC
    start_date=datetime(2026, 5, 8, tzinfo=timezone.utc),
    catchup=False,
    max_active_runs=1,
    tags=["gsip", "ingestion", "gadm"],
) as dag:

    states = PythonOperator(
        task_id="ingest_states_level1",
        python_callable=_run_gadm,
        op_kwargs={"level": 1},
    )

    districts = PythonOperator(
        task_id="ingest_districts_level2",
        python_callable=_run_gadm,
        op_kwargs={"level": 2},
    )

    # States must load before districts (districts reference state names)
    states >> districts
