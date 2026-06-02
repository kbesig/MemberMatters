# Spec 04: Billing Group System

## Summary

Allow a primary member to create a billing group, invite other members (existing or new), and pay for their membership via addon charges on the primary member's Stripe subscription. Includes locked pricing, invitation workflows, and admin management.

## Dependencies

- **Spec 01**: Subscription Addon System (SubscriptionAddon model, Stripe sync)
- **Spec 02**: Flexible Billing (mixed interval support on subscriptions)
- **Spec 03**: Subscription Status Enhancement (`group_active`/`group_inactive` statuses, webhook cascading)

## Data Models

### `BillingGroup` (new model in `profile/models.py`)

```python
class BillingGroup(models.Model):
    id = AutoField(primary_key=True)
    name = CharField(max_length=255)
    primary_member = OneToOneField(
        "Profile",
        on_delete=SET_NULL,
        related_name="billing_group_primary_member",
        null=True, blank=True,
    )

    def get_members(self):
        return self.members.all()  # via Profile.billing_group FK

    def get_primary_member(self):
        return self.primary_member

    def get_head(self):
        return self.get_primary_member()

    def get_invites(self):
        return self.members_invites.all()  # via Profile.billing_group_invite FK
```

### `BillingGroupInvite` (new model in `profile/models.py`)

Tracks pending invitations for **non-registered** users to join a billing group via email.

```python
class BillingGroupInvite(models.Model):
    id = AutoField(primary_key=True)
    email = EmailField(max_length=255, db_index=True)  # stored lowercase
    billing_group = ForeignKey(BillingGroup, on_delete=CASCADE, related_name="invitations")
    invited_by = ForeignKey(User, on_delete=SET_NULL, null=True, related_name="sent_billing_group_invitations")
    invitation_token = UUIDField(default=uuid.uuid4, unique=True, db_index=True, editable=False)
    created_date = DateTimeField(auto_now_add=True)
    expires_date = DateTimeField()  # default: 7 days from creation (set in save())
    accepted = BooleanField(default=False)
    accepted_date = DateTimeField(null=True, blank=True)
    invalidated = BooleanField(default=False)
    invalidated_date = DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            Index(fields=["email", "billing_group"]),
            Index(fields=["expires_date"]),
        ]
        ordering = ["-created_date"]

    def save(self, *args, **kwargs):
        if self.email:
            self.email = self.email.lower()
        if not self.expires_date:
            self.expires_date = timezone.now() + timedelta(days=7)
        super().save(*args, **kwargs)

    def is_expired(self):
        return timezone.now() > self.expires_date

    def is_valid(self):
        return not self.accepted and not self.invalidated and not self.is_expired()

    def accept(self):
        self.accepted = True
        self.accepted_date = timezone.now()
        self.save()

    def invalidate(self):
        self.invalidated = True
        self.invalidated_date = timezone.now()
        self.save()
```

### `BillingGroupMemberAddon` (new model in `profile/models.py`)

Locks addon pricing at the time a member joins the group.

```python
class BillingGroupMemberAddon(models.Model):
    id = AutoField(primary_key=True)
    billing_group = ForeignKey(BillingGroup, on_delete=CASCADE, related_name="member_addons")
    member = ForeignKey("Profile", on_delete=CASCADE, related_name="billing_group_addons")
    addon = ForeignKey("api_admin_tools.SubscriptionAddon", on_delete=CASCADE, related_name="billing_group_members")
    locked_cost = IntegerField()  # cents at time of join
    locked_currency = CharField(max_length=3, default="aud")
    locked_interval = CharField(max_length=10)
    locked_interval_count = IntegerField(default=1)
    date_locked = DateTimeField(auto_now_add=True)
    stripe_subscription_item_id = CharField(max_length=255, blank=True, null=True)
    stripe_price_id = CharField(max_length=255, blank=True, null=True)

    class Meta:
        unique_together = [["billing_group", "member", "addon"]]
```

### `Profile` model additions

```python
# New FK fields on Profile:
billing_group = ForeignKey(
    BillingGroup, on_delete=SET_NULL,
    related_name="members", null=True, blank=True,
)
billing_group_invite = ForeignKey(
    BillingGroup, on_delete=SET_NULL,
    related_name="members_invites", null=True, blank=True,
)
pending_billing_group_invite_token = UUIDField(
    null=True, blank=True,
    help_text="Temporarily stores invitation token during registration",
)

# New helper methods:
def has_billing_group_invite(self):
    return self.billing_group_invite is not None

def has_billing_group(self):
    return self.billing_group is not None
```

### `User` model additions

```python
# Counter fields for quick lookups (on User, not Profile):
billing_group_invite = IntegerField(default=0)
billing_group_member = IntegerField(default=0)
```

## User API Endpoints

All user endpoints require authentication. Base path: `/api/billing/billing-group/`

### `GET /api/billing/billing-group/`

Get the current user's billing group and any pending invitations.

**Response (member in a group):**
```json
{
  "success": true,
  "billingGroup": {
    "id": 1,
    "name": "Smith Family",
    "primaryMember": { "id": 5, "name": "John Smith", "email": "john@example.com" },
    "members": [
      { "id": 5, "name": "John Smith", "isPrimary": true },
      { "id": 8, "name": "Jane Smith", "isPrimary": false }
    ],
    "isPrimaryMember": true
  },
  "pendingInvite": null
}
```

**Response (member with pending invite):**
```json
{
  "success": true,
  "billingGroup": null,
  "pendingInvite": {
    "groupName": "Smith Family",
    "invitedBy": "John Smith",
    "billingGroupId": 1
  }
}
```

### `POST /api/billing/billing-group/`

Create a new billing group. The requesting user becomes the primary member.

**Request:**
```json
{ "name": "Smith Family" }
```

**Validation:**
- User must not already be in a billing group
- User must have an active subscription

**Behavior:**
1. Create `BillingGroup` with `primary_member=profile`
2. Set `profile.billing_group = billing_group`
3. Save

### `DELETE /api/billing/billing-group/`

Delete the billing group. Only the primary member can delete.

**Behavior:**
1. Verify requester is primary member
2. For each secondary member:
   - Remove Stripe subscription items for their addon charges
   - Delete `BillingGroupMemberAddon` records
   - Set `member.billing_group = None`
   - Set `member.subscription_status = "inactive"`
3. Delete the `BillingGroup`

### `POST /api/billing/billing-group/members/`

Invite an **existing member** to the billing group. Only the primary member can invite.

**Request:**
```json
{ "email": "jane@example.com" }
```

**Behavior:**
1. Find user by email
2. Verify target user is not already in a billing group
3. Lock addon pricing: create `BillingGroupMemberAddon` with current `CURRENT_ADDITIONAL_MEMBER_ADDON` cost
4. Set `target_profile.billing_group_invite = billing_group`
5. Send notification email to target user

**Lock Addon Pricing Logic:**
```python
def _lock_addon_pricing_for_invited_member(billing_group, member_profile):
    addon_id = config.CURRENT_ADDITIONAL_MEMBER_ADDON
    addon = SubscriptionAddon.objects.get(id=addon_id)
    BillingGroupMemberAddon.objects.create(
        billing_group=billing_group,
        member=member_profile,
        addon=addon,
        locked_cost=addon.cost,
        locked_currency=addon.currency,
        locked_interval=addon.interval,
        locked_interval_count=addon.interval_count,
    )
```

### `DELETE /api/billing/billing-group/members/`

Remove a member from the billing group. Primary member can remove any secondary member.

**Request:**
```json
{ "member_id": 8 }
```

**Behavior:**
1. Find the member's `BillingGroupMemberAddon` records
2. Remove Stripe subscription items for each addon
3. Delete `BillingGroupMemberAddon` records
4. Set `member.billing_group = None`
5. Set `member.subscription_status = "inactive"`

### `POST /api/billing/billing-group/invite/`

Accept or decline a billing group invitation. Called by the invited member.

**Request:**
```json
{ "action": "accept" }  // or "decline"
```

**Accept Behavior:**
1. If member has an active individual subscription, cancel it with proration:
   ```python
   def _cancel_individual_subscription_with_proration(profile):
       stripe.Subscription.modify(
           profile.stripe_subscription_id,
           cancel_at_period_end=False,  # immediate cancel
           proration_behavior="create_prorations",
       )
       stripe.Subscription.delete(profile.stripe_subscription_id)
       profile.stripe_subscription_id = ""
       profile.membership_plan = None
       profile.save()
   ```
2. Create Stripe subscription item on primary's subscription:
   ```python
   def _create_stripe_subscription_item_for_member(billing_group, member_profile):
       member_addon = BillingGroupMemberAddon.objects.get(
           billing_group=billing_group, member=member_profile
       )
       # Create a custom Stripe price for this member's locked rate
       price = stripe.Price.create(
           unit_amount=member_addon.locked_cost,
           currency=member_addon.locked_currency,
           recurring={
               "interval": member_addon.locked_interval,
               "interval_count": member_addon.locked_interval_count,
           },
           product_data={
               "name": f"Additional Member - {member_profile.get_full_name()}",
               "metadata": {
                   "billing_group_id": str(billing_group.id),
                   "member_id": str(member_profile.user.id),
                   "addon_id": str(member_addon.addon.id),
               },
           },
       )
       # Add to primary member's subscription
       primary = billing_group.primary_member
       sub_item = stripe.SubscriptionItem.create(
           subscription=primary.stripe_subscription_id,
           price=price.id,
           proration_behavior="create_prorations",
       )
       member_addon.stripe_subscription_item_id = sub_item.id
       member_addon.stripe_price_id = price.id
       member_addon.save()
   ```
3. Set `profile.billing_group = billing_group`
4. Clear `profile.billing_group_invite = None`
5. Set `profile.subscription_status = "group_active"`

**Decline Behavior:**
1. Delete `BillingGroupMemberAddon` records (remove locked pricing)
2. Clear `profile.billing_group_invite = None`

### `POST /api/billing/billing-group/leave/`

Leave a billing group. Only secondary members can leave (primary must delete the group).

**Behavior:**
1. Remove Stripe subscription items
2. Delete `BillingGroupMemberAddon` records
3. Set `profile.billing_group = None`
4. Set `profile.subscription_status = "inactive"`

### `POST /api/billing/billing-group/invite-nonmember/`

Send an email invitation to someone who doesn't have an account yet.

**Request:**
```json
{ "email": "newperson@example.com" }
```

**Behavior:**
1. Verify no existing user with that email
2. Invalidate any previous invitations for that email + billing group
3. Create `BillingGroupInvite` record (token generated automatically, 7-day expiry)
4. Lock addon pricing (create `BillingGroupMemberAddon` placeholder — without `member` FK for now)
5. Send email with registration URL containing the invitation token:
   ```
   {SITE_URL}/signup?billing_group_invite={invitation_token}
   ```

### `GET /api/billing/billing-group/invitation/<uuid:token>/`

**Public endpoint** (no auth required). Validates an invitation token.

**Response (valid):**
```json
{
  "valid": true,
  "billingGroupName": "Smith Family",
  "invitedBy": "John Smith",
  "expiresDate": "2025-01-22T00:00:00Z"
}
```

**Response (invalid/expired):**
```json
{
  "valid": false,
  "reason": "expired"  // or "accepted", "invalidated", "not_found"
}
```

### `GET /api/billing/billing-group/invitations/`

List all invitations for the primary member's billing group.

**Response:**
```json
[
  {
    "id": 1,
    "email": "newperson@example.com",
    "status": "pending",
    "createdDate": "2025-01-15T10:00:00Z",
    "expiresDate": "2025-01-22T10:00:00Z"
  }
]
```

### `POST /api/billing/billing-group/invitations/<id>/resend/`

Resend an invitation email. Invalidates the old invitation and creates a new one with a fresh token and 7-day expiry.

### `DELETE /api/billing/billing-group/invitations/<id>/cancel/`

Cancel a pending invitation. Sets `invalidated=true`.

## Admin API Endpoints

Base path: `/api/admin/billing-groups/`. All require staff permission.

### `GET /api/admin/billing-groups/`

List all billing groups with member counts.

### `POST /api/admin/billing-groups/`

Create a billing group and assign a primary member.

**Request:**
```json
{
  "name": "Group Name",
  "primary_member_id": 5
}
```

### `GET /api/admin/billing-groups/<id>/`

Get billing group details including all members, addon records, and invitations.

### `PUT /api/admin/billing-groups/<id>/`

Update billing group name or reassign primary member.

### `DELETE /api/admin/billing-groups/<id>/`

Delete billing group. Same cleanup logic as user delete endpoint.

### `POST /api/admin/billing-groups/<id>/members/`

Admin add/remove member from billing group.

**Request:**
```json
{
  "action": "add",  // or "remove"
  "member_id": 8
}
```

### `POST /api/admin/billing-groups/<id>/invites/`

Admin manage invitations (send, resend, cancel).

## Registration Flow with Invitation Token

When a non-member registers via an invitation URL (`/signup?billing_group_invite={token}`):

1. Frontend passes `billing_group_invite` token during registration
2. Backend validates token via `GetBillingGroupInvitation`
3. On successful registration, store token on `profile.pending_billing_group_invite_token`
4. During `CompleteSignup`, check for pending token:
   - Find `BillingGroupInvite` by token
   - Auto-accept the invitation
   - Set `profile.billing_group` to the group
   - Set `profile.subscription_status = "group_active"`
   - Mark invite as accepted
   - Create Stripe subscription item on primary's subscription

## Frontend Components

### `BillingGroupManager.vue`

User-facing component shown on the Membership Plan page. Displays:
- Group name and members list (if in a group)
- "Create Billing Group" button (if not in a group and has subscription)
- "Invite Member" form (email input) for primary member
- "Remove" button next to each secondary member (primary only)
- "Leave Group" button (secondary members only)
- "Delete Group" button (primary only)

### `BillingGroupInviteBanner.vue`

Reusable banner component displayed on:
- **Dashboard** page
- **SelectTier** (plan selector) component
- **MembershipPlan** page

Shows when user has a `billing_group_invite` set. Displays:
- "You've been invited to join {group_name} by {inviter_name}"
- "Accept" and "Decline" buttons
- If user has active subscription, Accept shows confirmation dialog:
  > "Accepting this invitation will cancel your current individual subscription. You will receive a prorated refund for the remainder of your billing period. Your membership will be covered by the billing group."

### `CreateBillingGroupDialog.vue`

Modal dialog for creating a billing group:
- Name input field
- Confirmation that user will become primary member
- Warning if user doesn't have an active subscription

### `AdminBillingGroupManager.vue`

Admin component for managing all billing groups:
- Table listing all groups with name, primary member, member count
- Create group dialog (name + primary member selector)
- Edit group (rename, change primary)
- Add/remove members
- View/manage invitations
- Delete group with confirmation

## Migrations

```python
# profile/migrations/0023_rename_collective_to_billing_group.py
# Rename Collective model to BillingGroup (if upgrading from older name)

# profile/migrations/0024_billing_group_member_addon_pricing.py
# Create BillingGroupMemberAddon model

# Profile fields: billing_group, billing_group_invite, pending_billing_group_invite_token
```

## Testing Checklist

### Group Lifecycle
- [ ] Create billing group — primary member set, group FK updated
- [ ] Delete billing group — all members removed, Stripe items cleaned up, statuses reset

### Member Invitation (Existing Member)
- [ ] Invite existing member — `billing_group_invite` set, addon pricing locked
- [ ] Accept invitation without subscription — joins group, status `group_active`
- [ ] Accept invitation with active subscription — subscription cancelled with proration, joins group
- [ ] Decline invitation — addon pricing cleaned up, invite cleared
- [ ] Remove member — Stripe items removed, status reset to `inactive`

### Non-Member Invitation
- [ ] Send invitation email — `BillingGroupInvite` created with token
- [ ] Validate token (public endpoint) — returns group info
- [ ] Expired token — returns `valid: false`
- [ ] Register via invitation URL — auto-joins group after signup
- [ ] Resend invitation — old invalidated, new token created
- [ ] Cancel invitation — marked as invalidated

### Stripe Integration
- [ ] Accepting invite creates custom Stripe Price with member metadata
- [ ] Accepting invite creates subscription item on primary's subscription with proration
- [ ] Leaving group removes subscription item from primary's subscription
- [ ] Locked pricing is preserved even if addon cost changes later

### Admin
- [ ] List all billing groups
- [ ] Admin create/edit/delete billing group
- [ ] Admin add/remove members
- [ ] Admin manage invitations
