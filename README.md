# The Always-On Agentic Front Office

Reference code for the article series *The Always-On Agentic Front Office* by Robert H. Mowery III ([robertmowery.com](https://robertmowery.com)).

Agentic CX for businesses that can't miss a call, built on Google's Gemini Enterprise for Customer Experience (GECX) stack. By the end of the series this repository is a working MVP contact center: a Google-provisioned phone number answered by a CX Agent Studio agent that routes by business hours, books jobs into Google Calendar, sells through an ADK commerce agent over A2A and the Universal Commerce Protocol, hands off to a human with context, and proves itself with evals and a cost-per-call number.

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

## Quick start

```bash
export PROJECT=your-new-project-id
make venv
make landing-zone   # APIs, $40 budget, kill switch
make deploy         # the agent, from agent/
make smoke          # eight test conversations, about $4
```

Then attach a Google-provisioned phone number in the CX Agent Studio console. Each part has a step-by-step guide in [docs/](docs/), starting with [Part 1](docs/part1.md). `make teardown` removes everything.

## License

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
