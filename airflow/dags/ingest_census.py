"""Airflow DAG — Census 2011 Population Data Sync.

Runs once a month (first Sunday). Census data is static but the join
to GADM features may need refreshing after a GADM update.

Depends on gsip_ingest_gadm completing successfully first.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timedelta, timezone

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.sensors.external_task import ExternalTaskSensor

default_args = {
    "owner": "gsip",
    "retries": 1,
    "retry_delay": timedelta(minutes=30),
    "email_on_failure": False,
}


def _run_census(**context: object) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "app.tasks.ingest_census", "--download"],
        capture_output=True,
        text=True,
        cwd="/opt/airflow/gsip_backend",
    )
    if result.returncode != 0:
        raise RuntimeError(f"ingest_census failed:\n{result.stderr}")


with DAG(
    dag_id="gsip_ingest_census",
    description="Monthly Census 2011 population data join to district boundaries",
    default_args=default_args,
    schedule="0 20 1-7 * 0",  # First Sunday of each month, 01:30 IST
    start_date=datetime(2026, 5, 8, tzinfo=timezone.utc),
    catchup=False,
    max_active_runs=1,
    tags=["gsip", "ingestion", "census"],
) as dag:

    wait_for_gadm = ExternalTaskSensor(
        task_id="wait_for_gadm",
        external_dag_id="gsip_ingest_gadm",
        external_task_id="ingest_districts_level2",
        timeout=3600,
        poke_interval=120,
        mode="reschedule",
    )

    run_census = PythonOperator(
        task_id="ingest_census_2011",
        python_callable=_run_census,
    )

    wait_for_gadm >> run_census
