from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor


class TaskScheduler(ABC):
    @abstractmethod
    def submit(self, function, *args): ...

    @abstractmethod
    def close(self): ...


class ThreadTaskScheduler(TaskScheduler):
    def __init__(self, max_workers: int = 1, thread_prefix: str = "nodekit"):
        self.pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix=thread_prefix)

    def submit(self, function, *args):
        return self.pool.submit(function, *args)

    def close(self):
        self.pool.shutdown(wait=True)
