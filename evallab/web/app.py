"""
Monitoring dashboard: a small JSON API over the SQLite analytics plus a single-page frontend
(vanilla JS + Chart.js) in static/.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .. import analytics
from ..storage import Store

STATIC = Path(__file__).resolve().parent / "static"


def create_app(db_path: Path | str) -> FastAPI:
    store = Store(db_path)
    app = FastAPI(title="Agent Eval Lab", version="1.0.0",
                  description="Simulation-based evaluation and monitoring for conversational AI agents.")

    @app.get("/api/runs")
    def runs() -> list[dict]:
        with store.connect() as conn:
            return analytics.list_runs(conn)

    @app.get("/api/runs/{run_id}")
    def run(run_id: str) -> dict:
        with store.connect() as conn:
            summary = analytics.run_summary(conn, run_id)
        if summary is None:
            raise HTTPException(404, f"Run {run_id!r} not found")
        return summary

    @app.get("/api/runs/{run_id}/gtm")
    def gtm(run_id: str) -> dict:
        if not store.run_exists(run_id):
            raise HTTPException(404, f"Run {run_id!r} not found")
        with store.connect() as conn:
            return analytics.gtm_summary(conn, run_id)

    @app.get("/api/results/{result_id}")
    def result(result_id: int) -> dict:
        detail = store.get_result_detail(result_id)
        if detail is None:
            raise HTTPException(404, f"Result {result_id} not found")
        return detail

    @app.get("/api/compare")
    def compare(a: str = Query(..., description="baseline run id"), b: str = Query(..., description="candidate run id")) -> dict:
        with store.connect() as conn:
            try:
                return analytics.compare_runs(conn, a, b)
            except KeyError as e:
                raise HTTPException(404, e.args[0]) from e

    @app.get("/api/sql")
    def sql() -> dict[str, str]:
        """The SQL behind every dashboard card."""
        return {name: q.strip() for name, q in analytics.QUERIES.items()}

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
