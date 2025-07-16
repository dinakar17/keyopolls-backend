from typing import Any, Dict, List, Optional

from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db import models, transaction
from django.http import Http404
from django.shortcuts import get_object_or_404
from ninja import Query, Router, Schema

from keyopolls.communities.models import Community
from keyopolls.flashcards.models import Flashcard, FlashcardProgress, FlashcardSet
from keyopolls.flashcards.schemas import (
    FlashcardCreateSchema,
    FlashcardSchema,
    FlashcardSetCreateSchema,
    FlashcardSetDetails,
    FlashcardSetListItem,
    FlashcardSetUpdateSchema,
    FlashcardUpdateSchema,
    MessageSchema,
    StudySessionResultSchema,
    StudySessionSchema,
)
from keyopolls.profile.middleware import (
    OptionalPseudonymousJWTAuth,
    PseudonymousJWTAuth,
)

router = Router()


# ===============================
# FLASHCARD SET ENDPOINTS
# ===============================


@router.post("/sets/", response=FlashcardSetDetails, auth=PseudonymousJWTAuth())
def create_flashcard_set(request, data: FlashcardSetCreateSchema):
    """
    Create a new flashcard set with optional initial flashcards.
    Requires authentication.
    """
    # Verify community exists and user has access
    community = get_object_or_404(Community, id=data.community_id)

    with transaction.atomic():
        # Create the flashcard set
        flashcard_set = FlashcardSet.objects.create(
            title=data.title,
            description=data.description,
            community=community,
            creator=request.auth,  # PseudonymousProfile from JWT
            is_public=data.is_public,
        )

        # Create initial flashcards if provided
        for i, flashcard_data in enumerate(data.flashcards):
            Flashcard.objects.create(
                question=flashcard_data.question,
                answer=flashcard_data.answer,
                hint=flashcard_data.hint,
                difficulty=flashcard_data.difficulty,
                order=flashcard_data.order if flashcard_data.order is not None else i,
                flashcard_set=flashcard_set,
            )

    return FlashcardSetDetails.resolve(flashcard_set, request.auth)


@router.put(
    "/sets/{int:set_id}", response=FlashcardSetDetails, auth=PseudonymousJWTAuth()
)
def update_flashcard_set(request, set_id: int, data: FlashcardSetUpdateSchema):
    """
    Update an existing flashcard set.
    Only the creator can update their flashcard set.
    """
    flashcard_set = get_object_or_404(FlashcardSet, id=set_id)

    # Check if user is the creator
    if flashcard_set.creator.id != request.auth.id:
        raise Http404(
            "Flashcard set not found"
        )  # Don't reveal existence to non-creators

    # Update only provided fields
    if data.title is not None:
        flashcard_set.title = data.title
    if data.description is not None:
        flashcard_set.description = data.description
    if data.is_public is not None:
        flashcard_set.is_public = data.is_public

    flashcard_set.save()

    return FlashcardSetDetails.resolve(flashcard_set, request.auth)


@router.delete("/sets/{int:set_id}", response=MessageSchema, auth=PseudonymousJWTAuth())
def delete_flashcard_set(request, set_id: int):
    """
    Delete a flashcard set.
    Only the creator can delete their flashcard set.
    """
    flashcard_set = get_object_or_404(FlashcardSet, id=set_id)

    # Check if user is the creator
    if flashcard_set.creator.id != request.auth.id:
        raise Http404(
            "Flashcard set not found"
        )  # Don't reveal existence to non-creators

    flashcard_set.delete()

    return {"message": "Flashcard set deleted successfully"}


@router.get(
    "/sets/{int:set_id}",
    response=FlashcardSetDetails,
    auth=OptionalPseudonymousJWTAuth(),
)
def get_flashcard_set(request, set_id: int):
    """
    Get a specific flashcard set by ID with all flashcards.
    Authentication is optional - provides additional context if authenticated.
    """
    flashcard_set = get_object_or_404(
        FlashcardSet.objects.select_related("creator", "community"), id=set_id
    )

    # Only show public sets to non-creators
    if not flashcard_set.is_public and (
        not request.auth or flashcard_set.creator.id != request.auth.id
    ):
        raise Http404("Flashcard set not found")

    # Optionally increment view count here
    # flashcard_set.view_count = F('view_count') + 1
    # flashcard_set.save(update_fields=['view_count'])

    return FlashcardSetDetails.resolve(
        flashcard_set, request.auth, include_flashcards=True
    )


class FlashcardSetFilters(Schema):
    """Query parameters for filtering flashcard sets"""

    community_id: Optional[int] = None
    creator_username: Optional[str] = None
    is_public: Optional[bool] = True  # Default to public only
    search: Optional[str] = None
    page: Optional[int] = 1
    page_size: Optional[int] = 20


class PaginatedFlashcardSetResponse(Schema):
    """Paginated response for flashcard sets"""

    items: List[FlashcardSetListItem]
    total_count: int
    page: int
    page_size: int
    total_pages: int
    has_next: bool
    has_previous: bool


@router.get(
    "/sets/", response=PaginatedFlashcardSetResponse, auth=OptionalPseudonymousJWTAuth()
)
def list_flashcard_sets(request, filters: FlashcardSetFilters = Query(...)):
    """
    Get a paginated list of flashcard sets.
    Authentication is optional - provides additional context if authenticated.
    """
    queryset = FlashcardSet.objects.select_related("creator", "community").order_by(
        "-created_at"
    )

    # Apply filters
    if filters.community_id:
        queryset = queryset.filter(community_id=filters.community_id)

    if filters.creator_username:
        queryset = queryset.filter(creator__username=filters.creator_username)

    # Handle public filter
    if filters.is_public is not None:
        if not request.auth:
            # Non-authenticated users can only see public sets
            queryset = queryset.filter(is_public=True)
        else:
            # Authenticated users can see their own private sets
            if filters.is_public:
                queryset = queryset.filter(is_public=True)
            else:
                # Show private sets only if they are the creator
                queryset = queryset.filter(is_public=False, creator=request.auth)
    else:
        # If no public filter specified, show public + user's private
        if request.auth:
            from django.db.models import Q

            queryset = queryset.filter(Q(is_public=True) | Q(creator=request.auth))
        else:
            queryset = queryset.filter(is_public=True)

    # Apply search filter
    if filters.search:
        from django.db.models import Q

        queryset = queryset.filter(
            Q(title__icontains=filters.search)
            | Q(description__icontains=filters.search)
        )

    # Paginate results
    paginator = Paginator(queryset, filters.page_size or 20)

    try:
        page_obj = paginator.page(filters.page or 1)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    return {
        "items": [FlashcardSetListItem.resolve(fs, request.auth) for fs in page_obj],
        "total_count": paginator.count,
        "page": page_obj.number,
        "page_size": filters.page_size or 20,
        "total_pages": paginator.num_pages,
        "has_next": page_obj.has_next(),
        "has_previous": page_obj.has_previous(),
    }


# ===============================
# INDIVIDUAL FLASHCARD ENDPOINTS
# ===============================


@router.post(
    "/sets/{int:set_id}/flashcards/",
    response=FlashcardSchema,
    auth=PseudonymousJWTAuth(),
)
def create_flashcard(request, set_id: int, data: FlashcardCreateSchema):
    """
    Add a new flashcard to a flashcard set.
    Only the creator can add flashcards to their set.
    """
    flashcard_set = get_object_or_404(FlashcardSet, id=set_id)

    # Check if user is the creator
    if flashcard_set.creator.id != request.auth.id:
        raise Http404("Flashcard set not found")

    # Set order if not provided
    if data.order is None:
        max_order = (
            flashcard_set.flashcards.aggregate(max_order=models.Max("order"))[
                "max_order"
            ]
            or 0
        )
        data.order = max_order + 1

    flashcard = Flashcard.objects.create(
        question=data.question,
        answer=data.answer,
        hint=data.hint,
        difficulty=data.difficulty,
        order=data.order,
        flashcard_set=flashcard_set,
    )

    return FlashcardSchema.resolve(flashcard, request.auth)


@router.put(
    "/flashcards/{int:flashcard_id}",
    response=FlashcardSchema,
    auth=PseudonymousJWTAuth(),
)
def update_flashcard(request, flashcard_id: int, data: FlashcardUpdateSchema):
    """
    Update an existing flashcard.
    Only the creator of the flashcard set can update flashcards.
    """
    flashcard = get_object_or_404(
        Flashcard.objects.select_related("flashcard_set"), id=flashcard_id
    )

    # Check if user is the creator of the flashcard set
    if flashcard.flashcard_set.creator.id != request.auth.id:
        raise Http404("Flashcard not found")

    # Update only provided fields
    if data.question is not None:
        flashcard.question = data.question
    if data.answer is not None:
        flashcard.answer = data.answer
    if data.hint is not None:
        flashcard.hint = data.hint
    if data.difficulty is not None:
        flashcard.difficulty = data.difficulty
    if data.order is not None:
        flashcard.order = data.order

    flashcard.save()

    return FlashcardSchema.resolve(flashcard, request.auth)


@router.delete(
    "/flashcards/{int:flashcard_id}", response=MessageSchema, auth=PseudonymousJWTAuth()
)
def delete_flashcard(request, flashcard_id: int):
    """
    Delete a flashcard.
    Only the creator of the flashcard set can delete flashcards.
    """
    flashcard = get_object_or_404(
        Flashcard.objects.select_related("flashcard_set"), id=flashcard_id
    )

    # Check if user is the creator of the flashcard set
    if flashcard.flashcard_set.creator.id != request.auth.id:
        raise Http404("Flashcard not found")

    flashcard.delete()

    return {"message": "Flashcard deleted successfully"}


@router.get(
    "/flashcards/{int:flashcard_id}",
    response=FlashcardSchema,
    auth=OptionalPseudonymousJWTAuth(),
)
def get_flashcard(request, flashcard_id: int):
    """
    Get a specific flashcard by ID.
    Authentication is optional - provides additional context if authenticated.
    """
    flashcard = get_object_or_404(
        Flashcard.objects.select_related("flashcard_set", "flashcard_set__creator"),
        id=flashcard_id,
    )

    # Only show flashcards from public sets to non-creators
    if not flashcard.flashcard_set.is_public and (
        not request.auth or flashcard.flashcard_set.creator.id != request.auth.id
    ):
        raise Http404("Flashcard not found")

    return FlashcardSchema.resolve(flashcard, request.auth)


# ===============================
# STUDY SESSION ENDPOINTS
# ===============================


@router.post(
    "/sets/{int:set_id}/study",
    response=List[StudySessionResultSchema],
    auth=PseudonymousJWTAuth(),
)
def record_study_session(request, set_id: int, results: List[StudySessionSchema]):
    """
    Record the results of a study session.
    Updates user progress for each flashcard studied.
    """
    flashcard_set = get_object_or_404(FlashcardSet, id=set_id)

    # Verify flashcard set is accessible
    if not flashcard_set.is_public and flashcard_set.creator.id != request.auth.id:
        raise Http404("Flashcard set not found")

    session_results = []

    with transaction.atomic():
        for result in results:
            # Get the flashcard
            flashcard = get_object_or_404(
                Flashcard, id=result.flashcard_id, flashcard_set=flashcard_set
            )

            # Get or create progress record
            progress, created = FlashcardProgress.objects.get_or_create(
                user=request.auth,
                flashcard=flashcard,
                defaults={
                    "times_studied": 0,
                    "times_correct": 0,
                    "mastery_level": "learning",
                },
            )

            previous_mastery = progress.mastery_level

            # Update progress
            progress.times_studied += 1
            if result.was_correct:
                progress.times_correct += 1

            # Update mastery level based on performance
            accuracy = progress.accuracy
            if accuracy >= 90 and progress.times_studied >= 3:
                progress.mastery_level = "mastered"
            elif accuracy >= 70 and progress.times_studied >= 2:
                progress.mastery_level = "reviewing"
            else:
                progress.mastery_level = "learning"

            progress.save()

            session_results.append(
                {
                    "flashcard_id": flashcard.id,
                    "previous_mastery_level": previous_mastery,
                    "new_mastery_level": progress.mastery_level,
                    "accuracy": accuracy,
                    "times_studied": progress.times_studied,
                }
            )

    return session_results


@router.get("/sets/{int:set_id}/progress", response=Dict, auth=PseudonymousJWTAuth())
def get_study_progress(request, set_id: int):
    """
    Get detailed study progress for a flashcard set.
    """
    flashcard_set = get_object_or_404(FlashcardSet, id=set_id)

    # Verify flashcard set is accessible
    if not flashcard_set.is_public and flashcard_set.creator.id != request.auth.id:
        raise Http404("Flashcard set not found")

    total_flashcards = flashcard_set.flashcard_count()
    progress_data = FlashcardProgress.objects.filter(
        user=request.auth, flashcard__flashcard_set=flashcard_set
    )

    studied_count = progress_data.count()
    mastery_breakdown = {
        "learning": progress_data.filter(mastery_level="learning").count(),
        "reviewing": progress_data.filter(mastery_level="reviewing").count(),
        "mastered": progress_data.filter(mastery_level="mastered").count(),
    }

    total_accuracy = (
        sum(p.accuracy for p in progress_data) / studied_count
        if studied_count > 0
        else 0
    )

    return {
        "flashcard_set_id": flashcard_set.id,
        "total_flashcards": total_flashcards,
        "studied_count": studied_count,
        "unstudied_count": total_flashcards - studied_count,
        "mastery_breakdown": mastery_breakdown,
        "overall_progress_percentage": round(
            (studied_count / total_flashcards) * 100, 1
        ),
        "mastery_percentage": round(
            (mastery_breakdown["mastered"] / total_flashcards) * 100, 1
        ),
        "average_accuracy": round(total_accuracy, 1),
    }


# ===============================
# ADDITIONAL CONVENIENCE ENDPOINTS
# ===============================


class CommunityFlashcardFilters(Schema):
    """Query parameters for community flashcard sets"""

    page: Optional[int] = 1
    page_size: Optional[int] = 20


@router.get(
    "/sets/community/{int:community_id}",
    response=PaginatedFlashcardSetResponse,
    auth=OptionalPseudonymousJWTAuth(),
)
def list_community_flashcard_sets(
    request, community_id: int, filters: CommunityFlashcardFilters = Query(...)
):
    """
    Get flashcard sets for a specific community.
    """
    # Verify community exists
    get_object_or_404(Community, id=community_id)

    queryset = (
        FlashcardSet.objects.select_related("creator", "community")
        .filter(community_id=community_id)
        .order_by("-created_at")
    )

    # Filter by public status based on authentication
    if not request.auth:
        queryset = queryset.filter(is_public=True)
    else:
        # Show public sets + user's own private sets
        from django.db.models import Q

        queryset = queryset.filter(Q(is_public=True) | Q(creator=request.auth))

    # Paginate results
    paginator = Paginator(queryset, filters.page_size or 20)

    try:
        page_obj = paginator.page(filters.page or 1)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    return {
        "items": [FlashcardSetListItem.resolve(fs, request.auth) for fs in page_obj],
        "total_count": paginator.count,
        "page": page_obj.number,
        "page_size": filters.page_size or 20,
        "total_pages": paginator.num_pages,
        "has_next": page_obj.has_next(),
        "has_previous": page_obj.has_previous(),
    }


class MyFlashcardSetsFilters(Schema):
    """Query parameters for user's own flashcard sets"""

    page: Optional[int] = 1
    page_size: Optional[int] = 20


@router.get(
    "/sets/my-sets", response=PaginatedFlashcardSetResponse, auth=PseudonymousJWTAuth()
)
def list_my_flashcard_sets(request, filters: MyFlashcardSetsFilters = Query(...)):
    """
    Get current user's flashcard sets (both public and private).
    Requires authentication.
    """
    queryset = (
        FlashcardSet.objects.select_related("community")
        .filter(creator=request.auth)
        .order_by("-created_at")
    )

    # Paginate results
    paginator = Paginator(queryset, filters.page_size or 20)

    try:
        page_obj = paginator.page(filters.page or 1)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    return {
        "items": [FlashcardSetListItem.resolve(fs, request.auth) for fs in page_obj],
        "total_count": paginator.count,
        "page": page_obj.number,
        "page_size": filters.page_size or 20,
        "total_pages": paginator.num_pages,
        "has_next": page_obj.has_next(),
        "has_previous": page_obj.has_previous(),
    }


class StudyProgressFilters(Schema):
    """Query parameters for study progress"""

    page: Optional[int] = 1
    page_size: Optional[int] = 20


class PaginatedStudyProgressResponse(Schema):
    """Paginated response for study progress"""

    items: List[Dict[str, Any]]
    total_count: int
    page: int
    page_size: int
    total_pages: int
    has_next: bool
    has_previous: bool


@router.get(
    "/sets/my-progress",
    response=PaginatedStudyProgressResponse,
    auth=PseudonymousJWTAuth(),
)
def list_my_study_progress(request, filters: StudyProgressFilters = Query(...)):
    """
    Get current user's study progress across all flashcard sets they've studied.
    Requires authentication.
    """
    # Get all flashcard sets the user has made progress on
    flashcard_sets_with_progress = (
        FlashcardSet.objects.filter(flashcards__user_progress__user=request.auth)
        .distinct()
        .select_related("creator", "community")
        .order_by("-created_at")
    )

    # Paginate the flashcard sets first
    paginator = Paginator(flashcard_sets_with_progress, filters.page_size or 20)

    try:
        page_obj = paginator.page(filters.page or 1)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    progress_data = []
    for flashcard_set in page_obj:
        total_flashcards = flashcard_set.flashcard_count()
        user_progress = FlashcardProgress.objects.filter(
            user=request.auth, flashcard__flashcard_set=flashcard_set
        )

        studied_count = user_progress.count()
        mastered_count = user_progress.filter(mastery_level="mastered").count()
        avg_accuracy = (
            sum(p.accuracy for p in user_progress) / studied_count
            if studied_count > 0
            else 0
        )

        progress_data.append(
            {
                "flashcard_set": FlashcardSetListItem.resolve(
                    flashcard_set, request.auth
                ),
                "progress_summary": {
                    "total_flashcards": total_flashcards,
                    "studied_count": studied_count,
                    "mastered_count": mastered_count,
                    "progress_percentage": round(
                        (studied_count / total_flashcards) * 100, 1
                    ),
                    "mastery_percentage": round(
                        (mastered_count / total_flashcards) * 100, 1
                    ),
                    "average_accuracy": round(avg_accuracy, 1),
                    "last_studied": (
                        user_progress.order_by("-last_studied").first().last_studied
                        if user_progress.exists()
                        else None
                    ),
                },
            }
        )

    return {
        "items": progress_data,
        "total_count": paginator.count,
        "page": page_obj.number,
        "page_size": filters.page_size or 20,
        "total_pages": paginator.num_pages,
        "has_next": page_obj.has_next(),
        "has_previous": page_obj.has_previous(),
    }


@router.get(
    "/sets/{int:set_id}/study-queue",
    response=List[FlashcardSchema],
    auth=PseudonymousJWTAuth(),
)
def get_study_queue(request, set_id: int, limit: int = 20):
    """
    Get a queue of flashcards to study, prioritized by mastery level and
    last studied time.
    Returns flashcards that need the most practice first.
    """
    flashcard_set = get_object_or_404(FlashcardSet, id=set_id)

    # Verify flashcard set is accessible
    if not flashcard_set.is_public and flashcard_set.creator.id != request.auth.id:
        raise Http404("Flashcard set not found")

    # Get all flashcards in the set
    flashcards = flashcard_set.flashcards.all().order_by("order")

    # Prioritize flashcards based on user progress
    flashcard_priority = []

    for flashcard in flashcards:
        try:
            progress = FlashcardProgress.objects.get(
                user=request.auth, flashcard=flashcard
            )

            # Calculate priority score (lower = higher priority)
            # Factors: mastery level, accuracy, time since last study
            mastery_weight = {"learning": 1, "reviewing": 2, "mastered": 3}[
                progress.mastery_level
            ]
            accuracy_weight = progress.accuracy / 100  # 0-1 scale

            # Time weight (more recent = lower priority)
            from django.utils import timezone

            time_diff = (timezone.now() - progress.last_studied).days
            time_weight = min(time_diff / 7, 1)  # Normalize to 0-1 over a week

            priority_score = mastery_weight + accuracy_weight - time_weight

        except FlashcardProgress.DoesNotExist:
            # New flashcards get highest priority
            priority_score = 0

        flashcard_priority.append((flashcard, priority_score))

    # Sort by priority (lowest score first) and take the requested limit
    flashcard_priority.sort(key=lambda x: x[1])
    study_queue = [fc for fc, _ in flashcard_priority[:limit]]

    return [FlashcardSchema.resolve(fc, request.auth) for fc in study_queue]


@router.post(
    "/sets/{int:set_id}/reset-progress",
    response=MessageSchema,
    auth=PseudonymousJWTAuth(),
)
def reset_study_progress(request, set_id: int):
    """
    Reset all study progress for a flashcard set.
    This will delete all progress records for the user on this set.
    """
    flashcard_set = get_object_or_404(FlashcardSet, id=set_id)

    # Verify flashcard set is accessible
    if not flashcard_set.is_public and flashcard_set.creator.id != request.auth.id:
        raise Http404("Flashcard set not found")

    # Delete all progress records for this user and flashcard set
    deleted_count = FlashcardProgress.objects.filter(
        user=request.auth, flashcard__flashcard_set=flashcard_set
    ).delete()[0]

    return {"message": f"Reset progress for {deleted_count} flashcards"}


@router.post(
    "/sets/{int:set_id}/reorder", response=MessageSchema, auth=PseudonymousJWTAuth()
)
def reorder_flashcards(request, set_id: int, flashcard_orders: List[Dict[str, int]]):
    """
    Reorder flashcards in a set.
    Expects a list of objects with 'flashcard_id' and 'order' keys.
    Only the creator can reorder flashcards.
    """
    flashcard_set = get_object_or_404(FlashcardSet, id=set_id)

    # Check if user is the creator
    if flashcard_set.creator.id != request.auth.id:
        raise Http404("Flashcard set not found")

    # Validate all flashcard IDs belong to this set
    flashcard_ids = [item["flashcard_id"] for item in flashcard_orders]
    valid_flashcards = set(
        flashcard_set.flashcards.filter(id__in=flashcard_ids).values_list(
            "id", flat=True
        )
    )

    if len(valid_flashcards) != len(flashcard_ids):
        return {"message": "Some flashcard IDs are invalid"}

    # Update orders
    with transaction.atomic():
        for item in flashcard_orders:
            Flashcard.objects.filter(
                id=item["flashcard_id"], flashcard_set=flashcard_set
            ).update(order=item["order"])

    return {"message": "Flashcards reordered successfully"}
