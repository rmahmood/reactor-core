import random

from reactor.testing.harness import start_instance, retry
from reactor.testing.harness import make_scale_manager, destroy_scale_manager
from reactor.testing.zookeeper import MockZookeeper, ZkEvent
from reactor.loadbalancer.connection import LoadBalancerConnection
from reactor.zookeeper import paths
from reactor.endpoint import Endpoint

class TestManager(object):
    """
    These set of tests run on a single manager and test basic manager
    functionality.
    """
    def test_find_loadbalancer_connection(self, scale_manager):
        # Default connection object should be None
        assert scale_manager._find_loadbalancer_connection() is not None

        # Test a couple of load balancer loading to ensure the manager finds the
        # correct modules.
        for lb in ['nginx', 'tcp', 'rdp', 'dnsmasq']:
            lbobj = scale_manager._find_loadbalancer_connection(lb)
            assert isinstance(lbobj, LoadBalancerConnection)
            assert lbobj.__module__ == 'reactor.loadbalancer.%s.connection' % lb

    def test_setup_loabalancer_connections(self, scale_manager, manager_config):
        # Ensure the manager loads all listed lbs from its config.
        manager_config.loadbalancers = ['tcp', 'rdp']

        scale_manager._setup_loadbalancer_connections(manager_config)
        assert isinstance(scale_manager.loadbalancers, dict)
        assert len(scale_manager.loadbalancers.items()) == 2
        for lb in manager_config.loadbalancers:
            assert scale_manager.loadbalancers.has_key(lb)

        # Ensure the manager correctly updates the lbs when the config changes.
        manager_config.loadbalancers = ['nginx']
        scale_manager._setup_loadbalancer_connections(manager_config)
        assert isinstance(scale_manager.loadbalancers, dict)
        assert len(scale_manager.loadbalancers.items()) == 1
        assert scale_manager.loadbalancers.has_key('nginx')

    def test_ensure_register_ip(self, scale_manager, reactor_zkclient, mock_endpoint):
        # 'Boot' our dummy instance.
        ip = '172.16.0.100' # Candidate IP.
        instance = start_instance(scale_manager, mock_endpoint,
            reactor_zkclient, ip=ip)

        with ZkEvent(
            scale_manager.zk_conn, paths.confirmed_ips(mock_endpoint.name),
            expt_value=[ip]):
            # 'Register' by writing ip into zk, (as the external API call would).
            reactor_zkclient.record_new_ip_address(ip)

        assert ip in scale_manager.active_ips(mock_endpoint.name)

    def test_update_metrics(self, scale_manager, manager_config,
        reactor_zkclient, mock_endpoint, mock_lb):

        # When there are no connections, we expect empty metrics.
        all_metrics, all_active_conn = scale_manager.update_metrics()
        assert len(all_metrics) == 0
        assert len(all_active_conn) == 0

        ips = [ '172.16.0.200', '172.16.0.101', '172.16.0.102' ]
        map(lambda ip: start_instance(scale_manager, mock_endpoint,
            reactor_zkclient, ip=ip), ips)

        with ZkEvent(
            scale_manager.zk_conn, paths.confirmed_ips(mock_endpoint.name),
            expt_value=ips):
            for ip in ips:
                reactor_zkclient.record_new_ip_address(ip)

        # Still no active connections.
        all_metrics, all_active_conn = scale_manager.update_metrics()
        assert len(all_metrics) == 0
        assert len(all_active_conn) == 0

        # Ask the lb to pretend there are some active connections.
        mock_lb._metrics[ips[0]] = { "active": (1, 10) }
        mock_lb._metrics[ips[1]] = { "active": (1, 15) }
        mock_lb._metrics[ips[2]] = { "active": (1, 5)  }

        # Should be 3 active hosts now.
        all_metrics, all_active_conn = scale_manager.update_metrics()
        assert len(all_metrics) == 1 # 1 manager
        assert all_metrics.has_key(mock_endpoint.key())
        assert sorted(all_metrics[mock_endpoint.key()][0]) == sorted(ips)

        assert all_active_conn.has_key(mock_endpoint.name)
        assert sorted(all_active_conn[mock_endpoint.name]) == sorted(ips)

        # Add some more metrics.
        mock_lb._metrics[ips[0]] = { "active": (1, 10), "cpu": (5, 100) }
        mock_lb._metrics[ips[1]] = { "active": (1, 15), "cpu": (5, 60)  }
        mock_lb._metrics[ips[2]] = { "active": (1, 5),  "cpu": (5, 75)  }

        all_metrics, all_active_conn = scale_manager.update_metrics()
        # We're not guranteed any ordering so just make sure all the values lie
        # in the expected values set.
        assert all_metrics[mock_endpoint.key()][1][0]["cpu"] in [(5, 100), (5, 60), (5, 75)]
        assert all_metrics[mock_endpoint.key()][1][1]["cpu"] in [(5, 100), (5, 60), (5, 75)]
        assert all_metrics[mock_endpoint.key()][1][2]["cpu"] in [(5, 100), (5, 60), (5, 75)]

        # Set active = 0 for an ip and make sure it's not present in the
        # all_active_conn dictionary.
        mock_lb._metrics[ips[0]] = { "active": (1, 0), "cpu": (5, 100) }
        mock_lb._metrics[ips[2]] = { "active": (1, 0), "cpu": (5, 75)  }
        all_metrics, all_active_conn = scale_manager.update_metrics()
        assert len(all_active_conn[mock_endpoint.name]) == 1
        assert ips[1] in all_active_conn[mock_endpoint.name]

class TestManagerClustering(object):
    """
    Tests around clustering managers.
    """

    @retry()
    def wait_for_clustering(self, managers):
        """ Wait until all managers know about all other managers. """
        # Build up master ip list.
        ips = []
        for m in managers:
            ips.extend(m.names)

        # Ensure all managers know about all other managers by all their
        # aliases.
        for m in managers:
            ip_list = [ elt.ip for elt in m.manager_ips ]
            for ip in ips:
                assert ip in ip_list

    def make_cluster(self, names_list):
        sms = []
        for names in names_list:
            sms.append(make_scale_manager(names))
        self.wait_for_clustering(sms)
        return sms

    def assert_endpoint_owned(self, managers, endpoint):
        """
        Ensures that one and only one manager in 'managers' owns 'endpoint'.
        """
        owner_found = False
        for m in managers:
            if not owner_found:
                owner_found = m.endpoint_owned(endpoint)
            else:
                assert not m.endpoint_owned(endpoint)
        assert owner_found

    def test_setup_cluster(self):
        sms = self.make_cluster(["127.0.0.1", "172.16.0.1", "192.168.0.100"])

        # Introduce a new manager, all the existing ones should pick it up.
        sms.append(make_scale_manager("10.0.0.1"))
        self.wait_for_clustering(sms)

        # Clean up managers.
        map(destroy_scale_manager, sms)

    def test_ensure_endpoint_owned(self):
        """ Make sure all endpoints are owned by some manager. """
        sms = self.make_cluster(
            [["127.0.0.1", "192.168.0.1"],
             "10.1.1.2",
             ["172.16.0.1", "172.16.0.2", "172.16.0.3"]])

        for i in xrange(0, 30):
            # Pick a random manager to initially add the endpoint to.
            sm = random.choice(sms)
            endpoint = Endpoint("endpoint-%d" % i, sm)

            # Add the endpoint and wait for each manager to observe the zk event
            # for a new endpoint.
            with ZkEvent([ m.zk_conn for m in sms ], paths.endpoints(),
                target_count=len(sms)):
                sm.add_endpoint(endpoint)

            # Make sure the endpoint has a single owner.
            self.assert_endpoint_owned(sms, endpoint)

        # Clean up managers.
        map(destroy_scale_manager, sms)

    def test_endpoint_delete(self, reactor_zkclient):
        """ Test that an endpoint is deleted from all managers. """
        sms = self.make_cluster(["127.0.0.1", "10.0.0.1", "172.16.0.1"])
        sm = random.choice(sms)
        endpoint = Endpoint("test_endpoint_delete", sm)

        with ZkEvent([ m.zk_conn for m in sms ], paths.endpoints(),
            target_count=len(sms)):
            sm.add_endpoint(endpoint)
        self.assert_endpoint_owned(sms, endpoint)

        with ZkEvent([ m.zk_conn for m in sms ], paths.endpoints(),
            target_count=len(sms)):
            # Delete the endpoint.
            reactor_zkclient.unmanage_endpoint(endpoint.name)

        # No one should own the endpoint anymore.
        try:
            self.assert_endpoint_owned(sms, endpoint)
        except AssertionError:
            pass

        map(destroy_scale_manager, sms)
