from worker.queue import TaskQueue


def run() -> None:
    queue = TaskQueue()
    queue.start()


if __name__ == "__main__":
    run()
