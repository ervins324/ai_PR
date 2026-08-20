import logging
import asyncio
from typing import Optional
from serpzilla_poster.serpzilla.client import SerpzillaClient

logger = logging.getLogger(__name__)


def inject_image_after_first_paragraph(html_content: str, image_url: str, alt_text: str = "SEO Guest Post Image") -> str:
    """Inject an <img> tag directly after the first closing paragraph </p> tag."""
    img_tag = f'\n<p class="article-media"><img src="{image_url}" alt="{alt_text}" style="max-width:100%;height:auto;" /></p>'
    if "</p>" in html_content:
        return html_content.replace("</p>", f"</p>{img_tag}", 1)
    return f"{img_tag}\n{html_content}"


async def upload_media(client: SerpzillaClient, project_id: int, image_bytes: bytes, filename: str = "image.jpg") -> str:
    """Upload media file to Serpzilla for a given project.

    Calls POST /rest/Content/articleMediaContent/projectId/{project_id}
    Returns Serpzilla's hosted media URL or content ID.
    """
    path = f"/rest/Content/articleMediaContent/projectId/{project_id}"
    files = {
        "file": (filename, image_bytes, "image/jpeg")
    }

    logger.info(f"Uploading media ({len(image_bytes)} bytes) to {path}")
    res = await asyncio.to_thread(client.post, path, files=files)
    
    # Parse returned media URL or ID from response structure
    media_url = res.get("url") or res.get("mediaUrl") or res.get("contentId") or res.get("id")
    if not media_url:
        logger.warning(f"Could not parse explicit media URL from upload response: {res}. Using response string fallback.")
        media_url = str(res)

    logger.info(f"Media uploaded successfully: {media_url}")
    return str(media_url)


async def upload_article(
    client: SerpzillaClient,
    project_id: int,
    title: str,
    html_content: str,
    media_url: Optional[str] = None
) -> int:
    """Upload article HTML content to Serpzilla for a given project.

    Injects hosted media URL if provided, then calls POST /rest/Content/add/article/projectId/{project_id}
    Returns the created articleId (integer).
    """
    path = f"/rest/Content/add/article/projectId/{project_id}"

    # Inject hosted image tag after first paragraph if media_url exists
    final_html = html_content
    if media_url:
        final_html = inject_image_after_first_paragraph(html_content, media_url, alt_text=title)

    payload = {
        "title": title,
        "content": final_html,
        "html": final_html,
        "text": final_html,
    }

    logger.info(f"Uploading article '{title}' to {path}")
    res = await asyncio.to_thread(client.post, path, json=payload)

    # Extract created articleId from response JSON
    article_id = res.get("articleId") or res.get("id") or res.get("article_id")
    if article_id is None:
        raise ValueError(f"Serpzilla API response did not contain an articleId: {res}")

    logger.info(f"Article uploaded successfully with articleId={article_id}")
    return int(article_id)
