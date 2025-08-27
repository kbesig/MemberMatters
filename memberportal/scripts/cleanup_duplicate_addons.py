#!/usr/bin/env python
"""
Script to identify and clean up duplicate subscription add-ons and their Stripe products.

This script helps identify:
1. Duplicate add-ons in the database
2. Duplicate Stripe products
3. Orphaned Stripe products (products without corresponding add-ons)

Usage:
    python scripts/cleanup_duplicate_addons.py --dry-run  # Just show what would be cleaned
    python scripts/cleanup_duplicate_addons.py --cleanup  # Actually perform cleanup
"""

import os
import sys
import django
import argparse
import stripe
from collections import defaultdict

# Add the parent directory to the Python path so we can import Django settings
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "membermatters.settings")
django.setup()

from constance import config
from api_admin_tools.models import SubscriptionAddon


def find_database_duplicates():
    """Find duplicate add-ons in the database"""
    print("=== Checking for duplicate add-ons in database ===")

    # Group by name and addon_type
    addon_groups = defaultdict(list)
    for addon in SubscriptionAddon.objects.all():
        key = f"{addon.name}_{addon.addon_type}"
        addon_groups[key].append(addon)

    duplicates = {k: v for k, v in addon_groups.items() if len(v) > 1}

    if duplicates:
        print(f"Found {len(duplicates)} duplicate groups:")
        for key, addons in duplicates.items():
            print(f"\n  {key}:")
            for addon in addons:
                print(
                    f"    - ID: {addon.id}, Created: {addon.created_at}, Stripe Product: {addon.stripe_product_id}"
                )
    else:
        print("✓ No duplicate add-ons found in database")

    return duplicates


def find_stripe_duplicates():
    """Find duplicate Stripe products"""
    print("\n=== Checking for duplicate Stripe products ===")

    if not config.ENABLE_STRIPE:
        print("✗ Stripe is not enabled")
        return {}

    try:
        stripe.api_key = config.STRIPE_SECRET_KEY

        # Get all products
        products = stripe.Product.list(limit=100, active=True)

        # Group by name and addon type
        product_groups = defaultdict(list)
        for product in products.data:
            addon_type = product.metadata.get("addon_type", "unknown")
            key = f"{product.name}_{addon_type}"
            product_groups[key].append(product)

        duplicates = {k: v for k, v in product_groups.items() if len(v) > 1}

        if duplicates:
            print(f"Found {len(duplicates)} duplicate product groups:")
            for key, products_list in duplicates.items():
                print(f"\n  {key}:")
                for product in products_list:
                    print(
                        f"    - ID: {product.id}, Created: {product.created}, Django ID: {product.metadata.get('django_id', 'N/A')}"
                    )
        else:
            print("✓ No duplicate Stripe products found")

        return duplicates

    except stripe.error.StripeError as e:
        print(f"✗ Stripe error: {str(e)}")
        return {}
    except Exception as e:
        print(f"✗ Error: {str(e)}")
        return {}


def find_orphaned_stripe_products():
    """Find Stripe products that don't have corresponding add-ons"""
    print("\n=== Checking for orphaned Stripe products ===")

    if not config.ENABLE_STRIPE:
        print("✗ Stripe is not enabled")
        return []

    try:
        stripe.api_key = config.STRIPE_SECRET_KEY

        # Get all products
        products = stripe.Product.list(limit=100, active=True)

        # Get all add-on Stripe product IDs
        addon_product_ids = set(
            SubscriptionAddon.objects.exclude(stripe_product_id="").values_list(
                "stripe_product_id", flat=True
            )
        )

        orphaned = []
        for product in products.data:
            if product.id not in addon_product_ids:
                orphaned.append(product)

        if orphaned:
            print(f"Found {len(orphaned)} orphaned products:")
            for product in orphaned:
                print(f"  - {product.id}: {product.name} (created: {product.created})")
        else:
            print("✓ No orphaned Stripe products found")

        return orphaned

    except stripe.error.StripeError as e:
        print(f"✗ Stripe error: {str(e)}")
        return []
    except Exception as e:
        print(f"✗ Error: {str(e)}")
        return []


def cleanup_database_duplicates(duplicates, dry_run=True):
    """Clean up duplicate add-ons in the database"""
    print("\n=== Cleaning up database duplicates ===")

    if not duplicates:
        print("No duplicates to clean up")
        return

    for key, addons in duplicates.items():
        print(f"\nProcessing {key}:")

        # Sort by creation date (keep the oldest)
        addons.sort(key=lambda a: a.created_at)

        # Keep the first one, delete the rest
        for i, addon in enumerate(addons[1:], 1):
            if dry_run:
                print(f"  Would delete: ID {addon.id} (created: {addon.created_at})")
            else:
                try:
                    # Archive Stripe objects first
                    if addon.stripe_product_id:
                        addon.delete_stripe_objects()

                    # Delete the addon
                    addon.delete()
                    print(f"  ✓ Deleted: ID {addon.id}")
                except Exception as e:
                    print(f"  ✗ Failed to delete {addon.id}: {str(e)}")


def cleanup_stripe_duplicates(duplicates, dry_run=True):
    """Clean up duplicate Stripe products"""
    print("\n=== Cleaning up Stripe duplicates ===")

    if not duplicates:
        print("No duplicates to clean up")
        return

    if not config.ENABLE_STRIPE:
        print("✗ Stripe is not enabled")
        return

    try:
        stripe.api_key = config.STRIPE_SECRET_KEY

        for key, products_list in duplicates.items():
            print(f"\nProcessing {key}:")

            # Sort by creation date (keep the oldest)
            products_list.sort(key=lambda p: p.created)

            # Keep the first one, archive the rest
            for i, product in enumerate(products_list[1:], 1):
                if dry_run:
                    print(f"  Would archive: {product.id} (created: {product.created})")
                else:
                    try:
                        # Archive the product
                        stripe.Product.modify(product.id, active=False)
                        print(f"  ✓ Archived product: {product.id}")

                        # Archive associated prices
                        prices = stripe.Price.list(product=product.id, active=True)
                        for price in prices.data:
                            stripe.Price.modify(price.id, active=False)
                            print(f"    ✓ Archived price: {price.id}")

                    except stripe.error.StripeError as e:
                        print(f"  ✗ Failed to archive {product.id}: {str(e)}")

    except stripe.error.StripeError as e:
        print(f"✗ Stripe error: {str(e)}")
    except Exception as e:
        print(f"✗ Error: {str(e)}")


def cleanup_orphaned_products(orphaned, dry_run=True):
    """Clean up orphaned Stripe products"""
    print("\n=== Cleaning up orphaned Stripe products ===")

    if not orphaned:
        print("No orphaned products to clean up")
        return

    if not config.ENABLE_STRIPE:
        print("✗ Stripe is not enabled")
        return

    try:
        stripe.api_key = config.STRIPE_SECRET_KEY

        for product in orphaned:
            if dry_run:
                print(f"Would archive orphaned product: {product.id} ({product.name})")
            else:
                try:
                    # Archive the product
                    stripe.Product.modify(product.id, active=False)
                    print(f"✓ Archived orphaned product: {product.id}")

                    # Archive associated prices
                    prices = stripe.Price.list(product=product.id, active=True)
                    for price in prices.data:
                        stripe.Price.modify(price.id, active=False)
                        print(f"  ✓ Archived price: {price.id}")

                except stripe.error.StripeError as e:
                    print(f"✗ Failed to archive {product.id}: {str(e)}")

    except stripe.error.StripeError as e:
        print(f"✗ Stripe error: {str(e)}")
    except Exception as e:
        print(f"✗ Error: {str(e)}")


def main():
    parser = argparse.ArgumentParser(
        description="Clean up duplicate subscription add-ons"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be cleaned without actually doing it",
    )
    parser.add_argument(
        "--cleanup", action="store_true", help="Actually perform the cleanup"
    )

    args = parser.parse_args()

    if not args.dry_run and not args.cleanup:
        print("Please specify either --dry-run or --cleanup")
        sys.exit(1)

    dry_run = args.dry_run

    # Find duplicates
    db_duplicates = find_database_duplicates()
    stripe_duplicates = find_stripe_duplicates()
    orphaned_products = find_orphaned_stripe_products()

    # Summary
    total_issues = len(db_duplicates) + len(stripe_duplicates) + len(orphaned_products)

    if total_issues == 0:
        print("\n🎉 No issues found! Your add-ons are clean.")
        return

    print(f"\n📊 Summary: Found {total_issues} issues to address")

    if dry_run:
        print("\n🔍 DRY RUN MODE - No changes will be made")
        print("Run with --cleanup to actually perform the cleanup")
    else:
        print("\n⚠️  CLEANUP MODE - Changes will be made")
        response = input("Are you sure you want to proceed? (y/N): ")
        if response.lower() != "y":
            print("Cleanup cancelled")
            return

    # Perform cleanup
    cleanup_database_duplicates(db_duplicates, dry_run)
    cleanup_stripe_duplicates(stripe_duplicates, dry_run)
    cleanup_orphaned_products(orphaned_products, dry_run)

    if not dry_run:
        print("\n✅ Cleanup completed!")
    else:
        print("\n🔍 Dry run completed. Review the output above.")


if __name__ == "__main__":
    main()
