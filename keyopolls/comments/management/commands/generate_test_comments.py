import random
from datetime import timedelta

from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.utils import timezone
from faker import Faker

# Import your models (adjusted for new architecture)
from keyoconnect.comments.models import GenericComment
from keyoconnect.profiles.models import AnonymousProfile, PublicProfile

fake = Faker()


class Command(BaseCommand):
    help = (
        "Generate test comments with nested structure for testing"
        "(Public/Anonymous profiles only)"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--content-type",
            type=str,
            default="post",
            help="Content type for comments (post, article, etc.)",
        )
        parser.add_argument(
            "--object-id",
            type=int,
            required=True,
            help="Object ID to attach comments to",
        )
        parser.add_argument(
            "--count",
            type=int,
            default=50,
            help="Number of top-level comments to create",
        )
        parser.add_argument(
            "--max-depth", type=int, default=8, help="Maximum nesting depth"
        )

    def handle(self, *args, **options):
        content_type_str = options["content_type"]
        object_id = options["object_id"]
        count = options["count"]
        max_depth = options["max_depth"]

        self.stdout.write(
            f"Generating {count} test comments for {content_type_str} {object_id}..."
        )

        # Get content type
        try:
            content_type = ContentType.objects.get(model=content_type_str)
        except ContentType.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(f"Content type '{content_type_str}' not found")
            )
            return

        # Get or create test profiles
        profiles = self.get_or_create_test_profiles()

        # Generate top-level comments
        top_level_comments = []
        for i in range(count):
            comment = self.create_comment(
                content_type=content_type,
                object_id=object_id,
                profiles=profiles,
                depth=0,
            )
            top_level_comments.append(comment)
            self.stdout.write(f"Created top-level comment {i+1}/{count}")

        # Generate nested replies
        self.generate_nested_replies(top_level_comments, profiles, max_depth)

        self.stdout.write(self.style.SUCCESS("Successfully generated test comments!"))

    def get_or_create_test_profiles(self):
        """Create or get test profiles for public and anonymous types only"""
        profiles = {
            "public": [],
            "anonymous": [],
        }

        # Create public profiles
        for i in range(10):
            profile, created = PublicProfile.objects.get_or_create(
                user_name=f"test_user_{i}",
                defaults={
                    "display_name": fake.name(),
                    "handle": f"test_handle_{i}",
                    "full_name": fake.name(),
                    "email": fake.email(),
                    "mobile_number": fake.phone_number()[:15],
                    "bio": fake.text(max_nb_chars=200),
                    "is_active": True,
                    "is_real_human": random.choice([True, False]),
                },
            )
            profiles["public"].append(profile)

        # Create anonymous profiles
        for i in range(10):
            profile, created = AnonymousProfile.objects.get_or_create(
                anonymous_id=f"anon_{i:04d}",
                defaults={
                    "display_name": f"Anonymous User {i}",
                    "bio": fake.text(max_nb_chars=100),
                    "is_active": True,
                },
            )
            profiles["anonymous"].append(profile)

        return profiles

    def create_comment(self, content_type, object_id, profiles, depth, parent=None):
        """Create a single comment"""
        # Choose random profile type and profile (public or anonymous only)
        profile_type = random.choice(["public", "anonymous"])
        profile = random.choice(profiles[profile_type])

        # Generate realistic content based on depth
        content_options = [
            fake.sentence(nb_words=10),
            fake.paragraph(nb_sentences=2),
            fake.text(max_nb_chars=300),
            "This is a great point!",
            "I completely disagree with this.",
            "Thanks for sharing this information.",
            "Could you provide more details?",
            "This reminds me of a similar situation...",
            "Interesting perspective!",
            "I'm not sure I understand. Can you clarify?",
            "Well said!",
            "I have a different opinion on this.",
            "This is exactly what I was thinking.",
            "Can you share more examples?",
            "I learned something new today, thanks!",
        ]

        content = random.choice(content_options)
        if depth > 3:  # Shorter comments at deeper levels
            content = random.choice(content_options[:8])

        # Generate anonymous identifier for anonymous comments
        anonymous_identifier = None
        if profile_type == "anonymous":
            # Generate creative anonymous identifiers using Faker
            anonymous_prefixes = [
                "Ghost",
                "Shadow",
                "Phantom",
                "Whisper",
                "Echo",
                "Void",
                "Mist",
                "Shade",
                "Cipher",
                "Enigma",
                "Mystery",
                "Unknown",
                "Hidden",
                "Veiled",
                "Masked",
                "Faceless",
                "Nameless",
                "Silent",
                "Invisible",
                "Anon",
                "Incognito",
                "Covert",
                "Secret",
                "Shrouded",
                "Obscured",
            ]

            prefix = random.choice(anonymous_prefixes)
            suffix = fake.word().capitalize()
            number = fake.random_int(min=10, max=999)
            anonymous_identifier = f"{prefix}{suffix}{number}"

        # Randomize timestamps (last 30 days)
        created_at = timezone.now() - timedelta(
            days=random.randint(0, 30),
            hours=random.randint(0, 23),
            minutes=random.randint(0, 59),
        )

        comment = GenericComment.objects.create(
            content=content,
            content_type=content_type,
            object_id=object_id,
            profile_type=profile_type,
            profile_id=profile.id,
            parent=parent,
            depth=depth,
            like_count=random.randint(0, 50) if random.random() > 0.3 else 0,
            reply_count=0,  # Will be updated later
            created_at=created_at,
            anonymous_comment_identifier=anonymous_identifier,
            moderation_status="approved",
            is_taken_down=False,
            is_deleted=False,
        )

        return comment

    def generate_nested_replies(self, parent_comments, profiles, max_depth):
        """Generate nested replies recursively"""
        current_level_comments = parent_comments
        current_depth = 0

        while current_level_comments and current_depth < max_depth:
            next_level_comments = []

            for parent_comment in current_level_comments:
                # Probability of having replies decreases with depth
                reply_probability = max(0.1, 0.8 - (current_depth * 0.15))

                if random.random() < reply_probability:
                    # Number of replies decreases with depth
                    max_replies = max(1, 5 - current_depth)
                    num_replies = random.randint(1, max_replies)

                    for _ in range(num_replies):
                        reply = self.create_comment(
                            content_type=parent_comment.content_type,
                            object_id=parent_comment.object_id,
                            profiles=profiles,
                            depth=current_depth + 1,
                            parent=parent_comment,
                        )
                        next_level_comments.append(reply)

                    # Update parent's reply count
                    parent_comment.reply_count = num_replies
                    parent_comment.save(update_fields=["reply_count"])

            current_level_comments = next_level_comments
            current_depth += 1

            self.stdout.write(f"Generated replies at depth {current_depth}")

    def generate_anonymous_identifier(self):
        """Generate creative anonymous identifier using Faker"""
        anonymous_prefixes = [
            "Ghost",
            "Shadow",
            "Phantom",
            "Whisper",
            "Echo",
            "Void",
            "Mist",
            "Shade",
            "Cipher",
            "Enigma",
            "Mystery",
            "Unknown",
            "Hidden",
            "Veiled",
            "Masked",
            "Faceless",
            "Nameless",
            "Silent",
            "Invisible",
            "Anon",
            "Incognito",
            "Covert",
            "Secret",
            "Shrouded",
            "Obscured",
        ]

        # Choose generation method randomly
        method = random.choice(["prefix_suffix", "word_number", "color_animal"])

        if method == "prefix_suffix":
            prefix = random.choice(anonymous_prefixes)
            suffix = fake.word().capitalize()
            identifier = f"{prefix}{suffix}"
        elif method == "word_number":
            word = random.choice(anonymous_prefixes)
            number = fake.random_int(min=100, max=9999)
            identifier = f"{word}{number}"
        else:  # color_animal
            prefix = random.choice(anonymous_prefixes)
            color = fake.color_name().replace(" ", "")
            animal = random.choice(
                ["Wolf", "Raven", "Owl", "Fox", "Cat", "Hawk", "Bat"]
            )
            identifier = f"{prefix}{color}{animal}"

        # Clean up the identifier
        identifier = "".join(char for char in identifier if char.isalnum())[:30]

        return identifier
