from reactor.config import Config

from reactor.cloud.osapi.connection import BaseOsEndpointConfig
from reactor.cloud.osapi.connection import BaseOsConnection

class OsVmsEndpointConfig(BaseOsEndpointConfig):

    instance_id = Config.string(order=2,
        validate=lambda self: \
            self._novaclient().servers.get(self.instance_id)._info['status'] == 'BLESSED' or \
            Config.error("Server is not in BLESSED state."),
        description="The live-image to use.")

class Connection(BaseOsConnection):
    """ Connects to a nova cloud that has the Gridcentric VMS extension enabled. """

    _ENDPOINT_CONFIG_CLASS = OsVmsEndpointConfig

    def _list_instances(self, config):
        """ 
        Returns a list of instances from the endpoint.
        """
        config = self._endpoint_config(config)
        server = config._novaclient().gridcentric.get(config.instance_id)
        return server.list_launched()

    def _start_instance(self, config, params={}):
        config = self._endpoint_config(config)
        server = config._novaclient().gridcentric.get(config.instance_id)
        if 'name' in params:
            server.launch(name=params['name'],
                          security_groups=config.security_groups,
                          availability_zone=config.availability_zone,
                          guest_params=params)
        else:
            server.launch(security_groups=config.security_groups,
                          availability_zone=config.availability_zone,
                          guest_params=params)