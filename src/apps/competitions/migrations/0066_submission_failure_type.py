from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('competitions', '0065_submission_resubmitted_from'),
    ]

    operations = [
        migrations.AddField(
            model_name='submission',
            name='failure_type',
            field=models.CharField(blank=True, choices=[('platform', 'Platform error'), ('submission', 'Invalid submission'), ('program', 'Program error'), ('scoring', 'Scoring error'), ('time_limit', 'Time limit exceeded')], max_length=32, null=True),
        ),
    ]
