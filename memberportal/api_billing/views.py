from asgiref.sync import sync_to_async
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
from services.emails import send_email_to_admin
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
                {"message": "error.postmarkNotConfigured"},
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


class SubscriptionAddons(APIView):
    """
    get: gets a list of all available subscription add-ons.
    """

    def get(self, request):
        from api_admin_tools.models import SubscriptionAddon

        addons = SubscriptionAddon.objects.filter(visible=True)
        formatted_addons = []

        for addon in addons:
            formatted_addons.append(addon.get_object())

        return Response(formatted_addons)


class PaymentPlanSignup(StripeAPIView):
    """
    post: attempts to sign the member up to a new payment plan.
    """

    def create_subscription(
        self,
        request: HttpRequest,
        new_plan: PaymentPlan,
        addons: list = None,
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

        try:
            # Start with the main plan
            items = [{"price": new_plan.stripe_id}]

            # Add any add-ons
            if addons:
                for addon in addons:
                    items.append(
                        {
                            "price": addon["stripe_price_id"],
                            "quantity": addon.get("quantity", 1),
                        }
                    )

            return stripe.Subscription.create(
                customer=request.user.profile.stripe_customer_id,
                items=items,
            )

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

                return self.create_subscription(attempts)

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

        # Get add-ons from request data
        addons = request.data.get("addons", [])

        new_subscription = self.create_subscription(request, new_plan, addons)

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

        if member_profile.subscription_status != "active":
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
            s = stripe.Subscription.retrieve(
                request.user.profile.stripe_subscription_id,
            )

            if s:
                # Get add-ons from subscription items
                addons = []
                from api_admin_tools.models import SubscriptionAddon

                for item in s.items.data:
                    if item.price.id != request.user.profile.membership_plan.stripe_id:
                        # This is an add-on item
                        try:
                            addon = SubscriptionAddon.objects.get(
                                stripe_price_id=item.price.id
                            )
                            addons.append(
                                {
                                    "id": addon.id,
                                    "name": addon.name,
                                    "quantity": item.quantity,
                                    "cost": item.price.unit_amount,
                                    "cost_display": f"${item.price.unit_amount/100:.2f}",
                                    "stripe_subscription_item_id": item.id,
                                }
                            )
                        except SubscriptionAddon.DoesNotExist:
                            # Unknown add-on, include basic info
                            addons.append(
                                {
                                    "name": "Unknown Add-on",
                                    "quantity": item.quantity,
                                    "cost": item.price.unit_amount,
                                    "cost_display": f"${item.price.unit_amount/100:.2f}",
                                    "stripe_subscription_item_id": item.id,
                                }
                            )

                subscription = {
                    "billingCycleAnchor": s.billing_cycle_anchor,
                    "currentPeriodEnd": s.current_period_end,
                    "cancelAt": s.cancel_at,
                    "cancelAtPeriodEnd": s.cancel_at_period_end,
                    "startDate": s.start_date,
                    "membershipTier": request.user.profile.membership_plan.member_tier.get_object(),
                    "membershipPlan": request.user.profile.membership_plan.get_object(),
                    "addons": addons,
                }
                return Response({"success": True, "subscription": subscription})

            return Response({"success": False})


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
                    request, current_plan
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


class SubscriptionAddonManagement(StripeAPIView):
    """
    post: adds or removes add-ons from an existing subscription.
    """

    def post(self, request):
        from api_admin_tools.models import SubscriptionAddon

        action = request.data.get("action")  # 'add' or 'remove'
        addon_id = request.data.get("addon_id")
        quantity = request.data.get("quantity", 1)

        if not request.user.profile.stripe_subscription_id:
            return Response(
                {"success": False, "message": "No active subscription found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            addon = SubscriptionAddon.objects.get(pk=addon_id, visible=True)
        except SubscriptionAddon.DoesNotExist:
            return Response(
                {"success": False, "message": "Add-on not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            subscription = stripe.Subscription.retrieve(
                request.user.profile.stripe_subscription_id
            )

            if action == "add":
                # Add the add-on to the subscription
                stripe.Subscription.modify(
                    request.user.profile.stripe_subscription_id,
                    items=[{"price": addon.stripe_price_id, "quantity": quantity}],
                    proration_behavior="create_prorations",
                )

                request.user.log_event(
                    f"Added add-on {addon.name} (quantity: {quantity}) to subscription.",
                    "stripe",
                )

            elif action == "remove":
                # Find the subscription item for this add-on and remove it
                for item in subscription.items.data:
                    if item.price.id == addon.stripe_price_id:
                        stripe.SubscriptionItem.delete(item.id)
                        break

                request.user.log_event(
                    f"Removed add-on {addon.name} from subscription.", "stripe"
                )

            return Response({"success": True})

        except stripe.error.StripeError as e:
            capture_exception(e)
            request.user.log_event(
                f"Stripe error while managing add-on: {str(e)}", "stripe"
            )
            return Response(
                {"success": False, "message": "Error updating subscription."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


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


class MemberBillingGroupManagement(APIView):
    """
    get: retrieves the current user's billing group information.
    post: creates a new billing group for the current user.
    delete: deletes the current user's billing group (only if they are the primary member and only member).
    """

    def get(self, request):
        from profile.models import BillingGroup

        user_profile = request.user.profile

        # Check if user is already in a billing group
        if user_profile.billing_group:
            billing_group = user_profile.billing_group
            return Response(
                {
                    "success": True,
                    "billing_group": {
                        "id": billing_group.id,
                        "name": billing_group.name,
                        "primary_member": (
                            {
                                "id": billing_group.primary_member.user.id,
                                "name": billing_group.primary_member.get_full_name(),
                            }
                            if billing_group.primary_member
                            else None
                        ),
                        "members": [
                            {
                                "id": member.user.id,
                                "name": member.get_full_name(),
                                "email": member.user.email,
                            }
                            for member in billing_group.members.all()
                        ],
                        "is_primary": billing_group.primary_member == user_profile,
                    },
                }
            )

        # Check if user has a pending invite
        if user_profile.billing_group_invite:
            return Response(
                {
                    "success": True,
                    "pending_invite": {
                        "id": user_profile.billing_group_invite.id,
                        "name": user_profile.billing_group_invite.name,
                    },
                }
            )

        return Response(
            {
                "success": True,
                "billing_group": None,
                "pending_invite": None,
            }
        )

    def post(self, request):
        from profile.models import BillingGroup

        body = request.data
        user_profile = request.user.profile

        # Check if user is already in a billing group
        if user_profile.billing_group:
            return Response(
                {
                    "success": False,
                    "message": "You are already a member of a billing group.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Validate required fields
        if not body.get("name"):
            return Response(
                {"success": False, "message": "Billing group name is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check if billing group name already exists
        if BillingGroup.objects.filter(name=body["name"]).exists():
            return Response(
                {
                    "success": False,
                    "message": "A billing group with this name already exists.",
                },
                status=status.HTTP_409_CONFLICT,
            )

        # Create the billing group with current user as primary member
        billing_group = BillingGroup.objects.create(
            name=body["name"],
            primary_member=user_profile,
        )

        # Add user to the billing group
        user_profile.billing_group = billing_group
        user_profile.save()

        request.user.log_event(
            f"Created billing group '{billing_group.name}'",
            "billing_group",
        )

        return Response({"success": True, "billing_group_id": billing_group.id})

    def delete(self, request):
        from profile.models import BillingGroup

        user_profile = request.user.profile

        # Check if user is in a billing group and is the primary member
        if (
            not user_profile.billing_group
            or user_profile.billing_group.primary_member != user_profile
        ):
            return Response(
                {
                    "success": False,
                    "message": "You must be the primary member of a billing group to delete it.",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        billing_group = user_profile.billing_group

        # Check if there are other members in the billing group
        if billing_group.members.count() > 1:
            return Response(
                {
                    "success": False,
                    "message": "Cannot delete billing group that has other members. Remove all other members first.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        billing_group_name = billing_group.name

        # Remove user from billing group and delete it
        user_profile.billing_group = None
        user_profile.save()

        billing_group.delete()

        request.user.log_event(
            f"Deleted billing group '{billing_group_name}'",
            "billing_group",
        )

        return Response(
            {"success": True, "message": "Billing group deleted successfully."}
        )


class MemberBillingGroupMemberManagement(APIView):
    """
    post: adds a member to the current user's billing group.
    delete: removes a member from the current user's billing group.
    """

    def post(self, request):
        from profile.models import Profile

        body = request.data
        user_profile = request.user.profile

        # Check if user is in a billing group and is the primary member
        if (
            not user_profile.billing_group
            or user_profile.billing_group.primary_member != user_profile
        ):
            return Response(
                {
                    "success": False,
                    "message": "You must be the primary member of a billing group to add members.",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        member_email = body.get("email")
        if not member_email:
            return Response(
                {"success": False, "message": "Member email is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            member_profile = Profile.objects.get(user__email=member_email)
        except Profile.DoesNotExist:
            return Response(
                {
                    "success": False,
                    "message": "No member found with this email address.",
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        # Check if member is already in a billing group
        if member_profile.billing_group:
            return Response(
                {
                    "success": False,
                    "message": "This member is already part of a billing group.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Add member to billing group
        member_profile.billing_group = user_profile.billing_group
        member_profile.save()

        request.user.log_event(
            f"Added {member_profile.get_full_name()} to billing group '{user_profile.billing_group.name}'",
            "billing_group",
        )

        return Response({"success": True})

    def delete(self, request):
        from profile.models import Profile

        body = request.data
        user_profile = request.user.profile

        # Check if user is in a billing group and is the primary member
        if (
            not user_profile.billing_group
            or user_profile.billing_group.primary_member != user_profile
        ):
            return Response(
                {
                    "success": False,
                    "message": "You must be the primary member of a billing group to remove members.",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        member_id = body.get("member_id")
        if not member_id:
            return Response(
                {"success": False, "message": "Member ID is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            member_profile = Profile.objects.get(
                user_id=member_id, billing_group=user_profile.billing_group
            )
        except Profile.DoesNotExist:
            return Response(
                {
                    "success": False,
                    "message": "Member not found in this billing group.",
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        # Remove member from billing group
        member_profile.billing_group = None
        member_profile.save()

        request.user.log_event(
            f"Removed {member_profile.get_full_name()} from billing group '{user_profile.billing_group.name}'",
            "billing_group",
        )

        return Response({"success": True})


class MemberBillingGroupInviteResponse(APIView):
    """
    post: accepts or declines a billing group invitation.
    """

    def post(self, request):
        from profile.models import Profile

        body = request.data
        user_profile = request.user.profile
        action = body.get("action")  # "accept" or "decline"

        if not action or action not in ["accept", "decline"]:
            return Response(
                {"success": False, "message": "Action must be 'accept' or 'decline'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not user_profile.billing_group_invite:
            return Response(
                {"success": False, "message": "No pending billing group invitation."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        billing_group = user_profile.billing_group_invite

        if action == "accept":
            # Check if user is already in a billing group
            if user_profile.billing_group:
                return Response(
                    {
                        "success": False,
                        "message": "You are already a member of a billing group.",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Add user to billing group
            user_profile.billing_group = billing_group
            user_profile.billing_group_invite = None
            user_profile.save()

            request.user.log_event(
                f"Accepted invitation to billing group '{billing_group.name}'",
                "billing_group",
            )

        else:  # decline
            # Remove invitation
            user_profile.billing_group_invite = None
            user_profile.save()

            request.user.log_event(
                f"Declined invitation to billing group '{billing_group.name}'",
                "billing_group",
            )

        return Response({"success": True})
