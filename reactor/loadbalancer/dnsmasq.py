import os
import signal

from mako.template import Template

from reactor.config import Config
from reactor.loadbalancer.connection import LoadBalancerConnection
from reactor.loadbalancer.netstat import connection_count

class DnsmasqManagerConfig(Config):

    config_path = Config.string(default="/etc/dnsmasq.d", \
        description="The configuration directory to insert base configuration.")

    hosts_path = Config.string(default="/etc/hosts.reactor", \
        description="The directory in which to generate site configurations.")

class Connection(LoadBalancerConnection):

    _MANAGER_CONFIG_CLASS = DnsmasqManagerConfig

    def __init__(self, **kwargs):
        LoadBalancerConnection.__init__(self, **kwargs)
        template_file = os.path.join(os.path.dirname(__file__),'dnsmasq.template')
        self.template = Template(filename=template_file)
        self.ipmappings = {}

    def _determine_dnsmasq_pid(self):
        if os.path.exists("/var/run/dnsmasq/dnsmasq.pid"):
            pid_file = file("/var/run/dnsmasq/dnsmasq.pid",'r')
            pid = pid_file.readline().strip()
            pid_file.close()
            return int(pid)
        else:
            return None

    def clear(self):
        self.ipmappings = {}

    def redirect(self, url, names, other_url, config=None):
        # We simply serve up the public servers as our DNS
        # records. It's very difficult to implement CNAME
        # records or even parse what is being specified in 
        # the other_url.
        self.change(url, names, [], [])

    def change(self, url, names, ips, config=None):
        # Save the mappings.
        for name in names:
            self.ipmappings[name] = ips

    def save(self):
        # Compute the address mapping.
        # NOTE: We do not currently support the weight parameter
        # for dns-based loadbalancer. This may be implemented in
        # the future -- but for now this parameter is ignored.
        ipmap = {}
        for (name, backends) in self.ipmappings.items():
            for backend in backends:
                if not(backend.ip in ipmap):
                    ipmap[backend.ip] = []
                ipmap[backend.ip].append(name)

        # Write out our hosts file.
        hosts = open(self._manager_config().hosts_path, 'wb')
        for (address, names) in ipmap.items():
            for name in set(names):
                hosts.write("%s %s\n" % (address, name))
        hosts.close()

        # Write out our configuration template.
        conf = self.template.render(domain=self.domain,
                                    hosts=self._manager_config().hosts_path)

        # Write out the config file.
        config_file = file(os.path.join(self._manager_config().config_path, "reactor.conf"), 'wb')
        config_file.write(conf)
        config_file.flush()
        config_file.close()

        # Send a signal to dnsmasq to reload the configuration
        # (Note: we might need permission to do this!!).
        dnsmasq_pid = self._determine_dnsmasq_pid()
        if dnsmasq_pid:
            os.kill(dnsmasq_pid, signal.SIGHUP)

    def metrics(self):
        return {}
