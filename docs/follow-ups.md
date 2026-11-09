# Follow-ups

Task: [#31](https://github.com/han33-dotcom/Sentra/issues/31). The **Follow-ups** page in the
private viewer records a brief observation, assigns an authorized reviewer, and tracks each
follow-up as open, ongoing or resolved with its full history. Notes are wellness notes for
health-and-safety conversations, not medical records.

## Who can do what

| Signed-in user | Reads | Records and updates |
| --- | --- | --- |
| Organization officer | Their organization's group follow-ups, and follow-ups about participants who currently share individual details with them | Yes |
| Organization reviewer | Same as an officer | Updates only follow-ups currently assigned to them; never opens one |
| Team operator | Every follow-up (operator access) | No; operators are not organization users |

- A follow-up is about the organization as a group, or about one participant who currently
  shares individual details with that organization (`individual` consent, open membership,
  not withdrawn). `group_only` participants never get individual follow-ups.
- If a participant later withdraws or reduces sharing, their follow-ups disappear from the
  organization's view, and the database refuses further updates about them. Team operators
  and later reports see such a follow-up as closed ("Sharing ended"), never open forever.
- The assignee must be an active officer or reviewer of the same organization.

## Notes

Brief, at most 500 characters, plain text. The page shows the guidance: wellness wording
only, about what was observed and what was agreed, with no diagnoses, medical details, names
or contact information. Notes are shown as plain text, never as formatted Markdown.

## Write path (`sql/010_follow_ups.sql`)

- Tables `org.follow_ups` and `org.follow_up_events` are append-only; every change is a new
  event, and update, delete and truncate are rejected even on the admin path.
- Writes go only through `org.open_follow_up(...)` and `org.update_follow_up(...)`. These
  security-definer functions re-check the officer, assignee, consent and note rules from the
  database's own rows. They are executable only by a new, separate `sentra_followups` role,
  which has no table privileges. **`sentra_viewer` stays read-only.**
- The signed-in e-mail comes from the viewer's Google sign-in and is passed to the function.
  The database checks that it belongs to an active officer (or the current assignee), but it
  cannot verify who is calling: anyone holding the `sentra_followups` password can record events
  as any officer. The secret must live only in the viewer's managed secrets, and the history's
  `actor` is only as trustworthy as that secret.

## Reading

- Scope comes first: an organization user's read is limited to their organization and to
  participants who currently share individual details, then to a page of the 50 follow-ups
  shown first (open and ongoing before resolved, most recently updated first).
- Each follow-up's current status, assignee and note come from its latest event, read
  separately from the history. "Latest" is the event order (`event_id`), which the row lock
  serializes; `recorded_at` is the transaction's start time, shown for display only; the history shows its latest 10 events and says when more exist.
- Egress is reserved for each page at its maximum size (about 3 KB per row) before reading.

## Operator setup (private)

1. Apply `sql/010_follow_ups.sql` after 007, as `postgres`, and set the `sentra_followups`
   password privately. The functions need their owner to read `org` tables under forced RLS,
   as `postgres` does on Supabase.
2. Add a `[followups]` section to the Streamlit secrets with only `user`
   (`sentra_followups.<project-ref>`) and `password`. Host, port, database and certificate come
   from the viewer section.

Until both are done, the page reads nothing (no follow-ups yet) and recording says it is not
configured. Writes are a few hundred bytes each; reads use the viewer's existing egress
reservation.

## Limitations

- Wellness wording is guidance; the database cannot judge note content.
- Reports (#42) will summarize follow-ups within the same boundaries.
