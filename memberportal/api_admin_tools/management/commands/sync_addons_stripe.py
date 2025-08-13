from django.core.management.base import BaseCommand
from api_admin_tools.models import SubscriptionAddon


class Command(BaseCommand):
    help = 'Sync all subscription add-ons with Stripe'

    def add_arguments(self, parser):
        parser.add_argument(
            '--create-only',
            action='store_true',
            help='Only create new Stripe objects, don\'t update existing ones',
        )
        parser.add_argument(
            '--update-only',
            action='store_true',
            help='Only update existing Stripe objects, don\'t create new ones',
        )
        parser.add_argument(
            '--addon-ids',
            nargs='+',
            type=int,
            help='Specific add-on IDs to sync',
        )

    def handle(self, *args, **options):
        if options['addon_ids']:
            addons = SubscriptionAddon.objects.filter(id__in=options['addon_ids'])
        else:
            addons = SubscriptionAddon.objects.all()

        success_count = 0
        error_count = 0
        error_messages = []

        self.stdout.write(f"Syncing {addons.count()} add-on(s) with Stripe...")

        for addon in addons:
            try:
                if options['create_only'] and addon.stripe_product_id:
                    self.stdout.write(f"Skipping {addon.name} (already has Stripe product)")
                    continue
                
                if options['update_only'] and not addon.stripe_product_id:
                    self.stdout.write(f"Skipping {addon.name} (no Stripe product to update)")
                    continue

                if addon.stripe_product_id:
                    # Update existing
                    success, message = addon.update_stripe_price()
                    action = "Updated"
                else:
                    # Create new
                    success, message = addon.create_stripe_product_and_price()
                    action = "Created"

                if success:
                    self.stdout.write(
                        self.style.SUCCESS(f"✓ {action} Stripe objects for '{addon.name}'")
                    )
                    success_count += 1
                else:
                    self.stdout.write(
                        self.style.ERROR(f"✗ Failed to sync '{addon.name}': {message}")
                    )
                    error_count += 1
                    error_messages.append(f"{addon.name}: {message}")

            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f"✗ Error syncing '{addon.name}': {str(e)}")
                )
                error_count += 1
                error_messages.append(f"{addon.name}: {str(e)}")

        # Summary
        self.stdout.write("\n" + "="*50)
        self.stdout.write("SYNC SUMMARY")
        self.stdout.write("="*50)
        self.stdout.write(f"Successfully synced: {success_count}")
        self.stdout.write(f"Failed: {error_count}")
        
        if error_messages:
            self.stdout.write("\nErrors:")
            for error in error_messages:
                self.stdout.write(f"  - {error}")

        if success_count > 0:
            self.stdout.write(
                self.style.SUCCESS(f"\n✓ Successfully synced {success_count} add-on(s) with Stripe")
            )
        
        if error_count > 0:
            self.stdout.write(
                self.style.ERROR(f"\n✗ {error_count} add-on(s) failed to sync")
            ) 