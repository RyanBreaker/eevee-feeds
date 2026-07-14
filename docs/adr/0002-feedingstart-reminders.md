# FeedingStart reminders use a separate log and a 15-minute cadence

While a **FeedingStart** exists, the app sends **FeedingStart reminders** every 15 minutes after the start timestamp. These reminders are independent of the normal post-feeding reminders (2/3/4 hours after the last completed **Feeding**), which are suppressed until the feed completes or is cancelled.

We chose a separate `FeedingStartReminderLog` table instead of reusing `NotificationLog`. The two concepts have different triggers (start timestamp vs. last feeding timestamp), different units (minutes vs. hours), and different lifecycles (ephemeral vs. tied to a completed feeding). Mixing them would have conflated two different clocks and made the existing log harder to reason about.
