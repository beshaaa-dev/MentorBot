"""
CLI script: inspect and clear persisted ConversationHandler states for a user.

A user stuck in a persisted conversation (e.g. an unfinished survey) can have
their updates swallowed by that handler forever, because it is registered before
the /start conversation. This script removes their entries so /start works again.

Usage:
    python scripts/clear_stuck_conversation.py <tg_user_id>                  # dry run
    python scripts/clear_stuck_conversation.py <tg_user_id> --apply
    python scripts/clear_stuck_conversation.py <tg_user_id> --apply --conversation survey_questions

Stop the bot before running with --apply: it flushes its in-memory state to the
pickle every 60 seconds and on shutdown, which would undo the change.
"""

import argparse
import os
import pickle
import shutil
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_DEFAULT_PICKLE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "bot_persistence.pickle",
)


def _load(path: str) -> dict:
    with open(path, "rb") as file:
        return pickle.load(file)


def _matching_keys(conversations: dict, user_id: int, include_ended: bool) -> dict:
    """Map conversation name -> list of keys belonging to the user.

    Keys are tuples of ids whose shape depends on per_chat/per_user; matching on
    membership covers every combination. A state of None means the conversation
    already ended, so those entries are inert and skipped unless asked for.
    """
    found = {}
    for name, states in conversations.items():
        keys = [
            key
            for key, state in states.items()
            if user_id in key and (include_ended or state is not None)
        ]
        if keys:
            found[name] = keys
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("user_id", type=int, help="Telegram user id")
    parser.add_argument(
        "--conversation",
        help="Only clear this conversation (default: all conversations)",
    )
    parser.add_argument("--pickle", default=_DEFAULT_PICKLE, help="Path to the persistence file")
    parser.add_argument(
        "--include-ended",
        action="store_true",
        help="Also match entries whose state is None (already-finished conversations)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write the change. Without it the script only reports what it would remove.",
    )
    args = parser.parse_args()

    if not os.path.exists(args.pickle):
        print(f"Persistence file not found: {args.pickle}")
        sys.exit(1)

    data = _load(args.pickle)
    conversations = data.get("conversations", {})

    found = _matching_keys(conversations, args.user_id, args.include_ended)
    if args.conversation:
        found = {k: v for k, v in found.items() if k == args.conversation}

    if not found:
        target = args.conversation or "any conversation"
        print(f"User {args.user_id} has no active persisted state in {target}. Nothing to do.")
        return

    for name, keys in found.items():
        for key in keys:
            print(f"{name}: key={key} state={conversations[name][key]!r}")

    if not args.apply:
        print("\nDry run. Re-run with --apply to remove these entries.")
        return

    backup = f"{args.pickle}.backup_{datetime.now():%Y%m%d_%H%M%S}"
    shutil.copy2(args.pickle, backup)
    print(f"\nBackup written to {backup}")

    removed = 0
    for name, keys in found.items():
        for key in keys:
            del conversations[name][key]
            removed += 1

    with open(args.pickle, "wb") as file:
        pickle.dump(data, file)

    print(f"Removed {removed} entr{'y' if removed == 1 else 'ies'}. Restart the bot.")


if __name__ == "__main__":
    main()
