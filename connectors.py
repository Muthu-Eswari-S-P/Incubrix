
from uuid import uuid4
from threading import Lock
from typing import Any
import hashlib
import json

from fastapi import APIRouter, Body, Header, HTTPException

router = APIRouter()

# Temporary mock platform storage.
# Data will be lost when the application restarts.
posts: dict[str, dict] = {}
idempotency_records: dict[str, dict] = {}
lock = Lock()


def make_error(
    code: str,
    message: str,
    retryable: bool = False,
    details: dict | None = None
):
    return {
        "error": {
            "code": code,
            "message": message,
            "retryable": retryable,
            "details": details or {}
        }
    }


def validate(rendition: dict, destination: dict):
    violations = []

    title = rendition.get("title", "")
    body = rendition.get("body", "")

    spec = destination.get("spec", {})
    title_limit = spec.get("title_max_chars", 255)
    body_limit = spec.get("body_max_chars", 32000)

    if not isinstance(title, str):
        violations.append({
            "field": "title",
            "reason": "Title must be a string"
        })
    elif len(title) > title_limit:
        violations.append({
            "field": "title",
            "reason": f"Title exceeds {title_limit} characters"
        })

    if not isinstance(body, str):
        violations.append({
            "field": "body",
            "reason": "Body must be a string"
        })
    elif len(body) > body_limit:
        violations.append({
            "field": "body",
            "reason": f"Body exceeds {body_limit} characters"
        })

    return {
        "ok": len(violations) == 0,
        "violations": violations
    }


def publish(
    rendition: dict,
    destination: dict,
    idempotency_key: str
):
    # Identify the request payload.
    request_hash = hashlib.sha256(
        json.dumps(
            {
                "rendition": rendition,
                "destination": destination
            },
            sort_keys=True,
            default=str
        ).encode("utf-8")
    ).hexdigest()

    with lock:
        # Check whether this key was already used.
        existing = idempotency_records.get(idempotency_key)

        if existing:
            if existing["request_hash"] != request_hash:
                raise HTTPException(
                    status_code=409,
                    detail=make_error(
                        "IDEMPOTENCY_KEY_CONFLICT",
                        "This Idempotency-Key was already used "
                        "with a different request"
                    )
                )

            # Return the original result for a retry.
            return existing["response"]

        # Validate before creating a post.
        result = validate(rendition, destination)

        if not result["ok"]:
            raise HTTPException(
                status_code=422,
                detail=make_error(
                    "VALIDATION_FAILED",
                    "The post contains validation errors",
                    details={
                        "violations": result["violations"]
                    }
                )
            )

        # Create a mock published post.
        post_id = str(uuid4())

        response = {
            "platform_post_id": post_id,
            "status": "published",
            "live_url": (
                f"https://discourse.example.com/posts/{post_id}"
            )
        }

        posts[post_id] = {
            "status": "published",
            "live_url": response["live_url"],
            "rendition": rendition,
            "destination": destination
        }

        # Store the original result against the idempotency key.
        idempotency_records[idempotency_key] = {
            "request_hash": request_hash,
            "response": response
        }

        return response


@router.post("/connector/v1/{connector_key}/{method}")
async def connector_method(
    connector_key: str,
    method: str,
    data: dict[str, Any] = Body(...),
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key"
    )
):
    if connector_key != "discourse":
        raise HTTPException(
            status_code=404,
            detail=make_error(
                "CONNECTOR_DISABLED",
                f"Unknown connector: {connector_key}"
            )
        )

    if method == "validate":
        rendition = data.get("rendition", {})
        destination = data.get("destination", {})

        return validate(rendition, destination)

    elif method == "publish":
        rendition = data.get("rendition", {})
        destination = data.get("destination", {})

        if not idempotency_key or not idempotency_key.strip():
            raise HTTPException(
                status_code=400,
                detail=make_error(
                    "IDEMPOTENCY_KEY_REQUIRED",
                    "Provide the Idempotency-Key header"
                )
            )

        return publish(
            rendition,
            destination,
            idempotency_key.strip()
        )

    elif method == "get_status":
        post_id = data.get("platform_post_id")

        with lock:
            post = posts.get(post_id)

            if not post:
                raise HTTPException(
                    status_code=404,
                    detail=make_error(
                        "POST_NOT_FOUND",
                        "Post was not found"
                    )
                )

            return {
                "status": post["status"],
                "live_url": post["live_url"]
            }

    elif method == "delete":
        post_id = data.get("platform_post_id")

        with lock:
            post = posts.get(post_id)

            if not post or post["status"] == "deleted":
                raise HTTPException(
                    status_code=404,
                    detail=make_error(
                        "POST_NOT_FOUND",
                        "Active post was not found"
                    )
                )

            post["status"] = "deleted"
            post["live_url"] = None

        return {"deleted": True}

    else:
        raise HTTPException(
            status_code=400,
            detail=make_error(
                "UNSUPPORTED_METHOD",
                f"Unsupported method: {method}"
            )
        )
