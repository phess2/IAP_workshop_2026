import asyncio
import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .config import settings

FEEDBACK_FILE = Path(".workshop_2_feedback.json")


class Decision(Enum):
    """Possible decisions for approval workflow."""

    ACCEPT = "accept"
    REJECT = "reject"
    EDIT = "edit"


@dataclass
class ApprovalResult:
    """Result of an approval request."""

    decision: Decision
    edited_content: Optional[str] = None
    feedback: Optional[str] = None


def load_feedback() -> dict:
    """Load the feedback file."""
    if FEEDBACK_FILE.exists():
        with open(FEEDBACK_FILE) as f:
            return json.load(f)
    return {"rejections": []}


def save_feedback(feedback_data: dict) -> None:
    """Save the feedback file."""
    with open(FEEDBACK_FILE, "w") as f:
        json.dump(feedback_data, f, indent=2, default=str)


def store_rejection(
    original_content: str,
    feedback: str,
    content_type: str = "post",
    page_title: Optional[str] = None,
    post_author: Optional[str] = None,
) -> None:
    """
    Store a rejection with feedback to the feedback file.

    Args:
        original_content: The content that was rejected
        feedback: The reason for rejection
        content_type: Either "post" or "reply"
        page_title: Title of the Notion page (for posts)
        post_author: Author of the original post (for replies)
    """
    data = load_feedback()

    rejection = {
        "timestamp": datetime.now().isoformat(),
        "type": content_type,
        "original_content": original_content,
        "feedback": feedback,
    }

    if page_title:
        rejection["page_title"] = page_title
    if post_author:
        rejection["post_author"] = post_author

    data["rejections"].append(rejection)
    save_feedback(data)


async def request_approval(
    content: str,
    context_info: str = "",
    content_type: str = "post",
) -> ApprovalResult:
    """
    Send content to Telegram for approval and wait for user decision.

    Args:
        content: The post/reply content to approve
        context_info: Additional context to display (e.g., page title, author)
        content_type: Either "post" or "reply" for display purposes

    Returns:
        ApprovalResult containing the decision and any edited content or feedback
    """
    # State for this approval request
    decision_result: Optional[Decision] = None
    edited_content: Optional[str] = None
    feedback_text: Optional[str] = None
    waiting_for_text: Optional[str] = None  # "edit" or "feedback"
    decision_made = asyncio.Event()

    async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        nonlocal decision_result, waiting_for_text
        query = update.callback_query
        await query.answer()

        action = query.data

        if action == "accept":
            decision_result = Decision.ACCEPT
            await query.edit_message_text(
                f"✅ APPROVED\n\n{content[:500]}{'...' if len(content) > 500 else ''}"
            )
            decision_made.set()

        elif action == "reject":
            decision_result = Decision.REJECT
            waiting_for_text = "feedback"
            await query.edit_message_text(
                "❌ REJECTED\n\n"
                "Please reply with the reason for rejection.\n"
                "This feedback helps improve future content.\n\n"
                f"Original content:\n\n{content}"
            )

        elif action == "edit":
            decision_result = Decision.EDIT
            waiting_for_text = "edit"
            await query.edit_message_text(
                "✏️ EDIT MODE\n\n"
                "Please send the updated content.\n"
                "The content will be posted as-is after you send it.\n\n"
                f"Original content:\n\n{content}"
            )

    async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        nonlocal edited_content, feedback_text, waiting_for_text

        if waiting_for_text is None:
            return

        text = update.message.text

        if waiting_for_text == "edit":
            edited_content = text
            waiting_for_text = None
            await update.message.reply_text(
                f"📝 Updated content received!\n\n"
                f"New content ({len(text)} chars):\n{text[:300]}{'...' if len(text) > 300 else ''}"
            )
            decision_made.set()

        elif waiting_for_text == "feedback":
            feedback_text = text
            waiting_for_text = None
            await update.message.reply_text(f"📝 Feedback recorded: {text}")
            decision_made.set()

    # Build message text
    type_emoji = "📝" if content_type == "post" else "💬"
    type_label = "New Post" if content_type == "post" else "Reply"

    context_section = f"{context_info}\n\n" if context_info else ""
    message_text = (
        f"{type_emoji} {type_label} for Approval\n\n"
        f"{context_section}"
        f"{content}\n\n"
        f"📊 Characters: {len(content)}/500"
    )

    # Create keyboard with three buttons
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Accept", callback_data="accept"),
                InlineKeyboardButton("❌ Reject", callback_data="reject"),
                InlineKeyboardButton("✏️ Edit", callback_data="edit"),
            ]
        ]
    )

    # Send the message
    bot = Bot(token=settings.telegram_bot_token)
    await bot.send_message(
        chat_id=int(settings.telegram_chat_id),
        text=message_text,
        reply_markup=keyboard,
    )
    print(f"📱 Sent {content_type} to Telegram. Waiting for approval...")

    # Set up the application and handlers
    app = Application.builder().token(settings.telegram_bot_token).build()
    app.add_handler(CallbackQueryHandler(handle_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Start polling
    await app.initialize()
    await app.start()
    await app.updater.start_polling()

    # Wait for decision
    await decision_made.wait()

    # Cleanup
    await app.updater.stop()
    await app.stop()
    await app.shutdown()

    return ApprovalResult(
        decision=decision_result,
        edited_content=edited_content,
        feedback=feedback_text,
    )


async def request_approval_batch(
    items: list[tuple[str, str, str, dict]],
) -> dict[str, ApprovalResult]:
    """
    Send multiple items for approval and wait for all decisions.

    Args:
        items: List of tuples (item_id, content, context_info, metadata)
               metadata can contain page_title, post_author, etc.

    Returns:
        Dict mapping item_id to ApprovalResult
    """
    # State for batch approval
    results: dict[str, ApprovalResult] = {}
    pending: dict[int, tuple[str, str, dict]] = {}  # message_id -> (item_id, content, metadata)
    waiting_for_text: dict[int, tuple[str, str]] = {}  # chat message context -> (item_id, "edit"/"feedback")
    decisions_remaining = len(items)
    all_done = asyncio.Event()

    async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        nonlocal decisions_remaining
        query = update.callback_query
        await query.answer()

        message_id = query.message.message_id
        if message_id not in pending:
            return

        item_id, content, metadata = pending[message_id]
        action = query.data

        if action == "accept":
            results[item_id] = ApprovalResult(decision=Decision.ACCEPT)
            await query.edit_message_text(
                f"✅ APPROVED\n\n{content[:300]}{'...' if len(content) > 300 else ''}"
            )
            decisions_remaining -= 1
            del pending[message_id]

        elif action == "reject":
            waiting_for_text[message_id] = (item_id, "feedback", content, metadata)
            await query.edit_message_text(
                "❌ REJECTED\n\n"
                "Please reply with the reason for rejection.\n\n"
                f"Original content:\n\n{content}"
            )

        elif action == "edit":
            waiting_for_text[message_id] = (item_id, "edit", content, metadata)
            await query.edit_message_text(
                "✏️ EDIT MODE\n\n"
                "Please send the updated content.\n\n"
                f"Original content:\n\n{content}"
            )

        if decisions_remaining == 0:
            all_done.set()

    async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        nonlocal decisions_remaining

        # Find which item this text response is for
        # We'll use the most recent pending text request
        if not waiting_for_text:
            return

        # Get the first (oldest) pending text request
        message_id = next(iter(waiting_for_text))
        item_id, text_type, content, metadata = waiting_for_text[message_id]

        text = update.message.text

        if text_type == "edit":
            results[item_id] = ApprovalResult(
                decision=Decision.EDIT, edited_content=text
            )
            await update.message.reply_text("📝 Updated content received for item!")

        elif text_type == "feedback":
            results[item_id] = ApprovalResult(
                decision=Decision.REJECT, feedback=text
            )
            await update.message.reply_text(f"📝 Feedback recorded: {text}")

        del waiting_for_text[message_id]
        if message_id in pending:
            del pending[message_id]
        decisions_remaining -= 1

        if decisions_remaining == 0:
            all_done.set()

    # Send all items
    bot = Bot(token=settings.telegram_bot_token)
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Accept", callback_data="accept"),
                InlineKeyboardButton("❌ Reject", callback_data="reject"),
                InlineKeyboardButton("✏️ Edit", callback_data="edit"),
            ]
        ]
    )

    for item_id, content, context_info, metadata in items:
        context_section = f"{context_info}\n\n" if context_info else ""
        message_text = (
            f"💬 Reply for Approval [{item_id}]\n\n"
            f"{context_section}"
            f"{content}\n\n"
            f"📊 Characters: {len(content)}/500"
        )

        message = await bot.send_message(
            chat_id=int(settings.telegram_chat_id),
            text=message_text,
            reply_markup=keyboard,
        )
        pending[message.message_id] = (item_id, content, metadata)

    print(f"📱 Sent {len(items)} items to Telegram. Waiting for approvals...")

    # Set up the application and handlers
    app = Application.builder().token(settings.telegram_bot_token).build()
    app.add_handler(CallbackQueryHandler(handle_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Start polling
    await app.initialize()
    await app.start()
    await app.updater.start_polling()

    # Wait for all decisions
    await all_done.wait()

    # Cleanup
    await app.updater.stop()
    await app.stop()
    await app.shutdown()

    return results
