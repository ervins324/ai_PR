import io
import logging
import asyncio
from typing import Tuple
import httpx
from PIL import Image, ImageDraw

from duckduckgo_search import DDGS

logger = logging.getLogger(__name__)


def _generate_fallback_image(keywords: str) -> bytes:
    """Create a clean 800x450 placeholder JPEG image with keyword text."""
    img = Image.new("RGB", (800, 450), color=(41, 128, 185))
    draw = ImageDraw.Draw(img)
    text = f"Article Image: {keywords[:35]}"
    draw.text((40, 200), text, fill=(255, 255, 255))
    
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG")
    return buffer.getvalue()


def _scrape_ddg_sync(keywords: str) -> list[str]:
    """Synchronous DDGS search run in a thread pool."""
    urls = []
    try:
        with DDGS() as ddgs:
            results = ddgs.images(keywords, max_results=5)
            for res in results:
                if isinstance(res, dict) and res.get("image"):
                    urls.append(res["image"])
    except Exception as e:
        logger.warning(f"DuckDuckGo image search exception: {e}")
    return urls


async def scrape_image_for_article(keywords: str) -> Tuple[bytes, str]:
    """Scrape/fetch an image based on keywords using DDG, Unsplash fallback, or placeholder generation.

    Returns:
        Tuple[bytes, str]: (image_bytes, filename)
    """
    logger.info(f"Fetching image for keywords: '{keywords}'")
    filename = "article_image.jpg"

    # Strategy 1: Try DuckDuckGo Image Search via thread pool
    try:
        urls = await asyncio.to_thread(_scrape_ddg_sync, keywords)
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            for image_url in urls:
                try:
                    resp = await client.get(image_url)
                    if resp.status_code == 200 and resp.content and len(resp.content) > 1000:
                        logger.info(f"Successfully scraped image from DuckDuckGo: {image_url}")
                        return resp.content, filename
                except Exception as inner_e:
                    logger.debug(f"Failed fetching DDG image {image_url}: {inner_e}")
    except Exception as e:
        logger.warning(f"DuckDuckGo image scrape attempt failed: {e}")

    # Strategy 2: Try Unsplash / Lorem Picsum Source API
    try:
        unsplash_url = f"https://picsum.photos/800/600"
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(unsplash_url)
            if resp.status_code == 200 and resp.content:
                logger.info(f"Successfully fetched image from fallback source: {unsplash_url}")
                return resp.content, filename
    except Exception as e:
        logger.warning(f"Fallback image service fetch failed: {e}")

    # Strategy 3: Dynamic Pillow placeholder image (guaranteed success)
    logger.info("Using dynamic Pillow placeholder image generation")
    fallback_bytes = _generate_fallback_image(keywords)
    return fallback_bytes, filename
