# Generated by Django 3.0.8 on 2020-07-07 07:17

from django.db import migrations, models
import matching.models


class Migration(migrations.Migration):

    dependencies = [
        ('matching', '0003_auto_20200707_1438'),
    ]

    operations = [
        migrations.AlterField(
            model_name='user',
            name='student_number',
            field=models.IntegerField(unique=True, validators=[matching.models.student_number_validator]),
        ),
    ]
