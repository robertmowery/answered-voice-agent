# Part 3: Booking into Google Calendar, prices from a Sheet, follow-up email

What you build: four more operations on the tools API (price list, open
windows, booking, follow-up email), a dispatch calendar owned by the tools-api
service account, and a price list the office edits in Google Sheets.

## Steps

1. Price list: create a Google Sheet with the columns in
   `services/tools-api/policy/price_list.csv`, share it with the
   `tools_api_email` from `terraform output` as a reader, and set
   `price_sheet_id` in `terraform.tfvars`. Without it, the CSV is used.

2. Dispatch calendar (no key file; you impersonate the service account once):

   ```bash
   # terraform.tfvars: operator_email = "you@yourdomain.com"
   make landing-zone
   .venv/bin/python scripts/seed_workspace.py --project $PROJECT --share-with you@yourdomain.com
   # put the printed ID in terraform.tfvars as dispatch_calendar_id, then:
   make landing-zone
   ```

3. Follow-up email from your Google Workspace business email. Set
   `followup_sender` to the mailbox. Until an admin grants delegation, emails
   wait in the Firestore `outbox` collection. To send for real, a Workspace
   super admin opens Admin console > Security > Access and data control > API
   controls > Domain-wide delegation, adds the `tools_api_client_id` from
   `terraform output` with the single scope
   `https://www.googleapis.com/auth/gmail.send`, and you set
   `gmail_delegation = "on"`. Remove the grant when you're done.

4. `make services && make deploy && make evals PART=3`.

## Gotchas

- Calendar event IDs allow only `0-9` and `a-v`; the booking ID is a hex hash,
  which fits, and makes a retried booking return the same event.
- New service accounts have no Drive storage of their own, so the office owns
  the sheets and shares them; the calendar is the one thing the service
  account owns, because a secondary calendar needs no storage quota.
- The guardrail from Parts 1 and 2 must allow a booked window and a published
  price range, or it blocks the very thing this part adds.
