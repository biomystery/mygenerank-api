# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2017-08-03 21:59
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0022_auto_20170802_2337'),
    ]

    operations = [
        migrations.AlterField(
            model_name='riskreductor',
            name='description',
            field=models.TextField(blank=True, max_length=800),
        ),
    ]
