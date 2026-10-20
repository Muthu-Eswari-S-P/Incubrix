
from datetime import datetime, timedelta, timezone
from threading import Lock
import re

# Temporary history for the local prototype.
# It resets when the application restarts.
publication_history = []
history_lock = Lock()

URL_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)


def check_rules(rendition: dict, destination: dict):
    """
    Check posting rules before publishing.

    Destination configuration example:
    {
        "destination_id": "forum-1",
        "frequency_cap": {
            "max_posts": 2,
            "window_seconds": 604800
        },
        "self_promo_allowed": False,
        "link_policy": "allowed",
        "disclosure_required": True
    }
    """

    violations = []
    now = datetime.now(timezone.utc)

    destination_id = destination.get(
        "destination_id",
        destination.get("url", destination.get("name", "default"))
    )

    # 1. Frequency cap
    cap = destination.get("frequency_cap", {})
    max_posts = cap.get("max_posts")
    window_seconds = cap.get("window_seconds", 604800)

    if max_posts is not None:
        try:
            max_posts = int(max_posts)
            window_seconds = int(window_seconds)

            if max_posts < 1 or window_seconds < 1:
                raise ValueError()

        except (TypeError, ValueError):
            violations.append({
                "rule": "frequency_cap",
                "reason": "Invalid frequency cap configuration"
            })
        else:
            cutoff = now - timedelta(seconds=window_seconds)

            with history_lock:
                recent_posts = [
                    post for post in publication_history
                    if post["destination_id"] == destination_id
                    and post["published_at"] > cutoff
                ]

            if len(recent_posts) >= max_posts:
                next_allowed = min(
                    post["published_at"] for post in recent_posts
                ) + timedelta(seconds=window_seconds)

                violations.append({
                    "rule": "frequency_cap",
                    "reason": "Destination posting frequency cap reached",
                    "retry_after": next_allowed.isoformat()
                })

    # 2. Self-promotion policy
    promotional = rendition.get("is_promotional", False)

    if promotional and not destination.get(
        "self_promo_allowed", True
    ):
        violations.append({
            "rule": "self_promotion",
            "reason": "This destination does not allow self-promotion"
        })

    # 3. Link policy
    link_policy = destination.get("link_policy", "allowed")
    text = str(rendition.get("body", ""))
    title = str(rendition.get("title", ""))

    links = rendition.get("links", [])
    if not isinstance(links, list):
        links = []

    detected_links = URL_PATTERN.findall(text + " " + title)
    all_links = list(set(links + detected_links))

    if link_policy == "no_links" and all_links:
        violations.append({
            "rule": "link_policy",
            "reason": "Links are not allowed on this destination"
        })

    elif link_policy not in (
        "allowed", "no_links", "canonical_only"
    ):
        violations.append({
            "rule": "link_policy",
            "reason": f"Unsupported link policy: {link_policy}"
        })

    elif link_policy == "canonical_only":
        canonical_url = rendition.get("canonical_url")

        if not canonical_url or any(
            link != canonical_url for link in all_links
        ):
            violations.append({
                "rule": "link_policy",
                "reason": "Only the canonical URL is allowed"
            })

    # 4. AI content disclosure
    ai_generated = rendition.get("ai_generated", False)
    ai_disclosed = rendition.get("ai_disclosed", False)
    disclosure_required = destination.get(
        "disclosure_required", False
    )

    if ai_generated and disclosure_required and not ai_disclosed:
        violations.append({
            "rule": "ai_disclosure",
            "reason": "AI-generated content must be disclosed"
        })

    return {
        "allowed": len(violations) == 0,
        "violations": violations
    }


def record_publication(destination: dict):
    """Record a successful mock publication for frequency checks."""

    destination_id = destination.get(
        "destination_id",
        destination.get("url", destination.get("name", "default"))
    )

    with history_lock:
        publication_history.append({
            "destination_id": destination_id,
            "published_at": datetime.now(timezone.utc)
        })
