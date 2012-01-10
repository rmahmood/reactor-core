
import ConfigParser
import logging
from StringIO import StringIO
import threading
import time
import uuid

from gridcentric.scalemanager.config import ManagerConfig, ServiceConfig
from gridcentric.scalemanager.service import Service
from gridcentric.scalemanager.zookeeper.connection import ZookeeperConnection
import gridcentric.scalemanager.zookeeper.paths as paths


class ScaleManager(object):
    
    def __init__(self):
        self.uuid = uuid.uuid4()
        self.services = {}
        self.watching_ips ={}
    
    def serve(self, zk_servers):
        # Create a connection to zk_configuration and read
        # in the ScaleManager service config
        
        self.zk_conn = ZookeeperConnection(zk_servers)
        manager_config = self.zk_conn.read(paths.config)
        self.config = ManagerConfig(manager_config)
        
        self.service_change(
                    self.zk_conn.watch_children(paths.services, self.service_change)) 
    
    def service_change(self, services):
        
        logging.info("Services have changed: new=%s, existing=%s" %(services, self.services.keys()))
        for service_name in services:
            if service_name not in self.services:
                self.create_service(service_name)
        
        services_to_remove = []
        for service_name in self.services:
            if service_name not in services:
                self.remove_service(service_name)
                services_to_remove += [service_name]
        
        for service in services_to_remove:
            del self.services[service]

    def create_service(self, service_name):
        
        logging.info("Assigning service %s to manager %s" %(service_name, self.uuid))
        
        service_path  = paths.service(service_name)
        service_config = ServiceConfig(self.zk_conn.read(service_path))
        service = Service(service_name, service_config, self)
        self.services[service_name] = service
        
        if self.zk_conn.read(paths.service_managed(service_name)) == None:
            logging.info("New service %s found to be managed." %(service_name))
            # This service is currently unmanaged.
            service.manage()
            self.zk_conn.write(paths.service_managed(service_name),"True")
        
        service.update()
        self.zk_conn.watch_contents(service_path, service.update_config)
            
    
    def remove_service(self, service_name):
        """
        This removes / unmanages the service.
        """
        logging.info("Removing service %s from manager %s" %(service_name, self.uuid))
        service = self.services.get(service_name, None)
        if service:
            logging.info("Unmanaging service %s" %(service_name))
            service.unmanage()

    def watch_for_new_ip(self, service):
        """
        This sets the scale manager to watch for a new IP address that will belong to this
        service.
        """
        if len(self.watching_ips) == 0:
            # Initialize the watch
            self.zk_conn.watch_children(paths.new_ips, self.ip_changed)
            
        self.watching_ips[service] = self.watching_ips.get(service,0) + 1

    def confirmed_ips(self, service_name):
        """
        Returns a list of all the confirmed ips for the the service.
        """
        ips = self.zk_conn.list_children(paths.confirmed_ips(service_name))
        if ips == None:
            ips = []
        return ips

    def drop_ip(self, service_name, ip_address):
        self.zk_conn.delete(paths.confirmed_ip(service_name, ip_address))

    def ip_changed(self, ips):
        
        delete_watches = []
        for service in self.watching_ips:
            logging.info("Service %s is watching ips. Checking if any match: %s." % (service.name, ips))
            service_ips = service.addresses()
            for ip in ips:
                if ip in service_ips:
	            logging.info("service %s found for IP %s" %(service.name, ip))
                    # We found the service that was waiting for this ip address.
                    # Remove this ip address from ZK, and decrement this watch count.
                    if self.watching_ips[service] == 1:
                        delete_watches += [service]
                    else:
                        self.watching_ips[service] = self.watching_ips[service] - 1
                    self.zk_conn.write(paths.confirmed_ip(service.name, ip), "")
                    self.zk_conn.delete(paths.new_ip(ip))
                    service.update_loadbalancer()
        
        # Delete watches, etc.
        for service in delete_watches:
            del self.watching_ips[service]

    def health_check(self):
        # Does a health check on all the services that are being managed.
        for service in self.services:
            service.health_check()

    def run(self):
        while True:
<<<<<<< local
            time.sleep(self.config.health_check)
            self.health_check()=======
            time.sleep(86400)
>>>>>>> other
