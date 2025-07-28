"""
Django REST Framework Serializer Integration Examples.

This module demonstrates how to integrate Django Smart Ratelimit with DRF
serializers, including rate limiting during serialization, validation,
and custom serializer methods.

Usage:
    from django_smart_ratelimit import rate_limit
    from rest_framework import serializers

    class MySerializer(serializers.ModelSerializer):
        def validate(self, attrs):
            # Apply rate limiting during validation
            return super().validate(attrs)
"""

from typing import Any, Dict, List, Optional

from rest_framework import serializers
from rest_framework.fields import SerializerMethodField

from django.utils import timezone


# Mock models for examples (replace with your actual models)
class Post:
    """Mock Post model for examples."""

    def __init__(
        self,
        id: int = 1,
        title: str = "Sample Post",
        content: str = "Content",
        author: Optional[str] = None,
        created_at: Optional[Any] = None,
    ) -> None:
        """Initialize Post instance."""
        self.id = id
        self.title = title
        self.content = content
        self.author = author
        self.created_at = created_at or timezone.now()


class Comment:
    """Mock Comment model for examples."""

    def __init__(
        self,
        id: int = 1,
        content: str = "Comment",
        post: Optional[Any] = None,
        author: Optional[str] = None,
        created_at: Optional[Any] = None,
    ) -> None:
        """Initialize Comment instance."""
        self.id = id
        self.content = content
        self.post = post
        self.author = author
        self.created_at = created_at or timezone.now()


# Example 1: Basic serializer with rate-limited validation
class PostSerializer(serializers.ModelSerializer):
    """
    Basic post serializer with rate-limited validation methods.

    This example shows how to apply rate limiting to serializer
    validation methods to prevent abuse of expensive validation logic.
    """

    class Meta:
        """Meta configuration for PostSerializer."""

        model = Post
        fields = ["id", "title", "content", "author", "created_at"]
        read_only_fields = ["id", "created_at"]

    def validate_title(self, value: str) -> str:
        """Validate title with rate limiting to prevent spam validation requests."""
        # In a real implementation, you would access the request context
        # request = self.context.get('request')
        # Apply rate limiting based on user or IP

        if len(value) < 3:
            raise serializers.ValidationError(
                "Title must be at least 3 characters long"
            )
        if len(value) > 200:
            raise serializers.ValidationError("Title cannot exceed 200 characters")

        # Simulate expensive validation (e.g., checking against spam database)
        banned_words = ["spam", "fake", "scam"]
        if any(word in value.lower() for word in banned_words):
            raise serializers.ValidationError("Title contains prohibited content")

        return value

    def validate_content(self, value: str) -> str:
        """Validate content with rate limiting."""
        if len(value) < 10:
            raise serializers.ValidationError(
                "Content must be at least 10 characters long"
            )
        if len(value) > 10000:
            raise serializers.ValidationError("Content cannot exceed 10,000 characters")

        return value

    def validate(self, attrs: dict) -> dict:
        """Global validation with rate limiting."""
        # Check for duplicate posts (expensive operation)
        title = attrs.get("title", "")
        content = attrs.get("content", "")

        if title and content and title.lower() == content.lower():
            raise serializers.ValidationError("Title and content cannot be identical")

        return super().validate(attrs)


# Example 2: Serializer with rate-limited method fields
class AdvancedPostSerializer(serializers.ModelSerializer):
    """
    Advanced post serializer with rate-limited SerializerMethodField.

    This example shows how to rate limit expensive computed fields
    that might involve complex calculations or external API calls.
    """

    # Method fields that might be expensive to compute
    popularity_score = SerializerMethodField()
    related_posts = SerializerMethodField()
    sentiment_analysis = SerializerMethodField()
    translation_available = SerializerMethodField()

    class Meta:
        """Meta configuration for AdvancedPostSerializer."""

        model = Post
        fields = [
            "id",
            "title",
            "content",
            "author",
            "created_at",
            "popularity_score",
            "related_posts",
            "sentiment_analysis",
            "translation_available",
        ]
        read_only_fields = ["id", "created_at"]

    def get_popularity_score(self, _obj: Any) -> Dict[str, Any]:
        """
        Calculate popularity score (expensive operation).

        In a real implementation, this might involve:
        - Database queries for likes, comments, shares
        - External analytics API calls
        - Complex algorithmic calculations
        """
        # Simulate expensive calculation
        return {
            "score": 85.5,
            "rank": "high",
            "trending": True,
            "last_updated": timezone.now().isoformat(),
        }

    def get_related_posts(self, _obj: Any) -> List[Dict[str, Any]]:
        """
        Get related posts (expensive operation).

        This might involve:
        - Machine learning recommendations
        - Complex database queries
        - External recommendation engine API calls
        """
        # Simulate expensive related post calculation
        return [
            {"id": 2, "title": "Related Post 1", "similarity": 0.85},
            {"id": 3, "title": "Related Post 2", "similarity": 0.72},
            {"id": 4, "title": "Related Post 3", "similarity": 0.68},
        ]

    def get_sentiment_analysis(self, _obj: Any) -> Dict[str, Any]:
        """
        Perform sentiment analysis (expensive operation).

        This might involve:
        - Natural language processing
        - External sentiment analysis API calls
        - Machine learning model inference
        """
        # Simulate expensive sentiment analysis
        return {
            "sentiment": "positive",
            "confidence": 0.92,
            "emotions": ["joy", "satisfaction"],
            "language": "en",
        }

    def get_translation_available(self, _obj: Any) -> Dict[str, Any]:
        """
        Check available translations (expensive operation).

        This might involve:
        - Translation service API calls
        - Language detection
        - Translation quality assessment
        """
        # Simulate expensive translation check
        return {
            "available_languages": ["es", "fr", "de", "pt"],
            "auto_translate": True,
            "quality_score": 0.88,
        }


# Example 3: Nested serializer with rate-limited operations
class CommentSerializer(serializers.ModelSerializer):
    """Comment serializer with rate-limited nested operations."""

    # Nested serializer for the author
    author_details = SerializerMethodField()
    reply_count = SerializerMethodField()
    moderation_status = SerializerMethodField()

    class Meta:
        """Meta configuration for CommentSerializer."""

        model = Comment
        fields = [
            "id",
            "content",
            "post",
            "author",
            "created_at",
            "author_details",
            "reply_count",
            "moderation_status",
        ]
        read_only_fields = ["id", "created_at"]

    def get_author_details(self, _obj: Any) -> Dict[str, Any]:
        """Get author details (potentially expensive)."""
        # In a real implementation, this might involve additional database queries
        return {
            "username": "sample_user",
            "reputation": 1250,
            "badges": ["verified", "contributor"],
            "join_date": "2023-01-15",
        }

    def get_reply_count(self, _obj: Any) -> int:
        """Get reply count (database query)."""
        # Simulate database query for reply count
        return 3

    def get_moderation_status(self, _obj: Any) -> Dict[str, Any]:
        """Get moderation status (potentially expensive)."""
        # This might involve spam detection, content analysis, etc.
        return {
            "status": "approved",
            "spam_score": 0.02,
            "toxicity_score": 0.01,
            "manual_review": False,
        }

    def validate_content(self, value: str) -> str:
        """Validate comment content with rate limiting."""
        if len(value) < 1:
            raise serializers.ValidationError("Comment cannot be empty")
        if len(value) > 1000:
            raise serializers.ValidationError("Comment cannot exceed 1,000 characters")

        # Simulate expensive content validation
        if "@" in value and "http" in value:
            raise serializers.ValidationError(
                "Comments cannot contain both @ mentions and URLs"
            )

        return value


# Example 4: Serializer with rate-limited create/update operations
class RateLimitedPostSerializer(serializers.ModelSerializer):
    """
    Post serializer with rate-limited create and update operations.

    This example shows how to implement rate limiting in serializer
    create() and update() methods to prevent abuse of expensive
    database operations.
    """

    class Meta:
        """Meta configuration for RateLimitedPostSerializer."""

        model = Post
        fields = ["id", "title", "content", "author", "created_at"]
        read_only_fields = ["id", "created_at"]

    def create(self, validated_data: Dict[str, Any]) -> Post:
        """
        Create a new post with rate limiting.

        This method might involve:
        - Database writes
        - Cache invalidation
        - Notification sending
        - Search index updates
        """
        # Get request context for rate limiting
        request = self.context.get("request")

        # In a real implementation, you would apply rate limiting here
        # based on the user or IP address from the request context
        if request:
            # Rate limiting logic would go here
            pass

        # Simulate expensive post creation operations
        post_data = {
            "id": 999,
            "title": validated_data["title"],
            "content": validated_data["content"],
            "author": validated_data.get("author", "anonymous"),
            "created_at": timezone.now(),
        }

        # Simulate additional operations
        self._send_notifications(post_data)
        self._update_search_index(post_data)
        self._invalidate_cache(post_data)

        return Post(**post_data)

    def update(self, instance: Post, validated_data: Dict[str, Any]) -> Post:
        """
        Update an existing post with rate limiting.

        This method might involve:
        - Database updates
        - Cache invalidation
        - Audit logging
        - Search index updates
        """
        # Get request context for rate limiting
        request = self.context.get("request")

        # In a real implementation, you would apply rate limiting here
        if request:
            # Rate limiting logic would go here
            pass

        # Update instance fields
        instance.title = validated_data.get("title", instance.title)
        instance.content = validated_data.get("content", instance.content)

        # Simulate expensive update operations
        self._log_changes(instance, validated_data)
        self._update_search_index(instance)
        self._invalidate_cache(instance)

        return instance

    def _send_notifications(self, _post_data: Dict[str, Any]) -> None:
        """Simulate sending notifications (expensive operation)."""

    def _update_search_index(self, _post_data: Any) -> None:
        """Simulate updating search index (expensive operation)."""

    def _invalidate_cache(self, _post_data: Any) -> None:
        """Simulate cache invalidation (expensive operation)."""

    def _log_changes(self, _instance: Post, _validated_data: Dict[str, Any]) -> None:
        """Simulate audit logging (expensive operation)."""


# Example 5: Serializer with conditional rate limiting
class ConditionalRateLimitSerializer(serializers.ModelSerializer):
    """
    Serializer with conditional rate limiting based on data characteristics.

    This example shows how to apply different rate limits based on
    the content being serialized or the user's characteristics.
    """

    class Meta:
        """Meta configuration for ConditionalRateLimitSerializer."""

        model = Post
        fields = ["id", "title", "content", "author", "created_at"]
        read_only_fields = ["id", "created_at"]

    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        """Conditional validation with different rate limits."""
        request = self.context.get("request")

        # Apply different rate limits based on content characteristics
        content_length = len(attrs.get("content", ""))

        if content_length > 5000:
            # Longer content gets stricter rate limiting
            # In a real implementation, apply stricter rate limiting here
            pass
        elif content_length > 1000:
            # Medium content gets moderate rate limiting
            # In a real implementation, apply moderate rate limiting here
            pass
        else:
            # Short content gets normal rate limiting
            # In a real implementation, apply normal rate limiting here
            pass

        # Apply different rate limits based on user characteristics
        if request and request.user.is_authenticated:
            if request.user.is_staff:
                # Staff users get higher limits
                pass
            elif hasattr(request.user, "profile") and request.user.profile.is_premium:
                # Premium users get higher limits
                pass
            else:
                # Regular users get normal limits
                pass

        return super().validate(attrs)


# Example 6: Serializer with rate-limited field validation
class FieldRateLimitedSerializer(serializers.ModelSerializer):
    """
    Serializer with rate limiting on individual field validation.

    This example shows how to apply rate limiting to specific
    field validation methods that might be expensive.
    """

    class Meta:
        """Meta configuration for FieldRateLimitedSerializer."""

        model = Post
        fields = ["id", "title", "content", "author", "created_at"]
        read_only_fields = ["id", "created_at"]

    def validate_title(self, value: str) -> str:
        """Title validation with rate limiting."""
        # In a real implementation, you would apply rate limiting here
        # based on the user or IP address before performing expensive operations

        # Simulate expensive title validation
        if self._is_duplicate_title(value):
            raise serializers.ValidationError("A post with this title already exists")

        if self._is_spam_title(value):
            raise serializers.ValidationError("Title appears to be spam")

        if self._is_inappropriate_title(value):
            raise serializers.ValidationError("Title contains inappropriate content")

        return value

    def validate_content(self, value: str) -> str:
        """Content validation with rate limiting."""
        # In a real implementation, you would apply rate limiting here

        # Simulate expensive content validation
        if self._is_duplicate_content(value):
            raise serializers.ValidationError("Similar content already exists")

        if self._is_spam_content(value):
            raise serializers.ValidationError("Content appears to be spam")

        if self._contains_malicious_links(value):
            raise serializers.ValidationError("Content contains suspicious links")

        return value

    def _is_duplicate_title(self, _title: str) -> bool:
        """Simulate expensive duplicate title check."""
        # This might involve database queries, fuzzy matching, etc.
        return False

    def _is_spam_title(self, _title: str) -> bool:
        """Simulate expensive spam detection."""
        # This might involve ML model inference, external API calls, etc.
        return False

    def _is_inappropriate_title(self, _title: str) -> bool:
        """Simulate expensive content moderation."""
        # This might involve content filtering APIs, ML models, etc.
        return False

    def _is_duplicate_content(self, _content: str) -> bool:
        """Simulate expensive duplicate content check."""
        return False

    def _is_spam_content(self, _content: str) -> bool:
        """Simulate expensive spam content detection."""
        return False

    def _contains_malicious_links(self, _content: str) -> bool:
        """Simulate expensive malicious link detection."""
        return False


# Example 7: Bulk serializer with rate limiting
class BulkPostSerializer(serializers.ListSerializer):
    """
    Bulk serializer with rate limiting for batch operations.

    This example shows how to apply rate limiting to bulk
    create/update operations that might be expensive.
    """

    def create(self, validated_data: List[Dict[str, Any]]) -> List[Post]:
        """
        Bulk create with rate limiting.

        This method applies rate limiting based on:
        - Number of items being created
        - User permissions
        - System load
        """
        request = self.context.get("request")
        batch_size = len(validated_data)

        # Apply rate limiting based on request context
        if request:
            # Rate limiting logic would go here
            pass

        # Apply different rate limits based on batch size
        if batch_size > 100:
            # Very large batches get strict rate limiting
            # In a real implementation, apply strict rate limiting here
            pass
        elif batch_size > 20:
            # Medium batches get moderate rate limiting
            # In a real implementation, apply moderate rate limiting here
            pass
        else:
            # Small batches get normal rate limiting
            # In a real implementation, apply normal rate limiting here
            pass

        # Create posts in batches to avoid overwhelming the system
        created_posts: List[Post] = []
        for item_data in validated_data:
            post = Post(
                id=len(created_posts) + 1000,
                title=item_data["title"],
                content=item_data["content"],
                author=item_data.get("author", "anonymous"),
                created_at=timezone.now(),
            )
            created_posts.append(post)

        return created_posts

    def update(
        self, instance: List[Post], validated_data: List[Dict[str, Any]]
    ) -> List[Post]:
        """Bulk update with rate limiting."""
        request = self.context.get("request")

        # Apply rate limiting based on update complexity
        # In a real implementation, apply appropriate rate limiting here
        if request:
            # Rate limiting logic would go here
            pass

        # Update instances
        updated_posts = []
        for i, item_data in enumerate(validated_data):
            if i < len(instance):
                post = instance[i]
                post.title = item_data.get("title", post.title)
                post.content = item_data.get("content", post.content)
                updated_posts.append(post)

        return updated_posts


# Usage example for bulk serializer
class BulkPostItemSerializer(serializers.ModelSerializer):
    """Individual item serializer for bulk operations."""

    class Meta:
        """Meta configuration for BulkPostItemSerializer."""

        model = Post
        fields = ["id", "title", "content", "author", "created_at"]
        read_only_fields = ["id", "created_at"]
        list_serializer_class = BulkPostSerializer


# Example 8: Serializer with rate-limited external API calls
class ExternalAPISerializer(serializers.ModelSerializer):
    """
    Serializer that makes external API calls with rate limiting.

    This example shows how to rate limit serializers that make
    external API calls during serialization or validation.
    """

    enriched_data = SerializerMethodField()
    validation_result = SerializerMethodField()

    class Meta:
        """Meta configuration for ExternalAPISerializer."""

        model = Post
        fields = [
            "id",
            "title",
            "content",
            "author",
            "created_at",
            "enriched_data",
            "validation_result",
        ]
        read_only_fields = ["id", "created_at"]

    def get_enriched_data(self, _obj: Post) -> Dict[str, Any]:
        """
        Get enriched data from external API with rate limiting.

        This method might involve:
        - Calls to content enrichment APIs
        - Social media API calls
        - Analytics API calls
        """
        # In a real implementation, apply rate limiting here
        # before making external API calls

        # Simulate external API call
        return {
            "social_mentions": 42,
            "external_links": 3,
            "domain_authority": 85,
            "seo_score": 92,
        }

    def get_validation_result(self, _obj: Post) -> Dict[str, Any]:
        """
        Get validation result from external service with rate limiting.

        This method might involve:
        - Spam detection API calls
        - Content moderation API calls
        - Fact-checking API calls
        """
        # In a real implementation, apply rate limiting here
        # before making external API calls

        # Simulate external validation API call
        return {
            "spam_probability": 0.02,
            "toxicity_score": 0.01,
            "fact_check_status": "verified",
            "content_quality": "high",
        }

    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        """Validate serializer data with external API calls and rate limiting."""
        # In a real implementation, apply rate limiting here
        # before making external API calls for validation

        # Simulate external validation
        title = attrs.get("title", "")
        content = attrs.get("content", "")

        # Simulate external spam detection API call
        if self._check_spam_external(title, content):
            raise serializers.ValidationError(
                "Content flagged as spam by external service"
            )

        return super().validate(attrs)

    def _check_spam_external(self, _title: str, _content: str) -> bool:
        """Simulate external spam detection API call."""
        # This would involve actual API calls to spam detection services
        return False


# Usage Examples and Best Practices

"""
USAGE EXAMPLES:

1. ViewSet Integration:

   from rest_framework import viewsets
   from django_smart_ratelimit import rate_limit

   class PostViewSet(viewsets.ModelViewSet):
       serializer_class = PostSerializer

       @rate_limit(key='user', rate='50/m')
       def create(self, request, *args, **kwargs):
           return super().create(request, *args, **kwargs)

2. Custom Rate Limiting in Serializers:

   class CustomPostSerializer(serializers.ModelSerializer):
       def validate(self, attrs):
           request = self.context.get('request')

           # Apply custom rate limiting logic
           if request and request.user.is_authenticated:
               # Check user-specific rate limits
               pass

           return super().validate(attrs)

3. Rate Limiting Method Fields:

   class PostSerializer(serializers.ModelSerializer):
       expensive_field = SerializerMethodField()

       def get_expensive_field(self, obj):
           # Apply rate limiting before expensive operations
           request = self.context.get('request')
           # ... rate limiting logic ...

           # Perform expensive operation
           return self.calculate_expensive_value(obj)

4. Conditional Rate Limiting:

   class ConditionalSerializer(serializers.ModelSerializer):
       def validate(self, attrs):
           request = self.context.get('request')

           # Apply different rate limits based on conditions
           if len(attrs.get('content', '')) > 1000:
               # Apply stricter rate limiting for long content
               pass

           return super().validate(attrs)

BEST PRACTICES:

1. Rate Limit Expensive Operations:
   - Apply rate limiting to expensive validation methods
   - Rate limit external API calls in method fields
   - Rate limit complex database operations

2. Use Appropriate Keys:
   - Use 'user' key for authenticated operations
   - Use 'ip' key for anonymous operations
   - Use custom keys for specific use cases

3. Set Reasonable Limits:
   - Consider the computational cost of operations
   - Account for legitimate use cases
   - Adjust limits based on user roles

4. Handle Errors Gracefully:
   - Provide clear error messages
   - Include retry information
   - Log rate limiting events

5. Monitor and Adjust:
   - Track rate limiting effectiveness
   - Monitor false positives
   - Adjust limits based on usage patterns

6. Consider Caching:
   - Cache expensive method field results
   - Use cached validation results when possible
   - Implement smart cache invalidation

7. Test Thoroughly:
   - Test rate limiting under various conditions
   - Test with different user roles
   - Test bulk operations
   - Test external API failures

8. Documentation:
   - Document rate limiting behavior
   - Provide examples for API consumers
   - Include rate limit information in API documentation
"""
