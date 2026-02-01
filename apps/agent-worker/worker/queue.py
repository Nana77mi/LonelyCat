from worker.executor import TaskExecutor


class TaskQueue:
    def __init__(self) -> None:
        self.executor = TaskExecutor()

    def start(self) -> None:
        # TODO: connect to queue backend
        self.executor.execute("TODO")
