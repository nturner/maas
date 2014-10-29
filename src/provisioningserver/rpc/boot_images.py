# Copyright 2014 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""RPC relating to boot images."""

from __future__ import (
    absolute_import,
    print_function,
    unicode_literals,
    )

str = None

__metaclass__ = type
__all__ = [
    "import_boot_images",
    "list_boot_images",
    "is_import_boot_images_running",
    ]

from urlparse import urlparse

from provisioningserver import concurrency
from provisioningserver.auth import get_maas_user_gpghome
from provisioningserver.boot import tftppath
from provisioningserver.config import Config
from provisioningserver.import_images import boot_resources
from provisioningserver.utils.env import environment_variables
from provisioningserver.utils.twisted import synchronous
from twisted.internet.threads import deferToThread


def list_boot_images():
    """List the boot images that exist on the cluster."""
    return tftppath.list_boot_images(
        Config.load_from_cache()['tftp']['resource_root'])


def get_hosts_from_sources(sources):
    """Return set of hosts that are contained in the given sources."""
    hosts = set()
    for source in sources:
        url = urlparse(source['url'])
        if url.hostname is not None:
            hosts.add(url.hostname)
    return hosts


@synchronous
def _run_import(sources, http_proxy=None, https_proxy=None):
    """Run the import.

    This is function is synchronous so it must be called with deferToThread.
    """
    variables = {
        'GNUPGHOME': get_maas_user_gpghome(),
        }
    if http_proxy is not None:
        variables['http_proxy'] = http_proxy
    if https_proxy is not None:
        variables['https_proxy'] = https_proxy
    # Communication to the sources and loopback should not go through proxy.
    no_proxy_hosts = ["localhost", "127.0.0.1", "::1"]
    no_proxy_hosts += list(get_hosts_from_sources(sources))
    variables['no_proxy'] = ','.join(no_proxy_hosts)
    with environment_variables(variables):
        boot_resources.import_images(sources)


def import_boot_images(sources, http_proxy=None, https_proxy=None):
    """Imports the boot images from the given sources."""
    lock = concurrency.boot_images
    if not lock.locked:
        return lock.run(
            deferToThread, _run_import, sources,
            http_proxy=http_proxy, https_proxy=https_proxy)


def is_import_boot_images_running():
    """Return True if the import process is currently running."""
    return concurrency.boot_images.locked
