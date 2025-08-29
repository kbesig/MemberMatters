"""
Management command to set up locked addon pricing for existing billing group members.

This command will:
1. Find all existing billing group members who don't have locked addon pricing
2. Apply the current additional member addon pricing to them
3. Provide a report of what was done

Usage:
    python manage.py setup_billing_group_addon_pricing --dry-run    # See what would be done
    python manage.py setup_billing_group_addon_pricing               # Actually apply changes
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from constance import config
from profile.models import Profile, BillingGroup, BillingGroupMemberAddon
from api_admin_tools.models import SubscriptionAddon


class Command(BaseCommand):
    help = "Set up locked addon pricing for existing billing group members"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be done without making changes",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Force update even if locked pricing already exists",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        force = options["force"]

        if dry_run:
            self.stdout.write(
                self.style.WARNING("DRY RUN MODE - No changes will be made")
            )

        # Get the current additional member addon
        current_addon_id = getattr(config, "CURRENT_ADDITIONAL_MEMBER_ADDON", None)

        if not current_addon_id:
            self.stdout.write(
                self.style.ERROR(
                    "No current additional member addon configured. Please set CURRENT_ADDITIONAL_MEMBER_ADDON in admin settings."
                )
            )
            return

        try:
            current_addon = SubscriptionAddon.objects.get(
                id=current_addon_id, addon_type="additional_member", visible=True
            )
        except SubscriptionAddon.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(
                    f"Additional member addon with ID {current_addon_id} not found or not visible."
                )
            )
            return

        self.stdout.write(
            f"Using addon: {current_addon.name} - ${current_addon.cost/100:.2f}/{current_addon.interval}"
        )

        # Find all billing group members
        billing_groups = BillingGroup.objects.all()
        total_groups = billing_groups.count()
        total_members_processed = 0
        total_locked_pricing_created = 0

        self.stdout.write(f"Found {total_groups} billing groups to process...")

        for billing_group in billing_groups:
            members = billing_group.members.all()
            members_count = members.count()

            if members_count == 0:
                continue

            self.stdout.write(
                f"\nProcessing billing group: {billing_group.name} ({members_count} members)"
            )

            for member in members:
                total_members_processed += 1

                # Check if they already have locked pricing for this addon
                existing_locked_pricing = BillingGroupMemberAddon.objects.filter(
                    billing_group=billing_group, member=member, addon=current_addon
                ).first()

                if existing_locked_pricing and not force:
                    self.stdout.write(
                        f"  ✓ {member.get_full_name()} already has locked pricing"
                    )
                    continue

                if force and existing_locked_pricing:
                    if not dry_run:
                        existing_locked_pricing.delete()
                    self.stdout.write(
                        f"  ! Removing existing locked pricing for {member.get_full_name()}"
                    )

                # Create locked pricing
                if not dry_run:
                    with transaction.atomic():
                        locked_addon, created = (
                            BillingGroupMemberAddon.objects.get_or_create(
                                billing_group=billing_group,
                                member=member,
                                addon=current_addon,
                                defaults={
                                    "locked_cost": current_addon.cost,
                                    "locked_currency": current_addon.currency,
                                    "locked_interval": current_addon.interval,
                                    "locked_interval_count": current_addon.interval_count,
                                },
                            )
                        )
                        if created:
                            total_locked_pricing_created += 1

                self.stdout.write(
                    f"  + Created locked pricing for {member.get_full_name()} - ${current_addon.cost/100:.2f}/{current_addon.interval}"
                )
                total_locked_pricing_created += 1

        # Summary
        self.stdout.write("\n" + "=" * 50)
        self.stdout.write(f"Summary:")
        self.stdout.write(f"  Total billing groups: {total_groups}")
        self.stdout.write(f"  Total members processed: {total_members_processed}")
        self.stdout.write(
            f"  Locked pricing records created: {total_locked_pricing_created}"
        )

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    "This was a dry run. Re-run without --dry-run to apply changes."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    "Successfully set up locked addon pricing for billing group members!"
                )
            )
