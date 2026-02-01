from runtime.lane_queue import LaneQueue


def test_lane_queue_stub_interface():
    queue = LaneQueue()
    queue.enqueue("lane-a", {"task": "demo"})
    assert queue.run("lane-a") == ["TODO"]
