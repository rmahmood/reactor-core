import getopt
import logging
import signal
import sys
import traceback
import threading
import json

from StringIO import StringIO
from ConfigParser import SafeConfigParser

from reactor.apiclient import ReactorApiClient
from reactor import log

def main_usage():
    print "usage: %s < -h|--help | [options] command >" % sys.argv[0]
    print ""
    print "Optional arguments:"
    print "   -h, --help              Display this help message"
    print ""
    print "   -a, --api=              The API url (default is localhost)."
    print ""
    print "   -p, --password=         The password used to connect to the API."
    print ""
    print "   -z, --zookeeper=        The host:port of a zookeeper instance. Use this option"
    print "                           multiple times to specific multiple instances. Only"
    print "                           necessary for run commands. The default is localhost."
    print ""
    print "   -d, --debug             Enables debugging log and full stack trace errors."
    print ""
    print "   -l, --log=              Log to a file instead of stdout."
    print ""
    print "   -u, --update            Perform an incremental configuration update."
    print ""
    print "Commands:"
    print "    version                Get the server API version."
    print ""
    print "    list                   List all the endpoints currently being managed."
    print ""
    print "    manage <endpoint>      Manage or update a serivce with the given name."
    print "                           The endpoint configuration is read from stdin."
    print "    unmanage <endpoint>    Unmanged the endpoint with the given name."
    print "    show <endpoint>        Show the current configuration for the endpoint."
    print ""
    print "    register <ip>          Register the given IP address."
    print "    drop <ip>              Remove the given IP address."
    print "    ips <endpoint>         Displays all of the confirmed IP addresses."
    print ""
    print "    state <endpoint>       Get the endpoint state."
    print "    start <endpoint>       "
    print "    stop  <endpoint>       Update the endpoint state."
    print "    pause <endpoint>       "
    print ""
    print "    get-metrics <endpoint> Get custom endpoint metrics."
    print "    set-metrics <endpoint> Set custom endpoint metrics. The metrics are read"
    print "                           as JSON { \"name\" : [weight, value] } from stdin."
    print ""
    print "    managers-configured    List all the configured managers."
    print "    managers-active        List all the active managers."
    print ""
    print "    update-manager [ip]    Update the current configuration for the manager."
    print "    show-manager [ip]      Show the current configuration for the manager."
    print "    show-log <uuid>        Show the log for the given manager."
    print "    forget-manager <ip>    Remove and forget the given manager."
    print ""
    print "    passwd [password]      Updates the API's password."
    print "    domain [domain]        Get or set the domain."
    print ""
    print "    runserver [names...]   Run the scale manager server."
    print "    runapi                 Runs the API server."
    print ""

def main():
    api_server = "http://localhost:8080"
    zk_servers = []
    password = None
    debug = False
    logfile = None
    update = False

    opts, args = getopt.getopt(sys.argv[1:],
                                "ha:p:z:dl:u",
                               ["help","api_server=","password=","zookeeper=","debug","log=","update"])

    for o, a in opts:
        if o in ('-h', '--help'):
            main_usage()
            sys.exit(0)
        elif o in ('-a', '--api'):
            api_server = a
        elif o in ('-p', '--password'):
            password = a
        elif o in ('-z', '--zookeeper'):
            zk_servers.append(a)
        elif o in ('-d', '--debug'):
            debug = True
        elif o in ('-l','--log'):
            logfile = a
        elif o in ('-u','--update'):
            update = True
    
    if len(zk_servers) == 0:
        zk_servers = ["localhost"]

    loglevel = logging.INFO
    if debug:
        loglevel = logging.DEBUG

    def get_arg(n):
        if len(args) < n+1:
            main_usage()
            sys.exit(1)
        return args[n]
    def get_args():
        return args[1:]

    command = get_arg(0)
    
    def get_api_client():
        return ReactorApiClient(api_server, password)
    
    try:
        if command == "version":
            api_client = get_api_client()
            print api_client.version()
    
        elif command == "list":
            api_client = get_api_client()
            endpoints = api_client.list_managed_endpoints()
            if endpoints:
                for endpoint in endpoints: 
                    print endpoint
    
        elif command == "manage":
            endpoint_name = get_arg(1)
            new_conf = ""
            for line in sys.stdin.readlines():
                new_conf += line
    
            api_client = get_api_client()
            config = SafeConfigParser()
            if update:
                # Read in the existing configuration and update it with
                # with the new configuration. This allows people to do a
                # partial update.
                endpoint_conf = api_client.get_endpoint_config(endpoint_name)
                config.readfp(StringIO(endpoint_conf))
            config.readfp(StringIO(new_conf))
    
            # Write out the full contents of the updated configuration.
            config_value = StringIO()
            config.write(config_value)
            api_client.manage_endpoint(endpoint_name, config_value.getvalue())
    
        elif command == "unmanage":
            endpoint_name = get_arg(1)
            api_client = get_api_client()
            api_client.unmanage_endpoint(endpoint_name)
    
        elif command == "show":
            endpoint_name = get_arg(1)
            api_client = get_api_client()
            config = api_client.get_endpoint_config(endpoint_name)
            print config.strip()

        elif command == "managers-configured":
            api_client = get_api_client()
            managers = api_client.list_managers_configured()
            for manager in managers:
                print manager
    
        elif command == "managers-active":
            api_client = get_api_client()
            managers = api_client.list_managers_active()
            for (ip, key) in managers.items():
                print ip, key
    
        elif command == "update-manager":
            if len(args) > 1:
                manager = get_arg(1)
            else:
                manager = None
            new_conf = ""
            for line in sys.stdin.readlines():
                new_conf += line
    
            api_client = get_api_client()
            config = SafeConfigParser()
            if update:
                # As per above, allow for incremental updates.
                manager_conf = api_client.get_manager_config(manager)
                config.readfp(StringIO(manager_conf))
            config.readfp(StringIO(new_conf))
    
            # Write out the full contents of the updated configuration.
            config_value = StringIO()
            config.write(config_value)
            api_client.update_manager(manager, config_value.getvalue())
    
        elif command == "show-manager":
            if len(args) > 1:
                manager = get_arg(1)
            else:
                manager = None
    
            api_client = get_api_client()
            config = api_client.get_manager_config(manager)
            print config.strip()

        elif command == "show-log":
            manager = get_arg(1)
            api_client = get_api_client()
            log = api_client.get_manager_log(manager)
            sys.stdout.write(log)

        elif command == "forget-manager":
            manager = get_arg(1)
            api_client = get_api_client()
            api_client.remove_manager_config(manager)
    
        elif command == "ips":
            endpoint_name = get_arg(1)
            api_client = get_api_client()
            ip_addresses = api_client.list_endpoint_ips(endpoint_name)
            for ip in ip_addresses:
                print ip
    
        elif command == "register":
            ip = get_arg(1)
            api_client = get_api_client()
            api_client.register_endpoint_ip(ip)

        elif command == "drop":
            ip = get_arg(1)
            api_client = get_api_client()
            api_client.drop_endpoint_ip(ip)

        elif command == "state":
            api_client = get_api_client()
            endpoint_name = get_arg(1)
            print json.dumps(api_client.get_endpoint_state(endpoint_name))
    
        elif command == "start" or command == "stop" or command == "pause": 
            api_client = get_api_client()
            endpoint_name = get_arg(1)
            api_client.endpoint_action(endpoint_name, command)
    
        elif command == "get-metrics":
            endpoint_name = get_arg(1)
            api_client = get_api_client()
            metrics = api_client.get_endpoint_metrics(endpoint_name)
            print metrics
    
        elif command == "set-metrics":
            new_metrics = ""
            for line in sys.stdin.readlines():
                new_metrics += line
    
            endpoint_name = get_arg(1)
            api_client = get_api_client()
            api_client.set_endpoint_metrics(endpoint_name, json.loads(new_metrics))
    
        elif command == "passwd":
            if len(args) > 1:
                new_password = get_arg(1)
            else:
                new_password = None
    
            api_client = get_api_client()
            api_client.update_api_key(new_password)
    
        elif command == "domain":
            api_client = get_api_client()
            if len(args) > 1:
                domain = get_arg(1)
                api_client.set_domain(domain)
            else:
                print api_client.get_domain()
    
        elif command == "runserver":
    
            from reactor.manager import ScaleManager
    
            log.configure(loglevel, logfile)
            manager = ScaleManager(zk_servers, get_args())
            manager.run()
    
        elif command == "runapi":
    
            from paste.httpserver import serve
            from reactor.api import ReactorApi
    
            log.configure(loglevel, logfile)
            api = ReactorApi(zk_servers)
            serve(api.get_wsgi_app(), host='0.0.0.0')
   
        else:
            main_usage()
            sys.exit(1)
    
    except Exception, e:
        if debug:
            traceback.print_exc()
        else:
            sys.stderr.write("%s\n" %(e))
            sys.exit(1)

def server_usage():
    print "usage: %s < -h|--help | [options] command >" % sys.argv[0]
    print ""
    print "Optional arguments:"
    print "   -h, --help              Display this help message"
    print ""
    print "   -d, --debug             Enables debugging log and full stack trace errors."
    print ""
    print "   -l, --log=              Log to a file instead of stdout."
    print ""

def server():
    debug = False
    logfile = None

    opts, args = getopt.getopt(sys.argv[1:],
                                "hdl:u",
                               ["help","debug","log="])

    for o, a in opts:
        if o in ('-h', '--help'):
            server_usage()
            sys.exit(0)
        elif o in ('-d', '--debug'):
            debug = True
        elif o in ('-l','--log'):
            logfile = a

    from paste.httpserver import serve
    import reactor.server.config as config
    from reactor.server.api import ServerApi

    loglevel = logging.INFO
    if debug:
        loglevel = logging.DEBUG
    log.configure(loglevel, logfile)

    try:
        # Try to read the saved configuration.
        zk_servers = config.read_config()
    except:
        zk_servers = []
    if len(zk_servers) == 0:
        # Otherwise, use localhost.
        zk_servers = ["localhost"]

    # Start the full server app.
    app = ServerApi(zk_servers)
    serve(app.get_wsgi_app(), host='0.0.0.0')
