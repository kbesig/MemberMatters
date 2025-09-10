# Billing Group Addon Pricing Lock Feature

## Overview

This feature ensures that when a new person is added or invited to a billing group, their addon pricing is locked to the current pricing plan at the time they join. This prevents existing billing group members from being affected by future pricing changes.

## How It Works

### When a Member Joins a Billing Group

1. **Direct Addition**: When a billing group owner directly adds a member via email
2. **Invitation Sent**: When an admin sends an invitation via the admin interface
3. **Invitation Acceptance**: When someone accepts an invitation to join a billing group

In each case, the system handles pricing differently:

**Direct Addition:**
- Looks up the current "Additional Member" addon pricing
- Creates a `BillingGroupMemberAddon` record that locks in the current pricing
- Records the exact cost, currency, billing interval, and date when the pricing was locked

**Invitation Process:**
- **When invitation is sent**: The system locks in the current addon pricing
- **When invitation is accepted**: The system uses the already-locked pricing (no new lock)
- **When invitation is declined/cancelled**: The system removes the locked pricing

### Database Structure

The new `BillingGroupMemberAddon` model tracks:
- `billing_group`: Which billing group this applies to
- `member`: Which member has the locked pricing
- `addon`: Which addon (typically the "additional member" addon)
- `locked_cost`: Cost in cents when the member joined
- `locked_currency`: Currency (e.g., "aud")
- `locked_interval`: Billing interval (e.g., "month")
- `locked_interval_count`: How many intervals (e.g., 1)
- `date_locked`: When this pricing was locked in

## Admin Configuration

### Setting Up the Additional Member Addon

1. Go to Django Admin → API Admin Tools → Subscription Add-ons
2. Create or edit an addon with type "Additional Member"
3. Set the current pricing for additional members
4. Go to Django Admin → Constance → Config
5. Set `CURRENT_ADDITIONAL_MEMBER_ADDON` to the ID of your addon

### Migrating Existing Billing Groups

For existing billing groups that were created before this feature, use the management command:

```bash
# See what would be done (dry run)
python manage.py setup_billing_group_addon_pricing --dry-run

# Apply the locked pricing to existing members
python manage.py setup_billing_group_addon_pricing

# Force update existing locked pricing
python manage.py setup_billing_group_addon_pricing --force
```

## Frontend Changes

### Billing Group Member Table

The billing group manager now shows:
- Member name and email (as before)
- **New**: Locked addon pricing information
- Actions (as before)

### Pricing Display

For each member, the table shows:
- Addon name (e.g., "Additional Member")
- Locked pricing (e.g., "$15.00/month")
- Date when pricing was locked

### Translations

New translation keys added:
- `billing.lockedAddonPricing`: "Locked Addon Pricing"
- `billing.lockedOn`: "Locked on"
- `billing.noLockedPricing`: "No locked pricing"

## API Changes

### Updated Endpoints

#### GET `/api/billing/billing-group/`

The response now includes `locked_addon_pricing` for each member:

```json
{
  "success": true,
  "billing_group": {
    "id": 1,
    "name": "Family Plan",
    "members": [
      {
        "id": 123,
        "name": "John Doe",
        "email": "john@example.com",
        "locked_addon_pricing": [
          {
            "addon_id": 1,
            "addon_name": "Additional Member",
            "addon_type": "additional_member",
            "locked_pricing": {
              "cost": 1500,
              "cost_display": "$15.00",
              "currency": "aud",
              "interval": "month",
              "interval_count": 1,
              "date_locked": "2025-08-29T10:30:00Z"
            }
          }
        ]
      }
    ]
  }
}
```

#### POST `/api/billing/billing-group/members/`

When adding a member, the system now automatically:
1. Adds the member to the billing group
2. Creates locked addon pricing records
3. Logs the pricing lock event

#### DELETE `/api/billing/billing-group/members/`

When removing a member, the system now:
1. Removes the member from the billing group
2. Deletes all locked addon pricing records for that member
3. Logs the removal event

#### POST `/api/admin/billing-groups/{id}/invites/`

When sending an invitation via admin interface, the system:
1. Creates the invitation
2. Locks in current addon pricing for the invited member
3. Sends email notification with pricing information
4. Logs the invitation and pricing lock event

When cancelling an invitation via admin interface, the system:
1. Removes the invitation
2. Deletes any locked addon pricing records
3. Logs the cancellation event

#### POST `/api/billing/billing-group/invite/`

When accepting an invitation, the system now:
1. Adds the member to the billing group
2. Uses the addon pricing that was locked when the invitation was sent (no new pricing lock)
3. Logs the acceptance event

When declining an invitation, the system:
1. Removes the invitation
2. Deletes any locked addon pricing records that were created when the invitation was sent
3. Logs the decline event

## Error Handling

### Missing Configuration

If `CURRENT_ADDITIONAL_MEMBER_ADDON` is not configured:
- The system logs a warning but continues to add the member
- No locked pricing is created
- The event is logged for admin review

### Addon Not Found

If the configured addon ID doesn't exist:
- The system logs a warning but continues to add the member
- No locked pricing is created
- The event is logged for admin review

### General Errors

Any other errors during pricing lock:
- Are caught and logged
- Don't prevent the member from being added
- Allow the system to continue functioning

## Logging

All pricing lock events are logged with type "billing_group":
- Successful pricing locks
- Warnings about missing configuration
- Errors during pricing lock operations
- Pricing removal when members are removed

## Use Cases

### Scenario 1: Price Increase
1. Current additional member cost: $10/month
2. Alice joins a billing group → locked at $10/month
3. Admin increases additional member cost to $15/month
4. Bob joins the same billing group → locked at $15/month
5. Alice keeps paying $10/month, Bob pays $15/month

### Scenario 2: Existing Members
1. Billing groups exist with members before this feature
2. Admin runs `setup_billing_group_addon_pricing`
3. All existing members get locked pricing at current rates
4. Future members get locked pricing when they join

### Scenario 3: Invitation Process
1. Current additional member cost: $10/month
2. Admin invites Alice to a billing group → pricing locked at $10/month
3. Admin increases additional member cost to $15/month
4. Alice accepts the invitation → she gets the previously locked $10/month rate
5. Bob gets invited after the price increase → his pricing locked at $15/month

### Scenario 4: Invitation Declined
1. Current additional member cost: $10/month
2. Admin invites Alice to a billing group → pricing locked at $10/month
3. Alice declines the invitation → locked pricing is removed
4. Later, Alice is invited again → pricing locked at current rate (which may be different)

### Scenario 5: No Additional Member Addon
1. Admin hasn't set up additional member addon
2. Members can still join billing groups
3. No locked pricing is created
4. System logs warnings for admin review

## Future Enhancements

Possible future improvements:
1. Support for multiple addon types per member
2. Bulk pricing updates with member consent
3. Pricing history and audit trails
4. Automatic Stripe subscription updates based on locked pricing
5. Member-specific addon customization
