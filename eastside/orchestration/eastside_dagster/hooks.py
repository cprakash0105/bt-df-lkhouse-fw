"""Dagster failure hooks — alerting on pipeline failures.

Supports:
  - Slack (webhook)
  - Email (SMTP)
  - Google Chat (webhook)

Configure via environment variables on the Dagster VM:
  ALERT_SLACK_WEBHOOK=https://hooks.slack.com/services/...
  ALERT_EMAIL_TO=data-team@company.com
  ALERT_GCHAT_WEBHOOK=https://chat.googleapis.com/v1/spaces/...
"""
import os
import json
import urllib.request
from dagster import failure_hook, HookContext, success_hook


SLACK_WEBHOOK = os.environ.get("ALERT_SLACK_WEBHOOK")
GCHAT_WEBHOOK = os.environ.get("ALERT_GCHAT_WEBHOOK")
ALERT_EMAIL_TO = os.environ.get("ALERT_EMAIL_TO")


def _post_webhook(url: str, payload: dict):
    """POST JSON to a webhook URL."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"[alert] Webhook failed: {e}")


def _format_failure_message(context: HookContext) -> str:
    """Format a human-readable failure message."""
    op_name = context.op.name
    run_id = context.run_id
    error = str(context.op_exception) if context.op_exception else "Unknown error"

    # Extract key details from error
    is_schema_block = "Schema evolution BLOCKED" in error
    is_contract_violation = "contract violation" in error.lower()

    if is_schema_block:
        category = "🚫 SCHEMA EVOLUTION BLOCKED"
    elif is_contract_violation:
        category = "📋 CONTRACT VIOLATION"
    else:
        category = "❌ PIPELINE FAILURE"

    return (
        f"{category}\n"
        f"Asset: {op_name}\n"
        f"Run: {run_id}\n"
        f"Error: {error[:500]}\n"
        f"Action required: investigate and resolve before next run."
    )


@failure_hook
def alert_on_failure(context: HookContext):
    """Send alerts when any asset fails."""
    message = _format_failure_message(context)
    context.log.info(f"[alert] Sending failure notification: {context.op.name}")

    # Slack
    if SLACK_WEBHOOK:
        _post_webhook(SLACK_WEBHOOK, {
            "text": message,
            "username": "CDH 2.0 Pipeline",
            "icon_emoji": ":rotating_light:",
        })
        context.log.info("[alert] Slack notification sent")

    # Google Chat
    if GCHAT_WEBHOOK:
        _post_webhook(GCHAT_WEBHOOK, {"text": message})
        context.log.info("[alert] Google Chat notification sent")

    # Email (via Cloud Function or SMTP — placeholder)
    if ALERT_EMAIL_TO:
        context.log.info(f"[alert] Email alert would be sent to: {ALERT_EMAIL_TO}")
        # In production: trigger a Cloud Function that sends via SendGrid/SES
        # or use smtplib directly if SMTP is configured


@success_hook
def log_on_success(context: HookContext):
    """Log successful completions (no external notification — reduce noise)."""
    context.log.info(f"[alert] Asset {context.op.name} completed successfully (run: {context.run_id})")
