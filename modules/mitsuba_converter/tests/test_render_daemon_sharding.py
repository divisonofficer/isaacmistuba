from mitsuba_converter.render_daemon import _interleaved_gpu_shard_assignments


def test_interleaved_gpu_shard_assignments_feed_all_gpus_from_start():
    assignments = _interleaved_gpu_shard_assignments(10, [0, 1, 2, 3])

    assert [item["target_gpu_index"] for item in assignments] == [
        0, 1, 2, 3, 0, 1, 2, 3, 0, 1
    ]
    assert [item["shard_index"] for item in assignments] == [
        0, 1, 2, 3, 0, 1, 2, 3, 0, 1
    ]
    assert [item["shard_item_index"] for item in assignments] == [
        0, 0, 0, 0, 1, 1, 1, 1, 2, 2
    ]
    assert [item["shard_size"] for item in assignments] == [
        3, 3, 2, 2, 3, 3, 2, 2, 3, 3
    ]


def test_interleaved_gpu_shard_assignments_limit_gpus_to_item_count():
    assignments = _interleaved_gpu_shard_assignments(2, [0, 1, 2, 3])

    assert [item["target_gpu_index"] for item in assignments] == [0, 1]
    assert [item["shard_count"] for item in assignments] == [2, 2]
    assert [item["shard_size"] for item in assignments] == [1, 1]
