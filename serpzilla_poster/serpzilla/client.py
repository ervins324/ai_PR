import logging
from typing import Any, Dict, Optional
import httpx

from serpzilla_poster.config import get_settings

logger = logging.getLogger(__name__)


class SerpzillaClient:
    """Async HTTP wrapper for the Serpzilla OAS 3.0 REST API."""

    def __init__(self, base_url: Optional[str] = None, login: Optional[str] = None, api_key: Optional[str] = None):
        settings = get_settings()
        self.base_url = (base_url or settings.SERPZILLA_BASE_URL).rstrip("/")
        self.login = login or settings.SERPZILLA_LOGIN
        self.api_key = api_key or settings.SERPZILLA_API_KEY
        self.auth_ticket: Optional[str] = None

    async def authenticate(self) -> str:
        """Authenticate via POST /login using login and API key.

        Obtains and stores the AUTH_TICKET / JWT token.
        """
        url = f"{self.base_url}/login"
        payload = {
            "login": self.login,
            "apiKey": self.api_key
        }
        
        logger.info(f"Authenticating with Serpzilla API at {url} for user '{self.login}'")
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
            
            # Extract ticket or token from response JSON or response headers
            ticket = data.get("ticket") or data.get("AUTH_TICKET") or data.get("token") or data.get("jwt")
            if not ticket and "X-Auth-Ticket" in response.headers:
                ticket = response.headers["X-Auth-Ticket"]

            if not ticket:
                # If the entire response string is the token itself
                if isinstance(data, str):
                    ticket = data
                else:
                    logger.warning(f"Could not automatically locate 'ticket' key in response data: {data}")
                    ticket = str(data)

            self.auth_ticket = ticket
            logger.info("Serpzilla authentication successful")
            return self.auth_ticket

    async def request(
        self,
        method: str,
        path: str,
        json: Optional[Dict[str, Any]] = None,
        data: Optional[Any] = None,
        files: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Send an authenticated HTTP request to Serpzilla REST API."""
        if not self.auth_ticket:
            await self.authenticate()

        url = f"{self.base_url}{path}" if path.startswith("/") else f"{self.base_url}/{path}"
        headers = {
            "Authorization": f"Bearer {self.auth_ticket}",
            "X-Auth-Ticket": self.auth_ticket or "",
        }

        logger.info(f"Serpzilla API request: {method} {url}")
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(
                method=method,
                url=url,
                headers=headers,
                json=json,
                data=data,
                files=files,
                params=params,
            )

            # If 401 Unauthorized, retry authentication once
            if response.status_code == 401:
                logger.info("Auth ticket expired or invalid. Re-authenticating...")
                await self.authenticate()
                headers["Authorization"] = f"Bearer {self.auth_ticket}"
                headers["X-Auth-Ticket"] = self.auth_ticket or ""
                response = await client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=json,
                    data=data,
                    files=files,
                    params=params,
                )

            response.raise_for_status()
            try:
                return response.json()
            except Exception:
                return {"text": response.text}

    async def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return await self.request("GET", path, params=params)

    async def post(self, path: str, json: Optional[Dict[str, Any]] = None, files: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return await self.request("POST", path, json=json, files=files)

    async def patch(self, path: str, json: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return await self.request("PATCH", path, json=json)
