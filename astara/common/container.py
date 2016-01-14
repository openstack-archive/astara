
import collections
import threading

class ResourceContainer(object):

    def __init__(self):
        self.resources = {}
        self.deleted = collections.deque(maxlen=50)
        self.lock = threading.Lock()

    def __delitem__(self, item):
        with self.lock:
            del self.resources[item]
            self.deleted.append(item)

    def items(self):
        """Get all state machines.
        :returns: all state machines in this RouterContainer
        """
        with self.lock:
            return list(self.resources.items())

    def values(self):
        with self.lock:
            return list(self.resources.values())

    def has_been_deleted(self, resource_id):
        """Check if a resource has been deleted.

        :param resource_id: The resource's id to check against the deleted list
        :returns: Returns True if the resource_id has been deleted.
        """
        with self.lock:
            return resource_id in self.deleted

    def __getitem__(self, item):
        with self.lock:
            return self.resources[item]

    def __setitem__(self, key, value):
        with self.lock:
            self.resources[key] = value

    def __contains__(self, item):
        with self.lock:
            return item in self.resources

    def __bool__(self):
        if self.values():
            return True
        else:
            return False

    def __nonzero__(self):
        return self.__bool__()
