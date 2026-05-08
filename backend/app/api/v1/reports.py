"""PDF pre-alignment report generation endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db

router = APIRouter()


@router.post("/{project_id}/generate")
async def generate_report(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Generate a PDF pre-alignment report for a project.

    Includes: project metadata, corridor map thumbnail, conflict summary table,
    gap analysis results, recommended alternatives, and regulatory clearances required.
    Uses WeasyPrint (free, open-source) + staticmap for embedded maps.
    """
    from app.models.project import Project
    from app.services.report_generator import ReportGenerator

    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    generator = ReportGenerator(db)
    pdf_bytes = await generator.generate(project_id)

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="gsip-report-{project_id}.pdf"',
            "Content-Length": str(len(pdf_bytes)),
        },
    )


@router.get("/{project_id}/status")
async def report_status(project_id: uuid.UUID) -> dict[str, str]:
    """Check whether a cached report exists for this project."""
    # Phase 5: check MinIO for cached PDF
    return {"status": "not_generated", "project_id": str(project_id)}
