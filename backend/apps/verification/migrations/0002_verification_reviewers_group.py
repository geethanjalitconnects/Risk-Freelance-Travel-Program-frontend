"""Create the "Verification reviewers" group: verification screens only (no users, rides or
bookings). Superusers add staff accounts to it in the admin. This is access control, not data."""
from django.db import migrations

GROUP = "Verification reviewers"
PERMISSIONS = [
    "view_driververification",
    "review_driververification",
    "view_documents",
    "view_verificationstatuschange",
]


def create_group(apps, schema_editor):
    from django.contrib.auth.management import create_permissions

    # Permissions are normally created after all migrations; make sure they exist now.
    app_config = apps.get_app_config("verification")
    app_config.models_module = True
    create_permissions(app_config, apps=apps, verbosity=0)

    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    group, _ = Group.objects.get_or_create(name=GROUP)
    group.permissions.set(Permission.objects.filter(content_type__app_label="verification", codename__in=PERMISSIONS))


def remove_group(apps, schema_editor):
    apps.get_model("auth", "Group").objects.filter(name=GROUP).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("verification", "0001_initial"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [migrations.RunPython(create_group, remove_group)]
