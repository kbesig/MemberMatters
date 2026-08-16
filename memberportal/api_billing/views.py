from asgiref.sync import sync_to_async
from datetime import datetime
from dateutil.relativedelta import relativedelta
from django.http import HttpRequest

from profile.models import Profile
from access.models import Doors, Interlock
from api_admin_tools.models import *

from rest_framework import status, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

import stripe
import logging
from services.canvas import Canvas
from services.moodle_integration import (
    moodle_get_course_activity_completion_status,
    moodle_get_user_from_email,
)
from services.emails import send_email_to_admin, send_single_email
from constance import config
from django.db.utils import OperationalError
from sentry_sdk import capture_exception
from django.utils import timezone

logger = logging.getLogger("billing")


class StripeAPIView(APIView):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not config.ENABLE_STRIPE:
            return

        try:
            stripe.api_key = config.STRIPE_SECRET_KEY
            stripe.api_version = "2025-06-30.basil"
        except OperationalError as error:
            capture_exception(error)


class MemberBucksAddCard(StripeAPIView):
    """
    get: gets the client secret used to add new card details.
    post: saves the customers card details.
    """

    def get(self, request):
        profile = request.user.profile
        customer_exists = True

        # check that the customer exists and isn't deleted
        if profile.stripe_customer_id:
            try:
                customer = stripe.Customer.retrieve(profile.stripe_customer_id)
                if customer.get("deleted") or not customer:
                    customer_exists = False

            except stripe.error.InvalidRequestError as error:
                # Invalid parameters were supplied to Stripe's API
                capture_exception(error)

                # if the customer doesn't exist then remove the Stripe customer id
                if error.http_status == 404:
                    profile.stripe_customer_id = None
                    profile.save()

                    customer_exists = False

        else:
            customer_exists = False

        if not customer_exists:
            try:
                request.user.log_event(
                    "Attempting to create stripe customer.", "stripe"
                )
                customer = stripe.Customer.create(
                    email=request.user.email,
                    name=profile.get_full_name(),
                    phone=profile.phone,
                )

                profile.stripe_customer_id = customer.id
                profile.save()

                request.user.log_event(
                    f"Created stripe customer {request.user.profile.get_full_name()} (Stripe ID: {customer.id}).",
                    "stripe",
                )

                intent = stripe.SetupIntent.create(customer=profile.stripe_customer_id)

                return Response({"clientSecret": intent.client_secret})

            except stripe.error.StripeError as e:
                request.user.log_event(
                    "Unknown stripe while saving payment details.",
                    "stripe",
                    request,
                )
                capture_exception(e)

                return Response(
                    {
                        "success": False,
                        "message": str(e),
                    },
                    status=status.HTTP_503_SERVICE_UNAVAILABLE,
                )

            except Exception as e:
                request.user.log_event(
                    "Unknown other error while saving payment details.",
                    "stripe",
                    request,
                )
                capture_exception(e)
                return Response(
                    {
                        "success": False,
                        "message": "Unknown error (unrelated to stripe).",
                    },
                    status=status.HTTP_503_SERVICE_UNAVAILABLE,
                )

        else:
            intent = stripe.SetupIntent.create(customer=profile.stripe_customer_id)

            return Response({"clientSecret": intent.client_secret})

    def post(self, request):
        profile = request.user.profile
        payment_method_id = request.data.get("paymentMethodId")

        payment_method = stripe.PaymentMethod.retrieve(payment_method_id)

        profile.stripe_card_last_digits = payment_method["card"]["last4"]
        profile.stripe_card_expiry = f"{str(payment_method['card']['exp_month']).zfill(2)}/{str(payment_method['card']['exp_year'])}"
        profile.stripe_payment_method_id = payment_method_id
        profile.save()

        # attached the payment method to the customer
        stripe.PaymentMethod.attach(
            payment_method_id,
            customer=profile.stripe_customer_id,
        )
        # Set the default payment method on the customer
        stripe.Customer.modify(
            profile.stripe_customer_id,
            invoice_settings={
                "default_payment_method": payment_method_id,
            },
        )

        subject = f"You just added a payment card to your {config.SITE_OWNER} account."

        try:
            request.user.email_notification(
                subject,
                "Don't worry, your card details are stored safe "
                "with Stripe and are not on our servers. You "
                "can remove this card at any time via the "
                f"{config.SITE_NAME}.",
            )
        except Exception as e:
            capture_exception(e)
            return Response(
                {"message": "error.emailNotConfigured"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response()

    def delete(self, request):
        profile = request.user.profile

        if profile.stripe_payment_method_id:
            stripe.PaymentMethod.detach(profile.stripe_payment_method_id)

        profile.stripe_payment_method_id = ""
        profile.stripe_card_last_digits = ""
        profile.stripe_card_expiry = ""
        profile.save()
        return Response()


class MemberTiers(StripeAPIView):
    """
    get: gets a list of all membership tiers.
    """

    def get(self, request):
        tiers = MemberTier.objects.filter(visible=True)
        formatted_tiers = []

        for tier in tiers:
            plans = []

            for plan in tier.plans.filter(visible=True):
                plans.append(plan.get_object())

            formatted_tiers.append(tier.get_object())

        return Response(formatted_tiers)


class PaymentPlanSignup(StripeAPIView):
    """
    post: attempts to sign the member up to a new payment plan.
    """

    @staticmethod
    def _calculate_billing_cycle_anchor():
        """Returns a Unix timestamp for the 1st of next month (UTC)."""
        now = datetime.utcnow()
        first_of_next_month = (now + relativedelta(months=1)).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        return int(first_of_next_month.timestamp())

    @staticmethod
    def _needs_flexible_billing(base_plan, addon_items):
        """Check if subscription items have mixed intervals requiring flexible billing."""
        intervals = {base_plan.interval.lower()}
        for addon in addon_items:
            intervals.add(addon.interval.lower())
        return len(intervals) > 1

    @staticmethod
    def validate_subscription_intervals(base_interval, addon_interval):
        """
        With flexible billing, all interval combinations are valid.
        Returns (is_valid, warning_message).
        """
        if base_interval == addon_interval:
            return True, None

        warning = (
            f"Note: Base plan uses '{base_interval}' billing while add-on uses "
            f"'{addon_interval}' billing. This is supported with flexible billing "
            f"but may result in complex billing cycles."
        )
        return True, warning

    def create_subscription(
        self,
        request: HttpRequest,
        new_plan: PaymentPlan,
        subscription_items: list,
        billing_cycle_anchor: int,
        billing_mode: dict = None,
        attempts: int = 0,
    ):
        attempts += 1

        if attempts > 3:
            request.user.log_event(
                "Too many attempts while creating subscription.",
                "stripe",
                "",
            )
            return Response(
                {
                    "success": False,
                    "message": None,
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        subscription_params = {
            "customer": request.user.profile.stripe_customer_id,
            "items": subscription_items,
            "billing_cycle_anchor": billing_cycle_anchor,
            "proration_behavior": "create_prorations",
        }
        if billing_mode:
            subscription_params["billing_mode"] = billing_mode

        try:
            return stripe.Subscription.create(**subscription_params)

        except stripe.error.InvalidRequestError as e:
            capture_exception(e)
            error = e.json_body.get("error")

            if (
                error["code"] == "resource_missing"
                and "default payment method" in error["message"]
            ):
                request.user.log_event(
                    "InvalidRequestError (missing default payment method) from Stripe while creating subscription.",
                    "stripe",
                    error,
                )

                # try to set the default and try again
                stripe.Customer.modify(
                    request.user.profile.stripe_customer_id,
                    invoice_settings={
                        "default_payment_method": request.user.profile.stripe_payment_method_id,
                    },
                )

                return self.create_subscription(
                    request,
                    new_plan,
                    subscription_items,
                    billing_cycle_anchor,
                    billing_mode,
                    attempts,
                )

            if (
                error["code"] == "resource_missing"
                and "a similar object exists in live mode" in error["message"]
            ):
                request.user.log_event(
                    "InvalidRequestError (used test key with production object) from Stripe while "
                    "creating subscription.",
                    "stripe",
                    error,
                )

                return Response(
                    {
                        "success": False,
                        "message": error["message"],
                    },
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

            else:
                request.user.log_event(
                    "InvalidRequestError from Stripe while creating subscription.",
                    "stripe",
                    error,
                )
                return Response(
                    {
                        "success": False,
                        "message": None,
                    },
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        except Exception as e:
            request.user.log_event(
                "InvalidRequestError from Stripe while creating subscription.",
                "stripe",
                e,
            )
            capture_exception(e)
            return Response(
                {
                    "success": False,
                    "message": None,
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def post(self, request, plan_id):
        current_plan = request.user.profile.membership_plan
        new_plan = PaymentPlan.objects.get(pk=plan_id)

        if current_plan:
            return Response({"success": False}, status=status.HTTP_409_CONFLICT)

        # Build subscription items: base plan + optional addons
        subscription_items = [{"price": new_plan.stripe_id}]
        selected_addons = []
        addon_data = request.data.get("addons", [])

        if addon_data:
            from api_admin_tools.models import SubscriptionAddon

            for item in addon_data:
                addon_id = item.get("addon_id")
                quantity = item.get("quantity", 1)
                try:
                    addon = SubscriptionAddon.objects.get(pk=addon_id, visible=True)
                except SubscriptionAddon.DoesNotExist:
                    return Response(
                        {"success": False, "message": f"Addon {addon_id} not found."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                if not addon.stripe_price_id:
                    return Response(
                        {
                            "success": False,
                            "message": f"Addon {addon.name} has not been synced to Stripe.",
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                subscription_items.append(
                    {"price": addon.stripe_price_id, "quantity": quantity}
                )
                selected_addons.append(addon)

        billing_cycle_anchor = self._calculate_billing_cycle_anchor()
        billing_mode = (
            {"type": "flexible"}
            if self._needs_flexible_billing(new_plan, selected_addons)
            else None
        )

        new_subscription = self.create_subscription(
            request, new_plan, subscription_items, billing_cycle_anchor, billing_mode
        )

        try:
            if new_subscription.status == "active":
                request.user.profile.stripe_subscription_id = new_subscription.id
                request.user.profile.membership_plan = new_plan
                request.user.profile.subscription_status = "active"
                request.user.profile.save()

                request.user.log_event(
                    "Successfully created subscription in Stripe.",
                    "stripe",
                    "",
                )

                return Response({"success": True})

            elif new_subscription.status == "incomplete":
                # if we got here, that means the subscription wasn't successfully created
                request.user.log_event(
                    f"Failed to create subscription in Stripe with status {new_subscription.status}.",
                    "stripe",
                    "",
                )

                return Response(
                    {"success": True, "message": "signup.subscriptionFailed"}
                )

            else:
                request.user.log_event(
                    f"Failed to create subscription in Stripe with status {new_subscription.status}.",
                    "stripe",
                    "",
                )
                return Response({"success": True})

        except KeyError as e:
            capture_exception(e)
            return new_subscription or e


class CanSignup(APIView):
    """
    get: checks if the member is eligible to signup, and what actions they need to complete.
    """

    def get(self, request):
        return Response(request.user.profile.can_signup())


class AssignAccessCard(APIView):
    """
    post: assigns the access card to the member.
    """

    def post(self, request):
        profile = request.user.profile
        profile.rfid = request.data["accessCard"]
        profile.save()

        return Response({"success": True})


class CheckInductionStatus(APIView):
    """
    post: checks if the member has completed the induction (via the canvas/moodle API).
    """

    def post(self, request):
        if "induction" not in request.user.profile.can_signup()["requiredSteps"]:
            return Response({"success": True, "score": 0, "notRequired": True})

        score = 0

        if config.MOODLE_INDUCTION_ENABLED:
            user_id = moodle_get_user_from_email(request.user.email).get("id")
            activities = moodle_get_course_activity_completion_status(
                config.MOODLE_INDUCTION_COURSE_ID, user_id
            )
            score = activities["percentage_completed"]

        elif config.CANVAS_INDUCTION_ENABLED:
            try:
                canvas_api = Canvas()
            except OperationalError as error:
                capture_exception(error)
                logger.error(error)
                return Response({"success": False, "score": 0})

            score = (
                canvas_api.get_student_score_for_course(
                    config.CANVAS_INDUCTION_COURSE_ID, request.user.email
                )
                or 0
            )

        try:
            if score or config.MIN_INDUCTION_SCORE == 0:
                induction_passed = score >= config.MIN_INDUCTION_SCORE

                if induction_passed:
                    request.user.profile.update_last_induction()

                    return Response({"success": True, "score": score})
            return Response({"success": False, "score": score})

        except Exception as e:
            capture_exception(e)
            logger.error(e)
            return Response({"success": False, "score": 0, "error": str(e)})


class CompleteSignup(StripeAPIView):
    """
    post: completes the member's signup if they have completed all requirements and enables access
    """

    def post(self, request):
        member_profile = request.user.profile

        # Handle pending billing group invite token from registration
        if member_profile.pending_billing_group_invite_token:
            from profile.models import BillingGroupInvite, BillingGroupMemberAddon

            token = member_profile.pending_billing_group_invite_token
            invite = None
            try:
                invite = BillingGroupInvite.objects.get(invitation_token=token)
            except BillingGroupInvite.DoesNotExist:
                # Token record gone — try to find a valid invite by email as fallback
                fallback = (
                    BillingGroupInvite.objects.filter(
                        email=member_profile.user.email.lower(),
                        accepted=False,
                    )
                    .order_by("-created_date")
                    .first()
                )
                if fallback and not fallback.is_expired():
                    invite = fallback

            if invite and not invite.accepted and not invite.is_expired():
                billing_group = invite.billing_group
                primary = billing_group.primary_member

                # Create Stripe subscription item on primary's subscription
                if primary and primary.stripe_subscription_id:
                    addon_id = config.CURRENT_ADDITIONAL_MEMBER_ADDON
                    if addon_id:
                        from api_admin_tools.models import SubscriptionAddon

                        try:
                            addon = SubscriptionAddon.objects.get(pk=int(addon_id))
                            member_addon, _ = (
                                BillingGroupMemberAddon.objects.get_or_create(
                                    billing_group=billing_group,
                                    member=member_profile,
                                    defaults={
                                        "addon": addon,
                                        "locked_cost": addon.cost,
                                        "locked_currency": addon.currency,
                                        "locked_interval": addon.interval,
                                        "locked_interval_count": addon.interval_count,
                                    },
                                )
                            )
                            if not member_addon.stripe_subscription_item_id:
                                custom_price = stripe.Price.create(
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
                                            "addon_id": str(addon.id),
                                        },
                                    },
                                )
                                sub_item = stripe.SubscriptionItem.create(
                                    subscription=primary.stripe_subscription_id,
                                    price=custom_price.id,
                                    proration_behavior="create_prorations",
                                )
                                member_addon.stripe_subscription_item_id = sub_item.id
                                member_addon.stripe_price_id = custom_price.id
                                member_addon.save()
                        except Exception as e:
                            capture_exception(e)

                member_profile.billing_group = billing_group
                member_profile.subscription_status = "group_active"
                member_profile.pending_billing_group_invite_token = None
                member_profile.save()
                invite.accept()
            else:
                # No usable invite found — clear the stale token
                member_profile.pending_billing_group_invite_token = None
                member_profile.save()

        if member_profile.subscription_status not in ("active", "group_active"):
            return Response(
                {
                    "success": False,
                    "message": "signup.requirementsNotMet",
                    "items": ["No active subscription found."],
                }
            )

        signupCheck = member_profile.can_signup()

        if signupCheck["success"]:
            member_profile.activate()

            # give default door access
            for door in Doors.objects.filter(all_members=True):
                member_profile.doors.add(door)

            # give default interlock access
            for interlock in Interlock.objects.filter(all_members=True):
                member_profile.interlocks.add(interlock)

            member_profile.user.email_membership_application()
            member_profile.user.email_welcome()

            return Response({"success": True})

        return Response(
            {
                "success": False,
                "message": "signup.requirementsNotMet",
                "items": signupCheck["requiredSteps"],
            }
        )


class SkipSignup(APIView):
    """
    post: skips the billing/tier signup process if they just want an account
    """

    def post(self, request):
        request.user.profile.set_account_only()

        return Response({"success": True})


class SubscriptionInfo(StripeAPIView):
    """
    get: retrieves information about the members subscription.
    """

    def get(self, request):
        current_plan = request.user.profile.membership_plan

        if not current_plan or not request.user.profile.stripe_subscription_id:
            return Response({"success": False})

        else:
            try:
                s = stripe.Subscription.retrieve(
                    request.user.profile.stripe_subscription_id,
                    expand=["items.data.price"],
                )
            except stripe.error.InvalidRequestError:
                logger.warning(
                    f"Stripe subscription {request.user.profile.stripe_subscription_id} not found for user {request.user.email}"
                )
                return Response({"success": False})

            if s:
                # Build addon items list from subscription items (excluding the base plan)
                addon_items = []
                base_plan_price_id = current_plan.stripe_id
                for item in s["items"]["data"]:
                    if item["price"]["id"] != base_plan_price_id:
                        recurring = item["price"].get("recurring") or {}
                        addon_items.append(
                            {
                                "id": item["id"],
                                "name": item["price"].get("nickname")
                                or item["price"]["id"],
                                "cost": item["price"].get("unit_amount"),
                                "currency": item["price"].get("currency"),
                                "interval": recurring.get("interval"),
                                "interval_count": recurring.get("interval_count"),
                                "quantity": item.get("quantity"),
                            }
                        )

                # Stripe API 2024-09-30+ moved period fields to subscription items
                first_item = s.get("items", {}).get("data", [None])[0] or {}
                current_period_end = s.get("current_period_end") or first_item.get(
                    "current_period_end"
                )
                billing_cycle_anchor = s.get("billing_cycle_anchor") or first_item.get(
                    "billing_cycle_anchor"
                )

                subscription = {
                    "billingCycleAnchor": billing_cycle_anchor,
                    "currentPeriodEnd": current_period_end,
                    "cancelAt": s.get("cancel_at"),
                    "cancelAtPeriodEnd": s.get("cancel_at_period_end"),
                    "startDate": s.get("start_date"),
                    "membershipTier": request.user.profile.membership_plan.member_tier.get_object(),
                    "membershipPlan": request.user.profile.membership_plan.get_object(),
                    "subscriptionStatus": request.user.profile.subscription_status,
                    "subscriptionFirstCreated": request.user.profile.subscription_first_created,
                    "addons": addon_items,
                }
                return Response({"success": True, "subscription": subscription})

            return Response({"success": False})


class MembershipPlanCostSummary(StripeAPIView):
    """
    get: returns the upcoming invoice details for the member's subscription.
    """

    def get(self, request):
        profile = request.user.profile

        if not profile.stripe_customer_id or not profile.stripe_subscription_id:
            return Response({"success": False})

        try:
            upcoming = stripe.Invoice.create_preview(
                customer=profile.stripe_customer_id,
                subscription=profile.stripe_subscription_id,
            )

            # Collect identifiers for classification
            main_price_id = (
                profile.membership_plan.stripe_id if profile.membership_plan else None
            )
            from profile.models import BillingGroupMemberAddon

            billing_group_item_ids = set(
                BillingGroupMemberAddon.objects.filter(
                    billing_group__primary_member=profile
                ).values_list("stripe_subscription_item_id", flat=True)
            )

            _sort_order = {
                "main": 0,
                "billing_group_addon": 1,
                "addon": 2,
                "proration": 3,
            }

            def _classify(line):
                parent = line.get("parent") or {}
                sub_details = parent.get("subscription_item_details") or {}
                if sub_details.get("proration"):
                    return "proration"
                pricing = line.get("pricing") or {}
                price_details = pricing.get("price_details") or {}
                price_id = price_details.get("price")
                if main_price_id and price_id == main_price_id:
                    return "main"
                sub_item = sub_details.get("subscription_item")
                if sub_item and sub_item in billing_group_item_ids:
                    return "billing_group_addon"
                return "addon"

            raw_lines = list(upcoming.lines.data)
            raw_lines.sort(key=lambda l: _sort_order[_classify(l)])

            lines = [
                {
                    "description": line.get("description") or "",
                    "amount": line.amount,
                    "category": _classify(line),
                }
                for line in raw_lines
            ]
            return Response(
                {
                    "success": True,
                    "upcoming": {
                        "amount_due": upcoming.amount_due,
                        "currency": upcoming.currency,
                        "period_start": upcoming.period_start,
                        "period_end": upcoming.period_end,
                        "lines": lines,
                    },
                }
            )
        except stripe.error.StripeError as e:
            capture_exception(e)
            return Response(
                {"success": False}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class PaymentPlanResumeCancel(StripeAPIView):
    """
    post: attempts to cancel a member's payment plan.
    """

    def post(self, request, resume):
        current_plan = request.user.profile.membership_plan
        resume = True if resume == "resume" else False

        if not current_plan:
            request.user.log_event(
                "Member tried to modify nonexistant membership plan.", "stripe"
            )
            return Response(
                {"success": False, "message": "paymentPlan.notExists"},
                status=status.HTTP_404_NOT_FOUND,
            )

        else:
            if resume and not request.user.profile.stripe_subscription_id:
                request.user.log_event(
                    "Member tried to resume a payment plan that doesn't exist - creating it.",
                    "stripe",
                )
                new_subscription = PaymentPlanSignup().create_subscription(
                    request,
                    current_plan,
                    subscription_items=[{"price": current_plan.stripe_id}],
                    billing_cycle_anchor=PaymentPlanSignup._calculate_billing_cycle_anchor(),
                )

                try:
                    if new_subscription.status == "active":
                        request.user.profile.stripe_subscription_id = (
                            new_subscription.id
                        )
                        request.user.profile.subscription_status = "active"
                        request.user.profile.save()

                        request.user.log_event(
                            "Successfully created subscription in Stripe.",
                            "stripe",
                            "",
                        )

                        return Response({"success": True})

                    elif new_subscription.status == "incomplete":
                        # if we got here, that means the subscription wasn't successfully created
                        request.user.log_event(
                            f"Failed to create subscription in Stripe with status {new_subscription.status}.",
                            "stripe",
                            "",
                        )

                        return Response(
                            {"success": True, "message": "signup.subscriptionFailed"}
                        )

                    else:
                        request.user.log_event(
                            f"Failed to create subscription in Stripe with status {new_subscription.status}.",
                            "stripe",
                            "",
                        )
                        return Response({"success": True})

                except KeyError as e:
                    capture_exception(e)
                    return new_subscription or e

            elif resume:
                modified_subscription = stripe.Subscription.modify(
                    request.user.profile.stripe_subscription_id,
                    cancel_at_period_end=False,
                )

                if not modified_subscription.cancel_at_period_end:
                    request.user.profile.subscription_status = "active"
                    request.user.profile.save()
                    subject = f"{request.user.get_full_name()} resumed their cancelling membership plan."
                    send_email_to_admin(
                        subject=subject,
                        template_vars={
                            "title": subject,
                            "message": subject,
                        },
                        user=request.user,
                        reply_to=request.user.email,
                    )
                    request.user.log_event(
                        subject,
                        "stripe",
                    )
                    return Response({"success": True})

                else:
                    subject = f"{request.user.get_full_name()} tried to resume their cancelling membership plan but it failed."
                    send_email_to_admin(
                        subject=subject,
                        template_vars={
                            "title": subject,
                            "message": subject,
                        },
                        user=request.user,
                        reply_to=request.user.email,
                    )
                    request.user.log_event(
                        subject,
                        "stripe",
                    )

            else:
                modified_subscription = stripe.Subscription.modify(
                    request.user.profile.stripe_subscription_id,
                    cancel_at_period_end=True,
                )

                if modified_subscription.cancel_at_period_end == True:
                    request.user.profile.subscription_status = "cancelling"
                    request.user.profile.save()
                    subject = f"{request.user.get_full_name()} requested to cancel their membership plan."
                    description = "No further action is required, the subscription will automatically cancel at the end of the current billing period."

                    send_email_to_admin(
                        subject=subject,
                        template_vars={
                            "title": subject,
                            "message": description,
                        },
                        user=request.user,
                        reply_to=request.user.email,
                    )

                    subject = "You've requested to cancel your membership plan."
                    description = "No further action is required, the subscription will automatically cancel at the end of the current billing period. You can cancel this request at any time from the member portal."
                    request.user.email_notification(subject, description)

                    request.user.log_event(
                        subject,
                        "stripe",
                    )
                    return Response({"success": True})

                else:
                    subject = f"{request.user.get_full_name()} requested to cancel their membership plan but it failed."

                    send_email_to_admin(
                        subject=subject,
                        template_vars={
                            "title": subject,
                            "message": "We're not sure what happened, you should check Stripe and contact the member.",
                        },
                        user=request.user,
                        reply_to=request.user.email,
                    )
                    request.user.log_event(
                        subject,
                        "stripe",
                    )

            return Response({"success": False})


class StripeWebhook(StripeAPIView):
    """
    post: processes a Stripe webhook event.
    """

    permission_classes = (permissions.AllowAny,)

    def post(self, request):
        webhook_secret = config.STRIPE_WEBHOOK_SECRET
        body = request.body
        request_data = request.data

        if webhook_secret:
            # Retrieve the event by verifying the signature if webhook signing is configured.
            signature = request.headers.get("stripe-signature")
            try:
                event = stripe.Webhook.construct_event(
                    payload=body, sig_header=signature, secret=webhook_secret
                )
                data = event["data"]
            except Exception as e:
                logger.error(e)
                capture_exception(e)
                return Response({"error": "Error validating Stripe signature."})

            # Get the type of webhook event sent - used to check the status of PaymentIntents.
            event_type = event["type"]
        else:
            data = request_data["data"]
            event_type = request_data["type"]

        data = data["object"]
        try:
            member_profile = Profile.objects.get(stripe_customer_id=data["customer"])

        except Profile.DoesNotExist as e:
            capture_exception(e)
            return Response()

        # Just in case the linked Stripe account also processes other payments we should just ignore a non existent
        # customer.
        if not member_profile:
            return Response()

        if event_type == "invoice.paid":
            invoice_status = data["status"]

            member_profile.user.log_event("Membership payment received.", "stripe")

            if (
                invoice_status == "paid"
                and not member_profile.subscription_first_created
            ):
                member_profile.subscription_first_created = timezone.now()
                member_profile.save()

            # If they aren't an active member, are allowed to signup, and have paid the invoice
            # then lets activate their account (this could be a new OR returning member)
            if (
                member_profile.state != "active"
                and member_profile.can_signup()["success"]
                and invoice_status == "paid"
            ):
                subject = "Your payment was successful."
                message = (
                    "Thanks for making a membership payment using our online payment system. "
                    "You've already met all of the requirements for activating your site access. Please check "
                    "for another email message confirming this was successful."
                )
                member_profile.user.email_notification(subject, message)

                # set the subscription status to active
                member_profile.subscription_status = "active"
                member_profile.save()

                # cascade to billing group members
                if hasattr(member_profile, "billing_group_primary_member"):
                    for (
                        member
                    ) in member_profile.billing_group_primary_member.get_members():
                        if member != member_profile:
                            member.subscription_status = "group_active"
                            member.save()

                # activate their access card
                member_profile.activate()

                member_profile.user.log_event(
                    "Activated membership because member met all requirements.",
                    "stripe",
                )

            # If they aren't an active member, are NOT allowed to signup, and have paid the invoice
            # then we need to let them know and mark the subscription as active
            # (this could be a new OR returning member that's been too long since induction etc.)
            elif member_profile.state != "active" and invoice_status == "paid":
                subject = "Your payment was successful."
                message = (
                    "Thanks for making a membership payment using our online payment system. "
                    "You haven't yet met all of the requirements for automatically activating your site access. "
                    "You'll receive confirmation that your site access is enabled soon, or we'll be in touch. "
                    "If you don't hear from us soon or require assistance, please contact us."
                )
                member_profile.user.email_notification(subject, message)

                member_profile.subscription_status = "active"
                member_profile.save()

                # cascade to billing group members
                if hasattr(member_profile, "billing_group_primary_member"):
                    for (
                        member
                    ) in member_profile.billing_group_primary_member.get_members():
                        if member != member_profile:
                            member.subscription_status = "group_active"
                            member.save()

                # if this is a returning member then send the exec an email (new members have
                # already had this sent)
                if member_profile.state != "noob":
                    subject = "Action Required: Verify returning member"
                    title = subject
                    message = (
                        "An existing member (or someone who clicked 'skip signup I just want an account') "
                        "has setup a membership subscription. You must now decide whether to enable their site access."
                    )
                    send_email_to_admin(
                        subject, title, message, reply_to=member_profile.user.email
                    )

                member_profile.user.log_event(
                    "Did not activate membership because member did not meet all requirements.",
                    "stripe",
                )

            # For already-active members, re-confirm subscription_status on renewal
            # (handles edge cases like cancelling -> renewed, or other status drift)
            elif member_profile.state == "active" and invoice_status == "paid":
                if member_profile.subscription_status not in (
                    "active",
                    "group_active",
                    "group_inactive",
                ):
                    member_profile.subscription_status = "active"
                    member_profile.save()

            # in all other instances, we don't care about a paid invoice and can ignore it

        if event_type == "invoice.payment_failed":
            subject = "Your membership payment failed"
            message = (
                "Hi there, we tried to collect your membership payment but "
                "weren't successful. Please update your billing method or contact "
                "us if you need more time. We'll try again a few times, but if we're unable to "
                "collect your payment soon, your membership may be cancelled."
            )

            member_profile.user.email_notification(subject, message)
            member_profile.user.log_event("Membership payment failed", "stripe")

        if event_type == "customer.subscription.deleted":
            # the subscription was deleted, so deactivate the member
            subject = "Your membership has been cancelled"
            message = (
                "You will receive another email shortly confirming that your access has been deactivated. Your "
                "membership was cancelled because we couldn't collect your payment, or you chose not to renew it."
            )

            member_profile.deactivate()
            member_profile.user.email_notification(subject, message)

            member_profile.membership_plan = None
            member_profile.stripe_subscription_id = None
            member_profile.subscription_status = "inactive"
            member_profile.save()

            # cascade group_inactive to all group members
            if hasattr(member_profile, "billing_group_primary_member"):
                billing_group = member_profile.billing_group_primary_member
                for member in billing_group.get_members():
                    if member != member_profile:
                        member.subscription_status = "group_inactive"
                        member.save()

            member_profile.user.log_event(
                "Membership was cancelled due to Stripe subscription ending", "stripe"
            )

            subject = f"The membership for {member_profile.get_full_name()} was just cancelled"
            title = subject
            message = (
                f"The Stripe subscription for {member_profile.get_full_name()} ended, so their membership has "
                f"been cancelled. Their site access has been turned off."
            )
            template_vars = {"title": title, "message": message}

            send_email_to_admin(
                subject,
                template_vars=template_vars,
                reply_to=member_profile.user.email,
                user=member_profile.user,
            )

        return Response()


class AddonList(StripeAPIView):
    """
    get: returns all visible subscription addons available to members.
    """

    def get(self, request):
        from api_admin_tools.models import SubscriptionAddon

        addons = SubscriptionAddon.objects.filter(visible=True)
        return Response([a.get_object() for a in addons])


class SubscriptionAddonManagement(StripeAPIView):
    """
    post: adds or removes an addon from the member's active subscription.
    """

    def post(self, request):
        profile = request.user.profile
        addon_id = request.data.get("addon_id")
        action = request.data.get("action")  # "add" or "remove"
        quantity = request.data.get("quantity", 1)

        if not addon_id or action not in ("add", "remove"):
            return Response(
                {"error": "addon_id and action ('add' or 'remove') are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not profile.stripe_subscription_id:
            return Response(
                {"error": "No active Stripe subscription found."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from api_admin_tools.models import SubscriptionAddon

        try:
            addon = SubscriptionAddon.objects.get(pk=addon_id)
        except SubscriptionAddon.DoesNotExist:
            return Response(
                {"error": "Addon not found."}, status=status.HTTP_404_NOT_FOUND
            )

        if not addon.stripe_price_id:
            return Response(
                {"error": "Addon has not been synced to Stripe yet."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            if action == "add":
                stripe.SubscriptionItem.create(
                    subscription=profile.stripe_subscription_id,
                    price=addon.stripe_price_id,
                    quantity=quantity,
                    proration_behavior="create_prorations",
                )
                request.user.log_event(
                    f"Added addon '{addon.name}' (qty {quantity}) to subscription.",
                    "stripe",
                )
                return Response(
                    {"success": True, "message": "Add-on added successfully."}
                )

            else:  # remove
                subscription = stripe.Subscription.retrieve(
                    profile.stripe_subscription_id
                )
                item_to_delete = None
                for item in subscription["items"]["data"]:
                    if item["price"]["id"] == addon.stripe_price_id:
                        item_to_delete = item["id"]
                        break

                if not item_to_delete:
                    return Response(
                        {"error": "Addon not found on subscription."},
                        status=status.HTTP_404_NOT_FOUND,
                    )

                stripe.SubscriptionItem.delete(
                    item_to_delete,
                    proration_behavior="create_prorations",
                )
                request.user.log_event(
                    f"Removed addon '{addon.name}' from subscription.",
                    "stripe",
                )
                return Response(
                    {"success": True, "message": "Add-on removed successfully."}
                )

        except stripe.error.StripeError as e:
            capture_exception(e)
            return Response(
                {"error": str(e)}, status=status.HTTP_503_SERVICE_UNAVAILABLE
            )


class BillingGroupView(StripeAPIView):
    """
    get: returns the current user's billing group info and any pending invite.
    post: creates a new billing group with the current user as primary member.
    delete: deletes the billing group (primary member only).
    """

    def get(self, request):
        profile = request.user.profile
        billing_group = profile.billing_group
        billing_group_invite = profile.billing_group_invite

        group_data = None
        if billing_group:
            group_obj = billing_group.get_object()
            group_obj["isPrimaryMember"] = billing_group.primary_member == profile

            # Augment each member entry with their locked addon pricing
            from profile.models import BillingGroupMemberAddon as BGMA

            addon_lookup = {
                ma.member.user_id: ma
                for ma in BGMA.objects.filter(
                    billing_group=billing_group
                ).select_related("addon", "member")
            }
            for member in group_obj["members"]:
                ma = addon_lookup.get(member["id"])
                if ma:
                    member["addonName"] = ma.addon.name
                    member["lockedCost"] = ma.locked_cost
                    member["lockedCurrency"] = ma.locked_currency
                    member["lockedInterval"] = ma.locked_interval
                    member["lockedIntervalCount"] = ma.locked_interval_count
                else:
                    member["addonName"] = None
                    member["lockedCost"] = None
                    member["lockedCurrency"] = None
                    member["lockedInterval"] = None
                    member["lockedIntervalCount"] = None

            group_data = group_obj

        invite_data = None
        if billing_group_invite:
            primary = billing_group_invite.primary_member
            invited_by_name = primary.get_full_name() if primary else None
            invite_data = {
                "groupName": billing_group_invite.name,
                "billingGroupId": billing_group_invite.id,
                "invitedBy": invited_by_name,
            }
            # Find who invited this member via BillingGroupMemberAddon record
            from profile.models import BillingGroupMemberAddon

            try:
                member_addon = BillingGroupMemberAddon.objects.get(
                    billing_group=billing_group_invite, member=profile
                )
                invite_data["lockedCost"] = member_addon.locked_cost
                invite_data["lockedInterval"] = member_addon.locked_interval
            except BillingGroupMemberAddon.DoesNotExist:
                pass

        return Response(
            {"success": True, "billingGroup": group_data, "pendingInvite": invite_data}
        )

    def post(self, request):
        profile = request.user.profile
        name = request.data.get("name", "").strip()

        if not name:
            return Response(
                {"success": False, "message": "Group name is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if profile.billing_group:
            return Response(
                {"success": False, "message": "You are already in a billing group."},
                status=status.HTTP_409_CONFLICT,
            )

        if not profile.has_active_subscription():
            return Response(
                {
                    "success": False,
                    "message": "You must have an active subscription to create a billing group.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        from profile.models import BillingGroup

        billing_group = BillingGroup.objects.create(name=name)
        billing_group.primary_member = profile
        billing_group.save()
        profile.billing_group = billing_group
        profile.save()

        request.user.log_event(f"Created billing group '{name}'.", "admin")

        return Response(
            {"success": True, "billingGroup": billing_group.get_object()},
            status=status.HTTP_201_CREATED,
        )

    def delete(self, request):
        profile = request.user.profile
        billing_group = profile.billing_group

        if not billing_group or billing_group.primary_member != profile:
            return Response(
                {
                    "success": False,
                    "message": "Only the primary member can delete the billing group.",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        # Clean up each secondary member
        for member in billing_group.get_members():
            if member == profile:
                continue
            from profile.models import BillingGroupMemberAddon

            member_addons = BillingGroupMemberAddon.objects.filter(
                billing_group=billing_group, member=member
            )
            for member_addon in member_addons:
                if member_addon.stripe_subscription_item_id:
                    try:
                        stripe.SubscriptionItem.delete(
                            member_addon.stripe_subscription_item_id,
                            proration_behavior="create_prorations",
                        )
                    except stripe.error.StripeError as e:
                        capture_exception(e)
                member_addon.delete()
            member.billing_group = None
            member.subscription_status = "inactive"
            member.save()

        # Clear any pending invites
        profile.billing_group = None
        profile.save()

        billing_group.delete()

        request.user.log_event("Deleted billing group.", "admin")

        return Response({"success": True})


class BillingGroupMembersView(StripeAPIView):
    """
    post: invite an existing member to the billing group.
    delete: remove a member from the billing group.
    """

    def post(self, request):
        profile = request.user.profile
        billing_group = profile.billing_group

        if not billing_group or billing_group.primary_member != profile:
            return Response(
                {
                    "success": False,
                    "message": "Only the primary member can invite members.",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        email = request.data.get("email", "").strip().lower()
        if not email:
            return Response(
                {"success": False, "message": "Email is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from django.contrib.auth import get_user_model

        User = get_user_model()

        try:
            target_user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            return Response(
                {"success": False, "message": "No member found with that email."},
                status=status.HTTP_404_NOT_FOUND,
            )

        target_profile = target_user.profile

        if target_profile.billing_group or target_profile.billing_group_invite:
            return Response(
                {
                    "success": False,
                    "message": "That member is already in or invited to a billing group.",
                },
                status=status.HTTP_409_CONFLICT,
            )

        # Lock addon pricing
        addon_id = config.CURRENT_ADDITIONAL_MEMBER_ADDON
        if not addon_id:
            return Response(
                {"success": False, "message": "No additional member addon configured."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        from api_admin_tools.models import SubscriptionAddon
        from profile.models import BillingGroupMemberAddon

        try:
            addon = SubscriptionAddon.objects.get(pk=int(addon_id))
        except (SubscriptionAddon.DoesNotExist, ValueError):
            return Response(
                {
                    "success": False,
                    "message": "Configured additional member addon not found.",
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        BillingGroupMemberAddon.objects.create(
            billing_group=billing_group,
            member=target_profile,
            addon=addon,
            locked_cost=addon.cost,
            locked_currency=addon.currency,
            locked_interval=addon.interval,
            locked_interval_count=addon.interval_count,
        )

        target_profile.billing_group_invite = billing_group
        target_profile.save()

        request.user.log_event(
            f"Invited {target_profile.get_full_name()} to billing group.", "admin"
        )

        try:
            target_user.email_link(
                subject=f"You've been invited to join the billing group '{billing_group.name}'",
                title="Billing Group Invitation",
                message=(
                    f"{request.user.profile.get_full_name()} has invited you to join their billing group "
                    f"'{billing_group.name}'. Log in to your account to accept or decline."
                ),
                link=f"{config.SITE_URL}/account/membership-plan",
                btn_text="View Invitation",
            )
        except Exception:
            pass

        return Response({"success": True})

    def delete(self, request):
        profile = request.user.profile
        billing_group = profile.billing_group

        if not billing_group or billing_group.primary_member != profile:
            return Response(
                {
                    "success": False,
                    "message": "Only the primary member can remove members.",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        member_id = request.data.get("member_id")
        if not member_id:
            return Response(
                {"success": False, "message": "member_id is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from profile.models import Profile, BillingGroupMemberAddon

        try:
            target_profile = Profile.objects.get(user__id=member_id)
        except Profile.DoesNotExist:
            return Response(
                {"success": False, "message": "Member not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if target_profile.billing_group != billing_group:
            return Response(
                {"success": False, "message": "Member not in this billing group."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        member_addons = BillingGroupMemberAddon.objects.filter(
            billing_group=billing_group, member=target_profile
        )
        for member_addon in member_addons:
            if member_addon.stripe_subscription_item_id:
                try:
                    stripe.SubscriptionItem.delete(
                        member_addon.stripe_subscription_item_id,
                        proration_behavior="create_prorations",
                    )
                except stripe.error.StripeError as e:
                    capture_exception(e)
            member_addon.delete()

        target_profile.billing_group = None
        target_profile.subscription_status = "inactive"
        target_profile.save()

        request.user.log_event(
            f"Removed {target_profile.get_full_name()} from billing group.", "admin"
        )

        return Response({"success": True})


class BillingGroupInviteAccept(StripeAPIView):
    """
    post: accept or decline a billing group invitation.
    """

    def post(self, request):
        profile = request.user.profile
        billing_group = profile.billing_group_invite

        if not billing_group:
            return Response(
                {"success": False, "message": "No pending billing group invitation."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        action = request.data.get("action")
        if action not in ("accept", "decline"):
            return Response(
                {"success": False, "message": "action must be 'accept' or 'decline'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from profile.models import BillingGroupMemberAddon

        if action == "decline":
            BillingGroupMemberAddon.objects.filter(
                billing_group=billing_group, member=profile
            ).delete()
            profile.billing_group_invite = None
            profile.save()
            request.user.log_event("Declined billing group invitation.", "admin")
            return Response({"success": True})

        # Accept
        # Cancel individual subscription if active
        if profile.stripe_subscription_id:
            try:
                stripe.Subscription.delete(
                    profile.stripe_subscription_id,
                    proration_behavior="create_prorations",
                )
            except stripe.error.StripeError as e:
                capture_exception(e)
            profile.stripe_subscription_id = ""
            profile.membership_plan = None

        # Create a custom Stripe price for this member's locked rate on primary's subscription
        primary = billing_group.primary_member
        if primary and primary.stripe_subscription_id:
            try:
                member_addon = BillingGroupMemberAddon.objects.get(
                    billing_group=billing_group, member=profile
                )
                custom_price = stripe.Price.create(
                    unit_amount=member_addon.locked_cost,
                    currency=member_addon.locked_currency,
                    recurring={
                        "interval": member_addon.locked_interval,
                        "interval_count": member_addon.locked_interval_count,
                    },
                    product_data={
                        "name": f"Additional Member - {profile.get_full_name()}",
                        "metadata": {
                            "billing_group_id": str(billing_group.id),
                            "member_id": str(profile.user.id),
                            "addon_id": str(member_addon.addon.id),
                        },
                    },
                )
                sub_item = stripe.SubscriptionItem.create(
                    subscription=primary.stripe_subscription_id,
                    price=custom_price.id,
                    proration_behavior="create_prorations",
                )
                member_addon.stripe_subscription_item_id = sub_item.id
                member_addon.stripe_price_id = custom_price.id
                member_addon.save()
            except stripe.error.StripeError as e:
                capture_exception(e)

        profile.billing_group = billing_group
        profile.billing_group_invite = None
        profile.subscription_status = "group_active"
        profile.save()

        request.user.log_event(
            f"Accepted billing group invitation to '{billing_group.name}'.", "admin"
        )

        return Response({"success": True})


class BillingGroupLeave(StripeAPIView):
    """
    post: leave the current billing group (secondary members only).
    """

    def post(self, request):
        profile = request.user.profile
        billing_group = profile.billing_group

        if not billing_group:
            return Response(
                {"success": False, "message": "You are not in a billing group."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if billing_group.primary_member == profile:
            return Response(
                {
                    "success": False,
                    "message": "Primary members must delete the group, not leave.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        from profile.models import BillingGroupMemberAddon

        member_addons = BillingGroupMemberAddon.objects.filter(
            billing_group=billing_group, member=profile
        )
        for member_addon in member_addons:
            if member_addon.stripe_subscription_item_id:
                try:
                    stripe.SubscriptionItem.delete(
                        member_addon.stripe_subscription_item_id,
                        proration_behavior="create_prorations",
                    )
                except stripe.error.StripeError as e:
                    capture_exception(e)
            member_addon.delete()

        profile.billing_group = None
        profile.subscription_status = "inactive"
        profile.save()

        request.user.log_event("Left billing group.", "admin")

        return Response({"success": True})


class BillingGroupInviteNonMember(StripeAPIView):
    """
    post: send a billing group invitation to a non-registered email.
    """

    def post(self, request):
        profile = request.user.profile
        billing_group = profile.billing_group

        if not billing_group or billing_group.primary_member != profile:
            return Response(
                {
                    "success": False,
                    "message": "Only the primary member can send invitations.",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        email = request.data.get("email", "").strip().lower()
        if not email:
            return Response(
                {"success": False, "message": "Email is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from django.contrib.auth import get_user_model

        User = get_user_model()

        if User.objects.filter(email__iexact=email).exists():
            return Response(
                {
                    "success": False,
                    "message": "A member with that email already exists. Use the invite member endpoint.",
                },
                status=status.HTTP_409_CONFLICT,
            )

        from profile.models import BillingGroupInvite

        # Invalidate any prior invitations for this email + group
        existing = BillingGroupInvite.objects.filter(
            email=email, billing_group=billing_group, accepted=False, invalidated=False
        )
        for inv in existing:
            inv.invalidate()

        invite = BillingGroupInvite.objects.create(
            email=email,
            billing_group=billing_group,
            invited_by=request.user,
        )

        invite_url = (
            f"{config.SITE_URL}/register?billing_group_invite={invite.invitation_token}"
        )
        request.user.log_event(f"Sent billing group invitation to {email}.", "admin")

        try:
            send_single_email(
                to_email=email,
                subject=f"You've been invited to join {config.SITE_OWNER}",
                template_vars={
                    "title": f"Join {billing_group.name}",
                    "message": (
                        f"{request.user.profile.get_full_name()} has invited you to join "
                        f"'{billing_group.name}' at {config.SITE_OWNER}. "
                        f"Click below to create your account and join the group."
                    ),
                    "link": invite_url,
                    "btn_text": "Create Account & Join",
                },
                template_name="email_with_button.html",
                user=request.user,
            )
        except Exception:
            pass

        # Email notification handled by Spec 06
        return Response({"success": True, "inviteUrl": invite_url})


class GetBillingGroupInvitation(APIView):
    """
    get: validate a billing group invitation token (public endpoint).
    """

    permission_classes = (permissions.AllowAny,)

    def get(self, request, token):
        from profile.models import BillingGroupInvite

        try:
            invite = BillingGroupInvite.objects.get(invitation_token=token)
        except BillingGroupInvite.DoesNotExist:
            return Response({"valid": False, "reason": "not_found"})

        if invite.accepted:
            return Response({"valid": False, "reason": "accepted"})
        if invite.invalidated:
            return Response({"valid": False, "reason": "invalidated"})
        if invite.is_expired():
            return Response({"valid": False, "reason": "expired"})

        primary = invite.billing_group.primary_member
        return Response(
            {
                "valid": True,
                "billingGroupName": invite.billing_group.name,
                "invitedBy": primary.get_full_name() if primary else None,
                "expiresDate": invite.expires_date,
            }
        )


class BillingGroupInvitations(StripeAPIView):
    """
    get: list all non-member invitations for the primary member's billing group.
    """

    def get(self, request):
        profile = request.user.profile
        billing_group = profile.billing_group

        if not billing_group or billing_group.primary_member != profile:
            return Response(
                {
                    "success": False,
                    "message": "Only the primary member can view invitations.",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        from profile.models import BillingGroupInvite

        invitations = BillingGroupInvite.objects.filter(
            billing_group=billing_group,
            accepted=False,
            invalidated=False,
        )
        data = []
        for inv in invitations:
            inv_status = "expired" if inv.is_expired() else "pending"
            data.append(
                {
                    "id": inv.id,
                    "email": inv.email,
                    "status": inv_status,
                    "createdDate": inv.created_date,
                    "expiresDate": inv.expires_date,
                }
            )

        return Response(data)


class BillingGroupInvitationResend(StripeAPIView):
    """
    post: resend a billing group invitation (invalidates old, creates new).
    """

    def post(self, request, invite_id):
        profile = request.user.profile
        billing_group = profile.billing_group

        if not billing_group or billing_group.primary_member != profile:
            return Response(
                {
                    "success": False,
                    "message": "Only the primary member can resend invitations.",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        from profile.models import BillingGroupInvite

        try:
            old_invite = BillingGroupInvite.objects.get(
                pk=invite_id, billing_group=billing_group
            )
        except BillingGroupInvite.DoesNotExist:
            return Response(
                {"success": False, "message": "Invitation not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        email = old_invite.email
        old_invite.invalidate()

        new_invite = BillingGroupInvite.objects.create(
            email=email,
            billing_group=billing_group,
            invited_by=request.user,
        )

        invite_url = f"{config.SITE_URL}/register?billing_group_invite={new_invite.invitation_token}"
        request.user.log_event(f"Resent billing group invitation to {email}.", "admin")

        try:
            send_single_email(
                to_email=email,
                subject=f"You've been invited to join {config.SITE_OWNER}",
                template_vars={
                    "title": f"Join {billing_group.name}",
                    "message": (
                        f"{request.user.profile.get_full_name()} has invited you to join "
                        f"'{billing_group.name}' at {config.SITE_OWNER}. "
                        f"Click below to create your account and join the group."
                    ),
                    "link": invite_url,
                    "btn_text": "Create Account & Join",
                },
                template_name="email_with_button.html",
                user=request.user,
            )
        except Exception:
            pass

        return Response({"success": True, "inviteUrl": invite_url})


class BillingGroupInvitationCancel(StripeAPIView):
    """
    delete: cancel a pending billing group invitation.
    """

    def delete(self, request, invite_id):
        profile = request.user.profile
        billing_group = profile.billing_group

        if not billing_group or billing_group.primary_member != profile:
            return Response(
                {
                    "success": False,
                    "message": "Only the primary member can cancel invitations.",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        from profile.models import BillingGroupInvite

        try:
            invite = BillingGroupInvite.objects.get(
                pk=invite_id, billing_group=billing_group
            )
        except BillingGroupInvite.DoesNotExist:
            return Response(
                {"success": False, "message": "Invitation not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        invite.invalidate()
        request.user.log_event(
            f"Cancelled billing group invitation to {invite.email}.", "admin"
        )

        return Response({"success": True})
