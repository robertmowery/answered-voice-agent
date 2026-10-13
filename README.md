# Answered

Reference code for the article series *Answered* by Robert H. Mowery III ([robertmowery.com](https://robertmowery.com)).

Agentic voice on Google's Gemini Enterprise for Customer Experience (GECX) stack, built for small and mid-market businesses that can't afford a missed call. By the end of the series this repository is a working MVP contact center: a Google-provisioned phone number answered by a CX Agent Studio agent that routes by business hours, books jobs into Google Calendar, sells through an ADK commerce agent over A2A and the Universal Commerce Protocol, hands off to a human with context, and proves itself with evals and a cost-per-call number.

Each part pairs an executive article on Medium with a technical companion on Substack. Every number in the articles comes from code and results files in this repository.

| Part | Topic |
| --- | --- |
| 1 | A real phone number answered by CX Agent Studio |
| 2 | Business-hours routing, transfer, and after-hours tickets |
| 3 | OpenAPI tools on Cloud Run: booking into Google Calendar |
| 4 | An ADK commerce agent over A2A, with UCP checkout |
| 5 | Warm hand-offs and the mid-market path |
| 6 | Guardrails, redaction, and authority grants |
| 7 | Evals, traffic splitting, and cost per call |

The company used throughout, Brightwater Home Services, is fictional, and its data is synthetic.

## Status

Part 1 code lands here before its articles publish on November 4, 2026. Setup instructions arrive with it.

## License

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
