from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse


router = APIRouter()
template_path = Path(__file__).resolve().parent.parent / "templates" / "contextual_similarity.html"


@router.get("/analise-similaridade-contextual", response_class=HTMLResponse)
async def contextual_similarity_page():
    return template_path.read_text(encoding="utf-8")
