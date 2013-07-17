import sys
import logging
from Queue import Queue
from threading import Thread, Lock, Condition
from collections import OrderedDict

MOCK_ZK_OBJECT = None

class ZkNotFoundType(type):
    def __getattr__(self, key):
        raise Exception("Zookeeper not installed")

class ZkNotFound(object):
    __metaclass__ = ZkNotFoundType # Raise exception on static getattr.
    def __getattr__(self, key):
        if key == "ZooKeeperException":
            return Exception
        raise Exception("Zookeeper not installed")

# Manually load the python-zookeeper library. We need to resort to doing this to
# avoid having the reactor zookeeper module load instead, since we just added
# the entire reactor tree to the modules path. Note that we may not end up using
# the real zookeeper if a test requests a mock zookeeper during the session.
import imp
try:
    zookeeper = imp.load_dynamic("zookeeper",
        "/usr/lib/python2.7/dist-packages/zookeeper.so")
except:
    # Zookeeper probably not installed on the machine.
    zookeeper = ZkNotFound

    # Prevent reactor.zookeeper.connection from immediately exploding on the
    # zookeeper import. If we only run tests which use the mock zookeeper,
    # reactor will never attempt to touch the real zookeeper other the initial
    # import, so this should fool reactor into initially thinking zookeeper is
    # installed until we can do our shimming.
    sys.modules["zookeeper"] = ZkNotFound()

class MockZookeeper(object):
    """
    Mock Zookeeper Implementation. This implemenetation is very limited compared
    to the real zookeeper. No data is persistent and we only implement the
    methods and flags reactor requires. To install this mock, call
    use_mock() prior to running any test functions.

    The real zookeeper object tracks sessions via an opaque handle rather than
    as a python object. However, the call signature of all zookeeper functions
    conveniently take the handle as the first argument. This lets us trivially
    substitute the handle for a reference the the mock zookeeper object to
    trivially track sessions without doing extra work to map between sessions
    and mock zookeeper objects.
    """

    # States.
    CONNECTED_STATE = 3

    # Return Values.
    OK = 0
    NONODE = -101

    # Flags.
    EPHEMERAL = 1

    # Events.
    ZOO_EVENT_NONE = 0
    ZOO_EVENT_NODE_CREATED = 1
    ZOO_EVENT_NODE_DELETED = 2
    ZOO_EVENT_NODE_DATA_CHANGED = 3
    ZOO_EVENT_NODE_CHILDREN_CHANGED = 4

    # Log level.
    LOG_LEVEL_ERROR = 0

    class NoNodeException(Exception):
        pass

    class NodeExistsException(Exception):
        pass

    class ZookeeperException(Exception):
        pass

    class ZkWatchWorker(Thread):
        """
        Worker thread for execting zookeeper watch callbacks. We do this to
        maintain the threading model provided by the real zookeeper, where all
        callbacks run in a threadpool.
        """
        def __init__(self, queue):
            super(MockZookeeper.ZkWatchWorker, self).__init__()
            self.queue = queue
            self.running = False

        def run(self):
            self.running = True
            while self.running:
                task = self.queue.get()
                task[0](*task[2])
                self.queue.task_done()

        def join(self):
            self.running = False
            super(MockZookeeper.ZkWatchWorker, self).join()

    class ZkNode(object):
        """
        Represents a single zookeeper node.

        All operations on a node object must be locked by the caller in a
        multithreaded environment.
        """
        def __init__(self, name, handle):
            self.parent = None
            self.name = name
            self.children = OrderedDict()
            self.data = ""
            self.flags = 0
            self.handle = handle
            self.data_callbacks = [] # Called when the data changes.
            self.children_callbacks = [] # Called when a node child is added or deleted.

        def dump(self, depth=0):
            print "".join([" " * depth * 2, (self.name or "/") + ": ", "'" + self.data + "'"])
            for child in self.children.values():
                child.dump(depth + 1)

        def abspath(self, inner=False):
            if self.parent is None:
                res = ""
            else:
                res = "/".join([self.parent.abspath(inner=True), self.name])
            if not inner and len(res) == 0:
                res = "/"
            return res

        def add_child(self, child_name):
            child = MockZookeeper.ZkNode(child_name, self.handle)
            child.parent = self
            # Don't just blindly overwrite existing child nodes. Higher level
            # create function shouldn't be attempting to create nodes that
            # already exist.
            assert not self.children.has_key(child.name)
            self.children[child.name] = child

            # Notify watchers.
            self.handle._queue_notifications(
                self.children_callbacks,
                "Node %s created" % child.abspath(),
                self.handle, MockZookeeper.ZOO_EVENT_NODE_CHILDREN_CHANGED, 0,
                self.abspath())

            return child

        def set_data(self, data):
            self.data = data

            # Notify watchers.
            self.handle._queue_notifications(
                self.data_callbacks,
                "Node %s data set to %s" % (self.abspath(), self.data),
                self.handle, MockZookeeper.ZOO_EVENT_NODE_DATA_CHANGED, 0,
                self.abspath())

        def delete(self):
            del self.parent.children[self.name]

            # Notify watchers.
            self.handle._queue_notifications(
                self.parent.children_callbacks,
                "Node %s deleted" % self.abspath(),
                self.handle, MockZookeeper.ZOO_EVENT_NODE_CHILDREN_CHANGED, 0,
                self.parent.abspath())

        def __repr__(self):
            return "<ZKNode '%s'>" % self.abspath()

    def __init__(self, servers, workers=2):
        self.lock = Lock()
        self.clients = 0
        self.root = MockZookeeper.ZkNode("", self)
        self.servers = set(servers)

        self.notifications = Queue()
        self.worker_pool = []
        for i in xrange(0, workers):
            worker = MockZookeeper.ZkWatchWorker(self.notifications)
            worker.daemon = True
            worker.start()

    def _connect(self, servers):
        self.servers.union(set(servers))

    def _queue_notifications(self, callbacks, reason, *args):
        # Our parent external zookeeper function is already holding a lock which
        # prevents interleaving of callbacks from multiple operations.
        for callback in callbacks:
            self.notifications.put((callback, reason, args))

    def _find_node(self, path):
        path_so_far = "/"
        cursor = self.root
        for comp in path.split("/")[1:]:
            try:
                cursor = cursor.children[comp]
            except:
                raise MockZookeeper.NoNodeException()
            path_so_far += cursor.name
        # We got to the end, so we must've found our node.
        return cursor

    @staticmethod
    def set_debug_level(level):
        pass

    @staticmethod
    def init(servers, callback, timeout):
        """ Returns the harness mock zookeeper singleton. """
        global MOCK_ZK_OBJECT
        if MOCK_ZK_OBJECT is None:
            logging.debug(
                "MOCK_ZK: First connection to mock zookeeper, initializing.")
            MOCK_ZK_OBJECT = MockZookeeper(servers)
        else:
            logging.debug("MOCK_ZK: New connection to mock zookeeper.")
            MOCK_ZK_OBJECT._connect(servers)
        # The callback must run in a different thread to avoid a deadlock.
        Thread(target=callback,
            args=(MOCK_ZK_OBJECT, -1, MockZookeeper.CONNECTED_STATE, "")).start()
        return MOCK_ZK_OBJECT

    def close(self):
        with self.lock:
            self.clients -= 1

    def exists(self, path):
        with self.lock:
            try:
                self._find_node(path)
                return True
            except:
                return False

    def create(self, path, data, acl, flags):
        comps = path.split("/")
        base = "/".join(comps[:-1])
        child_name = comps[-1]
        with self.lock:
            parent = self._find_node(base)
            if parent.children.has_key(child_name):
                raise MockZookeeper.NodeExistsException()
            child = parent.add_child(child_name)
            child.data = data
            child.flags = flags
            return path

    def delete(self, path):
        with self.lock:
            self._find_node(path).delete()

    def set(self, path, data):
        with self.lock:
            self._find_node(path).set_data(data)

    def get_children(self, path, callback=None):
        with self.lock:
            try:
                parent = self._find_node(path)
                if (callback is not None) and \
                        (callback not in parent.children_callbacks):
                    parent.children_callbacks.append(callback)
                return parent.children.keys()
            except MockZookeeper.NoNodeException:
                return None

    def get(self, path, callback=None):
        with self.lock:
            node = self._find_node(path)
            if (callback is not None) and (callback not in node.data_callbacks):
                node.data_callbacks.append(callback)
            return node.data, None

from reactor.zookeeper import connection
def use_mock():
    """
    Replaces the real zookeeper bindings with MockZookeeper. For this to be
    effective, this must be called before any reactor objects (such as managers)
    are instantiated.
    """
    connection.zookeeper = MockZookeeper

def use_real():
    """
    Uses a real zookeeper instance (replacing and destroying any mock zookeeper
    objects in the process.
    """
    MOCK_ZK_OBJECT = None
    connection.zookeeper = zookeeper

# Use the mock zookeeper implementation by default. Tests that want the real
# zookeeper can enable it for their module.
use_mock()

class ZkEvent(object):
    """
    A context object for waiting for a particular zookeeper watch to be
    triggered. This is useful for synchronizing bits of tests which rely on
    reactor having received particular zookeeper notifications prior to
    asserting reactor state.

    This mechanism works by appending a private callback to the zookeeper watch
    callbacks list for the specified path. When this callback is called, we can
    be sure that reactor has already executed all it's callbacks since the
    appear earlier in the callback list. We avoid a race between us installing
    the special callback and some other reactor code installing a callback after
    ours by replacing the callback list with a special object which is guranteed
    to always return our callback last for the scope of the context.
    """

    class ConstLastList(list):
        """
        A subclass of list which always returns a special 'last' element during
        iteration. Behaves identically to a pure python list otherwise.
        """
        def __init__(self, original, last):
            super(ZkEvent.ConstLastList, self).__init__()
            self.last = last
            self.extend(original)

        def __iter__(self):
            l = self[:] # Copy self.
            l.append(self.last)
            return l.__iter__()

        def unbox(self):
            """
            Return our contents as a pure list. We need to first make a copy to
            avoid the list constructor from picking up our __iter__ method and
            including the const last element in the new list.
            """
            return list(self[:])

    def __init__(self, zk_conn, path, expt_value=None):
        self.zk_conn = zk_conn
        self.path = path
        self.cond = Condition()
        self.result = None
        self.expt_value = expt_value

    def __call__(self, result):
        self.cond.acquire()
        try:
            if self.expt_value is not None:
                if isinstance(self.expt_value, list):
                    match = sorted(result) == sorted(self.expt_value)
                else:
                    match = result == expt_value

                if not match:
                    logging.warning(
                        "Got zk event with result %s, didn't match expt result %s." % \
                            (str(result), str(self.expt_value)))
                    return
            self.result = result
            self.cond.notifyAll()
        finally:
            self.cond.release()

    def __enter__(self):
        # Since we're running a test where we expect a particular zookeeper
        # event, there must be some reactor callback registered for the path.
        self.zk_conn.watches[self.path] = \
            ZkEvent.ConstLastList(self.zk_conn.watches[self.path], self)
        return self

    def __exit__(self, *args):
        self.wait()
        self.zk_conn.watches[self.path] = \
            self.zk_conn.watches[self.path].unbox()

    def wait(self):
        self.cond.acquire()
        logging.debug("Waiting for zk event on path '%s'." % self.path)
        while self.result is None:
            self.cond.wait()
        logging.debug("Observed zk event on path '%s'." % self.path)
        self.cond.release()
