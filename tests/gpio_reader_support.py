"""Control scheduling while retaining the real GPIO reader constructor."""


class DeferredReaderThread:
    def __init__(self, **kwargs):
        self.target = kwargs['target']

    def start(self):
        # Tests invoke the reader explicitly after installing an IO fault.
        pass

    def join(self, **kwargs):
        pass

    def is_alive(self):
        return False
