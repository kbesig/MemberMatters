from django.db import models
from django_prometheus.models import ExportModelOperationsMixin


# This is a Stripe Product
class MemberTier(ExportModelOperationsMixin("kiosk"), models.Model):
    """A membership tier that a member can be billed for."""

    id = models.AutoField(primary_key=True)
    name = models.CharField("Name", max_length=150, unique=True)
    description = models.CharField("Description", max_length=250, unique=True)
    stripe_id = models.CharField("Stripe Id", max_length=100, unique=True)
    visible = models.BooleanField("Is this plan visible to members?", default=True)
    featured = models.BooleanField("Is this plan featured?", default=False)

    def __str__(self):
        return f"{self.name}{' (hidden)' if not self.visible else ''}{' (featured)' if self.featured else ''} - Stripe ID: {self.stripe_id}"

    def get_object(self):
        plans = []

        for plan in self.plans.filter(visible=True):
            plans.append(plan.get_object())

        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "featured": self.featured,
            "plans": plans,
        }


# This is a Stripe Price
class PaymentPlan(ExportModelOperationsMixin("payment-plan"), models.Model):
    """A Membership Plan that specifies how a member is billed for a member tier."""

    BILLING_PERIODS = [("month", "month"), ("week", "week"), ("day", "day")]

    id = models.AutoField(primary_key=True)
    name = models.CharField("Name", max_length=50)
    stripe_id = models.CharField("Stripe Id", max_length=100, unique=True)
    member_tier = models.ForeignKey(
        MemberTier, on_delete=models.CASCADE, related_name="plans"
    )
    visible = models.BooleanField("Is this plan visible to members?", default=True)
    currency = models.CharField(
        "Three letter ISO currency code.", max_length=3, default="aud"
    )
    cost = models.IntegerField("The cost in cents for this membership plan.")
    interval_count = models.IntegerField(
        "How frequently the price is charged at (per billing interval)."
    )
    interval = models.CharField(choices=BILLING_PERIODS, max_length=10)

    def __str__(self):
        return f"{self.name} {self.member_tier.name}{' (hidden)' if not self.visible else ''} - Stripe ID: {self.stripe_id}"

    def get_object(self):
        return {
            "id": self.id,
            "name": self.name,
            "currency": self.currency,
            "cost": self.cost,
            "intervalAmount": self.interval_count,
            "interval": self.interval,
        }


class SubscriptionAddon(ExportModelOperationsMixin("subscription-addon"), models.Model):
    """Additional items that can be added to subscriptions (e.g., additional members, storage, etc.)"""

    ADDON_TYPES = [
        ("additional_member", "Additional Member"),
        ("storage_upgrade", "Storage Upgrade"),
        ("priority_support", "Priority Support"),
        ("equipment_rental", "Equipment Rental"),
        ("custom", "Custom Add-on"),
    ]

    id = models.AutoField(primary_key=True)
    name = models.CharField("Name", max_length=100)
    description = models.CharField("Description", max_length=250, blank=True)
    stripe_price_id = models.CharField(
        "Stripe Price ID", max_length=100, unique=True, blank=True
    )
    stripe_product_id = models.CharField(
        "Stripe Product ID", max_length=100, blank=True
    )
    addon_type = models.CharField("Add-on Type", max_length=50, choices=ADDON_TYPES)
    visible = models.BooleanField("Is this add-on visible to members?", default=True)
    currency = models.CharField("Currency", max_length=3, default="aud")
    cost = models.IntegerField("Cost in cents")
    interval_count = models.IntegerField("Billing interval count", default=1)
    interval = models.CharField(
        "Billing interval",
        max_length=10,
        choices=PaymentPlan.BILLING_PERIODS,
        default="month",
    )
    max_quantity = models.IntegerField("Maximum quantity allowed", default=10)
    min_quantity = models.IntegerField("Minimum quantity required", default=1)

    # Stripe sync status
    stripe_synced = models.BooleanField("Synced with Stripe", default=False)
    last_stripe_sync = models.DateTimeField("Last Stripe Sync", null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} - {self.get_addon_type_display()} (${self.cost/100:.2f}/{self.interval})"

    def get_object(self):
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "addon_type": self.addon_type,
            "addon_type_display": self.get_addon_type_display(),
            "visible": self.visible,
            "currency": self.currency,
            "cost": self.cost,
            "cost_display": f"${self.cost/100:.2f}",
            "interval_count": self.interval_count,
            "interval": self.interval,
            "max_quantity": self.max_quantity,
            "min_quantity": self.min_quantity,
            "stripe_synced": self.stripe_synced,
        }

    def create_stripe_product_and_price(self):
        """Create Stripe product and price for this add-on"""
        import stripe
        from constance import config
        from django.utils import timezone

        if not config.ENABLE_STRIPE:
            return False, "Stripe is not enabled"

        try:
            stripe.api_key = config.STRIPE_SECRET_KEY

            # Create or get product
            if not self.stripe_product_id:
                product = stripe.Product.create(
                    name=self.name,
                    description=self.description,
                    metadata={"addon_type": self.addon_type, "django_id": str(self.id)},
                )
                self.stripe_product_id = product.id
            else:
                # Update existing product
                stripe.Product.modify(
                    self.stripe_product_id,
                    name=self.name,
                    description=self.description,
                    metadata={"addon_type": self.addon_type, "django_id": str(self.id)},
                )

            # Only create price if one doesn't exist
            if not self.stripe_price_id:
                price = stripe.Price.create(
                    unit_amount=self.cost,
                    currency=self.currency.lower(),
                    recurring={
                        "interval": self.interval,
                        "interval_count": self.interval_count,
                    },
                    product=self.stripe_product_id,
                    metadata={"addon_type": self.addon_type, "django_id": str(self.id)},
                )

                self.stripe_price_id = price.id

            self.stripe_synced = True
            self.last_stripe_sync = timezone.now()
            self.save()

            return True, "Successfully created Stripe product and price"

        except stripe.error.StripeError as e:
            return False, f"Stripe error: {str(e)}"
        except Exception as e:
            return False, f"Error: {str(e)}"

    def update_stripe_product(self):
        """Update existing Stripe product (name, description, metadata)"""
        import stripe
        from constance import config
        from django.utils import timezone

        if not config.ENABLE_STRIPE:
            return False, "Stripe is not enabled"

        if not self.stripe_product_id:
            return False, "No Stripe product ID found"

        try:
            stripe.api_key = config.STRIPE_SECRET_KEY

            # Update existing product
            stripe.Product.modify(
                self.stripe_product_id,
                name=self.name,
                description=self.description,
                metadata={"addon_type": self.addon_type, "django_id": str(self.id)},
            )

            self.stripe_synced = True
            self.last_stripe_sync = timezone.now()
            self.save()

            return True, "Successfully updated Stripe product"

        except stripe.error.StripeError as e:
            return False, f"Stripe error: {str(e)}"
        except Exception as e:
            return False, f"Error: {str(e)}"

    def update_stripe_price(self):
        """Update existing Stripe price (creates new price if needed)"""
        import stripe
        from constance import config
        from django.utils import timezone

        if not config.ENABLE_STRIPE:
            return False, "Stripe is not enabled"

        try:
            stripe.api_key = config.STRIPE_SECRET_KEY

            # Create new price (Stripe doesn't allow modifying existing prices)
            price = stripe.Price.create(
                unit_amount=self.cost,
                currency=self.currency.lower(),
                recurring={
                    "interval": self.interval,
                    "interval_count": self.interval_count,
                },
                product=self.stripe_product_id,
                metadata={"addon_type": self.addon_type, "django_id": str(self.id)},
            )

            # Archive old price if it exists
            if self.stripe_price_id:
                try:
                    old_price = stripe.Price.retrieve(self.stripe_price_id)
                    old_price.active = False
                    old_price.save()
                except:
                    pass  # Price might not exist

            self.stripe_price_id = price.id
            self.stripe_synced = True
            self.last_stripe_sync = timezone.now()
            self.save()

            return True, "Successfully updated Stripe price"

        except stripe.error.StripeError as e:
            return False, f"Stripe error: {str(e)}"
        except Exception as e:
            return False, f"Error: {str(e)}"

    def delete_stripe_objects(self):
        """Delete Stripe product and price"""
        import stripe
        from constance import config

        if not config.ENABLE_STRIPE:
            return False, "Stripe is not enabled"

        try:
            stripe.api_key = config.STRIPE_SECRET_KEY

            # Archive price
            if self.stripe_price_id:
                try:
                    price = stripe.Price.retrieve(self.stripe_price_id)
                    price.active = False
                    price.save()
                except:
                    pass

            # Archive product
            if self.stripe_product_id:
                try:
                    product = stripe.Product.retrieve(self.stripe_product_id)
                    product.active = False
                    product.save()
                except:
                    pass

            return True, "Successfully archived Stripe objects"

        except stripe.error.StripeError as e:
            return False, f"Stripe error: {str(e)}"
        except Exception as e:
            return False, f"Error: {str(e)}"

    def check_existing_stripe_product(self):
        """Check if a similar Stripe product already exists"""
        import stripe
        from constance import config

        if not config.ENABLE_STRIPE:
            return None, "Stripe is not enabled"

        try:
            stripe.api_key = config.STRIPE_SECRET_KEY

            # Search for products with similar metadata
            products = stripe.Product.list(limit=100, active=True)

            for product in products.data:
                if product.metadata.get("django_id") == str(self.id) or (
                    product.name == self.name
                    and product.metadata.get("addon_type") == self.addon_type
                ):
                    return product, "Found existing product"

            return None, "No existing product found"

        except stripe.error.StripeError as e:
            return None, f"Stripe error: {str(e)}"
        except Exception as e:
            return None, f"Error: {str(e)}"

    def clean(self):
        """Validate the model before saving"""
        from django.core.exceptions import ValidationError

        # Check for duplicate names within the same addon type
        if self.pk:
            # Exclude self when checking for duplicates
            existing = SubscriptionAddon.objects.filter(
                name=self.name, addon_type=self.addon_type
            ).exclude(pk=self.pk)
        else:
            existing = SubscriptionAddon.objects.filter(
                name=self.name, addon_type=self.addon_type
            )

        if existing.exists():
            raise ValidationError(
                {
                    "name": f'An add-on with name "{self.name}" and type "{self.get_addon_type_display()}" already exists.'
                }
            )

    class Meta:
        verbose_name = "Subscription Add-on"
        verbose_name_plural = "Subscription Add-ons"
        unique_together = [["name", "addon_type"]]
