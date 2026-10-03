# Posting date editor — 2026-10-03

Generated designs now offer Change posting date. A single inline date/time field
uses Africa/Cairo, with Save date and Cancel. Editing is available before plan
approval, once the batch is complete. The plan's week bounds are shown by the
native picker; approval is disabled while an editor is open.

The CSRF-protected schedule PATCH requires workspace write access, locks the
workspace and latest draft, and checks the previous timestamp. It rejects past,
conflicting, outside-week, nonexistent and ambiguous Cairo times. Scheduling
changes only the plan item, preserving artwork, captions and generation history;
review and package schedules use the new time.

Validation: 22 targeted integration tests passed (9 posting-date scenarios and
13 owner-control scenarios), 11 UI tests passed, and production build passed.
Browser verification used an isolated SQLite test workspace and synthetic images,
with no external providers or publishing connection. Save changed 29 December
11:00 to 30 December 15:30 Cairo; refresh retained it. Cancel discarded a subsequent
31 December edit. Browser console showed no errors or warnings. The final form
reads the submitted input directly through FormData. Screenshot:
../../.runtime/posting-date-editor.png.

The owner's deleted plan was left deleted. API was restarted with the new route;
the tunnel and browser helper were preserved. No posts were approved or published.
