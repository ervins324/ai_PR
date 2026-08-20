from datetime import datetime
from typing import AsyncGenerator, Optional
from enum import Enum

from sqlmodel import Field, SQLModel
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from serpzilla_poster.config import get_settings


class TaskStatus(str, Enum):
    PENDING = "pending"
    GENERATED = "generated"
    CONTENT_UPLOADED = "content_uploaded"
    PLACED = "placed"
    FAILED = "failed"


class Task(SQLModel, table=True):
    __tablename__ = "tasks"

    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(index=True)
    site_id: int = Field(index=True)
    target_url: str
    anchor_text: str
    topic: str
    article_id: Optional[int] = Field(default=None)
    placement_id: Optional[int] = Field(default=None)
    status: TaskStatus = Field(default=TaskStatus.PENDING, index=True)
    error_message: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)


settings = get_settings()
engine = create_async_engine(settings.DATABASE_URL, echo=False, future=True)
async_session_maker = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session
