---
name: message-owner
description: Send a proactive message to your operator. Use when you need input, hit a blocker, or want to report progress.
---

# Message Owner

Send a message to your operator proactively.

## Steps

1. **Compose** — Write a clear, concise message. Include context about what you're working on and what you need.

2. **Send** — Use `send_message(cogamer_name="operator", message=<your message>)` to deliver it. The operator will see it next time they check.

3. **Continue** — Don't block waiting for a response. Continue with other work if possible, or move to the next task.
