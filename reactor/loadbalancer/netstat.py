"""
Simple parser to extract active connections via netstat.
"""

import subprocess

def connections():
    active = []

    netstat = subprocess.Popen(["netstat", "-tn"], stdout=subprocess.PIPE)
    (stdout, stderr) = netstat.communicate()

    lines = stdout.split("\n")

    if len(lines) < 2:
        return []

    lines = lines[2:]
    for line in lines:
        try:
            (proto, recvq, sendq, local, foreign, state) = line.split()
            (host, port) = foreign.split(":")
            active.append((host, int(port)))
        except:
            pass

    return active

def connection_count():
    active_count = {}
    active = connections()

    for (host, port) in active:
        try:
            active_count[(host, port)] = \
                active_count.get((host, port), 0) + 1
        except:
            pass

    return active_count
