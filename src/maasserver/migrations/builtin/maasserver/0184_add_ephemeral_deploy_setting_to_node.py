# -*- coding: utf-8 -*-
# Generated by Django 1.11.11 on 2019-02-22 23:36
from __future__ import unicode_literals

from django.db import (
    migrations,
    models,
)


class Migration(migrations.Migration):

    dependencies = [
        ('maasserver', '0183_node_uuid'),
    ]

    operations = [
        migrations.AddField(
            model_name='node',
            name='ephemeral_deploy',
            field=models.BooleanField(default=False),
        ),
    ]
