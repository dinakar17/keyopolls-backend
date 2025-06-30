import logging
from datetime import timedelta
from typing import List, Optional

from django.contrib.gis.geoip2 import GeoIP2
from django.core.cache import cache
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from keyoconnect.common.models import Impression
from keyoconnect.posts.models import Post
from keyoconnect.profiles.middleware import PublicJWTAuth
from ninja import Router, Schema

logger = logging.getLogger(__name__)


# Response Schemas
class AuthorSchema(Schema):
    handle: str
    display_name: str
    profile_type: str
    profile_photo: Optional[str] = None


class PostDataSchema(Schema):
    content: str
    author: str
    handle: str
    date: str
    views: str
    likes: int
    comments: int
    shares: int
    bookmarks: int
    profile_type: str
    profile_photo: Optional[str] = None


class HourlyViewsSchema(Schema):
    hour: str
    views: int


class CountryViewsSchema(Schema):
    country: str
    flag: str
    percentage: float


class PostInsightsSchema(Schema):
    post: PostDataSchema
    first_48_hours_data: List[HourlyViewsSchema]
    top_countries: List[CountryViewsSchema]
    total_impressions: int
    unique_profiles: int
    anonymous_impressions: int
    public_impressions: int


# Country mapping for flags (you can expand this)
COUNTRY_FLAGS = {
    "US": {"name": "United States", "flag": "🇺🇸"},
    "GB": {"name": "United Kingdom", "flag": "🇬🇧"},
    "CA": {"name": "Canada", "flag": "🇨🇦"},
    "AU": {"name": "Australia", "flag": "🇦🇺"},
    "DE": {"name": "Germany", "flag": "🇩🇪"},
    "FR": {"name": "France", "flag": "🇫🇷"},
    "IN": {"name": "India", "flag": "🇮🇳"},
    "JP": {"name": "Japan", "flag": "🇯🇵"},
    "BR": {"name": "Brazil", "flag": "🇧🇷"},
    "MX": {"name": "Mexico", "flag": "🇲🇽"},
    "IT": {"name": "Italy", "flag": "🇮🇹"},
    "ES": {"name": "Spain", "flag": "🇪🇸"},
    "NL": {"name": "Netherlands", "flag": "🇳🇱"},
    "SE": {"name": "Sweden", "flag": "🇸🇪"},
    "CH": {"name": "Switzerland", "flag": "🇨🇭"},
    "SG": {"name": "Singapore", "flag": "🇸🇬"},
    "KR": {"name": "South Korea", "flag": "🇰🇷"},
    "CN": {"name": "China", "flag": "🇨🇳"},
    "RU": {"name": "Russia", "flag": "🇷🇺"},
    "IR": {"name": "Iran", "flag": "🇮🇷"},
    "IL": {"name": "Israel", "flag": "🇮🇱"},
    "XX": {"name": "Unknown", "flag": "🌍"},  # Fallback for unknown countries
}


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


def format_count(count):
    """Format large numbers with K, M suffixes"""
    if count >= 1000000:
        return f"{count / 1000000:.1f}M"
    elif count >= 1000:
        return f"{count / 1000:.1f}K"
    else:
        return str(count)


def get_time_ago(created_at):
    """Convert datetime to human-readable time ago"""
    now = timezone.now()
    diff = now - created_at

    if diff.days > 0:
        return f"{diff.days}d ago"
    elif diff.seconds >= 3600:
        hours = diff.seconds // 3600
        return f"{hours}h ago"
    elif diff.seconds >= 60:
        minutes = diff.seconds // 60
        return f"{minutes}m ago"
    else:
        return "Just now"


router = Router(tags=["Post Insights"])


@router.get(
    "/posts/{post_id}/insights", response=PostInsightsSchema, auth=PublicJWTAuth()
)
def get_post_insights(request, post_id: int):
    """
    Get comprehensive insights for a specific post including:
    - Post details
    - 48-hour hourly view breakdown
    - Top countries by views (as percentages)
    - Total analytics
    """

    # Get the post
    try:
        post = get_object_or_404(Post, id=post_id, is_deleted=False)
    except Http404:
        raise Http404("Post not found")

    # Check if user has permission to view insights
    # You might want to add authentication/authorization here
    # For now, assuming the user can view insights for their own posts

    # Get post profile details
    profile_details = post.get_profile_details()

    # Get 48-hour analytics data
    analytics_data = post.get_impressions_data(days=2)  # Last 2 days

    # Get hourly breakdown for first 48 hours
    now = timezone.now()
    first_48_hours_data = []

    # Get impressions grouped by hour for the last 48 hours
    for i in range(24):  # 24 intervals of 2 hours each = 48 hours
        hour_start = now - timedelta(hours=(i + 1) * 2)
        hour_end = now - timedelta(hours=i * 2)

        hour_impressions = Impression.objects.filter(
            content_type__model="post",
            object_id=post.id,
            created_at__gte=hour_start,
            created_at__lt=hour_end,
        ).count()

        hour_label = f"{(i + 1) * 2}h"
        first_48_hours_data.append({"hour": hour_label, "views": hour_impressions})

    # Reverse to show oldest to newest
    first_48_hours_data.reverse()

    # Get top countries by views (as percentages)
    # Get all impressions for this post
    post_impressions = Impression.objects.filter(
        content_type__model="post", object_id=post.id
    )

    # Group by country (you'll need to implement IP to country mapping)
    country_data = {}
    total_impressions_with_location = 0

    for impression in post_impressions:
        if impression.ip_address:
            country_code = get_country_from_ip(impression.ip_address)
            if country_code != "XX" and country_code in COUNTRY_FLAGS:
                country_data[country_code] = country_data.get(country_code, 0) + 1
                total_impressions_with_location += 1

    # Calculate percentages and format for response
    top_countries = []
    for country_code, count in sorted(
        country_data.items(), key=lambda x: x[1], reverse=True
    )[:5]:
        percentage = (
            (count / total_impressions_with_location * 100)
            if total_impressions_with_location > 0
            else 0
        )
        country_info = COUNTRY_FLAGS[country_code]
        top_countries.append(
            {
                "country": country_info["name"],
                "flag": country_info["flag"],
                "percentage": round(percentage, 1),
            }
        )

    # Prepare post data
    post_data = {
        "content": post.content,
        "author": profile_details.get("display_name", "Unknown"),
        "handle": profile_details.get("user_name", "unknown"),
        "date": get_time_ago(post.created_at),
        "views": format_count(post.impressions_count),
        "likes": post.like_count,
        "comments": post.comment_count,
        "shares": post.share_count,
        "bookmarks": post.bookmark_count,
        "profile_type": post.profile_type,
        "profile_photo": profile_details.get("profile_photo"),
    }

    # Prepare response
    response_data = {
        "post": post_data,
        "first_48_hours_data": first_48_hours_data,
        "top_countries": top_countries,
        "total_impressions": analytics_data.get("total_impressions", 0),
        "unique_profiles": analytics_data.get("unique_profiles", 0),
        "anonymous_impressions": analytics_data.get("anonymous_impressions", 0),
        "public_impressions": analytics_data.get("public_impressions", 0),
    }

    return response_data


@router.get("/posts/{slug}/insights", response=PostInsightsSchema, auth=PublicJWTAuth())
def get_post_insights_by_slug(request, slug: str):
    """
    Get post insights by slug instead of ID
    """
    try:
        post = get_object_or_404(Post, slug=slug, is_deleted=False)
        return get_post_insights(request, post.id)
    except Http404:
        raise Http404("Post not found")


# Usage in your main ninja API:
# from ninja import NinjaAPI
# from .post_insights import router as insights_router
#
# api = NinjaAPI()
# api.add_router("/insights/", insights_router)
