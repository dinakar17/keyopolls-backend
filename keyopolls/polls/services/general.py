from typing import List

from django.db.models import Count

from keyopolls.polls.models import Poll, PollOption, PollVote


def validate_vote_for_poll_type(
    poll: Poll, votes: List[PollVote], poll_options: dict
) -> dict:
    """Validate votes based on poll type"""

    if poll.poll_type == "single":
        # Single choice: exactly one vote, no rank
        if len(votes) != 1:
            return {
                "valid": False,
                "error": "Single choice polls require exactly one vote",
            }

        vote = votes[0]
        if vote.rank is not None:
            return {"valid": False, "error": "Single choice polls do not use ranking"}

    elif poll.poll_type == "multiple":
        # Multiple choice: 1 to max_choices votes, no rank
        if poll.max_choices and len(votes) > poll.max_choices:
            return {
                "valid": False,
                "error": f"Cannot select more than {poll.max_choices} options",
            }

        if len(votes) == 0:
            return {"valid": False, "error": "Must select at least one option"}

        # Check for duplicates
        option_ids = [vote.option_id for vote in votes]
        if len(option_ids) != len(set(option_ids)):
            return {
                "valid": False,
                "error": "Cannot vote for the same option multiple times",
            }

        # No ranks allowed
        for vote in votes:
            if vote.rank is not None:
                return {
                    "valid": False,
                    "error": "Multiple choice polls do not use ranking",
                }

    elif poll.poll_type == "ranking":
        # Ranking: must rank all options, ranks must be sequential 1,2,3...
        total_options = len(poll_options)

        if len(votes) != total_options:
            return {"valid": False, "error": f"Must rank all {total_options} options"}

        # Check all options are included
        voted_option_ids = {vote.option_id for vote in votes}
        all_option_ids = set(poll_options.keys())
        if voted_option_ids != all_option_ids:
            return {"valid": False, "error": "Must vote for all options exactly once"}

        # Check ranks are valid
        ranks = [vote.rank for vote in votes]
        if any(rank is None for rank in ranks):
            return {"valid": False, "error": "All votes must have a rank"}

        expected_ranks = set(range(1, total_options + 1))
        actual_ranks = set(ranks)
        if actual_ranks != expected_ranks:
            return {
                "valid": False,
                "error": f"Ranks must be {list(expected_ranks)} (one of each)",
            }

    else:
        return {"valid": False, "error": f"Unknown poll type: {poll.poll_type}"}

    return {"valid": True, "error": None}


# Helper functions for ranking calculations
def calculate_option_ranking_results(option: PollOption, poll: Poll):
    """Calculate best rank and percentage for a ranking poll option"""
    if poll.total_voters == 0:
        return {"best_rank": None, "best_rank_percentage": 0.0}

    # Get vote counts for each rank for this option
    rank_counts = {}
    votes = option.votes.values("rank").annotate(count=Count("rank"))

    for vote_data in votes:
        rank = vote_data["rank"]
        count = vote_data["count"]
        rank_counts[rank] = count

    if not rank_counts:
        return {"best_rank": None, "best_rank_percentage": 0.0}

    # Find the rank with the highest count
    best_rank = max(rank_counts.keys(), key=lambda r: rank_counts[r])
    best_count = rank_counts[best_rank]
    best_percentage = round((best_count / poll.total_voters) * 100, 1)

    return {"best_rank": best_rank, "best_rank_percentage": best_percentage}


def calculate_rank_breakdown(option: PollOption, poll: Poll):
    """Calculate full rank breakdown for detailed view"""
    if poll.total_voters == 0:
        return {}

    rank_breakdown = {}
    votes = option.votes.values("rank").annotate(count=Count("rank"))

    for vote_data in votes:
        rank = vote_data["rank"]
        count = vote_data["count"]
        percentage = round((count / poll.total_voters) * 100, 1)
        rank_breakdown[rank] = percentage

    return rank_breakdown


def calculate_multiple_choice_distribution(poll):
    """
    Calculate how many people chose exactly X out of Y options.
    Returns dict like {1: 5, 2: 10, 3: 2} meaning:
    - 5 people chose exactly 1 option
    - 10 people chose exactly 2 options
    - 2 people chose exactly 3 options
    """
    if poll.poll_type != "multiple" or poll.total_voters == 0:
        return {}

    # Group votes by user and count how many options each user selected
    user_choice_counts = (
        poll.votes.values("profile")
        .annotate(choice_count=Count("option"))
        .values_list("choice_count", flat=True)
    )

    # Count how many users selected each number of choices
    distribution = {}
    for choice_count in user_choice_counts:
        distribution[choice_count] = distribution.get(choice_count, 0) + 1

    return distribution


def get_text_input_results(poll: Poll, show_correct_answers: bool = False):
    """
    Get aggregated text input results for a poll.
    Returns list of {text_value, count, percentage, is_correct} dicts
    """
    if poll.poll_type != "text_input":
        return []

    results = []
    aggregates = poll.text_aggregates.all().order_by("-response_count")

    for agg in aggregates:
        is_correct = False
        if (
            show_correct_answers
            and poll.has_correct_answer
            and poll.correct_text_answer
        ):
            is_correct = agg.text_value.lower() == poll.correct_text_answer.lower()

        results.append(
            {
                "text_value": agg.text_value,
                "response_count": agg.response_count,
                "percentage": agg.percentage,
                "is_correct": is_correct,
            }
        )

    return results


def calculate_poll_accuracy(poll):
    """
    Calculate what percentage of users got the correct answer.
    Works for all poll types that have correct answers set.
    """
    if not poll.has_correct_answer or poll.total_voters == 0:
        return {"correct_count": 0, "correct_percentage": 0.0}

    return poll.get_correct_answer_stats()
