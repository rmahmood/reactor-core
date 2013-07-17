import logging
from reactor.testing.harness import start_instance
from reactor.testing.zookeeper import ZkEvent
from reactor.endpoint import EndpointConfig
from reactor.zookeeper import paths
from reactor.metrics.calculator import calculate_weighted_averages

class TestEndpoint(object):
    def test_update_config(self, scale_manager, base_endpoint, endpoint_config,
        reactor_zkclient):

        # Setup a basic tcp-base service.
        endpoint_config.url = "tcp://9000"
        endpoint_config.port = 3389
        endpoint_config.redirect = "http://reactor.com/endpoint-down.html"
        endpoint_config.weight = 500
        endpoint_config.cloud = "mock_cloud"
        endpoint_config.loadbalancer = "mock_lb"

        assert base_endpoint.cloud_conn.description() is None
        assert base_endpoint.lb_conn.description() is None

        with ZkEvent(
            scale_manager.zk_conn,
            paths.endpoint(base_endpoint.name)):
            reactor_zkclient.update_endpoint(base_endpoint.name,
                endpoint_config._values())

        assert base_endpoint.url() == "tcp://9000"
        assert base_endpoint.port() == 3389
        assert base_endpoint.redirect() == "http://reactor.com/endpoint-down.html"
        assert base_endpoint.weight() == 500
        assert base_endpoint.cloud_conn == scale_manager.clouds["mock_cloud"]
        assert base_endpoint.lb_conn == scale_manager.loadbalancers["mock_lb"]

    def test_determine_target_instances_range(self, scale_manager, mock_endpoint,
        endpoint_config, scaling_config, reactor_zkclient, mock_lb):

        scaling_config.min_instances = 1
        scaling_config.max_instances = 50
        scaling_config.rules = "1 < active < 10"

        endpoint_config = EndpointConfig(obj=scaling_config)

        endpoint_config.cloud = "mock_cloud"
        endpoint_config.loadbalancer = "mock_lb"

        with ZkEvent(
            scale_manager.zk_conn,
            paths.endpoint(mock_endpoint.name)):
            reactor_zkclient.update_endpoint(mock_endpoint.name,
                endpoint_config._values())

        ips = [ "192.168.0.1", "192.168.0.2", "192.168.0.3" ]
        map(lambda ip: start_instance(scale_manager,
                                      mock_endpoint, reactor_zkclient, ip=ip), ips)

        # with ZkEvent(
        #     scale_manager.zk_conn, paths.confirmed_ips(mock_endpoint.name),
        #     expt_value=ips):
        #     for ip in ips:
        #         reactor_zkclient.record_new_ip_address(ip)

        mock_lb._metrics[ips[0]] = { "active": (1, 20) }
        mock_lb._metrics[ips[1]] = { "active": (1, 20) }
        mock_lb._metrics[ips[2]] = { "active": (1, 20) }

        endpoint_metrics, active_connections = scale_manager.update_metrics()
        metrics, metric_ips, endpoint_connections = \
            scale_manager.load_metrics(mock_endpoint, endpoint_metrics)

        metrics = calculate_weighted_averages(metrics)

        logging.error("FOO: %s" % metrics)
        logging.error("bar: %s" % endpoint_metrics)
        logging.error("METRIC IPS: %s" % metric_ips)
        logging.error(mock_endpoint._determine_target_instances_range(metrics, len(metric_ips)))
