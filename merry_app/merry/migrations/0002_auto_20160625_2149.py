# -*- coding: utf-8 -*-
# Generated by Django 1.9.7 on 2016-06-25 21:49
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('merry', '0001_initial'),
    ]

    operations = [
        migrations.RenameField(
            model_name='pointcloud',
            old_name='file',
            new_name='pcd',
        ),
        migrations.RemoveField(
            model_name='feature',
            name='points',
        ),
        migrations.AddField(
            model_name='pointcloud',
            name='points',
            field=models.TextField(default=b'{"points":[{"x":"", "y":"", "z":""}]}'),
        ),
    ]
