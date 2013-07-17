from reactor.loadbalancer.connection import LoadBalancerConnection

class MockLoadBalancerConnection(LoadBalancerConnection):
    def __init__(self, config=None, locks=None):
        name = "mock_lb"
        LoadBalancerConnection.__init__(self, name, config=config, locks=locks)
        self._metrics = {}
        self._sessions = None
    def metrics(self):
        return self._metrics
    def sessions(self):
        return self._sessions
