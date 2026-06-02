from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("profile", "0017_alter_log_logtype"),
    ]

    operations = [
        migrations.AlterField(
            model_name="profile",
            name="subscription_status",
            field=models.CharField(
                choices=[
                    ("inactive", "Inactive"),
                    ("active", "Active"),
                    ("cancelling", "Cancelling"),
                    ("group_active", "Group Member (Active)"),
                    ("group_inactive", "Group Member (Inactive)"),
                ],
                default="inactive",
                max_length=20,
            ),
        ),
    ]
