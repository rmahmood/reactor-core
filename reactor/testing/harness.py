#
# Reactor unittesting harness.
#
# This module MUST be imported before any other reactor modules from
# the toplevel unit test source file. This is because we manually set
# up some import paths before the rest of reactor starts importing
# reactor modules.
#

import time
import os
import sys
import logging
from functools import wraps
from uuid import uuid4

# Patch up python module path.
sys.path.insert(0, os.path.abspath("../.."))

import reactor.testing.zookeeper as testing_zk

# Important: Load all reactor modules below this point, now that it's safe to
# import reactor's zookeeper module.
from reactor.zookeeper import connection
from reactor import manager
from reactor.testing.mock_cloud import MockCloudConnection
from reactor.testing.mock_loadbalancer import MockLoadBalancerConnection

# Enable debug-level logging.
logging.basicConfig(format="%(asctime)s %(levelname)s: %(message)s",
    level=logging.DEBUG)

# Open the testing zookeeper handle. We'll just take advantage of the
# reactor zookeeper code to do this for now.
LOCAL_ZK_ADDRESS = "localhost:2181"
try:
    LOCAL_ZK_HANDLE = connection.connect([LOCAL_ZK_ADDRESS])
except:
    # Zookeeper may not be installed on this machine.
    LOCAL_ZK_HANDLE = None
REACTOR_ZK_ROOT_PREFIX = "/reactor-unittest-"

# Enable debug-level logging
logging.basicConfig(format="%(asctime)s %(levelname)s: %(message)s",
    level=logging.DEBUG)

def zookeeper_recursive_delete(path):
    logging.debug("Recursively deleting zk path %s" % path)
    if not zookeeper.exists(LOCAL_ZK_HANDLE, path):
        return

    def recursive_delete(target_path):
        for child in zookeeper.get_children(LOCAL_ZK_HANDLE, target_path):
            recursive_delete(os.path.join(target_path, child))
        zookeeper.delete(LOCAL_ZK_HANDLE, target_path)
    recursive_delete(path)

def zookeeper_global_testroot_cleanup():
    ROOT = "/"
    for path in [ os.path.join(ROOT, p) for p in \
        zookeeper.get_children(LOCAL_ZK_HANDLE, ROOT) ]:
        if path.startswith(REACTOR_ZK_ROOT_PREFIX):
            logging.debug("Deleting stale zk root %s" % path)
            zookeeper_recursive_delete(path)

# Delete all stale test roots we find (probably left over from previously
# failed/crashed tests). If we collide with a stale name, the test will fail
# since the resulting zookeeper state is ambiguous.
try:
    zookeeper_global_testroot_cleanup()
except:
    # Zookeeper may not be installed on this machine.
    pass

def make_zk_testroot(idstr):
    path = REACTOR_ZK_ROOT_PREFIX + idstr + "-" + str(uuid4())
    if testing_zk.MOCK_ZK_OBJECT is None:
        create_func = testing_zk.zookeeper.create
    else:
        create_func = testing_zk.MockZookeeper.create
    create_func(LOCAL_ZK_HANDLE, path, '', [connection.ZOO_OPEN_ACL_UNSAFE], 0)
    return path

def make_scale_manager(name):
    if not isinstance(name, list):
        name = [name]
    m = manager.ScaleManager([LOCAL_ZK_ADDRESS], names=name)
    m.serve()
    m.clouds["mock_cloud"] = MockCloudConnection()
    m.loadbalancers["mock_lb"] = MockLoadBalancerConnection()
    return m

def start_instance(scale_manager, endpoint, ip=None, instance_id=None, name=None):
    # We only know how to start instances on a mock cloud.
    assert isinstance(endpoint.cloud_conn, MockCloudConnection)
    instance = endpoint.cloud_conn.start_instance(
        endpoint.config,
        ip=ip,
        instance_id=instance_id,
        name=name)
    scale_manager.add_endpoint_instance(
        endpoint.name,
        endpoint.cloud_conn.id(endpoint.config, instance),
        endpoint.cloud_conn.name(endpoint.config, instance))
    return instance
