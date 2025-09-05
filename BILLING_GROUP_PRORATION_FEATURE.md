# Billing Group Invitation with Subscription Proration Feature

## Overview

This feature implements automatic cancellation and proration of individual subscriptions when users accept invitations to join billing groups. When a user with an active individual subscription accepts an invitation to join a billing group, their current subscription is cancelled immediately with proration, and they are added to the billing group's shared subscription.

## Key Features

1. **Automatic Subscription Cancellation**: When accepting a billing group invitation, individual subscriptions are cancelled immediately with proration
2. **User Warnings**: Users with active subscriptions receive warnings in both email invitations and the UI before accepting
3. **Robust Error Handling**: Handles edge cases like already-cancelled subscriptions or missing Stripe subscriptions
4. **Detailed Logging**: Comprehensive logging for all subscription changes and billing group activities

## Backend Changes

### New Method: `_cancel_individual_subscription_with_proration`

**Location**: `/memberportal/api_billing/views.py` in `MemberBillingGroupInviteResponse` class

**Purpose**: Cancels a member's individual subscription with proration when they join a billing group.

**Key Features**:
- Immediate cancellation with proration using `proration_behavior="create_prorations"`
- Handles edge cases (already cancelled, subscription not found in Stripe)
- Updates profile fields (`stripe_subscription_id`, `membership_plan`, `subscription_status`)
- Comprehensive error handling and logging

**Code Flow**:
1. Validates subscription exists
2. Checks if subscription is already cancelled in Stripe
3. Handles missing subscriptions gracefully
4. Cancels subscription with proration
5. Updates user profile
6. Logs all actions

### Enhanced Invitation Acceptance Logic

**Location**: `/memberportal/api_billing/views.py` in `MemberBillingGroupInviteResponse.post()` method

**Changes**:
- Added subscription cancellation step before joining billing group
- Enhanced error handling with specific error messages
- Updated logging to reflect subscription cancellation

### Enhanced Invitation Creation Logic

**Location**: `/memberportal/api_billing/views.py` in `MemberBillingGroupMemberManagement.post()` method

**Changes**:
- Enhanced email notifications to warn about subscription cancellation
- Different messages for users with/without active subscriptions
- Enhanced logging to track users with active subscriptions

**Location**: `/memberportal/api_admin_tools/views.py` in `BillingGroupInviteManagement.post()` method

**Changes**:
- Same enhancements as above for admin-initiated invitations

## Frontend Changes

### Enhanced User Interface

**Location**: `/src-frontend/src/components/Billing/BillingGroupManager.vue`

**New Features**:
1. **Warning Dialog**: Shows confirmation dialog when users with active subscriptions try to accept invitations
2. **Subscription Status Check**: Checks user's subscription status from profile store
3. **Improved UX**: Separates invitation response logic into two methods for better flow

**Key Changes**:
- Modified `respondToInvite()` method to check subscription status
- Added `processInviteResponse()` method to handle actual API calls
- Added confirmation dialog using Quasar's `$q.dialog()`

### New Translation Strings

**Locations**: 
- `/src-frontend/src/i18n/en-US/index.ts`
- `/src-frontend/src/i18n/en-AU/index.ts`

**New Translations**:
```typescript
confirmAcceptInvite: 'Confirm Invitation Acceptance',
subscriptionCancellationWarning: 
  'Warning: You currently have an active individual subscription. If you accept this invitation, your current subscription will be cancelled immediately with proration for any remaining time, and you will join the billing group\'s shared subscription. This action cannot be undone. Do you want to proceed?'
```

## User Experience Flow

### For Users Being Invited

1. **Email Notification**: 
   - Users with active subscriptions receive detailed warning about cancellation
   - Users without active subscriptions receive standard invitation message

2. **UI Interaction**:
   - Users see standard invitation in billing group manager
   - When clicking "Accept" with active subscription, warning dialog appears
   - Users can cancel or proceed with full knowledge of consequences

3. **Acceptance Process**:
   - Individual subscription cancelled immediately with proration
   - User added to billing group
   - Billing group subscription item created
   - Detailed logging of all actions

### For Billing Group Administrators

1. **Enhanced Logging**: All invitation and acceptance activities include subscription status information
2. **Clear Audit Trail**: Detailed logs help track subscription changes and billing group modifications

## Technical Implementation Details

### Proration Behavior

The implementation uses Stripe's `proration_behavior="create_prorations"` which:
- Immediately cancels the subscription
- Creates credit for unused time
- Applies credit to customer's account
- Credit appears on next invoice or as account balance

### Error Handling

The system handles multiple edge cases:
1. **Already Cancelled Subscriptions**: Gracefully handles subscriptions already cancelled in Stripe
2. **Missing Subscriptions**: Handles cases where subscription ID exists in database but not in Stripe
3. **Stripe API Errors**: Comprehensive error handling for all Stripe API interactions
4. **Database Consistency**: Ensures user profile is updated even if Stripe operations fail

### Logging Strategy

All operations are logged with detailed information:
- User identification
- Billing group information
- Subscription details
- Action outcomes
- Error details (when applicable)

## Database Impact

### Profile Model Updates

When a user accepts a billing group invitation with an active subscription:
- `stripe_subscription_id` → `None`
- `membership_plan` → `None` 
- `subscription_status` → `"inactive"`
- `billing_group` → Set to target billing group
- `billing_group_invite` → `None`

### BillingGroupMemberAddon Records

- Existing locked pricing records are maintained
- New subscription items created in Stripe with locked pricing
- Subscription item IDs stored for future management

## Security Considerations

1. **User Consent**: Users must explicitly confirm subscription cancellation
2. **Data Integrity**: All subscription changes are atomic operations
3. **Audit Trail**: Comprehensive logging for compliance and debugging
4. **Error Recovery**: Graceful handling of partial failures

## Testing Recommendations

### Unit Tests
1. Test subscription cancellation with various subscription states
2. Test error handling for Stripe API failures
3. Test profile updates after cancellation
4. Test logging output

### Integration Tests
1. Test full invitation acceptance flow
2. Test email notification content
3. Test UI warning dialogs
4. Test proration credit application

### Manual Testing Scenarios
1. User with active monthly subscription accepts invitation
2. User with cancelled subscription accepts invitation
3. User with subscription that doesn't exist in Stripe accepts invitation
4. Network/API failures during acceptance process

## Future Enhancements

1. **Subscription Transfer**: Instead of cancelling, transfer subscription to billing group
2. **Partial Period Handling**: More sophisticated handling of partial billing periods
3. **Cancellation Analytics**: Track subscription cancellation patterns
4. **Bulk Operations**: Handle multiple invitation acceptances efficiently

## Deployment Notes

1. **Backup Requirements**: Ensure database backups before deployment
2. **Monitoring**: Monitor Stripe webhook processing after deployment
3. **Rollback Plan**: Ability to disable feature via feature flag if needed
4. **User Communication**: Notify users about new billing group invitation behavior

## Documentation Updates Required

1. Update user documentation about billing group invitations
2. Update admin documentation about subscription management
3. Update API documentation for invitation endpoints
4. Update troubleshooting guides for subscription issues
