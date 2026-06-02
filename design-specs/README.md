# Design Specs

This folder contains detailed implementation specifications for features added in this fork of MemberMatters. These specs are written to be used as a blueprint for reimplementing the same features on another fork of the upstream project (membermatters/MemberMatters v3.8.0).

## Specs Overview

| Spec | Name | Description |
|------|------|-------------|
| [01](./01-subscription-addon-system.md) | Subscription Addon System | Configurable add-on model for extras attached to Stripe subscriptions |
| [02](./02-flexible-billing-and-cycle-anchoring.md) | Flexible Billing & Cycle Anchoring | Mixed billing intervals and 1st-of-month billing cycle anchoring |
| [03](./03-subscription-status-enhancement.md) | Subscription Status Enhancement | Expand subscription status to 5 states including group membership |
| [04](./04-billing-group-system.md) | Billing Group System | Shared billing groups with invitation flow and Stripe integration |
| [05](./05-shelf-rental-system.md) | Shelf Rental System | Physical shelf rental with request queue and Stripe billing |
| [06](./06-email-and-notifications.md) | Email & Notification Enhancements | Postmark email integration for billing and shelf notifications |

## Implementation Order

```
Phase 1 (parallel):
  ├── Spec 01: Subscription Addon System (foundation)
  └── Spec 03: Subscription Status Enhancement (foundation)

Phase 2 (depends on Phase 1):
  └── Spec 02: Flexible Billing & Billing Cycle Anchoring

Phase 3 (depends on Specs 01, 02, 03 — can run in parallel):
  ├── Spec 04: Billing Group System
  └── Spec 05: Shelf Rental System

Phase 4 (parallel with Phases 3–4):
  └── Spec 06: Email & Notification Enhancements
```

## Key Architectural Decisions

- **Locked pricing pattern**: When a member joins a billing group or is assigned a shelf, the addon price at that moment is captured in a "locked pricing" record. This prevents future price changes from affecting existing members.
- **Stripe metadata**: Custom Stripe Prices are created per-member with metadata (`billing_group_id`, `member_id`, `addon_id`) for traceability.
- **Proration everywhere**: All subscription modifications use `proration_behavior="create_prorations"`.
- **Billing cycle anchor**: All new subscriptions anchor to the 1st of the next month.
- **Status cascading**: Primary billing group member status changes propagate to all secondary members via webhooks.
- **Constance config**: Runtime configuration via django-constance for addon IDs, email templates, and feature toggles.
