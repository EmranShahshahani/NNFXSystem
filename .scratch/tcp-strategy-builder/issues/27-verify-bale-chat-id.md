# 27: Verify the Bale chat id

**What to build:** A user can only switch on Bale alerts for a chat they have proven they can read. They save a chat id in the paper tab, ask for a code, the bot sends a one-time code to that chat, and they type it back. Until then Bale alerts are never sent to that chat; the in-site feed is unaffected. Changing the chat id takes the proof away. (Follow-up of ticket 22: the chat id was never verified to belong to the user.)

**Blocked by:** 22 (Paper mode and alerts)

**Status:** resolved

- [x] A code is sent to the saved chat id and only the right, unexpired code verifies it; codes are one-use, rate-limited per user, and limited in tries
- [x] Switching Bale on needs a verified chat; the notifier never sends to an unverified chat
- [x] Changing the chat id removes the verification and turns Bale off
- [x] The paper tab has the verify step; messages are in Persian
- [x] API tests for the whole handshake and the refusals

Spec: `.scratch/tcp-strategy-builder/spec.md` (story 109; ticket 22 limits)

## Resolution

`bale_verified` in the alert settings, `AlertStore.issue_code` / `check_code` (hashed, ten minutes, five tries, one a minute), `POST /api/alerts/bale/code` and `/verify`, the notifier gate, the verify step in the paper tab, ADR 10 §29. Notes: existing settings files have no `bale_verified`, so current Bale users verify once; the user must have started a chat with the bot; verified means readable by the user, not private to them.
