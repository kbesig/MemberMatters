from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api_admin_tools", "0011_alter_paymentplan_interval"),
    ]

    operations = [
        migrations.CreateModel(
            name="SubscriptionAddon",
            fields=[
                ("id", models.AutoField(primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=100)),
                ("description", models.CharField(blank=True, max_length=250)),
                ("stripe_price_id", models.CharField(blank=True, max_length=100)),
                ("stripe_product_id", models.CharField(blank=True, max_length=100)),
                (
                    "addon_type",
                    models.CharField(
                        choices=[
                            ("additional_member", "Additional Member"),
                            ("storage_upgrade", "Storage Upgrade"),
                            ("priority_support", "Priority Support"),
                            ("equipment_rental", "Equipment Rental"),
                            ("shelf_rental", "Shelf Rental"),
                            ("custom", "Custom Add-on"),
                        ],
                        max_length=50,
                    ),
                ),
                ("visible", models.BooleanField(default=True)),
                ("currency", models.CharField(default="aud", max_length=3)),
                ("cost", models.IntegerField()),
                ("interval_count", models.IntegerField(default=1)),
                (
                    "interval",
                    models.CharField(
                        choices=[
                            ("month", "month"),
                            ("week", "week"),
                            ("day", "day"),
                        ],
                        default="month",
                        max_length=10,
                    ),
                ),
                ("max_quantity", models.IntegerField(default=10)),
                ("min_quantity", models.IntegerField(default=1)),
                ("stripe_synced", models.BooleanField(default=False)),
                ("last_stripe_sync", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "unique_together": {("name", "addon_type")},
            },
        ),
    ]
