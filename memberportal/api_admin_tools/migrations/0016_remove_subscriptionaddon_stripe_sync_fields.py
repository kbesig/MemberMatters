from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("api_admin_tools", "0015_add_shelf_rental_models"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="subscriptionaddon",
            name="stripe_synced",
        ),
        migrations.RemoveField(
            model_name="subscriptionaddon",
            name="last_stripe_sync",
        ),
    ]
