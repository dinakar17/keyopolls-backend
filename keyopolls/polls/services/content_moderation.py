import base64
import io
import json
import logging
from typing import Dict, List, Optional, Tuple

import anthropic
from django.conf import settings
from django.core.files.uploadedfile import UploadedFile
from PIL import Image

logger = logging.getLogger(__name__)


class ContentModerationService:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        self.max_image_size = 5 * 1024 * 1024  # 5MB
        self.allowed_formats = ["JPEG", "PNG", "GIF", "WEBP"]

    def evaluate_poll_content(
        self,
        poll_title: str,
        poll_description: str,
        poll_options: List[str],
        community_name: str,
        community_description: str,
        community_rules: List[str],
        category_name: str,
        category_description: str,
        community_type: str = "public",
        option_images: Optional[List[UploadedFile]] = None,
    ) -> Tuple[bool, str, Dict]:
        """
        Evaluate if poll content (text + images) is appropriate,
        relevant to the category, and follows community rules.

        Returns:
            Tuple of (is_appropriate, reason, detailed_analysis)
        """

        try:
            # Process images if provided
            processed_images = []
            if option_images:
                processed_images = self._process_images(option_images)

            # Construct the prompt for Claude
            prompt = self._build_moderation_prompt(
                poll_title,
                poll_description,
                poll_options,
                community_name,
                community_description,
                community_rules,
                category_name,
                category_description,
                community_type,
            )

            # Prepare messages with images
            messages = self._prepare_messages_with_images(prompt, processed_images)

            response = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1500,
                temperature=0.1,  # Low temperature for consistent moderation
                messages=messages,
            )

            # Parse Claude's response
            return self._parse_moderation_response(response.content[0].text)

        except Exception as e:
            logger.error(f"Error calling Claude API: {str(e)}")
            # Fallback to reject content if API fails (safer approach)
            return False, f"Moderation service error: {str(e)}", {}

    def _process_images(self, images: List[UploadedFile]) -> List[Dict]:
        """Process and validate uploaded images"""
        processed_images = []

        for i, image_file in enumerate(images):
            try:
                # Validate file size
                if image_file.size > self.max_image_size:
                    logger.warning(f"Image {i} too large: {image_file.size} bytes")
                    continue

                # Read and validate image
                image_data = image_file.read()
                image_file.seek(0)  # Reset file pointer

                # Validate image format
                try:
                    with Image.open(io.BytesIO(image_data)) as img:
                        if img.format not in self.allowed_formats:
                            logger.warning(f"Image {i} invalid format: {img.format}")
                            continue

                        # Resize if too large (for API efficiency)
                        if img.width > 1024 or img.height > 1024:
                            img.thumbnail((1024, 1024), Image.Resampling.LANCZOS)

                            # Convert back to bytes
                            output = io.BytesIO()
                            img.save(output, format=img.format, quality=85)
                            image_data = output.getvalue()

                except Exception as img_error:
                    logger.error(f"Error processing image {i}: {str(img_error)}")
                    continue

                # Encode to base64
                base64_image = base64.b64encode(image_data).decode("utf-8")

                # Determine media type
                media_type = f"image/{image_file.content_type.split('/')[-1].lower()}"
                if media_type == "image/jpg":
                    media_type = "image/jpeg"

                processed_images.append(
                    {
                        "index": i,
                        "data": base64_image,
                        "media_type": media_type,
                        "filename": image_file.name,
                    }
                )

            except Exception as e:
                logger.error(f"Error processing image {i}: {str(e)}")
                continue

        return processed_images

    def _prepare_messages_with_images(
        self, prompt: str, images: List[Dict]
    ) -> List[Dict]:
        """Prepare messages array with text and images for Claude API"""

        content = [{"type": "text", "text": prompt}]

        # Add images to content
        for image_info in images:
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": image_info["media_type"],
                        "data": image_info["data"],
                    },
                }
            )

        return [{"role": "user", "content": content}]

    def _build_moderation_prompt(
        self,
        title: str,
        description: str,
        options: List[str],
        community_name: str,
        community_description: str,
        community_rules: List[str],
        category_name: str,
        category_description: str,
        community_type: str,
    ) -> str:
        """Build the moderation prompt for Claude"""

        options_text = "\n".join([f"- {option}" for option in options])
        rules_text = (
            "\n".join([f"- {rule}" for rule in community_rules])
            if community_rules
            else "No specific rules"
        )

        prompt = f"""
(
    "You are a content moderator for an online community platform. "
    "Please evaluate whether this poll is appropriate and follows the guidelines."
)

CATEGORY INFORMATION:
Name: {category_name}
Description: {category_description}

COMMUNITY INFORMATION:
Name: {community_name}
Type: {community_type}
Description: {community_description}

COMMUNITY RULES:
{rules_text}

POLL TO EVALUATE:
Title: {title}
Description: {description}
Options:
{options_text}

MODERATION CRITERIA:

1. CATEGORY RELEVANCE:
   - Content must be relevant to the category "{category_name}"
   - Poll topic should align with the category's purpose and description

2. IMAGE QUALITY & CONTENT (if images provided):
   - Images must be of reasonable quality (not blurry, pixelated, or low-effort)
   - No offensive content (hate symbols, inappropriate imagery, etc.)
   - Images should be relevant to the poll options

3. COMMUNITY RULES COMPLIANCE:
   - Be fair and reasonable when evaluating community rules
   - Don't be overly strict - allow content that generally fits the community spirit
   - Focus on clear violations rather than borderline cases

(
    "Be fair and balanced in your evaluation. Approve content that generally fits "
    "the category and follows basic community guidelines, even if it's not perfect."
)

Please respond in the following JSON format:
{{
    "is_appropriate": true/false,
    "belongs_to_category": true/false,
    "images_approved": true/false,
    "follows_community_rules": true/false,
    "overall_approved": true/false,
    "reason": "Brief explanation of your decision",
    "detailed_analysis": {{
        "category_relevance": "How well content fits the category",
        "image_quality": "Assessment of image quality and appropriateness (if any)",
        "community_rules_assessment": "How well content follows community rules",
        "rule_violations": ["List any specific rule violations"],
        "suggestions": "Any suggestions for improvement (if applicable)"
    }}
}}
"""
        return prompt

    def _parse_moderation_response(self, response_text: str) -> Tuple[bool, str, Dict]:
        """Parse Claude's JSON response"""
        try:
            # Extract JSON from response (in case there's additional text)
            start = response_text.find("{")
            end = response_text.rfind("}") + 1

            if start == -1 or end == 0:
                raise ValueError("No JSON found in response")

            json_str = response_text[start:end]
            analysis = json.loads(json_str)

            is_approved = analysis.get("overall_approved", False)
            reason = analysis.get("reason", "No reason provided")
            detailed_analysis = analysis.get("detailed_analysis", {})

            return is_approved, reason, detailed_analysis

        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"Error parsing Claude response: {str(e)}")
            logger.error(f"Response text: {response_text}")
            # Default to rejection if we can't parse
            return False, "Unable to parse moderation response", {}
