from django.db import migrations, models


class Migration(migrations.Migration):
    """Adds the "setup" failure type (task without scoring program or reference data). Choices only: no data change."""

    dependencies = [
        ('competitions', '0066_submission_failure_type'),
    ]

    operations = [
        migrations.AlterField(
            model_name='submission',
            name='failure_type',
            field=models.CharField(blank=True, choices=[('platform', 'Platform error'), ('submission', 'Invalid submission'), ('program', 'Program error'), ('scoring', 'Scoring error'), ('time_limit', 'Time limit exceeded'), ('setup', 'Task setup issue')], max_length=32, null=True),
        ),
    ]
