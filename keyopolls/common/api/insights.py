import logging
from datetime import timedelta
from typing import List

from django.contrib.gis.geoip2 import GeoIP2
from django.core.cache import cache
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from ninja import Router, Schema

from keyopolls.common.models import Impression
from keyopolls.polls.models import Poll, PollVote
from keyopolls.profile.middleware import PseudonymousJWTAuth
from keyopolls.profile.models import PseudonymousProfile

logger = logging.getLogger(__name__)


# Response Schemas
class AuthorSchema(Schema):
    username: str
    display_name: str
    total_aura: int


class PollDataSchema(Schema):
    title: str
    description: str
    poll_type: str
    author: str
    username: str
    date: str
    views: str
    likes: int
    total_votes: int
    total_voters: int
    option_count: int
    bookmarks: int
    comments: int
    shares: int
    total_aura: int


class HourlyViewsSchema(Schema):
    hour: str
    views: int


class CountryViewsSchema(Schema):
    country: str
    flag: str
    percentage: float


class PollInsightsSchema(Schema):
    poll: PollDataSchema
    first_48_hours_data: List[HourlyViewsSchema]
    top_countries: List[CountryViewsSchema]
    total_impressions: int
    unique_profiles: int
    anonymous_impressions: int
    authenticated_impressions: int


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


router = Router(tags=["Poll Insights"])


@router.get(
    "/polls/{poll_id}/insights", response=PollInsightsSchema, auth=PseudonymousJWTAuth()
)
def get_poll_insights(request, poll_id: int):
    """
    Get comprehensive insights for a specific poll including:
    - Poll details and voting statistics
    - 48-hour hourly view breakdown
    - Top countries by views (as percentages)
    - Total analytics
    """

    # Get the authenticated profile
    profile = request.auth

    # Get the poll
    try:
        poll = get_object_or_404(Poll, id=poll_id, is_deleted=False)
    except Http404:
        raise Http404("Poll not found")

    # Check if user has permission to view insights
    # Only poll creator can view insights
    if poll.profile.id != profile.id:
        raise Http404("You don't have permission to view insights for this poll")

    # Get 48-hour analytics data
    analytics_data = poll.get_impressions_data(days=2)  # Last 2 days

    # Get hourly breakdown for first 48 hours
    now = timezone.now()
    first_48_hours_data = []

    # Get impressions grouped by hour for the last 48 hours
    for i in range(24):  # 24 intervals of 2 hours each = 48 hours
        hour_start = now - timedelta(hours=(i + 1) * 2)
        hour_end = now - timedelta(hours=i * 2)

        hour_impressions = Impression.objects.filter(
            content_type__model="poll",
            object_id=poll.id,
            created_at__gte=hour_start,
            created_at__lt=hour_end,
        ).count()

        hour_label = f"{(i + 1) * 2}h"
        first_48_hours_data.append({"hour": hour_label, "views": hour_impressions})

    # Reverse to show oldest to newest
    first_48_hours_data.reverse()

    # Get top countries by views (as percentages)
    # Get all impressions for this poll
    poll_impressions = Impression.objects.filter(
        content_type__model="poll", object_id=poll.id
    )

    # Group by country
    country_data = {}
    total_impressions_with_location = 0

    for impression in poll_impressions:
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

    # Prepare poll data
    poll_data = {
        "title": poll.title,
        "description": poll.description,
        "poll_type": poll.get_poll_type_display(),
        "author": poll.profile.display_name,
        "username": poll.profile.username,
        "date": get_time_ago(poll.created_at),
        "views": format_count(getattr(poll, "view_count", 0)),
        "likes": poll.like_count if hasattr(poll, "like_count") else 0,
        "total_votes": poll.total_votes,
        "total_voters": poll.total_voters,
        "option_count": poll.option_count,
        "bookmarks": poll.bookmark_count if hasattr(poll, "bookmark_count") else 0,
        "comments": poll.comment_count,
        "shares": poll.share_count,
        "total_aura": poll.profile.total_aura,
    }

    # Prepare response
    response_data = {
        "poll": poll_data,
        "first_48_hours_data": first_48_hours_data,
        "top_countries": top_countries,
        "total_impressions": analytics_data.get("total_impressions", 0),
        "unique_profiles": analytics_data.get("unique_profiles", 0),
        "anonymous_impressions": analytics_data.get("anonymous_impressions", 0),
        "authenticated_impressions": analytics_data.get("authenticated_impressions", 0),
    }

    return response_data


@router.get(
    "/polls/{poll_id}/voting-insights", response=dict, auth=PseudonymousJWTAuth()
)
def get_poll_voting_insights(request, poll_id: int):
    """
    Get detailed voting insights for a poll including:
    - Vote distribution by option
    - Voting timeline
    - Voter demographics (if available)
    """

    # Get the authenticated profile
    profile = request.auth

    # Get the poll
    try:
        poll = get_object_or_404(Poll, id=poll_id, is_deleted=False)
    except Http404:
        raise Http404("Poll not found")

    # Check if user has permission to view voting insights
    # Only poll creator can view detailed voting insights
    if poll.profile.id != profile.id:
        raise Http404("You don't have permission to view voting insights for this poll")

    # Option distribution
    options_data = []
    for option in poll.options.all().order_by("order"):
        option_data = {
            "id": option.id,
            "text": option.text,
            "order": option.order,
            "vote_count": option.vote_count,
            "percentage": option.vote_percentage,
            "has_image": bool(option.image),
        }
        options_data.append(option_data)

    # Voting timeline (last 7 days, hourly)
    voting_timeline = []
    now = timezone.now()

    for i in range(24 * 7):  # 7 days worth of hours
        hour_start = now - timedelta(hours=i + 1)
        hour_end = now - timedelta(hours=i)

        votes_in_hour = PollVote.objects.filter(
            poll=poll,
            created_at__gte=hour_start,
            created_at__lt=hour_end,
        ).count()

        voting_timeline.append(
            {
                "hour": hour_start.strftime("%Y-%m-%d %H:00"),
                "votes": votes_in_hour,
            }
        )

    # Reverse to show oldest to newest
    voting_timeline.reverse()

    # Voter aura distribution (for engagement analysis)
    aura_distribution = {
        "0-100": 0,
        "101-500": 0,
        "501-1000": 0,
        "1000+": 0,
    }

    # Get unique voters for this poll
    unique_voters = PollVote.objects.filter(poll=poll).values("profile").distinct()

    for voter_data in unique_voters:
        try:
            voter_profile = PseudonymousProfile.objects.get(id=voter_data["profile"])
            total_aura = voter_profile.total_aura

            if total_aura <= 100:
                aura_distribution["0-100"] += 1
            elif total_aura <= 500:
                aura_distribution["101-500"] += 1
            elif total_aura <= 1000:
                aura_distribution["501-1000"] += 1
            else:
                aura_distribution["1000+"] += 1

        except Exception:
            # Skip if profile not found
            continue

    return {
        "poll_id": poll.id,
        "poll_title": poll.title,
        "poll_type": poll.poll_type,
        "total_votes": poll.total_votes,
        "total_voters": poll.total_voters,
        "options": options_data,
        "voting_timeline": voting_timeline,
        "voter_aura_distribution": aura_distribution,
        "created_at": poll.created_at.isoformat(),
        "expires_at": poll.expires_at.isoformat() if poll.expires_at else None,
        "is_active": poll.is_active,
    }


@router.get(
    "/communities/{community_id}/insights", response=dict, auth=PseudonymousJWTAuth()
)
def get_community_insights(request, community_id: int):
    """
    Get insights for a community including:
    - Poll performance
    - Member engagement
    - Growth metrics
    """

    # Get the authenticated profile
    profile = request.auth

    # Get the community
    try:
        from keyopolls.polls.models import Community, CommunityMembership

        community = get_object_or_404(Community, id=community_id, is_active=True)
    except Http404:
        raise Http404("Community not found")

    # Check if user has permission to view community insights
    # Only community creator and admins can view insights
    try:
        membership = CommunityMembership.objects.get(
            community=community, profile=profile, status="active"
        )
        if membership.role not in ["creator", "admin"]:
            raise Http404(
                "You don't have permission to view insights for this community"
            )
    except CommunityMembership.DoesNotExist:
        raise Http404("You are not a member of this community")

    # Get community polls
    community_polls = Poll.objects.filter(
        community=community, is_deleted=False
    ).order_by("-created_at")

    # Poll performance metrics
    total_polls = community_polls.count()
    total_votes = sum(poll.total_votes for poll in community_polls)
    total_comments = sum(poll.comment_count for poll in community_polls)

    # Top performing polls
    top_polls = []
    for poll in community_polls.order_by("-total_votes")[:5]:
        top_polls.append(
            {
                "id": poll.id,
                "title": poll.title,
                "total_votes": poll.total_votes,
                "total_voters": poll.total_voters,
                "created_at": poll.created_at.isoformat(),
                "author": poll.profile.username,
            }
        )

    # Member growth (last 30 days)
    member_growth = []
    now = timezone.now()

    for i in range(30):
        day = now - timedelta(days=i)
        day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)

        new_members = CommunityMembership.objects.filter(
            community=community,
            joined_at__gte=day_start,
            joined_at__lt=day_end,
        ).count()

        member_growth.append(
            {
                "date": day.strftime("%Y-%m-%d"),
                "new_members": new_members,
            }
        )

    # Reverse to show oldest to newest
    member_growth.reverse()

    return {
        "community_id": community.id,
        "community_name": community.name,
        "member_count": community.member_count,
        "poll_count": community.poll_count,
        "metrics": {
            "total_polls": total_polls,
            "total_votes": total_votes,
            "total_comments": total_comments,
            "avg_votes_per_poll": total_votes / total_polls if total_polls > 0 else 0,
        },
        "top_polls": top_polls,
        "member_growth": member_growth,
        "created_at": community.created_at.isoformat(),
    }
