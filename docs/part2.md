# Part 2: Business hours in code, transfers, and after-hours tickets

What you build: the tools API (hours, on-call, tickets) on Cloud Run, a
Pub/Sub event path to a ticket worker that writes the office's Google Sheet,
and an agent that asks for the hours, transfers emergencies to the on-call
technician, and turns everything else into a ticket.

Cost: about $3 for the six eval conversations, plus pennies of Cloud Run,
Pub/Sub and Firestore.

## Steps

1. Edit `services/tools-api/policy/schedule.yaml` for your hours, holidays and
   rotation. Keep real phone numbers out of Git; set them on the service:

   ```bash
   gcloud run services update tools-api --region us-central1 --project $PROJECT \
     --update-env-vars ON_CALL_NUMBERS='Dana=+1XXXXXXXXXX,Luis=+1XXXXXXXXXX'
   ```

2. Optional: create a Google Sheet for tickets, share it with the
   `ticket_worker_email` from `terraform output` as an editor, and set
   `tickets_sheet_id` in `terraform.tfvars`. Without it, tickets stay in Firestore.

3. Build and deploy:

   ```bash
   make landing-zone   # Firestore, Pub/Sub, Cloud Run services, identities
   make services       # builds the code into those services
   make deploy         # the agent, with its toolset and transfer
   make evals PART=2   # run after hours to exercise the after-hours path
   ```

## Gotchas

- The platform calls the OpenAPI contract's `servers` URL; the deployer writes
  the deployed URL there.
- Quote YAML descriptions that contain commas.
- `end_session` is a system tool: reference it, don't create it.
- A dead-letter topic without a subscription drops messages. Terraform adds
  `tickets-dead-letter-hold`.
- Cloud Run reserves some paths ending in `z` (such as `/healthz`) at the
  Google front end; probe `/v1/...` routes instead.
- `fail_open: false` on a guardrail means a guardrail timeout (10 seconds)
  becomes the guardrail's fixed reply.
