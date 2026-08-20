import logging
import asyncio
from typing import Any, Dict
from serpzilla_poster.serpzilla.client import SerpzillaClient

logger = logging.getLogger(__name__)


async def create_guest_post_placement(
    client: SerpzillaClient,
    project_id: int,
    site_id: int,
    article_id: int
) -> Dict[str, Any]:
    """Buy/create guest post permanent placement on Serpzilla.

    Calls POST /rest/Placement/permanent/create/projectId/{project_id}
    Returns placement response object.
    """
    path = f"/rest/Placement/permanent/create/projectId/{project_id}"
    payload = {
        "siteId": site_id,
        "articleId": article_id,
    }

    logger.info(f"Creating guest post placement: project_id={project_id}, site_id={site_id}, article_id={article_id}")
    res = await asyncio.to_thread(client.post, path, json=payload)
    logger.info(f"Placement created successfully: {res}")
    return res
