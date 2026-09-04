"""Indeed platform support."""

from config import app_config

# config/app_config.py belongs to the user and is not shipped, so a config
# written before these settings existed must not break the import
DEFAULT_INDEED_DOMAIN = "www.indeed.com"


def indeed_domain() -> str:
    """The configured Indeed country domain (e.g. ch.indeed.com)"""
    domain = getattr(app_config, "INDEED_DOMAIN", None) or DEFAULT_INDEED_DOMAIN
    return domain.strip().strip("/")


def indeed_base_url() -> str:
    """Base URL of the configured Indeed domain (e.g. https://ch.indeed.com)"""
    return f"https://{indeed_domain()}"


def indeed_search_radius() -> int | None:
    """Search radius to apply around each location, or None for Indeed's default"""
    radius = getattr(app_config, "INDEED_SEARCH_RADIUS", None)
    return int(radius) if radius is not None else None
