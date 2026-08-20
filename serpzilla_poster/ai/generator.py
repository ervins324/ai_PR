import re
import logging
from google import genai
from google.genai import types

from serpzilla_poster.config import get_settings

logger = logging.getLogger(__name__)


async def generate_article(topic: str, anchor_text: str, target_url: str) -> str:
    """Generate an SEO guest post HTML article using Google Gen AI SDK (`gemini-3.5-flash`).

    Weaves `<a href="{target_url}">{anchor_text}</a>` naturally within clean HTML body tags.
    """
    settings = get_settings()
    client = genai.Client(api_key=settings.GEMINI_API_KEY)

    system_instruction = (
        "You are an expert SEO copywriter and guest post author. "
        "Your task is to write high-quality, engaging, informative, and naturally formatted HTML articles. "
        "Strictly return clean HTML body content (using tags like <p>, <h2>, <h3>, <ul>, <li>, <strong>). "
        "Do NOT include markdown backtick code blocks (```html), <html>, <head>, or <body> tags."
    )

    prompt = (
        f"Write a comprehensive SEO article (~600-900 words) on the topic: '{topic}'.\n\n"
        f"Requirements:\n"
        f"1. Structure the article logically using <h2> and <h3> subheadings and <p> paragraphs.\n"
        f"2. You MUST contextually insert the following exact backlink into the flow of one of the main paragraphs: "
        f'<a href="{target_url}">{anchor_text}</a>\n'
        f"3. Ensure the anchor text reads completely naturally within the surrounding sentence context.\n"
        f"4. Do NOT output markdown code fences or full HTML document boilerplate."
    )

    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=0.7,
    )

    logger.info(f"Generating article for topic='{topic}', anchor='{anchor_text}' using model gemini-3.5-flash")
    
    # Use async client interface via .aio
    response = await client.aio.models.generate_content(
        model="gemini-3.5-flash",
        contents=prompt,
        config=config,
    )

    content = response.text or ""

    # Clean markdown fences if Gemini still wrapped the output
    content = re.sub(r"^```(?:html)?\s*", "", content, flags=re.MULTILINE)
    content = re.sub(r"\s*```$", "", content, flags=re.MULTILINE)
    content = content.strip()

    # Ensure backlink exists if Gemini omitted it by accident
    backlink_html = f'<a href="{target_url}">{anchor_text}</a>'
    if backlink_html not in content and target_url not in content:
        logger.warning("Backlink missing in generated content. Appending to content.")
        content += f"\n<p>For more information, visit {backlink_html}.</p>"

    return content
