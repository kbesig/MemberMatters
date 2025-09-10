# Billing Group Subscription Status Implementation

## Summary

This implementation adds support for 5 subscription states to properly handle billing group members' subscription status:

### New Subscription States

1. **`inactive`** - No subscription, not in billing group
2. **`active`** - Individual subscription active  
3. **`cancelling`** - Individual subscription cancelling
4. **`group_active`** - Member of billing group with active primary subscription
5. **`group_inactive`** - Member of billing group with inactive/failed primary subscription

## Key Changes Made

### Database Changes
- **Profile Model**: Added `group_active` and `group_inactive` to `SUBSCRIPTION_STATES`
- **Field Length**: Increased `subscription_status` max_length from 10 to 20 characters
- **Migration 0027**: Adds new subscription state choices and increases field length
- **Migration 0028**: Data migration to update existing billing group members to correct status

### Backend Logic Updates
- **Billing Group Join**: Sets `subscription_status = "group_active"` when joining
- **Billing Group Leave**: Sets `subscription_status = "inactive"` when leaving  
- **Webhook Handling**: Cascades primary member subscription changes to group members
- **Helper Methods**: Added `has_active_subscription()` and `get_effective_subscription_status()`

### Frontend Updates
- **Types**: Updated `SubscriptionStateSchema` to include new states
- **Translations**: Added labels for new states in all language files
- **UI Logic**: Updated components to handle 5 states instead of 3
- **Styling**: Added CSS for `group-inactive` state

### Webhook Behavior
- **Primary Subscription Cancelled**: All group members → `group_inactive`
- **Primary Subscription Reactivated**: All group members → `group_active`
- **Payment Failed**: Group members receive notifications about group status

## Benefits

1. **Clear Status Representation**: Members always know their billing relationship
2. **Proper Cascading**: Group members' status reflects primary member's subscription
3. **Better UX**: Users understand when group subscription issues affect them
4. **Accurate Analytics**: Can distinguish between individual vs group subscriptions
5. **Future-Proof**: Foundation for group-specific features

## Usage Examples

### Checking for Active Subscription
```python
# Backend
if profile.has_active_subscription():  # Checks for 'active' or 'group_active'
    # Member has active coverage

# Frontend  
if (['active', 'group_active'].includes(subscriptionStatus)) {
    // Show active subscription features
}
```

### Identifying Payment Responsibility
```python
if profile.subscription_status == "active":
    # Individual subscriber - can manage own subscription
elif profile.subscription_status == "group_active": 
    # Group member - primary member manages subscription
```

## Migration Path

1. Run `python manage.py migrate` to apply database changes:
   - **0027_add_group_subscription_states**: Updates the model field choices and length
   - **0028_update_billing_group_subscription_status**: Updates existing billing group members to correct status
2. Existing billing group members will be automatically updated to correct status
3. Frontend will immediately show new status labels
4. No breaking changes to existing functionality

## Commands to Run

```bash
# Navigate to the Django project directory
cd memberportal

# Apply the migrations
python manage.py migrate

# Verify the migration worked
python manage.py shell -c "
from profile.models import Profile
print('Subscription status distribution:')
for status in ['inactive', 'active', 'cancelling', 'group_active', 'group_inactive']:
    count = Profile.objects.filter(subscription_status=status).count()
    print(f'{status}: {count}')
"
```

## Future Enhancements

- Group member notifications when primary subscription changes
- Billing group management UI improvements
- Group-specific subscription features
- Enhanced analytics and reporting
