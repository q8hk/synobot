#-*- coding: utf-8 -*-

from threading import Lock, Timer

from LogManager import log

# Usage :
# variable = ThreadTimer(time_value(second), Handler Function)
# variable.start()
# Stopped timer -> t.cance()
# t = ThreadTimer(3,printer)
#t2 = ThreadTimer(1,printer2)
#t.start()
#t2.start()

class ThreadTimer():
 
    def __init__(self,t,hFunction):
        self.t=t
        self.hFunction = hFunction
        self.thread = None
        self.cancelled = False
        self.lock = Lock()

    def _new_timer(self):
        timer = Timer(self.t, self.handle_function)
        timer.daemon = True
        return timer

    def handle_function(self):
        try:
            self.hFunction()
        except Exception:
            log.exception('ThreadTimer handler failed')
        finally:
            with self.lock:
                if self.cancelled:
                    return
                self.thread = self._new_timer()
                self.thread.start()

    def start(self):
        with self.lock:
            if self.cancelled or (self.thread is not None and self.thread.is_alive()):
                return
            self.thread = self._new_timer()
            self.thread.start()

    def cancel(self):
        with self.lock:
            self.cancelled = True
            if self.thread is not None:
                self.thread.cancel()

