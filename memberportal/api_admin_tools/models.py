from django.db import models
from django.utils import timezone
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

    BILLING_PERIODS = [("Month", "month"), ("Week", "week"), ("Day", "day")]

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
    """A purchasable add-on product/price in Stripe that can be attached to a member's subscription."""

    ADDON_TYPES = [
        ("additional_member", "Additional Member"),
        ("storage_upgrade", "Storage Upgrade"),
        ("priority_support", "Priority Support"),
        ("equipment_rental", "Equipment Rental"),
        ("shelf_rental", "Shelf Rental"),
        ("custom", "Custom Add-on"),
    ]

    BILLING_PERIODS = [
        ("month", "month"),
        ("week", "week"),
        ("day", "day"),
    ]

    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=100)
    description = models.CharField(max_length=250, blank=True)
    stripe_price_id = models.CharField(max_length=100, null=True, blank=True, unique=True)
    stripe_product_id = models.CharField(max_length=100, blank=True)
    addon_type = models.CharField(max_length=50, choices=ADDON_TYPES)
    visible = models.BooleanField(default=True)
    currency = models.CharField(max_length=3, default="aud")
    cost = models.IntegerField()  # in cents
    interval_count = models.IntegerField(default=1)
    interval = models.CharField(max_length=10, choices=BILLING_PERIODS, default="month")
    max_quantity = models.IntegerField(default=10)
    min_quantity = models.IntegerField(default=1)
    stripe_synced = models.BooleanField(default=False)
    last_stripe_sync = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [["name", "addon_type"]]

    def __str__(self):
        return f"{self.name} ({self.get_addon_type_display()}) - {self.cost} {self.currency}/{self.interval}"

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
            "cost_display": f"${self.cost / 100:.2f}",
            "interval_count": self.interval_count,
            "interval": self.interval,
            "max_quantity": self.max_quantity,
            "min_quantity": self.min_quantity,
            "stripe_synced": self.stripe_synced,
        }

    def check_existing_stripe_product(self):
        """Searches Stripe for a product matching by django_id metadata or name+type."""
        import stripe as stripe_module

        if self.id:
            try:
                products = stripe_module.Product.search(
                    query=f'metadata["django_id"]:"{self.id}"'
                )
                if products.data:
                    return products.data[0]
            except stripe_module.error.StripeError:
                pass

        products = stripe_module.Product.list(active=True)
        for product in products.auto_paging_iter():
            meta = product.get("metadata", {})
            if (
                meta.get("addon_type") == self.addon_type
                and product.get("name") == self.name
            ):
                return product
        return None

    def create_stripe_product_and_price(self):
        """Creates Stripe Product + Price for this addon. Updates stripe_product_id, stripe_price_id, stripe_synced."""
        import stripe as stripe_module

        existing = self.check_existing_stripe_product()
        if existing:
            self.stripe_product_id = existing.id
        else:
            product = stripe_module.Product.create(
                name=self.name,
                description=self.description or self.name,
                metadata={
                    "addon_type": self.addon_type,
                    "django_id": str(self.id),
                },
            )
            self.stripe_product_id = product.id

        price = stripe_module.Price.create(
            unit_amount=self.cost,
            currency=self.currency,
            recurring={
                "interval": self.interval,
                "interval_count": self.interval_count,
            },
            product=self.stripe_product_id,
            metadata={
                "addon_type": self.addon_type,
                "django_id": str(self.id),
            },
        )
        self.stripe_price_id = price.id
        self.stripe_synced = True
        self.last_stripe_sync = timezone.now()
        self.save()

    def update_stripe_product(self):
        """Updates Stripe Product name/description/metadata."""
        import stripe as stripe_module

        if not self.stripe_product_id:
            return self.create_stripe_product_and_price()

        stripe_module.Product.modify(
            self.stripe_product_id,
            name=self.name,
            description=self.description or self.name,
            metadata={
                "addon_type": self.addon_type,
                "django_id": str(self.id),
            },
        )
        self.last_stripe_sync = timezone.now()
        self.save()

    def update_stripe_price(self):
        """Creates a new Stripe Price (archiving old one). Stripe doesn't allow modifying prices."""
        import stripe as stripe_module

        if not self.stripe_product_id:
            return self.create_stripe_product_and_price()

        # Archive old price
        if self.stripe_price_id:
            stripe_module.Price.modify(self.stripe_price_id, active=False)

        price = stripe_module.Price.create(
            unit_amount=self.cost,
            currency=self.currency,
            recurring={
                "interval": self.interval,
                "interval_count": self.interval_count,
            },
            product=self.stripe_product_id,
            metadata={
                "addon_type": self.addon_type,
                "django_id": str(self.id),
            },
        )
        self.stripe_price_id = price.id
        self.stripe_synced = True
        self.last_stripe_sync = timezone.now()
        self.save()

    def clean(self):
        """Validate no duplicate name+addon_type combinations."""
        from django.core.exceptions import ValidationError

        qs = SubscriptionAddon.objects.filter(
            name=self.name, addon_type=self.addon_type
        )
        if self.pk:
            qs = qs.exclude(pk=self.pk)
        if qs.exists():
            raise ValidationError(
                f"A subscription addon with name '{self.name}' and type '{self.addon_type}' already exists."
            )

    def delete_stripe_objects(self):
        """Archives (deactivates) Stripe Product and Price."""
        import stripe as stripe_module

        if self.stripe_price_id:
            stripe_module.Price.modify(self.stripe_price_id, active=False)
        if self.stripe_product_id:
            stripe_module.Product.modify(self.stripe_product_id, active=False)
