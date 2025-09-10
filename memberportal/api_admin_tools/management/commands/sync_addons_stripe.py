from django.core.management.base import BaseCommand
from api_admin_tools.models import SubscriptionAddon


class Command(BaseCommand):
    help = "Sync all subscription add-ons with Stripe"

    def add_arguments(self, parser):
        parser.add_argument(
            "--create-only",
            action="store_true",
            help="Only create new Stripe objects",
        )
        parser.add_argument(
            "--update-only",
            action="store_true",
            help="Only update existing Stripe objects",
        )
        parser.add_argument(
            "--addon-ids",
            nargs="+",
            type=int,
            help="Sync specific add-on IDs",
        )
        parser.add_argument(
            "--cleanup-duplicates",
            action="store_true",
            help="Detect and clean up duplicate Stripe products",
        )

    def handle(self, *args, **options):
        if options["cleanup_duplicates"]:
            self.cleanup_duplicate_stripe_products()
            return

        if options["addon_ids"]:
            addons = SubscriptionAddon.objects.filter(id__in=options["addon_ids"])
        else:
            addons = SubscriptionAddon.objects.all()

        self.stdout.write(f"Syncing {addons.count()} add-on(s) with Stripe...")

        success_count = 0
        error_count = 0
        error_messages = []

        for addon in addons:
            try:
                if options["create_only"] and addon.stripe_product_id:
                    self.stdout.write(
                        f"Skipping {addon.name} (already has Stripe product)"
                    )
                    continue

                if options["update_only"] and not addon.stripe_product_id:
                    self.stdout.write(
                        f"Skipping {addon.name} (no Stripe product to update)"
                    )
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
                        self.style.SUCCESS(
                            f"✓ {action} Stripe objects for '{addon.name}'"
                        )
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
        self.stdout.write("\n" + "=" * 50)
        self.stdout.write("SYNC SUMMARY")
        self.stdout.write("=" * 50)
        self.stdout.write(f"Successfully synced: {success_count}")
        self.stdout.write(f"Failed: {error_count}")

        if error_messages:
            self.stdout.write("\nErrors:")
            for error in error_messages:
                self.stdout.write(f"  - {error}")

        if success_count > 0:
            self.stdout.write(
                self.style.SUCCESS(f"\n✓ Successfully synced {success_count} add-on(s)")
            )

    def cleanup_duplicate_stripe_products(self):
        """Detect and clean up duplicate Stripe products"""
        import stripe
        from constance import config

        if not config.ENABLE_STRIPE:
            self.stdout.write(self.style.ERROR("Stripe is not enabled"))
            return

        try:
            stripe.api_key = config.STRIPE_SECRET_KEY

            self.stdout.write("Scanning for duplicate Stripe products...")

            # Get all products
            products = stripe.Product.list(limit=100, active=True)

            # Group products by name and addon type
            product_groups = {}
            for product in products.data:
                addon_type = product.metadata.get("addon_type", "unknown")
                key = f"{product.name}_{addon_type}"

                if key not in product_groups:
                    product_groups[key] = []
                product_groups[key].append(product)

            # Find duplicates
            duplicates_found = 0
            for key, product_list in product_groups.items():
                if len(product_list) > 1:
                    duplicates_found += 1
                    self.stdout.write(
                        f"\nFound {len(product_list)} products for '{key}':"
                    )

                    # Sort by creation date (keep the oldest)
                    product_list.sort(key=lambda p: p.created)

                    # Keep the first one, archive the rest
                    for i, product in enumerate(product_list[1:], 1):
                        try:
                            # Archive the product
                            stripe.Product.modify(product.id, active=False)
                            self.stdout.write(
                                f"  ✓ Archived duplicate product: {product.id}"
                            )

                            # Archive associated prices
                            prices = stripe.Price.list(product=product.id, active=True)
                            for price in prices.data:
                                stripe.Price.modify(price.id, active=False)
                                self.stdout.write(f"    ✓ Archived price: {price.id}")

                        except stripe.error.StripeError as e:
                            self.stdout.write(
                                f"  ✗ Failed to archive {product.id}: {str(e)}"
                            )

            if duplicates_found == 0:
                self.stdout.write(self.style.SUCCESS("✓ No duplicate products found"))
            else:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"\n✓ Cleaned up {duplicates_found} duplicate product groups"
                    )
                )

        except stripe.error.StripeError as e:
            self.stdout.write(self.style.ERROR(f"Stripe error: {str(e)}"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error: {str(e)}"))
