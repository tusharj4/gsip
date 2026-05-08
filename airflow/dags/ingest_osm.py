"""Airflow DAG — Daily OSM Data Sync for GSIP.

Runs every day at 02:00 IST (20:30 UTC previous day).
Idempotent: all inserts use ON CONFLICT DO NOTHING.

Parameters (can be set via Airflow UI → Trigger DAG w/ config):
  place:    OSM place name (default: "India")
  datasets: comma-separated keys (default: "roads,railways,hospitals,schools,forests,water")

Each dataset is a separate task so failures are isolated.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from datetime import datetime, timedelta, timezone

from airflow import DAG
from airflow.operators.python import PythonOperator

logger = logging.getLogger(__name__)

IST_OFFSET = timedelta(hours=5, minutes=30)

default_args = {
    "owner": "gsip",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=15),
}

DATASETS = ["roads", "railways", "hospitals", "schools", "forests", "water", "anganwadis"]


def _run_ingest(place: str, dataset: str, **context: object) -> None:
    """Run a single dataset ingestion via subprocess to isolate imports."""
    # Airflow runs as a different user/env than the FastAPI backend container.
    # We invoke the loader as a module so it picks up the backend's PYTHONPATH.
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.tasks.ingest_osm",
            "--place",
            place,
            "--tags",
            dataset,
        ],
        capture_output=True,
        text=True,
        cwd="/opt/airflow/gsip_backend",
    )
    if result.returncode != 0:
        logger.error("ingest_osm failed for %s/%s:\n%s", place, dataset, result.stderr)
        raise RuntimeError(f"ingest_osm exited {result.returncode}")
    logger.info(result.stdout)


def _make_ingest_task(dag: DAG, dataset: str, place: str) -> PythonOperator:
    return PythonOperator(
        task_id=f"ingest_{dataset}",
        python_callable=_run_ingest,
        op_kwargs={"place": place, "dataset": dataset},
        dag=dag,
    )


with DAG(
    dag_id="gsip_ingest_osm",
    description="Daily OSM data sync for all GSIP infrastructure and regulatory layers",
    default_args=default_args,
    schedule="30 20 * * *",  # 02:00 IST = 20:30 UTC
    start_date=datetime(2026, 5, 8, tzinfo=timezone.utc),
    catchup=False,
    max_active_runs=1,
    tags=["gsip", "ingestion", "osm"],
    params={
        "place": "India",
        "datasets": ",".join(DATASETS),
    },
) as dag:
    dag.doc_md = """
    ## GSIP OSM Daily Sync

    Downloads fresh OSM data for all configured datasets and upserts into PostGIS.

    **Parameters** (set at trigger time):
    - `place`: OSM place name, e.g. `"Gujarat, India"` or `"India"`
    - `datasets`: comma-separated keys from `{roads, railways, hospitals, schools, forests, water, anganwadis}`

    **Idempotent**: safe to re-run. Uses `ON CONFLICT DO NOTHING`.
    """

    place = "{{ params.place }}"

    tasks = [_make_ingest_task(dag, ds, place) for ds in DATASETS]

    # Run all dataset tasks in parallel (they're independent)
    # If one fails, others continue (Airflow default behaviour with retries)
