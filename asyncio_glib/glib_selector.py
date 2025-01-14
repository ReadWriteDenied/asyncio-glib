import selectors

from gi.repository import GLib


__all__ = (
    'GLibSelector',
)

class _SelectorSource(GLib.Source):
    """A GLib source that gathers selector """

    def __init__(self, selector):
        super().__init__()
        self._fd_to_tag = {}
        self._fd_to_events = {}
        self._selector = selector

    def prepare(self):
        return False, self._selector._get_timeout_ms()

    def check(self):
        return False

    def dispatch(self, callback, args):
        for (fd, tag) in self._fd_to_tag.items():
            condition = self.query_unix_fd(tag)
            events = self._fd_to_events.setdefault(fd, 0)
            if (
              condition & GLib.IOCondition.IN
              or condition & GLib.IOCondition.HUP
            ):
                events |= selectors.EVENT_READ
            if condition & GLib.IOCondition.OUT:
                events |= selectors.EVENT_WRITE
            self._fd_to_events[fd] = events
        return GLib.SOURCE_CONTINUE

    def register(self, fd, events):
        assert fd not in self._fd_to_tag

        condition = GLib.IOCondition(0)
        if events & selectors.EVENT_READ:
            condition |= GLib.IOCondition.IN
        if events & selectors.EVENT_WRITE:
            condition |= GLib.IOCondition.OUT
        self._fd_to_tag[fd] = self.add_unix_fd(fd, condition)

    def unregister(self, fd):
        tag = self._fd_to_tag.pop(fd)
        self.remove_unix_fd(tag)

    def get_events(self, fd):
        return self._fd_to_events.get(fd, 0)

    def clear(self):
        self._fd_to_events.clear()


class GLibSelector(selectors._BaseSelectorImpl):

    def __init__(self, context):
        super().__init__()
        self._context = context
        self._source = _SelectorSource(self)
        self._source.attach(self._context)
        self._timeout = -1

    def close(self):
        self._source.destroy()
        super().close()

    def register(self, fileobj, events, data=None):
        key = super().register(fileobj, events, data)
        self._source.register(key.fd, events)
        return key

    def unregister(self, fileobj):
        key = super().unregister(fileobj)
        self._source.unregister(key.fd)
        return key

    def _get_timeout_ms(self):
        """Return the timeout for the current select/iteration"""
        return self._timeout

    def select(self, timeout=None):
        # Calling .set_ready_time() always causes a mainloop iteration to finish.
        if timeout is not None:
            # Negative timeout implies an immediate dispatch
            self._timeout = int(max(0, timeout) * 1000)
        else:
            self._timeout = -1

        self._source.clear()
        self._context.iteration(True)

        ready = []
        for key in self.get_map().values():
            events = self._source.get_events(key.fd) & key.events
            if events != 0:
                ready.append((key, events))
        return ready
