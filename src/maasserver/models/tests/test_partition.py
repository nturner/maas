# Copyright 2015 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `Partition`."""

from __future__ import (
    absolute_import,
    print_function,
    unicode_literals,
    )

str = None

__metaclass__ = type
__all__ = []

from uuid import uuid4

from django.core.exceptions import ValidationError
from maasserver.enum import PARTITION_TABLE_TYPE
from maasserver.testing.factory import factory
from maasserver.testing.testcase import MAASServerTestCase


class TestPartition(MAASServerTestCase):
    """Tests for the `Partition` model."""

    def test_get_node_returns_partition_table_node(self):
        partition = factory.make_Partition()
        self.assertEquals(
            partition.partition_table.get_node(), partition.get_node())

    def test_get_block_size_returns_partition_table_block_size(self):
        partition = factory.make_Partition()
        self.assertEquals(
            partition.partition_table.get_block_size(),
            partition.get_block_size())

    def test_doesnt_set_uuid_if_partition_table_is_MBR(self):
        table = factory.make_PartitionTable(
            table_type=PARTITION_TABLE_TYPE.MBR)
        partition = factory.make_Partition(partition_table=table)
        self.assertIsNone(partition.uuid)

    def test_set_uuid_if_partition_table_is_GPT(self):
        table = factory.make_PartitionTable(
            table_type=PARTITION_TABLE_TYPE.GPT)
        partition = factory.make_Partition(partition_table=table)
        self.assertIsNotNone(partition.uuid)

    def test_save_doesnt_overwrite_uuid(self):
        uuid = uuid4()
        table = factory.make_PartitionTable(
            table_type=PARTITION_TABLE_TYPE.GPT)
        partition = factory.make_Partition(partition_table=table, uuid=uuid)
        partition.save()
        self.assertEquals('%s' % uuid, partition.uuid)

    def test_start_end_block(self):
        """Tests the start_block, size_blocks and end_block helpers."""
        device = factory.make_BlockDevice(size=10 * 1000 ** 3, block_size=4096)
        partition_table = factory.make_PartitionTable(block_device=device)
        # A partition that takes up blocks 0, 1 and 2.
        partition = factory.make_Partition(partition_table=partition_table,
                                           start_offset=0,
                                           size=4096 * 3)

        self.assertEqual(partition.start_block, 0)
        self.assertEqual(partition.size_blocks, 3)
        self.assertEqual(partition.end_block, 2)

    def test_block_sizing(self):
        """Ensure start_block and  and size are rounded to block boundaries."""
        device = factory.make_BlockDevice(size=10 * 1000 ** 3, block_size=4096)
        # A billion bytes slightly misaligned.
        partition_size = 1 * 1000 ** 3
        partition_offset = device.block_size * 3 + 50
        partition_table = factory.make_PartitionTable(block_device=device)
        partition = factory.make_Partition(partition_table=partition_table,
                                           start_offset=partition_offset,
                                           size=partition_size)

        # Size should be larger than the desired.
        self.assertGreaterEqual(partition.size_blocks * device.block_size,
                                partition_size)
        # But not more than one block larger.
        self.assertLessEqual((partition.size_blocks - 1) * device.block_size,
                             partition_size)
        # Partition should start on the 4th block (we count from zero).
        self.assertEqual(partition.start_block, 3)

    def test_clean(self):
        """Ensure size and offset are rounded on save."""
        device = factory.make_BlockDevice(size=10 * 1000 ** 3, block_size=4096)
        # A billion bytes slightly misaligned.
        partition_size = 1 * 1000 ** 3
        partition_offset = device.block_size * 3 + 50
        partition_table = factory.make_PartitionTable(block_device=device)
        partition = factory.make_Partition(partition_table=partition_table,
                                           start_offset=partition_offset,
                                           size=partition_size)

        # Start should be slightly less than desired start.
        self.assertLessEqual(partition.start_offset, partition_offset)
        self.assertLess(partition_offset - partition.start_offset,
                        device.block_size)
        # Size should be no more than one block larger.
        self.assertLess(partition.size - partition_size, device.block_size)

    def test_size_validator(self):
        """Checks impossible values for size and offset"""
        device = factory.make_BlockDevice(size=10 * 1000 ** 3, block_size=4096)
        partition_table = factory.make_PartitionTable(block_device=device)

        # Should not be able to make a partition with zero blocks.
        self.assertRaises(ValidationError, factory.make_Partition,
                          **{'partition_table': partition_table,
                             'start_offset': 0,
                             'size': 0})
        # Should not be able to make a partition starting on block -1
        self.assertRaises(ValidationError, factory.make_Partition,
                          **{'partition_table': partition_table,
                             'start_offset': -1,
                             'size': 10})

    def test_overlap_prevention(self):
        """Checks whether overlap prevention works."""
        block_size = 4096
        device = factory.make_BlockDevice(size=10 * 1000 ** 3,
                                          block_size=block_size)
        partition_table = factory.make_PartitionTable(block_device=device)

        # Create a partition occupying blocks 5, 6, 7, 8 and 9.
        factory.make_Partition(partition_table=partition_table,
                               start_offset=5 * block_size,
                               size=5 * block_size)
        # Uses blocks 3, 4, 5 and 6.
        self.assertRaises(ValidationError, factory.make_Partition,
                          **{'partition_table': partition_table,
                             'start_offset': 3 * block_size,
                             'size': 4 * block_size})
        # Uses blocks 8, 9, 10.
        self.assertRaises(ValidationError, factory.make_Partition,
                          **{'partition_table': partition_table,
                             'start_offset': 8 * block_size,
                             'size': 3 * block_size})
        # Uses blocks 6, 7, 8.
        self.assertRaises(ValidationError, factory.make_Partition,
                          **{'partition_table': partition_table,
                             'start_offset': 6 * block_size,
                             'size': 3 * block_size})
        # Should succeed - uses blocks 0, 1, 2.
        factory.make_Partition(partition_table=partition_table,
                               start_offset=0,
                               size=3 * block_size)

    def test_partition_past_end_of_device(self):
        """Attempt to allocate a partition past the end of the device."""
        block_size = 1024
        device = factory.make_BlockDevice(size=10000 * block_size)
        partition_table = factory.make_PartitionTable(block_device=device)

        # Should not make a partition larger than the device
        self.assertRaises(ValidationError, factory.make_Partition,
                          **{'partition_table': partition_table,
                             'start_offset': 0,
                             'size': device.size + device.block_size})
        # Create a partition the size of the device
        partition = factory.make_Partition(partition_table=partition_table,
                                           start_offset=0,
                                           size=device.size)
        self.assertEqual(partition.size, device.size)
