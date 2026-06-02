from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api_admin_tools", "0012_subscriptionaddon"),
    ]

    operations = [
        # Convert existing empty strings to NULL before adding unique constraint
        migrations.RunSQL(
            sql="UPDATE api_admin_tools_subscriptionaddon SET stripe_price_id = NULL WHERE stripe_price_id = '';",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.AlterField(
            model_name="subscriptionaddon",
            name="stripe_price_id",
            field=models.CharField(blank=True, max_length=100, null=True, unique=True),
        ),
    ]
