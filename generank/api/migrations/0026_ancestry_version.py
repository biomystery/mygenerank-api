# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2017-09-26 19:50
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0025_riskscore_version'),
    ]

    operations = [
        migrations.AddField(
            model_name='ancestry',
            name='version',
            field=models.CharField(default='', max_length=10),
        ),
    ]
