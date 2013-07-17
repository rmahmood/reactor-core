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
from reactor.zookeeper import connection, paths
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
    """ Deletes all reactor paths which start with the test root prefix. """
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

def destroy_scale_manager(scale_manager):
    """
    Cleans up a scale manager. In particular, ensures the zookeeper connection
    for the manager is closed. We have to be particularly careful to close zk
    connections because the default connection limit from the same address is
    very small (10).
    """
    scale_manager.clean_stop()
    scale_manager.zk_conn.close()

def start_instance(scale_manager, endpoint, reactor_zkclient, ip=None,
    instance_id=None, name=None, register=True):
    """
    Boots a mock instance.

    Fakes the booting of an instance on the given endpoint. At the moment, this
    only works when the endpoint uses a mock cloud connection and mock
    loadbalancer. Assigns the various optional parameters to the new instance if
    provided, otherwise suitable values are randomly generated.

    Args:
        scale_manager: A reactor manager object.
        endpoint: A reactor endpoint object managed by 'scale_manager'.
        reactor_zkclient: A connected reactor zooclient object.
        ip: IP address to assigned to new instance.
        instance_id: Instace id to assign to new instance.
        name: Name to assign to new instance.
        register: Flag controlling whether the instance is automatically
            registered with reactor. If True, the call blocks until registration
            is complete and the manager confirms the registration.

    Returns:
        An instance named tuple representing the mock instance. This object
        contains the various instance attributes, see MockInstance in
        reactor.testing.mock_cloud.
    """

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

    if register:
        with testing_zk.ZkEvent(scale_manager.zk_conn,
            paths.confirmed_ips(endpoint.name),
            expt_value=ip,
            compare="contains"):
            reactor_zkclient.record_new_ip_address(ip)

    return instance

class retry(object):
    """
    Decorator for retrying function calls.

    Calls the decorated function until it either succeeds (does not raise an
    exception) or a maximum number of retries have been attempted.

    Args:
        interval: Time interval in seconds between retriesl
        retries: Maximum number of times the call is attempted.

    Returns:
        The return value from the function if the call succeeds. Re-raises the
        last exception raised by the function if all attempts fail.
    """
    def __init__(self, interval=0.1, retries=10):
        self.interval = interval
        self.retries = retries
    def __call__(self, func):
        @wraps(func)
        def retry_decorator_wrapper(*args, **kwargs):
            attempts = 0
            last_exc = None
            while attempts < self.retries:
                attempts += 1
                try:
                    return func(*args, **kwargs)
                except Exception:
                    logging.warn("Function %s failed %d of %d attempts.",
                                 func.__name__, attempts, self.retries)
                    last_exc = sys.exc_info()
                    time.sleep(self.interval)
            # We're out of retries, bubble up last exception.
            logging.error("Function %s failed too many times, giving up.",
                          func.__name__)
            if last_exc is not None:
                raise last_exc[0], last_exc[1], last_exc[2]
        return retry_decorator_wrapper

import pprint
pprint = pprint.PrettyPrinter().pprint

def repl(ctx):
    import code
    import readline
    code.InteractiveConsole(locals=ctx).interact()

def ttrace():
    import reactor.ttrace
    reactor.ttrace.trace_start("/tmp/trace.html")
