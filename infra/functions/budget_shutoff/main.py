"""Unlink billing from the project when its budget alert reports the cap is reached.

Google Cloud budgets only send alerts. This function turns the alert into a
hard stop: when costAmount reaches budgetAmount, it removes the project's
billing account, which stops every billable service in the project. Re-link
billing in the console to bring the project back.

Copyright 2026 Robert H. Mowery III. Licensed under the Apache License, Version 2.0.
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any

import functions_framework


def _log(severity: str, message: str, **fields: Any) -> None:
    """One structured line on stdout; Cloud Run turns it into a log entry with this severity."""
    print(json.dumps({"severity": severity, "message": message, **fields}), flush=True)


def should_shut_off(alert: dict[str, Any]) -> bool:
    """True only when reported cost has reached the budget amount."""
    cost = float(alert.get("costAmount", 0))
    budget = float(alert.get("budgetAmount", 0))
    return budget > 0 and cost >= budget


def unlink_billing(project_id: str) -> None:
    from google.cloud import billing_v1

    client = billing_v1.CloudBillingClient()
    name = f"projects/{project_id}"
    current = client.get_project_billing_info(name=name)
    if not current.billing_enabled:
        _log("INFO", "Billing already disabled", project=project_id)
        return
    client.update_project_billing_info(
        name=name, project_billing_info=billing_v1.ProjectBillingInfo(billing_account_name="")
    )
    _log("WARNING", "Billing unlinked: budget cap reached", project=project_id)


@functions_framework.cloud_event
def on_budget_alert(event: Any) -> None:
    data = event.data["message"]["data"]
    alert = json.loads(base64.b64decode(data).decode("utf-8"))
    _log("INFO", "Budget alert received", cost=alert.get("costAmount"), budget=alert.get("budgetAmount"))
    if should_shut_off(alert):
        unlink_billing(os.environ["PROJECT_ID"])
    else:
        _log("INFO", "Below the cap: billing left on")
