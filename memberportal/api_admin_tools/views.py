import json

import stripe
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from constance import config
from constance.backends.database.models import Constance as ConstanceSetting
from django.db.models import F, Sum, Value, CharField, Count, Max
from django.db.models.functions import Concat
from django.db.utils import OperationalError
from rest_framework import permissions
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_api_key.permissions import HasAPIKey
from sentry_sdk import capture_exception
from sentry_sdk import capture_message

from access import models
from access.models import DoorLog, InterlockLog
from memberbucks.models import (
    MemberBucks,
    MemberbucksProductPurchaseLog,
)
from profile.models import User, UserEventLog
from services import sms
from services.emails import send_email_to_admin
from .models import MemberTier, PaymentPlan


class StripeAPIView(APIView):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not config.ENABLE_STRIPE:
            return

        try:
            stripe.api_key = config.STRIPE_SECRET_KEY
        except OperationalError as error:
            capture_exception(error)


class GetMembers(APIView):
    """
    get: This method returns a list of members.
    """

    permission_classes = (permissions.IsAdminUser | HasAPIKey,)

    def get(self, request):
        filtered = []

        members_queryset = User.objects.select_related("profile")

        screenName = request.GET.get("screenName")
        if screenName is not None:
            members_queryset = members_queryset.filter(profile__screen_name=screenName)

        members = members_queryset.all()

        for member in members:
            filtered.append(member.profile.get_basic_profile())

        return Response(filtered)


class MemberState(APIView):
    """
    get: This method gets a member's state.
    post: This method sets a member's state.
    """

    permission_classes = (permissions.IsAdminUser,)

    def get(self, request, member_id, state=None):
        member = User.objects.get(id=member_id)

        return Response({"state": member.profile.state})

    def post(self, request, member_id, state):
        member = User.objects.get(id=member_id)
        if state == "active":
            member.profile.activate(request)
        elif state == "inactive":
            member.profile.deactivate(request)
        else:
            return Response(status=status.HTTP_400_BAD_REQUEST)

        return Response()


class MakeMember(APIView):
    """
    post: This activates a new member.
    """

    permission_classes = (permissions.IsAdminUser,)

    def post(self, request, member_id):
        user = User.objects.get(id=member_id)

        # if they're a new member or account only
        if user.profile.state == "noob" or user.profile.state == "accountonly":
            # give default door access
            for door in models.Doors.objects.filter(all_members=True):
                user.profile.doors.add(door)

            # give default interlock access
            for interlock in models.Interlock.objects.filter(all_members=True):
                user.profile.interlocks.add(interlock)

            # send the welcome email
            email = user.email_welcome()

            # mark them as "active"
            user.profile.activate()

            subject = f"{user.profile.get_full_name()} just got turned into a member!"
            send_email_to_admin(
                subject=subject,
                template_vars={"title": subject, "message": subject},
                user=request.user,
            )

            if email:
                return Response(
                    {
                        "success": True,
                        "message": "adminTools.makeMemberSuccess",
                    }
                )

            # if there was an error sending the welcome email
            elif email is False:
                return Response(
                    {"success": False, "message": "adminTools.makeMemberErrorEmail"}
                )

            # otherwise some other error happened
            else:
                capture_message("Unknown error occurred when running makemember.")
                return Response(
                    {
                        "success": False,
                        "message": "adminTools.makeMemberError",
                    }
                )
        else:
            return Response(
                {
                    "success": False,
                    "message": "adminTools.makeMemberErrorExists",
                }
            )


class Doors(APIView):
    """
    get: returns a list of doors.
    put: updates a specific door.
    delete: deletes a specific door.
    """

    permission_classes = (permissions.IsAdminUser,)

    def get(self, request):
        doors = models.Doors.objects.all()

        def get_door(door):
            logs = models.DoorLog.objects.filter(door_id=door.id)

            # Query to get the statistics
            stats = (
                logs.select_related("user__profile")
                .values("door_id")
                .annotate(
                    screen_name=F("user__profile__screen_name"),
                    full_name=Concat(
                        F("user__profile__first_name"),
                        Value(" "),
                        F("user__profile__last_name"),
                        output_field=CharField(),
                    ),
                    total_swipes=Count("door_id"),
                    last_swipe=Max("date"),
                )
                .order_by("-total_swipes")
            )

            return {
                "id": door.id,
                "name": door.name,
                "description": door.description,
                "ipAddress": door.ip_address,
                "serialNumber": door.serial_number,
                "lastSeen": door.last_seen,
                "offline": door.get_unavailable(),
                "defaultAccess": door.all_members,
                "maintenanceLockout": door.locked_out,
                "playThemeOnSwipe": door.play_theme,
                "postDiscordOnSwipe": door.post_to_discord,
                "postSlackOnSwipe": door.post_to_slack,
                "exemptFromSignin": door.exempt_signin,
                "hiddenToMembers": door.hidden,
                "totalSwipes": logs.count(),
                "userStats": stats,
            }

        return Response(map(get_door, doors))

    def put(self, request, door_id):
        door = models.Doors.objects.get(pk=door_id)
        data = request.data
        all_members_added = False
        all_members_removed = False
        locked_out_changed = False

        if door.all_members != data.get("defaultAccess"):
            if data.get("defaultAccess"):
                all_members_added = True
            else:
                all_members_removed = True

        if door.locked_out != data.get("maintenanceLockout"):
            locked_out_changed = True

        door.name = data.get("name")
        door.description = data.get("description")
        door.ip_address = data.get("ipAddress")
        door.serial_number = data.get("serialNumber")
        door.all_members = data.get("defaultAccess")
        door.locked_out = data.get("maintenanceLockout")
        door.play_theme = data.get("playThemeOnSwipe")
        door.post_to_discord = data.get("postDiscordOnSwipe")
        door.post_to_slack = data.get("postSlackOnSwipe")
        door.exempt_signin = data.get("exemptFromSignin")
        door.hidden = data.get("hiddenToMembers")
        door.save()

        if locked_out_changed:
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                door.serial_number, {"type": "update_device_locked_out"}
            )

        if all_members_added or all_members_removed:
            members = User.objects.all()

            for member in members:
                if all_members_added:
                    member.profile.doors.add(door)
                else:
                    member.profile.doors.remove(door)

                member.profile.save()

        if (
            all_members_added
            or all_members_removed
            or locked_out_changed
            or door.exempt_signin != data.get("exemptFromSignin")
        ):
            # once we're done, sync changes to the device
            door.sync()

            # update the door object on the websocket consumer
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                door.serial_number, {"type": "update_device_object"}
            )

        return Response()

    def delete(self, request, door_id):
        door = models.Doors.objects.get(pk=door_id)
        door.delete()

        return Response()


class Interlocks(APIView):
    """
    get: returns a list of interlocks.
    put: update a specific interlock.
    delete: delete a specific interlock.
    """

    permission_classes = (permissions.IsAdminUser,)

    def get(self, request):
        interlocks = models.Interlock.objects.all()

        def get_interlock(interlock):
            # Calculate total on time
            logs = InterlockLog.objects.filter(interlock_id=interlock.id)
            total_time = logs.aggregate(total_time=Sum("total_time")).get("total_time")
            total_time_seconds = total_time.total_seconds() if total_time else 0

            # Retrieve stats
            stats = (
                logs.select_related("user_started__profile")
                .values("interlock_id")
                .annotate(
                    screen_name=F("user_started__profile__screen_name"),
                    full_name=Concat(
                        F("user_started__profile__first_name"),
                        Value(" "),
                        F("user_started__profile__last_name"),
                        output_field=CharField(),
                    ),
                    total_swipes=Count("total_time"),
                    total_seconds=Sum("total_time"),
                )
                .order_by("-total_seconds", "-total_swipes")
            )

            return {
                "id": interlock.id,
                "authorised": interlock.authorised,
                "name": interlock.name,
                "description": interlock.description,
                "ipAddress": interlock.ip_address,
                "lastSeen": interlock.last_seen,
                "offline": interlock.get_unavailable(),
                "defaultAccess": interlock.all_members,
                "maintenanceLockout": interlock.locked_out,
                "playThemeOnSwipe": interlock.play_theme,
                "exemptFromSignin": interlock.exempt_signin,
                "hiddenToMembers": interlock.hidden,
                "totalTimeSeconds": total_time_seconds,
                "userStats": list(stats),
            }

        return Response(map(get_interlock, interlocks))

    def put(self, request, interlock_id):
        interlock = models.Interlock.objects.get(pk=interlock_id)
        data = request.data
        all_members_added = False
        all_members_removed = False
        locked_out_changed = False

        if interlock.all_members != data.get("defaultAccess"):
            if data.get("defaultAccess"):
                all_members_added = True
            else:
                all_members_removed = True

        if interlock.locked_out != data.get("maintenanceLockout"):
            locked_out_changed = True

        interlock.name = data.get("name")
        interlock.description = data.get("description")
        interlock.ip_address = data.get("ipAddress")
        interlock.all_members = data.get("defaultAccess")
        interlock.locked_out = data.get("maintenanceLockout")
        interlock.play_theme = data.get("playThemeOnSwipe")
        interlock.exempt_signin = data.get("exemptFromSignin")
        interlock.hidden = data.get("hiddenToMembers")
        interlock.save()

        if locked_out_changed:
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                interlock.serial_number, {"type": "update_device_locked_out"}
            )

        if all_members_added or all_members_removed:
            members = User.objects.all()

            for member in members:
                if all_members_added:
                    member.profile.interlocks.add(interlock)
                else:
                    member.profile.interlocks.remove(interlock)

                member.profile.save()

        if (
            all_members_added
            or all_members_removed
            or locked_out_changed
            or interlock.exempt_signin != data.get("exemptFromSignin")
        ):
            # once we're done, sync changes to the device
            interlock.sync()

            # update the door object on the websocket consumer
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                interlock.serial_number, {"type": "update_device_object"}
            )

        return Response()

    def delete(self, request, interlock_id):
        interlock = models.Interlock.objects.get(pk=interlock_id)
        interlock.delete()

        return Response()


class MemberbucksDevices(APIView):
    """
    get: returns a list of memberbucks devices.
    put: update a specific memberbucks device.
    delete: delete a specific memberbucks device.
    """

    permission_classes = (permissions.IsAdminUser,)

    def get(self, request):
        devices = models.MemberbucksDevice.objects.all()

        def get_device(device):
            # Calculate total transaction volume
            purchases = MemberbucksProductPurchaseLog.objects.filter(
                memberbucks_device_id=device.id, success=True
            )
            total_count = purchases.count()
            total_volume = (
                purchases.aggregate(total_volume=Sum("price")).get("total_volume") or 0
            ) / 100

            # Retrieve stats
            stats = (
                purchases.select_related("user__profile")
                .values("memberbucks_device_id")
                .annotate(
                    screen_name=F("user__profile__screen_name"),
                    full_name=Concat(
                        F("user__profile__first_name"),
                        Value(" "),
                        F("user__profile__last_name"),
                        output_field=CharField(),
                    ),
                    total_purchases=Count("price"),
                    total_volume=(Sum("price") or 0) / 100,
                )
                .order_by("-total_purchases", "-total_volume")
            )

            return {
                "id": device.id,
                "authorised": device.authorised,
                "name": device.name,
                "description": device.description,
                "ipAddress": device.ip_address,
                "lastSeen": device.last_seen,
                "offline": device.get_unavailable(),
                "defaultAccess": device.all_members,
                "maintenanceLockout": device.locked_out,
                "playThemeOnSwipe": device.play_theme,
                "exemptFromSignin": device.exempt_signin,
                "hiddenToMembers": device.hidden,
                "totalPurchases": total_count,
                "totalVolume": total_volume,
                "userStats": list(stats),
            }

        return Response(map(get_device, devices))

    def put(self, request, device_id):
        device = models.MemberbucksDevice.objects.get(pk=device_id)

        data = request.data

        device.name = data.get("name")
        device.description = data.get("description")
        device.ip_address = data.get("ipAddress")

        device.all_members = data.get("defaultAccess")
        device.locked_out = data.get("maintenanceLockout")
        device.play_theme = data.get("playThemeOnSwipe")
        device.exempt_signin = data.get("exemptFromSignin")
        device.hidden = data.get("hiddenToMembers")

        device.save()

        return Response()

    def delete(self, request, device_id):
        device = models.MemberbucksDevice.objects.get(pk=device_id)
        device.delete()

        return Response()


class MemberAccess(APIView):
    """
    get: This method gets a member's access permissions.
    """

    permission_classes = (permissions.IsAdminUser | HasAPIKey,)

    def get(self, request, member_id):
        member = User.objects.get(id=member_id)

        return Response(member.profile.get_access_permissions(ignore_user_state=True))


class MemberWelcomeEmail(APIView):
    """
    post: This method sends a welcome email to the specified member.
    """

    permission_classes = (permissions.IsAdminUser,)

    def post(self, request, member_id):
        member = User.objects.get(id=member_id)
        member.email_welcome()

        return Response()


class MemberSendSms(APIView):
    """
    post: This method sends a custom sms alert to the specified member.
    """

    permission_classes = (permissions.IsAdminUser,)

    def post(self, request, member_id):
        member = User.objects.get(id=member_id)
        sms_body = request.data["smsBody"]

        if not config.SMS_ENABLE:
            return Response(
                {"success": False, "message": "SMS functionality not enabled."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        if not member.profile.phone:
            return Response(
                {"success": False, "message": "Member does not have a phone number."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # check if the sms body exists, is at least 1 character, and isn't more than 320 characters
        if not sms_body or len(sms_body) < 1 or len(sms_body) > 320:
            return Response(
                {"success": False, "message": "SMS body is invalid."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        sms_message = sms.SMS()
        sms_message.send_custom_notification(
            to_number=member.profile.phone,
            message=sms_body,
            portal_user_sender=request.user,
            portal_user_recipient=member,
        )

        return Response()


class MemberProfile(APIView):
    """
    put: This method updates a member's profile.
    """

    permission_classes = (permissions.IsAdminUser,)

    def put(self, request, member_id):
        if not member_id:
            return Response(status=status.HTTP_400_BAD_REQUEST)

        body = json.loads(request.body)
        member = User.objects.get(id=member_id)
        rfid_changed = False

        if member.profile.rfid != body.get("rfidCard"):
            rfid_changed = True

        member.email = body.get("email")
        member.profile.first_name = body.get("firstName")
        member.profile.last_name = body.get("lastName")
        member.profile.rfid = body.get("rfidCard")
        member.profile.phone = body.get("phone")
        member.profile.screen_name = body.get("screenName")
        member.profile.vehicle_registration_plate = body.get("vehicleRegistrationPlate")
        member.profile.exclude_from_email_export = body.get("excludeFromEmailExport")

        member.save()
        member.profile.save()

        if rfid_changed:
            for door in member.profile.doors.all():
                door.sync()

        return Response()


class ManageMembershipTier(StripeAPIView):
    """
    get: gets a membership tier.
    post: creates a new membership tier.
    put: updates a membership tier.
    delete: deletes a membership tier.
    """

    permission_classes = (permissions.IsAdminUser,)

    def get_tier(self, tier: MemberTier):
        return {
            "id": tier.id,
            "name": tier.name,
            "description": tier.description,
            "visible": tier.visible,
            "featured": tier.featured,
            "stripeId": tier.stripe_id,
        }

    def get(self, request, tier_id=None):
        if tier_id:
            try:
                tier = MemberTier.objects.get(pk=tier_id)
                return Response(self.get_tier(tier))

            except MemberTier.DoesNotExist as e:
                return Response(status=status.HTTP_404_NOT_FOUND)

        else:
            formatted_tiers = []

            for tier in MemberTier.objects.all():
                formatted_tiers.append(self.get_tier(tier))

            return Response(formatted_tiers)

    def post(self, request):
        body = request.data

        try:
            product = stripe.Product.create(
                name=body["name"], description=body["description"]
            )
            tier = MemberTier.objects.create(
                name=body["name"],
                description=body["description"],
                visible=body["visible"],
                featured=body["featured"],
                stripe_id=product.id,
            )

            return Response(self.get_tier(tier))

        except stripe.error.AuthenticationError:
            return Response(
                {"success": False, "message": "error.stripeNotConfigured"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def put(self, request, tier_id):
        body = request.data

        tier = MemberTier.objects.get(pk=tier_id)

        tier.name = body["name"]
        tier.description = body["description"]
        tier.visible = body["visible"]
        tier.featured = body["featured"]
        tier.save()

        return Response(self.get_tier(tier))

    def delete(self, request, tier_id):
        tier = MemberTier.objects.get(pk=tier_id)
        tier.delete()

        return Response()


class ManageMembershipTierPlan(StripeAPIView):
    """
    get: gets an individual or a list of payment plans.
    post: creates a new payment plan.

    """

    permission_classes = (permissions.IsAdminUser,)

    def get_plan(self, plan: PaymentPlan):
        return {
            "id": plan.id,
            "name": plan.name,
            "stripeId": plan.stripe_id,
            "memberTier": plan.member_tier.id,
            "visible": plan.visible,
            "currency": plan.currency,
            "cost": plan.cost / 100,  # convert to dollars
            "intervalCount": plan.interval_count,
            "interval": plan.interval,
        }

    def get(self, request, plan_id=None, tier_id=None):
        if plan_id:
            try:
                plan = PaymentPlan.objects.get(pk=plan_id)
                return Response(self.get_plan(plan))

            except PaymentPlan.DoesNotExist as e:
                return Response(status=status.HTTP_404_NOT_FOUND)

        if tier_id:
            try:
                formatted_plans = []

                for plan in PaymentPlan.objects.filter(member_tier=tier_id):
                    formatted_plans.append(self.get_plan(plan))

                return Response(formatted_plans)

            except PaymentPlan.DoesNotExist as e:
                return Response(status=status.HTTP_404_NOT_FOUND)

        else:
            formatted_plans = []

            for plan in PaymentPlan.objects.all():
                formatted_plans.append(self.get_plan(plan))

            return Response(formatted_plans)

    def post(self, request, tier_id=None):
        if tier_id is not None:
            return Response(status=status.HTTP_400_BAD_REQUEST)

        body = request.data

        member_tier = MemberTier.objects.get(pk=body["memberTier"])

        stripe_plan = stripe.Price.create(
            unit_amount=round(body["cost"]),
            currency=str(body["currency"]).lower(),
            recurring={
                "interval": body["interval"],
                "interval_count": body["intervalCount"],
            },
            product=member_tier.stripe_id,
        )

        plan = PaymentPlan.objects.create(
            name=body["name"],
            stripe_id=stripe_plan.id,
            member_tier_id=body["memberTier"],
            visible=body["visible"],
            currency=str(body["currency"]).lower(),
            cost=round(body["cost"]),
            interval_count=body["intervalCount"],
            interval=body["interval"],
        )

        return Response(self.get_plan(plan))

    def put(self, request, plan_id):
        body = request.data

        plan = PaymentPlan.objects.get(pk=plan_id)

        plan.name = body["name"]
        plan.visible = body["visible"]
        plan.cost = body["cost"]
        plan.save()

        return Response(self.get_plan(plan))

    def delete(self, request, plan_id):
        plan = PaymentPlan.objects.get(pk=plan_id)
        plan.delete()

        return Response()


class MemberBillingInfo(StripeAPIView):
    """
    get: This method gets a member's billing info.
    """

    permission_classes = (permissions.IsAdminUser | HasAPIKey,)

    def get(self, request, member_id):
        member = User.objects.get(id=member_id)
        current_plan = member.profile.membership_plan

        billing_info = {}

        if current_plan:
            s = None

            # if we have a subscription id, fetch the details
            if member.profile.stripe_subscription_id:
                s = stripe.Subscription.retrieve(
                    member.profile.stripe_subscription_id,
                )

            # if we got subscription details
            if s:
                billing_info["subscription"] = {
                    "status": member.profile.subscription_status,
                    "billingCycleAnchor": s.billing_cycle_anchor,
                    "currentPeriodEnd": s.current_period_end,
                    "cancelAt": s.cancel_at,
                    "cancelAtPeriodEnd": s.cancel_at_period_end,
                    "startDate": s.start_date,
                    "membershipTier": member.profile.membership_plan.member_tier.get_object(),
                    "membershipPlan": member.profile.membership_plan.get_object(),
                }
            else:
                billing_info["subscription"] = None

        # get the most recent memberbucks transactions and order them by date
        recent_transactions = MemberBucks.objects.filter(user=member).order_by("date")[
            ::-1
        ][:100]

        def get_transaction(transaction):
            return transaction.get_transaction_display()

        billing_info["memberbucks"] = {
            "balance": member.profile.memberbucks_balance,
            "stripe_card_last_digits": member.profile.stripe_card_last_digits,
            "stripe_card_expiry": member.profile.stripe_card_expiry,
            "transactions": map(get_transaction, recent_transactions),
            "lastPurchase": member.profile.last_memberbucks_purchase,
        }

        return Response(billing_info)


class MemberLogs(APIView):
    """
    get: This method gets a member's logs.
    """

    permission_classes = (permissions.IsAdminUser | HasAPIKey,)

    def get(self, request, member_id):
        user = User.objects.get(id=member_id)

        user_event_logs = []
        door_logs = []
        interlock_logs = []

        for user_event_log in UserEventLog.objects.order_by("-date").filter(user=user)[
            :1000
        ]:
            user_event_logs.append(
                {
                    "date": user_event_log.date,
                    "description": user_event_log.description,
                    "logtype": user_event_log.get_logtype_display(),
                }
            )

        for door_log in DoorLog.objects.order_by("-date").filter(user=user)[:500]:
            door_logs.append(
                {
                    "date": door_log.date,
                    "door": door_log.door.name,
                    "success": door_log.success,
                }
            )

        for interlock_log in InterlockLog.objects.filter(user_started=user)[:1000]:
            status = None

            if not interlock_log.success:
                status = -1
            else:
                status = 1 if interlock_log.date_ended else 0

            interlock_logs.append(
                {
                    "interlockName": interlock_log.interlock.name,
                    "dateStarted": interlock_log.date_started,
                    "totalTime": interlock_log.total_time,
                    "totalCost": (interlock_log.total_cost or 0) / 100,
                    "status": status,
                    "userEnded": (
                        interlock_log.user_ended.get_full_name()
                        if interlock_log.user_ended
                        else None
                    ),
                }
            )

        logs = {
            "userEventLogs": user_event_logs,
            "doorLogs": door_logs,
            "interlockLogs": interlock_logs,
        }

        return Response(logs)


class ManageSettings(APIView):
    """
    get: This method gets a constance setting value or values.
    put: This method updates a constance setting value.
    """

    permission_classes = (permissions.IsAdminUser,)

    def get_setting(self, setting):
        return {
            "key": setting.key,
            "value": setting.value,
        }

    def get(self, request, setting_key=None):
        if setting_key:
            try:
                setting = ConstanceSetting.objects.get(key=setting_key)
                return Response({"success": True, **self.get_setting(setting)})

            except ConstanceSetting.DoesNotExist as e:
                return Response(
                    {"success": False, "message": "Setting not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )

        else:
            settings = []

            for setting in ConstanceSetting.objects.all():
                settings.append(self.get_setting(setting))

            return Response(settings)

    def put(self, request, setting_key=None):
        if not setting_key:
            return Response(status=status.HTTP_400_BAD_REQUEST)

        body = request.data

        try:
            setting = ConstanceSetting.objects.get(key=setting_key)
            setting.value = body["value"]
            setting.save()

            return Response({"success": True, **self.get_setting(setting)})

        except ConstanceSetting.DoesNotExist:
            # Create the setting if it doesn't exist
            setting = ConstanceSetting.objects.create(
                key=setting_key, value=body["value"]
            )

            return Response({"success": True, **self.get_setting(setting)})


class BillingGroupManagement(APIView):
    """
    get: retrieves a list of all billing groups.
    post: creates a new billing group.
    """

    permission_classes = (permissions.IsAdminUser,)

    def get(self, request):
        from profile.models import BillingGroup

        billing_groups = BillingGroup.objects.all()

        def get_billing_group(billing_group):
            return {
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
                "member_count": billing_group.members.count(),
                "invite_count": billing_group.members_invites.count(),
            }

        return Response(list(map(get_billing_group, billing_groups)))

    def post(self, request):
        from profile.models import BillingGroup, Profile

        body = request.data

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

        # Create the billing group
        billing_group = BillingGroup.objects.create(
            name=body["name"],
            primary_member_id=body.get("primary_member_id"),
        )

        # If a primary member was specified, add them to the billing group
        if body.get("primary_member_id"):
            try:
                primary_member = Profile.objects.get(user_id=body["primary_member_id"])
                primary_member.billing_group = billing_group
                primary_member.save()
            except Profile.DoesNotExist:
                pass

        request.user.log_event(
            f"Created billing group '{billing_group.name}'",
            "admin",
        )

        return Response({"success": True, "billing_group_id": billing_group.id})


class BillingGroupDetail(APIView):
    """
    get: retrieves details of a specific billing group.
    put: updates a billing group.
    delete: deletes a billing group.
    """

    permission_classes = (permissions.IsAdminUser,)

    def get(self, request, billing_group_id):
        from profile.models import BillingGroup

        try:
            billing_group = BillingGroup.objects.get(id=billing_group_id)
        except BillingGroup.DoesNotExist:
            return Response(
                {"success": False, "message": "Billing group not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        def get_member(member):
            return {
                "id": member.user.id,
                "name": member.get_full_name(),
                "email": member.user.email,
                "state": member.state,
            }

        def get_invite(invite):
            return {
                "id": invite.user.id,
                "name": invite.get_full_name(),
                "email": invite.user.email,
                "state": invite.state,
            }

        return Response(
            {
                "id": billing_group.id,
                "name": billing_group.name,
                "primary_member": (
                    get_member(billing_group.primary_member)
                    if billing_group.primary_member
                    else None
                ),
                "members": list(map(get_member, billing_group.members.all())),
                "invites": list(map(get_invite, billing_group.members_invites.all())),
            }
        )

    def put(self, request, billing_group_id):
        from profile.models import BillingGroup, Profile

        try:
            billing_group = BillingGroup.objects.get(id=billing_group_id)
        except BillingGroup.DoesNotExist:
            return Response(
                {"success": False, "message": "Billing group not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        body = request.data

        # Update name if provided
        if body.get("name") and body["name"] != billing_group.name:
            # Check if new name already exists
            if (
                BillingGroup.objects.filter(name=body["name"])
                .exclude(id=billing_group_id)
                .exists()
            ):
                return Response(
                    {
                        "success": False,
                        "message": "A billing group with this name already exists.",
                    },
                    status=status.HTTP_409_CONFLICT,
                )
            billing_group.name = body["name"]

        # Update primary member if provided
        if "primary_member_id" in body:
            if body["primary_member_id"]:
                try:
                    primary_member = Profile.objects.get(
                        user_id=body["primary_member_id"]
                    )
                    billing_group.primary_member = primary_member
                except Profile.DoesNotExist:
                    return Response(
                        {"success": False, "message": "Primary member not found."},
                        status=status.HTTP_404_NOT_FOUND,
                    )
            else:
                billing_group.primary_member = None

        billing_group.save()

        request.user.log_event(
            f"Updated billing group '{billing_group.name}'",
            "admin",
        )

        return Response({"success": True})

    def delete(self, request, billing_group_id):
        from profile.models import BillingGroup

        try:
            billing_group = BillingGroup.objects.get(id=billing_group_id)
        except BillingGroup.DoesNotExist:
            return Response(
                {"success": False, "message": "Billing group not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        billing_group_name = billing_group.name

        # Remove Stripe subscription items for all members before removing them
        for member in billing_group.members.all():
            self._remove_stripe_subscription_item_for_member(
                member, billing_group, request.user
            )
            member.billing_group = None
            member.save()

        # Remove all invites from the billing group and their locked pricing
        for invite in billing_group.members_invites.all():
            self._remove_addon_pricing_for_invited_member(
                invite, billing_group, request.user
            )
            invite.billing_group_invite = None
            invite.save()

        billing_group.delete()

        request.user.log_event(
            f"Deleted billing group '{billing_group_name}' with proper Stripe cleanup",
            "admin",
        )

        return Response({"success": True})

    def _remove_stripe_subscription_item_for_member(
        self, member_profile, billing_group, requesting_user
    ):
        """
        Remove Stripe subscription items for a member leaving a billing group.
        """
        try:
            from profile.models import BillingGroupMemberAddon

            # Get all locked addon records for this member
            locked_addons = BillingGroupMemberAddon.objects.filter(
                billing_group=billing_group, member=member_profile
            )

            for locked_addon in locked_addons:
                # Check if stripe_subscription_item_id field exists and has a value
                stripe_item_id = getattr(
                    locked_addon, "stripe_subscription_item_id", None
                )
                if stripe_item_id:
                    try:
                        # Remove the subscription item from Stripe
                        stripe.SubscriptionItem.delete(
                            stripe_item_id,
                            proration_behavior="create_prorations",
                        )

                        requesting_user.log_event(
                            f"Removed Stripe subscription item for {member_profile.get_full_name()} - {locked_addon.addon.name}",
                            "admin",
                        )
                    except stripe.error.InvalidRequestError as e:
                        # Subscription item might already be deleted
                        requesting_user.log_event(
                            f"Stripe subscription item for {member_profile.get_full_name()} was already deleted or not found",
                            "admin",
                        )
                else:
                    requesting_user.log_event(
                        f"No Stripe subscription item ID found for {member_profile.get_full_name()} - {locked_addon.addon.name} (may need database migration)",
                        "admin",
                    )

                # Clean up the locked addon record
                locked_addon.delete()

        except Exception as e:
            requesting_user.log_event(
                f"Error removing Stripe subscription item for {member_profile.get_full_name()}: {str(e)}",
                "admin",
            )
            capture_exception(e)

    def _remove_addon_pricing_for_invited_member(
        self, member_profile, billing_group, requesting_user
    ):
        """
        Remove locked addon pricing for an invited member who hasn't joined yet.
        """
        try:
            from profile.models import BillingGroupMemberAddon

            # Get all locked addon records for this invited member
            locked_addons = BillingGroupMemberAddon.objects.filter(
                billing_group=billing_group, member=member_profile
            )

            addon_names = []
            count = 0
            for locked_addon in locked_addons:
                addon_names.append(locked_addon.addon.name)
                locked_addon.delete()
                count += 1

            if count > 0:
                requesting_user.log_event(
                    f"Removed {count} locked addon pricing records for invited member {member_profile.get_full_name()}: {', '.join(addon_names)}",
                    "admin",
                )

        except Exception as e:
            requesting_user.log_event(
                f"Error removing addon pricing for invited member {member_profile.get_full_name()}: {str(e)}",
                "admin",
            )


class BillingGroupMemberManagement(APIView):
    """
    post: adds or removes members from a billing group.
    """

    permission_classes = (permissions.IsAdminUser,)

    def post(self, request, billing_group_id):
        from profile.models import BillingGroup, Profile

        try:
            billing_group = BillingGroup.objects.get(id=billing_group_id)
        except BillingGroup.DoesNotExist:
            return Response(
                {"success": False, "message": "Billing group not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        body = request.data
        action = body.get("action")  # "add" or "remove"
        member_id = body.get("member_id")

        if not action or not member_id:
            return Response(
                {"success": False, "message": "Action and member_id are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            member = Profile.objects.get(user_id=member_id)
        except Profile.DoesNotExist:
            return Response(
                {"success": False, "message": "Member not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if action == "add":
            # First, handle any existing individual subscription
            subscription_cancelled = True
            if member.stripe_subscription_id:
                subscription_cancelled = (
                    self._cancel_individual_subscription_with_proration(
                        member, request.user
                    )
                )

                if not subscription_cancelled:
                    return Response(
                        {
                            "success": False,
                            "message": "Failed to cancel member's existing subscription. Please try again or contact support.",
                        },
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    )

            # Remove from any existing billing group first
            if member.billing_group:
                # Remove Stripe subscription items for existing billing group membership
                self._remove_stripe_subscription_item_for_member(
                    member, member.billing_group, request.user
                )
                member.billing_group = None
                member.save()

            # Add to this billing group
            member.billing_group = billing_group
            member.save()

            # Lock in current addon pricing for this new member
            self._lock_addon_pricing_for_member(member, billing_group, request.user)

            # Create Stripe subscription item for this member if primary member has active subscription
            if (
                billing_group.primary_member
                and billing_group.primary_member.stripe_subscription_id
            ):
                self._create_stripe_subscription_item_for_member(
                    member, billing_group, request.user
                )

            action_description = (
                "with subscription cancellation and proration"
                if member.stripe_subscription_id
                else ""
            )
            request.user.log_event(
                f"Added {member.get_full_name()} to billing group '{billing_group.name}' {action_description}",
                "admin",
            )

        elif action == "remove":
            if member.billing_group == billing_group:
                # Remove Stripe subscription items before removing from billing group
                self._remove_stripe_subscription_item_for_member(
                    member, billing_group, request.user
                )

                # Create new individual subscription for the member when they leave the billing group
                self._create_individual_subscription_for_removed_member(
                    member, request.user
                )

                member.billing_group = None
                member.save()

                request.user.log_event(
                    f"Removed {member.get_full_name()} from billing group '{billing_group.name}' with Stripe cleanup and new individual subscription",
                    "admin",
                )
            else:
                return Response(
                    {
                        "success": False,
                        "message": "Member is not in this billing group.",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        else:
            return Response(
                {"success": False, "message": "Invalid action. Use 'add' or 'remove'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response({"success": True})

    def _remove_stripe_subscription_item_for_member(
        self, member_profile, billing_group, requesting_user
    ):
        """
        Remove Stripe subscription items for a member leaving a billing group.
        """
        try:
            from profile.models import BillingGroupMemberAddon

            # Get all locked addon records for this member
            locked_addons = BillingGroupMemberAddon.objects.filter(
                billing_group=billing_group, member=member_profile
            )

            for locked_addon in locked_addons:
                # Check if stripe_subscription_item_id field exists and has a value
                stripe_item_id = getattr(
                    locked_addon, "stripe_subscription_item_id", None
                )
                if stripe_item_id:
                    try:
                        # Remove the subscription item from Stripe
                        stripe.SubscriptionItem.delete(
                            stripe_item_id,
                            proration_behavior="create_prorations",
                        )

                        requesting_user.log_event(
                            f"Removed Stripe subscription item for {member_profile.get_full_name()} - {locked_addon.addon.name}",
                            "admin",
                        )
                    except stripe.error.InvalidRequestError as e:
                        # Subscription item might already be deleted
                        requesting_user.log_event(
                            f"Stripe subscription item for {member_profile.get_full_name()} was already deleted or not found",
                            "admin",
                        )
                else:
                    requesting_user.log_event(
                        f"No Stripe subscription item ID found for {member_profile.get_full_name()} - {locked_addon.addon.name} (may need database migration)",
                        "admin",
                    )

                # Clean up the locked addon record
                locked_addon.delete()

        except Exception as e:
            requesting_user.log_event(
                f"Error removing Stripe subscription item for {member_profile.get_full_name()}: {str(e)}",
                "admin",
            )
            capture_exception(e)

    def _cancel_individual_subscription_with_proration(
        self, member_profile, requesting_user
    ):
        """
        Cancel a member's individual subscription with proration when they join a billing group.
        This ensures they get credit for the remaining time on their current subscription.
        """
        try:
            if not member_profile.stripe_subscription_id:
                requesting_user.log_event(
                    f"Cannot cancel subscription for {member_profile.get_full_name()} - no active subscription found",
                    "admin",
                )
                return False

            # First, retrieve the subscription to verify it exists and get its status
            try:
                existing_subscription = stripe.Subscription.retrieve(
                    member_profile.stripe_subscription_id
                )

                # If subscription is already cancelled, just update the profile
                if existing_subscription.status in ["canceled", "cancelled"]:
                    requesting_user.log_event(
                        f"Subscription for {member_profile.get_full_name()} was already cancelled in Stripe",
                        "admin",
                    )
                    # Update profile to reflect the cancellation
                    member_profile.stripe_subscription_id = None
                    member_profile.membership_plan = None
                    # Don't set to inactive here since they're joining a billing group
                    member_profile.save()
                    return True

            except stripe.error.InvalidRequestError:
                # Subscription doesn't exist in Stripe, just update the profile
                requesting_user.log_event(
                    f"Subscription {member_profile.stripe_subscription_id} for {member_profile.get_full_name()} not found in Stripe - updating profile only",
                    "admin",
                )
                member_profile.stripe_subscription_id = None
                member_profile.membership_plan = None
                member_profile.save()
                return True

            # Cancel the subscription immediately with proration
            cancelled_subscription = stripe.Subscription.modify(
                member_profile.stripe_subscription_id,
                cancel_at_period_end=False,
                proration_behavior="create_prorations",
            )

            # Update the profile to reflect the cancellation
            member_profile.stripe_subscription_id = None
            member_profile.membership_plan = None
            member_profile.save()

            requesting_user.log_event(
                f"Successfully cancelled individual subscription for {member_profile.get_full_name()} with proration when joining billing group",
                "admin",
            )

            return True

        except stripe.error.StripeError as e:
            requesting_user.log_event(
                f"Stripe error cancelling subscription for {member_profile.get_full_name()}: {str(e)}",
                "admin",
            )
            capture_exception(e)
            return False
        except Exception as e:
            requesting_user.log_event(
                f"Error cancelling subscription for {member_profile.get_full_name()}: {str(e)}",
                "admin",
            )
            capture_exception(e)
            return False

    def _lock_addon_pricing_for_member(
        self, member_profile, billing_group, requesting_user
    ):
        """
        Lock in the current addon pricing for a member joining a billing group.
        This captures the current additional member addon pricing.
        """
        from profile.models import BillingGroupMemberAddon
        from api_admin_tools.models import SubscriptionAddon

        try:
            # Get the current additional member addon setting
            current_addon_id = getattr(config, "CURRENT_ADDITIONAL_MEMBER_ADDON", None)

            # Handle empty string or None values
            if current_addon_id and str(current_addon_id).strip():
                try:
                    current_addon = SubscriptionAddon.objects.get(
                        id=int(current_addon_id),
                        addon_type="additional_member",
                        visible=True,
                    )

                    # Create the locked pricing record
                    BillingGroupMemberAddon.objects.get_or_create(
                        billing_group=billing_group,
                        member=member_profile,
                        addon=current_addon,
                        defaults={
                            "locked_cost": current_addon.cost,
                            "locked_currency": current_addon.currency,
                            "locked_interval": current_addon.interval,
                            "locked_interval_count": current_addon.interval_count,
                        },
                    )

                    requesting_user.log_event(
                        f"Locked addon pricing for {member_profile.get_full_name()} in billing group '{billing_group.name}' - {current_addon.name} at ${current_addon.cost/100:.2f}/{current_addon.interval}",
                        "admin",
                    )

                except SubscriptionAddon.DoesNotExist:
                    requesting_user.log_event(
                        f"Warning: Could not lock addon pricing for {member_profile.get_full_name()} - addon with ID {current_addon_id} not found",
                        "admin",
                    )
            else:
                requesting_user.log_event(
                    f"Warning: No current additional member addon configured - pricing not locked for {member_profile.get_full_name()}",
                    "admin",
                )

        except Exception as e:
            requesting_user.log_event(
                f"Error locking addon pricing for {member_profile.get_full_name()}: {str(e)}",
                "admin",
            )

    def _create_stripe_subscription_item_for_member(
        self, member_profile, billing_group, requesting_user
    ):
        """
        Create a Stripe subscription item for an additional member in a billing group.
        This adds the additional member charge to the primary member's subscription.
        """
        try:
            from profile.models import BillingGroupMemberAddon

            # Get the locked addon record for this member
            try:
                locked_addon = BillingGroupMemberAddon.objects.get(
                    billing_group=billing_group, member=member_profile
                )
            except BillingGroupMemberAddon.DoesNotExist:
                requesting_user.log_event(
                    f"No locked addon pricing found for {member_profile.get_full_name()} - cannot create Stripe subscription item",
                    "admin",
                )
                return False

            primary_member = billing_group.primary_member
            if not primary_member.stripe_subscription_id:
                requesting_user.log_event(
                    f"Primary member {primary_member.get_full_name()} has no active subscription - cannot add subscription item for {member_profile.get_full_name()}",
                    "admin",
                )
                return False

            # Create a Stripe price for this locked pricing if not already created
            stripe_price_id = getattr(locked_addon, "stripe_price_id", None)
            if not stripe_price_id:
                try:
                    price = stripe.Price.create(
                        unit_amount=locked_addon.locked_cost,
                        currency=locked_addon.locked_currency,
                        recurring={
                            "interval": locked_addon.locked_interval,
                            "interval_count": locked_addon.locked_interval_count,
                        },
                        product_data={
                            "name": f"Additional Member - {member_profile.get_full_name()}",
                            "metadata": {
                                "billing_group_id": str(billing_group.id),
                                "member_id": str(member_profile.user.id),
                            },
                        },
                    )
                    stripe_price_id = price.id

                    # Update the locked addon record with the Stripe price ID
                    if hasattr(locked_addon, "stripe_price_id"):
                        locked_addon.stripe_price_id = stripe_price_id
                        locked_addon.save()

                except stripe.error.StripeError as e:
                    requesting_user.log_event(
                        f"Failed to create Stripe price for {member_profile.get_full_name()}: {str(e)}",
                        "admin",
                    )
                    return False

            # Create the subscription item
            try:
                subscription_item = stripe.SubscriptionItem.create(
                    subscription=primary_member.stripe_subscription_id,
                    price=stripe_price_id,
                    proration_behavior="create_prorations",
                )

                # Store the Stripe subscription item ID in the locked addon record
                if hasattr(locked_addon, "stripe_subscription_item_id"):
                    locked_addon.stripe_subscription_item_id = subscription_item.id
                    locked_addon.save()

                requesting_user.log_event(
                    f"Created Stripe subscription item for {member_profile.get_full_name()} in billing group '{billing_group.name}'",
                    "admin",
                )

                return True

            except stripe.error.StripeError as e:
                requesting_user.log_event(
                    f"Failed to create Stripe subscription item for {member_profile.get_full_name()}: {str(e)}",
                    "admin",
                )
                return False

        except Exception as e:
            requesting_user.log_event(
                f"Error creating Stripe subscription item for {member_profile.get_full_name()}: {str(e)}",
                "admin",
            )
            capture_exception(e)
            return False

    def _create_individual_subscription_for_removed_member(
        self, member_profile, requesting_user
    ):
        """
        Create a new individual subscription for a member who was removed from a billing group.
        This ensures they maintain their membership after leaving the billing group.
        """
        try:
            from .models import PaymentPlan

            # Get the default individual membership plan
            default_plan_id = getattr(config, "DEFAULT_INDIVIDUAL_PLAN", None)
            if not default_plan_id or str(default_plan_id).strip() == "":
                requesting_user.log_event(
                    f"Cannot create individual subscription for {member_profile.get_full_name()} - no default individual plan configured",
                    "admin",
                )
                return False

            try:
                payment_plan = PaymentPlan.objects.get(
                    id=int(default_plan_id), enabled=True
                )
            except PaymentPlan.DoesNotExist:
                requesting_user.log_event(
                    f"Cannot create individual subscription for {member_profile.get_full_name()} - default plan {default_plan_id} not found or disabled",
                    "admin",
                )
                return False

            # Create a new Stripe subscription for the member
            try:
                subscription = stripe.Subscription.create(
                    customer=member_profile.stripe_customer_id,
                    items=[
                        {
                            "price": payment_plan.stripe_price_id,
                        }
                    ],
                    proration_behavior="create_prorations",
                    metadata={
                        "user_id": str(member_profile.user.id),
                        "plan_id": str(payment_plan.id),
                        "plan_name": payment_plan.name,
                        "removed_from_billing_group": "true",
                    },
                )

                # Update the member's profile
                member_profile.stripe_subscription_id = subscription.id
                member_profile.membership_plan = payment_plan
                member_profile.save()

                requesting_user.log_event(
                    f"Created new individual subscription for {member_profile.get_full_name()} after removing from billing group - Plan: {payment_plan.name}",
                    "admin",
                )

                return True

            except stripe.error.StripeError as e:
                requesting_user.log_event(
                    f"Failed to create Stripe subscription for {member_profile.get_full_name()}: {str(e)}",
                    "admin",
                )
                return False

        except Exception as e:
            requesting_user.log_event(
                f"Error creating individual subscription for {member_profile.get_full_name()}: {str(e)}",
                "admin",
            )
            capture_exception(e)
            return False


class BillingGroupInviteManagement(APIView):
    """
    post: sends or cancels billing group invites.
    """

    permission_classes = (permissions.IsAdminUser,)

    def _lock_addon_pricing_for_invited_member(
        self, member_profile, billing_group, requesting_user
    ):
        """
        Lock in the current addon pricing for an invited billing group member.
        This captures the current additional member addon pricing when someone
        is invited to a billing group.
        """
        from profile.models import BillingGroupMemberAddon
        from api_admin_tools.models import SubscriptionAddon

        try:
            # Get the current additional member addon setting
            current_addon_id = getattr(config, "CURRENT_ADDITIONAL_MEMBER_ADDON", None)

            # Handle empty string or None values
            if current_addon_id and str(current_addon_id).strip():
                try:
                    current_addon = SubscriptionAddon.objects.get(
                        id=int(current_addon_id),
                        addon_type="additional_member",
                        visible=True,
                    )

                    # Create the locked pricing record
                    BillingGroupMemberAddon.objects.get_or_create(
                        billing_group=billing_group,
                        member=member_profile,
                        addon=current_addon,
                        defaults={
                            "locked_cost": current_addon.cost,
                            "locked_currency": current_addon.currency,
                            "locked_interval": current_addon.interval,
                            "locked_interval_count": current_addon.interval_count,
                        },
                    )

                    requesting_user.log_event(
                        f"Locked addon pricing for {member_profile.get_full_name()} for billing group invite '{billing_group.name}' - {current_addon.name} at ${current_addon.cost/100:.2f}/{current_addon.interval}",
                        "admin",
                    )

                except SubscriptionAddon.DoesNotExist:
                    requesting_user.log_event(
                        f"Warning: Could not lock addon pricing for {member_profile.get_full_name()} - addon with ID {current_addon_id} not found",
                        "admin",
                    )
            else:
                requesting_user.log_event(
                    f"Warning: No current additional member addon configured - pricing not locked for {member_profile.get_full_name()}",
                    "admin",
                )

        except Exception as e:
            requesting_user.log_event(
                f"Error locking addon pricing for {member_profile.get_full_name()}: {str(e)}",
                "admin",
            )

    def _remove_addon_pricing_for_invited_member(
        self, member_profile, billing_group, requesting_user
    ):
        """
        Remove the locked addon pricing records when an invitation is cancelled.
        """
        from profile.models import BillingGroupMemberAddon

        try:
            # Remove all locked addon pricing for this member in this billing group
            removed_addons = BillingGroupMemberAddon.objects.filter(
                billing_group=billing_group, member=member_profile
            )

            addon_names = [addon.addon.name for addon in removed_addons]
            count = removed_addons.count()

            removed_addons.delete()

            if count > 0:
                requesting_user.log_event(
                    f"Removed {count} locked addon pricing records for {member_profile.get_full_name()}: {', '.join(addon_names)}",
                    "admin",
                )

        except Exception as e:
            requesting_user.log_event(
                f"Error removing addon pricing for {member_profile.get_full_name()}: {str(e)}",
                "admin",
            )

    def post(self, request, billing_group_id):
        from profile.models import BillingGroup, Profile

        try:
            billing_group = BillingGroup.objects.get(id=billing_group_id)
        except BillingGroup.DoesNotExist:
            return Response(
                {"success": False, "message": "Billing group not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        body = request.data
        action = body.get("action")  # "invite" or "cancel"
        member_id = body.get("member_id")

        if not action or not member_id:
            return Response(
                {"success": False, "message": "Action and member_id are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            member = Profile.objects.get(user_id=member_id)
        except Profile.DoesNotExist:
            return Response(
                {"success": False, "message": "Member not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if action == "invite":
            # Remove from any existing billing group invite first
            if member.billing_group_invite:
                member.billing_group_invite = None
                member.save()

            # Send invite to this billing group
            member.billing_group_invite = billing_group
            member.save()

            # Lock in current addon pricing for this invited member
            self._lock_addon_pricing_for_invited_member(
                member, billing_group, request.user
            )

            # Send email notification with appropriate message based on subscription status
            subject = (
                f"You've been invited to join billing group '{billing_group.name}'"
            )

            if member.stripe_subscription_id and member.subscription_status == "active":
                message = (
                    f"You have been invited to join the billing group '{billing_group.name}'. "
                    f"Please note: If you accept this invitation, your current individual subscription will be "
                    f"cancelled immediately with proration for any remaining time, and you will join the billing group's "
                    f"shared subscription. Please log into your account to accept or decline this invitation."
                )
            else:
                message = (
                    f"You have been invited to join the billing group '{billing_group.name}'. "
                    f"Please log into your account to accept or decline this invitation."
                )

            member.user.email_notification(subject, message)

            # Log with subscription status information
            if member.stripe_subscription_id and member.subscription_status == "active":
                request.user.log_event(
                    f"Invited {member.get_full_name()} (with active individual subscription) to billing group '{billing_group.name}'",
                    "admin",
                )
            else:
                request.user.log_event(
                    f"Invited {member.get_full_name()} to billing group '{billing_group.name}'",
                    "admin",
                )

        elif action == "cancel":
            if member.billing_group_invite == billing_group:
                member.billing_group_invite = None
                member.save()

                # Remove locked addon pricing for this cancelled invitation
                self._remove_addon_pricing_for_invited_member(
                    member, billing_group, request.user
                )

                request.user.log_event(
                    f"Cancelled invite for {member.get_full_name()} to billing group '{billing_group.name}'",
                    "admin",
                )
            else:
                return Response(
                    {
                        "success": False,
                        "message": "Member is not invited to this billing group.",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        else:
            return Response(
                {
                    "success": False,
                    "message": "Invalid action. Use 'invite' or 'cancel'.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response({"success": True})


class ManageAddons(APIView):
    """
    get: returns a list of subscription addons
    post: creates a new subscription addon
    put: updates an existing subscription addon
    delete: deletes a subscription addon
    """

    permission_classes = (permissions.IsAdminUser | HasAPIKey,)

    def get(self, request, addon_id=None):
        from .models import SubscriptionAddon

        if addon_id:
            try:
                addon = SubscriptionAddon.objects.get(id=addon_id)
                return Response(addon.get_object())
            except SubscriptionAddon.DoesNotExist:
                return Response(
                    {"success": False, "message": "Addon not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )
        else:
            addon_type = request.GET.get("addon_type", None)
            if addon_type:
                addons = SubscriptionAddon.objects.filter(addon_type=addon_type)
            else:
                addons = SubscriptionAddon.objects.all()

            addon_list = []
            for addon in addons:
                addon_list.append(addon.get_object())

            return Response(addon_list)

    def post(self, request):
        from .models import SubscriptionAddon

        data = request.data

        # Validate required fields
        required_fields = ["name", "addon_type", "cost", "currency", "interval"]
        for field in required_fields:
            if not data.get(field):
                return Response(
                    {"success": False, "message": f"{field} is required"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        try:
            addon = SubscriptionAddon.objects.create(
                name=data["name"],
                description=data.get("description", ""),
                addon_type=data["addon_type"],
                visible=data.get("visible", True),
                currency=data["currency"],
                cost=int(data["cost"]),
                interval_count=data.get("interval_count", 1),
                interval=data["interval"],
                min_quantity=data.get("min_quantity", 1),
                max_quantity=data.get("max_quantity", 10),
            )

            request.user.log_event(
                f"Created addon '{addon.name}'",
                "admin",
            )

            return Response(
                {"success": True, "addon_id": addon.id},
                status=status.HTTP_201_CREATED,
            )

        except Exception as e:
            capture_exception(e)
            return Response(
                {"success": False, "message": "Failed to create addon"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def put(self, request, addon_id):
        from .models import SubscriptionAddon

        try:
            addon = SubscriptionAddon.objects.get(id=addon_id)
        except SubscriptionAddon.DoesNotExist:
            return Response(
                {"success": False, "message": "Addon not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        data = request.data

        # Update fields
        addon.name = data.get("name", addon.name)
        addon.description = data.get("description", addon.description)
        addon.visible = data.get("visible", addon.visible)
        addon.currency = data.get("currency", addon.currency)
        addon.cost = int(data.get("cost", addon.cost))
        addon.interval_count = data.get("interval_count", addon.interval_count)
        addon.interval = data.get("interval", addon.interval)
        addon.min_quantity = data.get("min_quantity", addon.min_quantity)
        addon.max_quantity = data.get("max_quantity", addon.max_quantity)

        addon.save()

        request.user.log_event(
            f"Updated addon '{addon.name}'",
            "admin",
        )

        return Response({"success": True})

    def delete(self, request, addon_id):
        from .models import SubscriptionAddon

        try:
            addon = SubscriptionAddon.objects.get(id=addon_id)
        except SubscriptionAddon.DoesNotExist:
            return Response(
                {"success": False, "message": "Addon not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        addon_name = addon.name
        addon.delete()

        request.user.log_event(
            f"Deleted addon '{addon_name}'",
            "admin",
        )

        return Response({"success": True})


class ManageCurrentAdditionalMemberAddon(APIView):
    """
    get: returns the current additional member addon
    post: sets the current additional member addon
    """

    permission_classes = (permissions.IsAdminUser | HasAPIKey,)

    def get(self, request):
        from .models import SubscriptionAddon

        current_addon_id = getattr(config, "CURRENT_ADDITIONAL_MEMBER_ADDON", None)

        # Handle empty string or None values
        if current_addon_id and str(current_addon_id).strip():
            try:
                addon = SubscriptionAddon.objects.get(
                    id=int(current_addon_id),
                    addon_type="additional_member",
                    visible=True,
                )
                return Response({"success": True, "current_addon": addon.get_object()})
            except SubscriptionAddon.DoesNotExist:
                return Response(
                    {
                        "success": True,
                        "current_addon": None,
                        "message": "Configured addon not found",
                    }
                )
        else:
            return Response({"success": True, "current_addon": None})

    def post(self, request):
        from .models import SubscriptionAddon

        addon_id = request.data.get("addon_id")

        if not addon_id or str(addon_id).strip() == "":
            # Clear the current addon
            config.CURRENT_ADDITIONAL_MEMBER_ADDON = ""
            request.user.log_event(
                "Cleared current additional member addon",
                "admin",
            )
            return Response({"success": True, "message": "Current addon cleared"})

        try:
            addon = SubscriptionAddon.objects.get(
                id=int(addon_id), addon_type="additional_member", visible=True
            )

            # Set the current addon
            config.CURRENT_ADDITIONAL_MEMBER_ADDON = str(addon_id)

            request.user.log_event(
                f"Set current additional member addon to '{addon.name}' (ID: {addon_id})",
                "admin",
            )

            return Response(
                {"success": True, "message": f"Current addon set to '{addon.name}'"}
            )

        except SubscriptionAddon.DoesNotExist:
            return Response(
                {
                    "success": False,
                    "message": "Addon not found or not an additional member addon",
                },
                status=status.HTTP_404_NOT_FOUND,
            )
