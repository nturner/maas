# Generated by Django 2.2.12 on 2020-12-16 21:30

import re

import django.core.validators
from django.db import migrations, models
import django.db.models.deletion

import maasserver.models.cleansave


class Migration(migrations.Migration):

    dependencies = [
        ("maasserver", "0219_vm_nic_link"),
    ]

    operations = [
        migrations.CreateModel(
            name="NodeDevice",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created", models.DateTimeField(editable=False)),
                ("updated", models.DateTimeField(editable=False)),
                (
                    "bus",
                    models.IntegerField(
                        choices=[(1, "PCIE"), (2, "USB")], editable=False
                    ),
                ),
                (
                    "hardware_type",
                    models.IntegerField(
                        choices=[
                            (0, "Node"),
                            (1, "CPU"),
                            (2, "Memory"),
                            (3, "Storage"),
                            (4, "Network"),
                            (5, "GPU"),
                        ],
                        default=0,
                    ),
                ),
                (
                    "vendor_id",
                    models.CharField(
                        editable=False,
                        max_length=4,
                        validators=[
                            django.core.validators.RegexValidator(
                                re.compile("^[\\da-f]{4}$", 2),
                                "Must be an 8 byte hex value",
                            )
                        ],
                    ),
                ),
                (
                    "product_id",
                    models.CharField(
                        editable=False,
                        max_length=4,
                        validators=[
                            django.core.validators.RegexValidator(
                                re.compile("^[\\da-f]{4}$", 2),
                                "Must be an 8 byte hex value",
                            )
                        ],
                    ),
                ),
                ("vendor_name", models.CharField(blank=True, max_length=256)),
                ("product_name", models.CharField(blank=True, max_length=256)),
                (
                    "commissioning_driver",
                    models.CharField(blank=True, max_length=256),
                ),
                (
                    "bus_number",
                    models.PositiveIntegerField(
                        validators=[
                            django.core.validators.MaxValueValidator(65536)
                        ]
                    ),
                ),
                (
                    "device_number",
                    models.PositiveIntegerField(
                        validators=[
                            django.core.validators.MaxValueValidator(65536)
                        ]
                    ),
                ),
                (
                    "pci_address",
                    models.CharField(
                        blank=True,
                        max_length=64,
                        null=True,
                        validators=[
                            django.core.validators.RegexValidator(
                                re.compile(
                                    "^(?P<domain>[\\da-f]+:)?(?P<bus>[\\da-f]+):(?P<device>[\\da-f]+)[.](?P<function>[\\da-f]+)(@(?P<extension>.*))?$",
                                    2,
                                ),
                                "Must use BDF notation",
                            )
                        ],
                    ),
                ),
                (
                    "node",
                    models.ForeignKey(
                        editable=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="node_devices",
                        to="maasserver.Node",
                    ),
                ),
                (
                    "numa_node",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="node_devices",
                        to="maasserver.NUMANode",
                    ),
                ),
                (
                    "physical_blockdevice",
                    models.OneToOneField(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="node_device",
                        to="maasserver.PhysicalBlockDevice",
                    ),
                ),
                (
                    "physical_interface",
                    models.OneToOneField(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="node_device",
                        to="maasserver.PhysicalInterface",
                    ),
                ),
            ],
            options={
                "unique_together": {
                    ("node", "bus_number", "device_number", "pci_address")
                },
            },
            bases=(
                maasserver.models.cleansave.CleanSave,
                models.Model,
                object,
            ),
        ),
    ]