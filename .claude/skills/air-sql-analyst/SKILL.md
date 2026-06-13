---
name: air-sql-analyst
description: Draft and review Zalopay AIR/OTA Presto/Trino SQL from business data requests. Use when the user asks about Air/OTA metrics, search_air/payment_air data, routes, providers, booking window, TPV, AOV, ARPPU, search-to-pay conversion, Air dashboards, or asks to turn an Air/OTA business question into SQL.
---

# Air SQL Analyst

## Core Workflow

Use the Zalopay AIR/OTA rules before drafting SQL.

1. Check whether the request maps to the Air/OTA catalog or playbook.
2. Restate the understood request in business terms.
3. Ask for missing required slots before SQL: time range, time column, counting unit, grain/dimension, filters, and top-N/ranking rules.
4. Confirm ambiguous choices before generating SQL.
5. Output Presto/Trino SQL only after the request is clear.
6. Include a SQL header comment with metric, source table, time range/time column, grain, filters, and caveats.
7. Do not run numbers or claim query results.

For fuzzy/open-ended requests, ask one focused question at a time until the business intent is clear.

## Required Rules

- Use `ref_zlp_metric_definitions.md` as the authority for AIR/OTA metrics; it overrides generic definitions.
- Use `search_air` for search/demand behavior and `payment_air` for purchase/transaction behavior.
- Use `search_air.user_id = payment_air.userID` for joins, and only within overlapping coverage when joining.
- Always distinguish search date, purchase date, and flight/departure date.
- For route requests, clarify one-way direction vs two-way grouped route and airport vs city grain.
- For provider/airline requests, clarify whether the user means `appID`, `appUser`, provider, or airline.
- Use Presto/Trino syntax: `DATE 'YYYY-MM-DD'`, `date_diff`, `date_trunc`, half-open timestamp ranges where needed, and explicit casts.
- Do not answer unavailable analyses as if they are possible. State the missing data instead.

## References

Load only the relevant reference:

- `references/rules_biz_request_to_view_query.md`: full request-to-SQL workflow, clarification checklist, SQL header, dialect rules, and data quirks.
- `references/rules_effective_data_request.md`: how to normalize a vague business request into the 7-slot request template.
- `references/ref_zlp_metric_definitions.md`: approved metric and business term definitions.
- `references/catalog_question_bank_air.md`: 66 Air/OTA view specs and unsupported-question list.
- `references/playbook_sql_air_views.md`: make-clear prompts and SQL templates for catalog views.

## Output Contract

When SQL is ready, return:

```sql
-- Metric:
-- Source:
-- Time range:
-- Time column:
-- Grain:
-- Filters:
-- Caveats:
SELECT ...
```

When SQL is not ready, return the restated request and the minimum clarification questions needed to continue.
