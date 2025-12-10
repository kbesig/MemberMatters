# Billing Group Invitation Banner Enhancement

## Problem
When a user is invited to a billing group but doesn't have a payment plan selected (or doesn't have a card on file), they would see the plan selector page instead of the billing group manager. This meant they would never see their pending invitation banner, making it impossible for them to accept or decline the invitation.

## Solution
Created a reusable `BillingGroupInviteBanner` component and added it to multiple pages so users will see their pending invitation regardless of where they are in the app.

## Changes Made

### 1. New Component: `BillingGroupInviteBanner.vue`
**Location**: `/src-frontend/src/components/Billing/BillingGroupInviteBanner.vue`

This is a standalone, reusable component that:
- Checks for pending billing group invitations on mount
- Displays a prominent blue banner with the invitation details
- Provides Accept and Decline buttons
- Handles the invitation response logic
- Shows a warning dialog if the user has an active subscription (they'll be warned about cancellation)
- Refreshes the user's profile after responding
- Redirects to the membership plan page after acceptance
- Emits an event so parent components can react if needed

### 2. Updated: `SelectTier.vue`
**Location**: `/src-frontend/src/components/Billing/SelectTier.vue`

Added the billing group invitation banner at the top of the plan selector, so users who don't have a plan yet will still see their invitation.

**Changes**:
- Imported `BillingGroupInviteBanner` component
- Added the banner component at the top of the template (above the "Account Only" warning banner)
- Added `handleInviteResponse` method to handle the event (currently just logs, but can be extended)
- Registered the component in the `components` object

### 3. Updated: `Dashboard.vue`
**Location**: `/src-frontend/src/pages/Dashboard.vue`

Added the billing group invitation banner at the top of the dashboard page, so users will see their invitation immediately when they log in.

**Changes**:
- Imported `BillingGroupInviteBanner` component
- Added the banner component at the top of the page content (above the inactive member warning)
- Wrapped it in a div with proper width styling
- Registered the component in the `components` object

## User Experience Flow

Now when a member is invited to a billing group, they will see the invitation banner in the following locations:

1. **Dashboard** - Immediately visible when they log in
2. **Membership Plan Page** - Shows in the billing group manager section (existing behavior)
3. **Plan Selector Page** - Shows at the top when they don't have a plan selected (NEW)

This ensures that no matter where a user is in the signup/configuration process, they will always see and be able to respond to their billing group invitation.

## API Endpoints Used

- `GET /api/billing/billing-group/` - Checks for pending invitations
- `POST /api/billing/billing-group/invite/` - Accepts or declines the invitation

## Testing Recommendations

1. Create a billing group with one primary member
2. Invite a new user who doesn't have a plan selected
3. Log in as the invited user
4. Verify the invitation banner appears on:
   - Dashboard
   - Membership plan page (plan selector)
   - Membership plan page (when they have a plan)
5. Test accepting the invitation
6. Test declining the invitation
7. Test with a user who has an active subscription (should show warning dialog)

## Benefits

- **Better User Experience**: Users can't miss their invitations
- **Reduced Support**: No confusion about "missing" invitations
- **Reusable Code**: Single component handles all invitation display/logic
- **Consistent UI**: Same banner appearance across all pages
- **Flexible**: Easy to add to additional pages in the future
