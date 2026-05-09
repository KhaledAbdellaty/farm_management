# Farm Management Module — Documentation

## Index

| File | Description |
|------|-------------|
| [analytic-gap-analysis.md](analytic-gap-analysis.md) | Full audit of analytic accounting gaps — field comparison, user stories, enhancement backlog |
| [implementation-plan.md](implementation-plan.md) | Master plan: 6 tasks, dependency map, recommended order, review checkpoints |
| [task-01-gl-mapping.md](task-01-gl-mapping.md) | **Task 1** — GL Account Mapping model (`farm.cost.account.mapping`) |
| [task-02-partner-traceability.md](task-02-partner-traceability.md) | **Task 2** — Partner field on analytic lines (vendor traceability) |
| [task-03-category-fix.md](task-03-category-fix.md) | **Task 3** — Set `category = 'vendor_bill'` (2-line fix, immediate Gross Margin impact) |
| [task-04-product-on-cost.md](task-04-product-on-cost.md) | **Task 4** — Add `product_id` field to cost analysis |
| [task-05-audit-ref.md](task-05-audit-ref.md) | **Task 5** — Set `ref` + `user_id` for audit trail (2-line fix) |
| [task-06-crop-analytic-plan.md](task-06-crop-analytic-plan.md) | **Task 6** — Second analytic plan for crop-level aggregation (advanced) |

## Recommended Implementation Order

```
Quick wins first → Foundation → Advanced
    Task 3           Task 1       Task 6
    Task 5           Task 2
                     Task 4
```

Start with **Task 3** (category fix) and **Task 5** (ref field) — both are 2-line changes with immediate visible impact on the Gross Margin report.
Then **Task 1** (GL mapping) as the foundation for proper accounting linkage.
Then **Task 2** (partner) and **Task 4** (product) to complete the data model.
Finally **Task 6** (crop plan) as the advanced multi-dimensional reporting layer.

## Status Tracking

| Task | Status | Review |
|------|--------|--------|
| Task 1 — GL Account on Cost | ✅ Implemented | ⬜ Review |
| Task 2 — Partner | ✅ Implemented | ⬜ Review |
| Task 3 — Category | ✅ Implemented | ⬜ Review |
| Task 4 — Product | ✅ Implemented | ⬜ Review |
| Task 5 — Audit Ref | ✅ Implemented | ⬜ Review |
| Task 6 — Crop Plan | 📋 Planned | ⬜ |
