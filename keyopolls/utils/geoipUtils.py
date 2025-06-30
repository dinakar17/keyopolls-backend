import logging

from django.contrib.gis.geoip2 import GeoIP2
from django.core.cache import cache

logger = logging.getLogger(__name__)


def get_country_from_ip(ip_address, use_cache=True):
    """
    Get country code from IP address with caching support.

    Args:
        ip_address (str): IP address to lookup
        use_cache (bool): Whether to use cache for lookups

    Returns:
        str: Two-letter country code or 'XX' if unknown
    """
    if not ip_address:
        return "XX"

    # Skip private/local IP addresses
    private_ranges = ["127.0.0.1", "::1", "0.0.0.0", "localhost"]

    if ip_address in private_ranges or ip_address.startswith(
        (
            "192.168.",
            "10.",
            "172.16.",
            "172.17.",
            "172.18.",
            "172.19.",
            "172.20.",
            "172.21.",
            "172.22.",
            "172.23.",
            "172.24.",
            "172.25.",
            "172.26.",
            "172.27.",
            "172.28.",
            "172.29.",
            "172.30.",
            "172.31.",
        )
    ):
        return "XX"

    # Check cache first
    cache_key = f"geoip_country_{ip_address}"
    if use_cache:
        cached_result = cache.get(cache_key)
        if cached_result:
            return cached_result

    try:
        g = GeoIP2()
        country_info = g.country(ip_address)
        country_code = country_info.get("country_code", "XX").upper()

        # Cache the result for 24 hours
        if use_cache:
            cache.set(cache_key, country_code, 86400)  # 24 hours

        return country_code

    except Exception as e:
        logger.warning(f"GeoIP lookup failed for IP {ip_address}: {str(e)}")

        # Cache negative results for shorter time
        if use_cache:
            cache.set(cache_key, "XX", 3600)  # 1 hour

        return "XX"
