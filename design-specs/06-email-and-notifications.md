# Spec 06: Email & Notification Enhancements

## Summary

Enhance the email service to support billing group invitations and shelf rental assignment notifications. The system uses Postmark for email delivery with Django template rendering and event logging.

## Dependencies

- **Spec 04**: Billing Group System (invitation emails)
- **Spec 05**: Shelf Rental System (assignment notification emails)

## Existing Email Infrastructure

### `services/emails.py`

The email system is already functional. Two core functions exist:

#### `send_single_email(to_email, subject, template_vars, template_name=None, reply_to=None, user=None)`

- Renders Django HTML template with `template_vars` and `config` context
- Sends via Postmark API (if `POSTMARK_API_KEY` is configured)
- Escapes `message` in template_vars, converts `~br~` to `<br>`
- Handles Postmark error code `406` (inactive recipient) gracefully — logs warning instead of raising
- Logs email send events via `user.log_event("email", ...)`
- Returns `True` on success or when email is skipped due to config

#### `send_email_to_admin(subject, template_vars, template_name=None, reply_to=None, user=None)`

- Wrapper that sends to `config.EMAIL_ADMIN`

### Email Templates

Templates are Django HTML templates in the standard templates directory:

| Template | Usage |
|----------|-------|
| `email_without_button.html` | Default — title + message |
| `email_with_button.html` | Title + message + CTA button (link, btn_text) |
| `email_password_reset.html` | Password reset link |
| `email_welcome.html` | Welcome email with home page cards |

All templates receive `{{ email }}` (template_vars) and `{{ config }}` (constance config) in context.

### `User` model email methods

| Method | Template | Usage |
|--------|----------|-------|
| `email_link(subject, title, message, link, btn_text)` | `email_with_button.html` | Generic link email |
| `email_notification(subject, message)` | `email_without_button.html` | Generic notification |
| `email_password_reset(link)` | `email_password_reset.html` | Password reset |
| `email_membership_application()` | `email_without_button.html` | Signup notification to admin |
| `email_welcome()` | `email_welcome.html` | Welcome email with cards |
| `email_disable_member()` | `email_without_button.html` | Access disabled |
| `email_enable_member()` | `email_without_button.html` | Access enabled |

## New Email Flows

### 1. Billing Group Invitation (Existing Member)

**Triggered by:** `POST /api/billing/billing-group/members/` (Spec 04)

**Implementation:** Use existing `user.email_link()` method:

```python
invited_user.email_link(
    subject=f"You've been invited to join the billing group '{billing_group.name}'",
    title="Billing Group Invitation",
    message=f"{inviter.get_full_name()} has invited you to join their billing group "
            f"'{billing_group.name}'. Log in to your account to accept or decline.",
    link=f"{config.SITE_URL}/account/membership-plan",
    btn_text="View Invitation",
)
```

### 2. Billing Group Invitation (Non-Member Registration)

**Triggered by:** `POST /api/billing/billing-group/invite-nonmember/` (Spec 04)

**Implementation:** Use `send_single_email()` with the button template:

```python
send_single_email(
    to_email=email,
    subject=f"You've been invited to join {config.SITE_OWNER}",
    template_vars={
        "title": f"Join {billing_group.name}",
        "message": f"{inviter.get_full_name()} has invited you to join "
                   f"'{billing_group.name}' at {config.SITE_OWNER}. "
                   f"Click below to create your account and join the group.",
        "link": f"{config.SITE_URL}/signup?billing_group_invite={invite.invitation_token}",
        "btn_text": "Create Account & Join",
    },
    template_name="email_with_button.html",
    user=inviter_user,
)
```

### 3. Billing Group Invitation Resend

**Triggered by:** `POST /api/billing/billing-group/invitations/<id>/resend/` (Spec 04)

Same email as flow #2, but with the new invitation token (old one is invalidated).

### 4. Billing Group Member Status Change

**Triggered by:** Stripe webhook when primary member's payment fails (Spec 03)

**Implementation:** Notify affected group members:

```python
for member in billing_group.get_members():
    if member != primary_member:
        member.user.email_notification(
            subject=f"Billing group subscription issue",
            message=f"The primary member of your billing group '{billing_group.name}' "
                    f"has a payment issue. Your site access may be affected until resolved.",
        )
```

### 5. Shelf Assignment Notification

**Triggered by:** `POST /api/shelf-rental/admin/shelves/` with `action="assign"` (Spec 05)

**Implementation:** Uses configurable templates from constance config:

```python
def _send_assignment_notification(shelf, member):
    subject = config.SHELF_RENTAL_ASSIGNMENT_EMAIL_SUBJECT.format(
        shelf_number=shelf.number,
        available_date=shelf.start_date.strftime("%B %d, %Y") if shelf.start_date else "immediately",
    )
    body = config.SHELF_RENTAL_ASSIGNMENT_EMAIL_BODY.format(
        shelf_number=shelf.number,
        available_date=shelf.start_date.strftime("%B %d, %Y") if shelf.start_date else "immediately",
        member_name=member.get_full_name(),
    )
    member.user.email_notification(subject=subject, message=body)
```

### 6. Shelf Next-Occupant Promotion Notification

**Triggered by:** When current shelf member is removed and next_member is promoted (Spec 05)

Same as flow #5, called for the promoted member.

## Constance Configuration

Already defined in Spec 05:

```python
"SHELF_RENTAL_ASSIGNMENT_EMAIL_SUBJECT": (
    "Shelf #{shelf_number} Assigned - Available {available_date}",
    "Subject line for shelf assignment emails. Placeholders: {shelf_number}, {available_date}.",
),
"SHELF_RENTAL_ASSIGNMENT_EMAIL_BODY": (
    "Congratulations! You have been assigned Shelf #{shelf_number}.\n\n"
    "Your shelf will be available starting on {available_date}.\n\n"
    "Please note the shelf number for your records.",
    "Body for shelf assignment emails. Placeholders: {shelf_number}, {available_date}, {member_name}.",
),
```

## No New Templates Required

All new email flows use existing templates (`email_with_button.html` and `email_without_button.html`) with different template variables. The `~br~` escape sequence can be used in messages for line breaks.

## Error Handling

- Postmark error code `406` (inactive/bounced recipient): Logged as warning, does not raise exception, email silently skipped
- All other Postmark errors: Raised as exceptions (caught and handled by caller)
- Missing `POSTMARK_API_KEY`: Logged as warning, emails silently skipped
- All email operations are logged via `user.log_event("email", ...)`

## Testing Checklist

- [ ] Billing group invite email sent to existing member with correct link
- [ ] Non-member invite email sent with registration URL containing token
- [ ] Invitation resend uses new token in URL
- [ ] Group payment failure notification sent to all secondary members
- [ ] Shelf assignment email uses configurable subject/body templates
- [ ] Shelf next-occupant promotion triggers assignment email
- [ ] Postmark 406 error handled gracefully (no crash)
- [ ] Missing Postmark API key logs warning, doesn't crash
- [ ] All email sends logged via user.log_event()
- [ ] Template placeholders ({shelf_number}, {available_date}, {member_name}) correctly substituted
