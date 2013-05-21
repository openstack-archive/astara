class AbortTask(Exception):
    """ Raised when a task shouldn't be enqueued anymore. """
    pass
