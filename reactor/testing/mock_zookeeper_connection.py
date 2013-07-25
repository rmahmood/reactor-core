import os
import sys
import logging
from Queue import Queue
from threading import Thread, Lock, Condition
from collections import OrderedDict

class MockZookeeperConnection(object):
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

    class ZkWatchWorker(Thread):
        """
        Worker thread for execting zookeeper watch callbacks. We do this to
        maintain the threading model provided by the real zookeeper, where all
        callbacks run in a threadpool.
        """
        def __init__(self, queue):
            super(MockZookeeperConnection.ZkWatchWorker, self).__init__()
            self.queue = queue
            self.running = False

        def run(self):
            self.running = True
            while self.running:
                callbacks, value, reason = self.queue.get()
                for callback in callbacks:
                    try:
                        callback(value)
                    except:
                        logging.exception("Error executing watch for mock zk.")
                self.queue.task_done()

        def join(self):
            self.running = False
            super(MockZookeeperConnection.ZkWatchWorker, self).join()

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
            self.ephemeral = False
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

        def add_child(self, child):
            child.parent = self
            # Don't just blindly overwrite existing child nodes. Higher level
            # create function shouldn't be attempting to create nodes that
            # already exist.
            assert not self.children.has_key(child.name)
            self.children[child.name] = child

            # Notify watchers.
            self.handle._queue_notifications(
                self.children_callbacks,
                self.children.keys(),
                "Node %s created" % child.abspath())

            # self.handle._queue_notifications(
            #     self.children_callbacks,
            #     "Node %s created" % child.abspath(),
            #     self.handle, MockZookeeper.ZOO_EVENT_NODE_CHILDREN_CHANGED, 0,
            #     self.abspath())

            return child

        def set_data(self, data):
            self.data = data

            # Notify watchers.
            self.handle._queue_notifications(
                self.data_callbacks,
                self.data,
                "Node %s data set to %s" % (self.abspath(), self.data))

            # self.handle._queue_notifications(
            #     self.data_callbacks,
            #     "Node %s data set to %s" % (self.abspath(), self.data),
            #     self.handle, MockZookeeper.ZOO_EVENT_NODE_DATA_CHANGED, 0,
            #     self.abspath())

        def delete(self):
            del self.parent.children[self.name]

            # Notify watchers.
            self.handle._queue_notifications(
                self.parent.children_callbacks,
                self.parent.children.keys(),
                "Node %s deleted" % self.abspath())

            # self.handle._queue_notifications(
            #     self.parent.children_callbacks,
            #     "Node %s deleted" % self.abspath(),
            #     self.handle, MockZookeeper.ZOO_EVENT_NODE_CHILDREN_CHANGED, 0,
            #     self.parent.abspath())

        def __repr__(self):
            return "<ZKNode '%s'>" % self.abspath()

    def __init__(self, servers, acl="Don't care"):
        self.lock = Lock()
        self.clients = 0
        self.root = MockZookeeperConnection.ZkNode("", self)
        self.servers = set(servers)

        self.notifications = Queue()
        self.worker_pool = []
        for i in xrange(0, workers):
            worker = MockZookeeperConnection.ZkWatchWorker(self.notifications)
            worker.daemon = True
            worker.start()

    def _queue_notifications(self, callbacks, value, reason):
        # Our parent external zookeeper function is already holding a lock which
        # prevents interleaving of callbacks from multiple operations. Also
        # don't both queuing a task if there are 0 callbacks on the list.
        if len(callbacks) > 0:
            self.notifications.put((callbacks, value, reason))

    def _touch_path(self, path):
        """
        Ensures all components of the given path exists.
        """
        cursor = self.root
        new = False
        for comp in path.split("/")[1:]:
            if not cursor.children.has_key(comp):
                cursor.add_child(MockZookeeperConnection.ZkNode(comp, self))
                new = True
            cursor = cursor.children[comp]
        return cursor, new

    def _find_node(self, path):
        path_so_far = "/"
        cursor = self.root
        for comp in path.split("/")[1:]:
            try:
                cursor = cursor.children[comp]
            except:
                raise KeyError("Node '%s' not found" % "/".join([path_so_far, comp]))
            path_so_far += cursor.name
        # We got to the end, so we must've found our node.
        return cursor

    def silence(self):
        pass

    def write(self, path, contents, ephemeral=False, exclusive=False):
        with self.lock:
            # Ensure all components leading upto the leaf node in the path exists.
            parent, _ = self._touch_path(os.path.dirname(path))
            leaf_name = os.path.basename(path)

            if parent.children.has_key(leaf_name):
                # Node exists and exclusive, write should fail.
                if exclusive:
                    return False
                leaf = parent.children[leaf_name]
                leaf.set_data(contents)
                return True
            else:
                leaf = MockZookeeperConnection(leaf_name, self)
                leaf.data = contents
                leaf.ephemeral = ephemeral
                parent.add_child(leaf)
                return True

    def read(self, path, default=None):
        with self.lock:
            try:
                return self._find_node(self, path).data
            except:
                return default

    def list_children(self, path):
        with self.lock:
            try:
                return self._find_node(self, path).children.keys()
            except:
                return None

    def delete(self, path):
        with self.lock:
            try:
                return self._find_node(self, path).delete()
            except:
                pass

    def trylock(self, path, default_value=""):
        return self.write(path, default_value, ephemeral=True, exclusive=True)

    def _watch_node(self, callback_list_accessor, value_accessor, path, fn, default_value="", clean=False):
        with self.lock:
            # Make sure the path exists.
            node, new = self._touch_path(path)
            if new:
                node.set_data(default_value)

            callback_list = callback_list_accessor(node)
            if fn not in callback_lsit:
                callback_list.append(fn)

            return value_accessor(node)

    def watch_contents(self, path, fn, default_value="", clean=False):
        return self._watch_node(lambda n: n.data_callbacks,
                                lambda n: n.data,
                                path, fn, default_value, clean)

    def watch_children(self, path, fn, default_value, clean=False):
        return self._watch_node(lambda n: n.children_callbacks,
                                lambda n: n.children.keys(),
                                path, fn, default_value, clean)

    def clear_watch_path(self, path):
        with self.lock:
            # Not one should be attempting to clear watches they
            # haven't set. Let it fault if anyone attempts to do so.
            node = self._find_node(path)
            node.data_callbacks = []
            node.children_callbacks = []

    def clear_watch_fn(self, fn):
        def clear(node, func):
            if func in node.data_callbacks:
                node.data_callbacks.remove(func)
            if func in node.children_callbacks:
                node.children_callbacks.remove(func)
            for child in node.children.values():
                recurse(child, func)

        with self.lock:
            clear(self.root, fn)
