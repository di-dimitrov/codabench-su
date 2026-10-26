from django.db import migrations


class Migration(migrations.Migration):
    """
    Joins the two leaf nodes of the profiles migration graph:

    - 0025_customgroup_is_selectable_by_participant  (upstream)
    - 0025_merge_20260922_1002                       (registration fields; already applied on our deployment)

    0025_merge_20260922_1002 is left untouched on purpose: editing the dependencies of an already
    applied migration would raise InconsistentMigrationHistory on the existing database.
    """

    dependencies = [
        ('profiles', '0025_customgroup_is_selectable_by_participant'),
        ('profiles', '0025_merge_20260922_1002'),
    ]

    operations = []
