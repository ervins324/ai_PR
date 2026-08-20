import logging
from contextlib import asynccontextmanager
from typing import List, Optional
from pathlib import Path

from fastapi import FastAPI, Form, BackgroundTasks, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession

from serpzilla_poster.config import get_settings
from serpzilla_poster.database import init_db, get_session, Task, TaskStatus, async_session_maker
from serpzilla_poster.ai.generator import generate_article
from serpzilla_poster.ai.image_scraper import scrape_image_for_article
from serpzilla_poster.serpzilla.client import SerpzillaClient
from serpzilla_poster.serpzilla.content import upload_media, upload_article
from serpzilla_poster.serpzilla.placement import create_guest_post_placement

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("serpzilla_poster")

templates_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing database tables...")
    await init_db()
    yield
    logger.info("Shutting down Serpzilla poster app.")


app = FastAPI(
    title="Serpzilla SEO Guest Post Automation",
    description="Automates SEO article generation (Gemini) & placement publishing (Serpzilla OAS 3.0 REST API)",
    version="1.0.0",
    lifespan=lifespan,
)


async def execute_guest_post_pipeline(task_id: int):
    """Background task processing the 3-step SEO guest post execution pipeline."""
    logger.info(f"Starting execution pipeline for Task #{task_id}")
    async with async_session_maker() as session:
        statement = select(Task).where(Task.id == task_id)
        result = await session.execute(statement)
        task: Optional[Task] = result.scalar_one_or_none()

        if not task:
            logger.error(f"Task #{task_id} not found in database")
            return

        try:
            # Step 1: Generate article via Gemini AI + Scrape Image
            logger.info(f"[Task #{task_id}] Step 1: Generating article & scraping image...")
            html_content = await generate_article(
                topic=task.topic,
                anchor_text=task.anchor_text,
                target_url=task.target_url,
            )
            image_bytes, filename = await scrape_image_for_article(task.topic)

            task.status = TaskStatus.GENERATED
            session.add(task)
            await session.commit()
            logger.info(f"[Task #{task_id}] Step 1 completed. Article generated.")

            # Step 2: Authenticate & Upload media + article to Serpzilla
            logger.info(f"[Task #{task_id}] Step 2: Uploading media & article to Serpzilla...")
            client = SerpzillaClient()
            await client.authenticate()

            # Upload media file
            hosted_media_url = await upload_media(
                client=client,
                project_id=task.project_id,
                image_bytes=image_bytes,
                filename=filename,
            )

            # Upload article HTML with injected <img> tag
            article_id = await upload_article(
                client=client,
                project_id=task.project_id,
                title=f"Guest Post: {task.topic[:50]}",
                html_content=html_content,
                media_url=hosted_media_url,
            )

            task.article_id = article_id
            task.status = TaskStatus.CONTENT_UPLOADED
            session.add(task)
            await session.commit()
            logger.info(f"[Task #{task_id}] Step 2 completed. Article uploaded with ID={article_id}.")

            # Step 3: Purchase Guest Post Placement on Serpzilla
            logger.info(f"[Task #{task_id}] Step 3: Creating permanent placement...")
            placement_res = await create_guest_post_placement(
                client=client,
                project_id=task.project_id,
                site_id=task.site_id,
                article_id=article_id,
            )

            placement_id = placement_res.get("placementId") or placement_res.get("id")
            if placement_id:
                task.placement_id = int(placement_id)

            task.status = TaskStatus.PLACED
            session.add(task)
            await session.commit()
            logger.info(f"[Task #{task_id}] Step 3 completed. Placement created successfully! Result={placement_res}")

        except Exception as exc:
            logger.exception(f"[Task #{task_id}] Pipeline execution failed: {exc}")
            task.status = TaskStatus.FAILED
            task.error_message = str(exc)
            session.add(task)
            await session.commit()


@app.get("/", response_class=HTMLResponse)
async def get_dashboard(request: Request):
    """Render HTML dashboard with form and live task table."""
    return templates.TemplateResponse(request=request, name="dashboard.html")



@app.post("/api/process-task")
async def process_task(
    background_tasks: BackgroundTasks,
    project_id: int = Form(...),
    site_id: int = Form(...),
    target_url: str = Form(...),
    anchor_text: str = Form(...),
    topic: str = Form(...),
    session: AsyncSession = Depends(get_session)
):
    """Endpoint to submit a new SEO guest post request and trigger async pipeline."""
    task = Task(
        project_id=project_id,
        site_id=site_id,
        target_url=target_url,
        anchor_text=anchor_text,
        topic=topic,
        status=TaskStatus.PENDING,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)

    # Queue execution background task
    background_tasks.add_task(execute_guest_post_pipeline, task.id)

    return JSONResponse(content={
        "status": "queued",
        "task_id": task.id,
        "message": f"Task #{task.id} created and processing in background."
    })


@app.get("/api/tasks")
async def list_tasks(session: AsyncSession = Depends(get_session)):
    """List all created tasks and their current database statuses."""
    statement = select(Task).order_by(Task.id.desc())
    result = await session.execute(statement)
    tasks = result.scalars().all()
    return tasks
