import logging
import pytest

from reactor.testing import harness, zookeeper
from reactor.testing.mock_cloud import MockCloudConnection
from reactor.testing.mock_loadbalancer import MockLoadBalancerConnection

from reactor import manager
from reactor import endpoint
from reactor.zooclient import ReactorClient
from reactor.zookeeper import paths

context = {}

def hashrequest(request):
    return (request.function.__name__, request.cls)

@pytest.fixture
def scale_manager(request):
    m = harness.make_scale_manager("127.0.0.1")
    context[hashrequest(request)] = m

    def stop_manager():
        m.clean_stop()
        logging.debug("Closing manager zookeeper connection for '%s'." % \
            request.function.__name__)
        m.zk_conn.close()

    request.addfinalizer(stop_manager)
    return m

@pytest.fixture
def base_endpoint(request):
    manager = context[hashrequest(request)]
    endpoint_name = request.function.__name__
    manager.create_endpoint(endpoint_name)
    return manager.endpoints[endpoint_name]

@pytest.fixture
def manager_config():
    return manager.ManagerConfig()

@pytest.fixture
def endpoint_config():
    return endpoint.EndpointConfig()

@pytest.fixture
def reactor_zkclient(request):
    client = ReactorClient([harness.LOCAL_ZK_ADDRESS])
    def cleanup_client():
        client.close()
    request.addfinalizer(cleanup_client)
    return client

@pytest.fixture
def mock_endpoint(request):
    endpoint = base_endpoint(request)
    scale_manager = context[hashrequest(request)]
    endpoint.cloud_conn = scale_manager.clouds["mock_cloud"]
    endpoint.lb_conn = scale_manager.loadbalancers["mock_lb"]
    return endpoint

@pytest.fixture
def mock_lb(request):
    m = context[hashrequest(request)]
    return m.loadbalancers["mock_lb"]

@pytest.fixture(autouse=True)
def isolate_zookeeper_root(request):
    path = harness.make_zk_testroot(
        request.cls.__name__ + "." + request.function.__name__)
    logging.debug("Setting zookeeper root for test %s to %s" % \
                      (request.function.__name__, path))
    paths.update_root(path)
    if zookeeper.MOCK_ZK_OBJECT is None:
        # We're using the real zookeeper, clean up on our way out.
        def cleanup_zk_node():
            harness.zookeeper_recursive_delete(path)

        request.addfinalizer(cleanup_zk_node)
