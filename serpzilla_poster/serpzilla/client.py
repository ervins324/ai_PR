import logging
from typing import Any, Dict, Optional
import requests

from serpzilla_poster.config import get_settings

logger = logging.getLogger(__name__)


class SerpzillaAPIError(Exception):
    """Custom exception for Serpzilla API errors."""
    pass


class SerpzillaClient:
    """Python REST client for Serpzilla API using requests.Session.

    Handles dual-authentication flow: AUTH_TICKET cookie and JWT token.
    """

    def __init__(
        self,
        login: Optional[str] = None,
        api_token: Optional[str] = None,
        base_url: str = "https://app.serpzilla.com"
    ) -> None:
        """Initialize Serpzilla client with credentials and session setup."""
        settings = get_settings()
        self.login = login if login is not None else settings.SERPZILLA_LOGIN
        self.api_token = api_token if api_token is not None else settings.SERPZILLA_API_KEY
        self.base_url = (base_url or settings.SERPZILLA_BASE_URL).rstrip("/")
        self.session = requests.Session()
        self.auth_ticket: Optional[str] = None
        self.jwt_token: Optional[str] = None

    def authenticate(self) -> None:
        """Perform the 2-step Serpzilla dual-authentication flow.

        Step 1: POST /login with login and apiToken to extract AUTH_TICKET cookie.
        Step 2: GET /auth with AUTH_TICKET cookie to extract JWT token.
        Step 3: Attach Authorization Bearer and Cookie headers to persistent session.
        """
        logger.info(f"Authenticating with Serpzilla API for user: {self.login}")

        # Step 1: Request login and extract AUTH_TICKET cookie
        login_url = f"{self.base_url}/login"
        login_payload = {
            "login": self.login,
            "apiToken": self.api_token
        }

        try:
            login_resp = self.session.post(login_url, json=login_payload, timeout=15.0)
            if login_resp.status_code in (401, 403):
                logger.error(f"Step 1 auth failed with HTTP {login_resp.status_code}: {login_resp.text}")
                raise SerpzillaAPIError("Invalid credentials or missing AUTH_TICKET cookie.")
            login_resp.raise_for_status()
        except requests.RequestException as exc:
            if isinstance(exc, requests.HTTPError) and exc.response is not None and exc.response.status_code in (401, 403):
                raise SerpzillaAPIError("Invalid credentials or missing AUTH_TICKET cookie.") from exc
            raise SerpzillaAPIError(f"Step 1 authentication failed at {login_url}: {exc}") from exc

        auth_ticket = login_resp.cookies.get("AUTH_TICKET")
        if not auth_ticket:
            try:
                body_data = login_resp.json()
                if isinstance(body_data, dict):
                    auth_ticket = body_data.get("AUTH_TICKET") or body_data.get("ticket") or body_data.get("authTicket")
            except Exception:
                pass

        if not auth_ticket and "Set-Cookie" in login_resp.headers:
            set_cookie_str = login_resp.headers.get("Set-Cookie", "")
            for cookie_part in set_cookie_str.split(";"):
                if "AUTH_TICKET=" in cookie_part:
                    auth_ticket = cookie_part.split("AUTH_TICKET=")[-1].strip()

        if not auth_ticket:
            auth_ticket = login_resp.text.strip()

        if not auth_ticket:
            raise SerpzillaAPIError("Invalid credentials or missing AUTH_TICKET cookie.")

        self.auth_ticket = auth_ticket
        self.session.cookies.set("AUTH_TICKET", self.auth_ticket)
        logger.info("Step 1 complete: AUTH_TICKET cookie obtained successfully.")

        # Step 2: Request auth endpoint passing AUTH_TICKET cookie to extract JWT
        auth_url = f"{self.base_url}/auth"
        auth_headers = {
            "Cookie": f"AUTH_TICKET={self.auth_ticket}"
        }

        try:
            auth_resp = self.session.get(auth_url, headers=auth_headers, timeout=15.0)
            if auth_resp.status_code in (401, 403):
                logger.error(f"Step 2 auth failed with HTTP {auth_resp.status_code}: {auth_resp.text}")
                raise SerpzillaAPIError("Invalid credentials or missing AUTH_TICKET cookie.")
            auth_resp.raise_for_status()
        except requests.RequestException as exc:
            if isinstance(exc, requests.HTTPError) and exc.response is not None and exc.response.status_code in (401, 403):
                raise SerpzillaAPIError("Invalid credentials or missing AUTH_TICKET cookie.") from exc
            raise SerpzillaAPIError(f"Step 2 authentication failed at {auth_url}: {exc}") from exc

        jwt_token = None
        try:
            auth_json = auth_resp.json()
            if isinstance(auth_json, dict):
                jwt_token = (
                    auth_json.get("token")
                    or auth_json.get("jwt")
                    or auth_json.get("accessToken")
                    or auth_json.get("jwtToken")
                )
            elif isinstance(auth_json, str):
                jwt_token = auth_json
        except Exception:
            jwt_token = auth_resp.text.strip()

        if not jwt_token:
            jwt_token = auth_resp.text.strip()

        if not jwt_token:
            raise SerpzillaAPIError("Invalid credentials or missing AUTH_TICKET cookie.")

        self.jwt_token = jwt_token
        logger.info("Step 2 complete: JWT token extracted successfully.")

        # Step 3: Attach persistent headers and cookie to self.session
        self.session.headers.update({
            "Authorization": f"Bearer {self.jwt_token}",
            "Cookie": f"AUTH_TICKET={self.auth_ticket}"
        })
        self.session.cookies.set("AUTH_TICKET", self.auth_ticket)
        logger.info("Step 3 complete: Persistent session headers and cookies configured.")

    def request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        """Execute an authenticated HTTP request using the persistent session.

        Automatically prepends base_url, handles JSON response parsing, and
        raises structured exceptions. Automatically re-authenticates on 401/403.
        """
        if not self.auth_ticket or not self.jwt_token:
            self.authenticate()

        url = f"{self.base_url}{endpoint}" if endpoint.startswith("/") else f"{self.base_url}/{endpoint}"
        logger.info(f"Executing Serpzilla API request: {method.upper()} {url}")

        if "timeout" not in kwargs:
            kwargs["timeout"] = 30.0

        try:
            response = self.session.request(method=method, url=url, **kwargs)
        except requests.RequestException as exc:
            raise SerpzillaAPIError(f"Network error during {method.upper()} {url}: {exc}") from exc

        # Automatic re-authentication on 401 or 403 status codes
        if response.status_code in (401, 403):
            logger.info(f"Received HTTP {response.status_code} response. Attempting automatic re-authentication...")
            try:
                self.authenticate()
                response = self.session.request(method=method, url=url, **kwargs)
            except SerpzillaAPIError:
                raise
            except requests.RequestException as exc:
                raise SerpzillaAPIError(f"Network error after re-authentication during {method.upper()} {url}: {exc}") from exc

            if response.status_code in (401, 403):
                logger.error(f"Request failed with HTTP {response.status_code} after re-authentication. Response: {response.text}")
                raise SerpzillaAPIError("Invalid credentials or missing AUTH_TICKET cookie.")

        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            logger.error(f"Serpzilla API HTTP {response.status_code} at {url}. Body: {response.text}")
            raise SerpzillaAPIError(f"Serpzilla API HTTP {response.status_code} error at {url}: {response.text}") from exc

        try:
            return response.json()
        except Exception:
            return {"text": response.text}

    def get(self, endpoint: str, **kwargs) -> Dict[str, Any]:
        """Shortcut method for HTTP GET requests."""
        return self.request("GET", endpoint, **kwargs)

    def post(self, endpoint: str, **kwargs) -> Dict[str, Any]:
        """Shortcut method for HTTP POST requests."""
        return self.request("POST", endpoint, **kwargs)

    def patch(self, endpoint: str, **kwargs) -> Dict[str, Any]:
        """Shortcut method for HTTP PATCH requests."""
        return self.request("PATCH", endpoint, **kwargs)

    def delete(self, endpoint: str, **kwargs) -> Dict[str, Any]:
        """Shortcut method for HTTP DELETE requests."""
        return self.request("DELETE", endpoint, **kwargs)

    def test_connection(self) -> Dict[str, Any]:
        """Call GET /rest/User/info to confirm credentials and return user details."""
        logger.info("Testing connection to Serpzilla user info endpoint.")
        return self.get("/rest/User/info")

    def get_projects(self) -> Dict[str, Any]:
        """Fetch active user projects using GET /rest/Project/briefList with fallback to GET /rest/Project.

        Logs raw status code and response body if status is non-200 or project list is empty.
        Raises SerpzillaAPIError if 0 projects are found.
        """
        logger.info("Fetching active user projects list.")

        res_data = None
        projects_list = []

        # Primary attempt: /rest/Project/briefList
        try:
            res_data = self.get("/rest/Project/briefList")
            if isinstance(res_data, dict):
                projects_list = res_data.get("projects") or res_data.get("list") or []
            elif isinstance(res_data, list):
                projects_list = res_data
        except SerpzillaAPIError as exc:
            logger.warning(f"GET /rest/Project/briefList failed: {exc}. Trying fallback /rest/Project...")
        except Exception as exc:
            logger.warning(f"Unexpected error calling /rest/Project/briefList: {exc}")

        # Fallback attempt: /rest/Project
        if not projects_list:
            logger.info("Primary project endpoint returned empty or failed. Trying fallback /rest/Project...")
            try:
                fallback_data = self.get("/rest/Project")
                if isinstance(fallback_data, dict):
                    projects_list = fallback_data.get("projects") or fallback_data.get("list") or []
                    if not projects_list and isinstance(fallback_data.get("data"), list):
                        projects_list = fallback_data.get("data")
                    res_data = fallback_data
                elif isinstance(fallback_data, list):
                    projects_list = fallback_data
                    res_data = fallback_data
            except SerpzillaAPIError as exc:
                logger.error(f"Fallback GET /rest/Project failed: {exc}")
                raise

        # Check for empty projects list and raise diagnostic exception
        if not projects_list:
            logger.warning(f"Serpzilla projects response status or body returned 0 projects. Raw response: {res_data}")
            raise SerpzillaAPIError("Authentication succeeded, but 0 active projects found in your Serpzilla account.")

        if isinstance(res_data, dict):
            return res_data
        return {"projects": projects_list}

    def lookup_site_by_domain(self, domain: str) -> Dict[str, Any]:
        """Call GET /rest/Search/siteIdByName?name={domain} to retrieve matching siteId."""
        logger.info(f"Looking up siteId for domain: {domain}")
        return self.get(f"/rest/Search/siteIdByName?name={domain}")

    def search_sites(self, project_id: int) -> Dict[str, Any]:
        """Call POST /rest/SearchPermanent/projectId/{project_id} to fetch candidate guest post sites."""
        logger.info(f"Searching candidate guest post publisher sites for project {project_id}.")
        return self.post(f"/rest/SearchPermanent/projectId/{project_id}", json={})
