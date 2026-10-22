# Part 1: A real phone number answered by CX Agent Studio

What you build: Brightwater Home Services' front desk (fictional company) as a
CX Agent Studio app deployed from files, an API test channel, a smoke test, a
$40 budget with a hard stop, and a Google-provisioned US phone number.

Cost: about $5 (eight smoke-test sessions at $0.50, plus a few test calls).

## Prerequisites

- A new Google Cloud project with billing linked (the kill switch can unlink it).
- Python 3.11+, Terraform 1.9+, gcloud CLI.
- `gcloud auth login` and `gcloud auth application-default login`.

## Steps

1. Landing zone and budget kill switch:

   ```bash
   cp infra/terraform/terraform.tfvars.example infra/terraform/terraform.tfvars
   # set project_id, billing_account, budget_usd
   export PROJECT=your-project-id
   make venv
   make landing-zone
   ```

2. Raise the CX Agent Studio token quota before testing. In the console, open
   IAM and admin > Quotas and system limits, filter for
   `RunSessionLLMTokensPerMinutePerProjectPerRegionPerBaseModel`, select the
   row for the model in `agent/app.yaml` (`gemini-3.8-flash`) in region `us`,
   and request a higher value (60,000 was granted within minutes in our test).
   The default of 1,000 tokens per minute is about one conversation turn.

3. Deploy the agent and run the smoke test:

   ```bash
   make deploy
   make smoke      # writes results/part1/smoke.json
   ```

4. Attach a phone number (console only). In CX Agent Studio
   (ces.cloud.google.com), open the app, then Deploy > New channel > Connect
   platform > Google Telephony Platform (GTP) > Standard phone number (PSTN).
   Choose the version the deploy script created, set modality to Voice, and
   create the channel. Google assigns the number.

5. Call it. Try: "What are your hours on Saturday?", "I smell gas in my
   basement," "How much is a new water heater?", and "Am I talking to a real
   person?"

## Tear down

Release the phone number in the console (Deploy > the GTP channel > Delete),
then run `make teardown`.

## Gotchas

- Resource IDs must be 5 to 36 characters (`[a-zA-Z0-9][a-zA-Z0-9-_]{4,35}`).
- Real phone numbers exist only in the `us` location.
- Budgets alert; they don't stop spending. The shutoff function does.
- A new project's first service account creation fails until the IAM API is
  enabled; the Terraform has `depends_on` for this.
- Pin the model. Token quotas are per base model.
