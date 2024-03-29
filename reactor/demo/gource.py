#!/usr/bin/env python

import os
import sys
import time
import subprocess
import getopt
import threading
import math
import random

from reactor.apiclient import ReactorApiClient

MANAGER_TYPE        = "manager"
ACTIVE_TYPE         = "active"
INACTIVE_TYPE       = "inactive"
DECOMMISSIONED_TYPE = "decommissioned"
COLOR_MAP = { \
    MANAGER_TYPE        : "FF0000",
    ACTIVE_TYPE         : "00FF00",
    INACTIVE_TYPE       : "00FF00",
    DECOMMISSIONED_TYPE : "008800",
    }

def query_state(client):
    # Just grab the list of managers.
    managers = client.list_managers_active()
    users = 0

    # Build a map of endpoint states.
    endpoints = {}
    endpoint_list = client.list_managed_endpoints()
    for endpoint in endpoint_list:
        if endpoint == "api":
            continue

        ip_map = {}
        ips = client.list_endpoint_ips(endpoint)
        try:
            info = client.get_endpoint_info(endpoint)
            active = info["active"]
            metrics = info["metrics"]
        except:
            active = []
            metrics = { }

        try:
            # Compute the number of "users" this endpoint will have.
            users = int(math.ceil(float(metrics["active"]) * len(active) / factor))
        except:
            users = 0

        for ip in ips:
            if ip in active:
                ip_map[ip] = ACTIVE_TYPE
            else:
                ip_map[ip] = INACTIVE_TYPE

        for ip in active:
            if not(ip in ips):
                ip_map[ip] = DECOMMISSIONED_TYPE

        # Save the final ip_list.
        endpoints[endpoint] = ip_map

    return managers, endpoints, users

# Global cached state.
managers_cache = []
endpoints_cache = {}

def make_name(endpoint, name):
    if endpoint:
        return "%s/%s" % (endpoint, name)
    else:
        return "%s" % name

def add_entry(output, endpoint, name, node_type):
    output.write("%d|reactor|A|%s|%s\n" % \
        (0, make_name(endpoint, name), COLOR_MAP[node_type]))
    output.flush()

def delete_entry(output, endpoint, name, node_type):
    output.write("%d|reactor|D|%s|%s\n" % \
        (0, make_name(endpoint, name), COLOR_MAP[node_type]))
    output.flush()

def change_entry(output, endpoint, name, node_type):
    output.write("%d|reactor|M|%s|%s\n" % \
        (0, make_name(endpoint, name), COLOR_MAP[node_type]))
    output.flush()

def active_entry(output, endpoint, name, node_type, user_number):
    output.write("%d|%s%d|M|%s|%s\n" % \
        (0, endpoint, user_number, make_name(endpoint, name), COLOR_MAP[node_type]))
    output.flush()

def generate_log(output, managers, endpoints, users):
    global managers_cache
    global endpoints_cache
    active = []

    for manager in managers:
        if not(manager in managers_cache):
            add_entry(output, None, manager, MANAGER_TYPE)

    for manager in managers_cache:
        if not(manager in managers):
            delete_entry(output, None, manager, MANAGER_TYPE)

    for endpoint in endpoints:
        if not(endpoint in endpoints_cache):
            curr = endpoints[endpoint]
            for ip in curr:
                add_entry(output, endpoint, ip, curr[ip])

        else:
            curr = endpoints[endpoint]
            cache = endpoints_cache[endpoint]

            for ip in curr:
                if not(ip in cache):
                    add_entry(output, endpoint, ip, curr[ip])
                elif cache[ip] != curr[ip]:
                    change_entry(output, endpoint, ip, curr[ip])

            for ip in cache:
                if not(ip in curr):
                    delete_entry(output, endpoint, ip, cache[ip])

            # We can't really change nodes in the middle of the visualization,
            # so instead we just do a modification to all the active nodes.
            for ip in curr:
                if curr[ip] != INACTIVE_TYPE:
                    active.append(ip)

    if len(active) > 0 and users > 0:
        current = random.randint(0, len(active) - 1)
        for user in range(0, users):
            ip = active[current % len(active)]
            active_entry(output, endpoint, ip, curr[ip], user)
            current += 1

    for endpoint in endpoints_cache:
        if not(endpoint in endpoints):
            cache = endpoints_cache[endpoint]
            for ip in cache:
                delete_entry(output, endpoint, ip, cache[ip])

    # Save the new state as our cache.
    managers_cache = managers
    endpoints_cache = endpoints

def usage():
    print "usage: reactor-demo < -h|--help | [options] command >"
    print "This tool requires 'gource' to be installed."
    print ""
    print "Optional arguments:"
    print "   -h, --help             Display this help message"
    print ""
    print "   -a, --api=             The API url (default is %s)." % api_server
    print ""
    print "   -p, --password=        The password used to connect to the API."
    print ""
    print "   -d, --dryrun           Just print the log."
    print ""
    print "   -f, --factor=          The active scaling factor."
    print ""
    print "   -i, --interval=        The update interval (in seconds)."
    print ""

def main():
    api_server = "http://localhost:8080"
    password = None
    dryrun = False
    interval = 1.0
    factor = 10.0

    opts, args = getopt.getopt(sys.argv[1:], 
            "ha:p:df:i:", ["help","api_server=","password=","dryrun","factor=","interval="])

    for o, a in opts:
        if o in ('-h', '--help'):
            usage()
            sys.exit(0)
        elif o in ('-a', '--api'):
            api_server = a
        elif o in ('-p', '--password'):
            password = a
        elif o in ('-d', '--dryrun'):
            dryrun = True
        elif o in ('-f', '--factor'):
            factor = float(a)
        elif o in ('-i', '--interval'):
            interval = float(a)

    if dryrun:
        # Open stdout.
        output = sys.stdout
    else:
        # Open our gource process.
        gource = subprocess.Popen(\
            ["gource", "-w", "--realtime", 
             "--log-format", "custom", 
             "--user-scale", "0.5",
             "--max-user-speed", "20",
             "--hide", "date",
             "--user-image-dir", os.path.dirname(__file__),
             "--highlight-dirs",
             "--font-size", "14",
             "--file-idle-time", "0",
             "-"], 
            stdin=subprocess.PIPE)
        output = gource.stdin

    # Connect to the API.
    client = ReactorApiClient(api_server, password)

    def update():
        while True:
            # Query state.
            managers, endpoints, users = query_state(client)

            # Generate differential log.
            generate_log(output, managers, endpoints, users)

            # Wait.
            time.sleep(interval)

    if dryrun:
        update()
    else:
        update_thread = threading.Thread(target=update)
        update_thread.daemon = True
        update_thread.start()
        gource.wait()
