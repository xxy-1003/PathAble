import pytest
from unittest.mock import Mock
from pathlib import Path

from camera_region_demo import ChairRegionMonitor
from vision import Obstacle, VisionResult
from manual_route_demo import ManualRouteDemo
from local_agent import RouteMap


def result(box=(235, 210, 450, 440), name='chair', score=.85):
    return VisionResult((Obstacle(name, score, box, None, (0, .2, 0)),), (0, .2, 0), 0)


def test_sustained_chair_overlap_proposes_route_without_physical_verification():
    monitor = ChairRegionMonitor()
    for t in [0, .2, .4, .6, .8]:
        assert not monitor.update(result(), t, (640, 480))['trigger']
    evidence = monitor.update(result(), 1., (640, 480))
    assert evidence['trigger']
    voice = Mock()
    demo = ManualRouteDemo(RouteMap.from_file(Path(__file__).resolve().parents[1] / 'map_graph.json'), voice)
    demo.propose_from_camera(evidence)
    assert demo.route == ('B', 'E', 'F', 'D')
    assert demo.last_event['source'] == 'camera_region_demo'
    assert not demo.last_event['camera_verified_blockage']
    assert 'Camera demo' in voice.speak.call_args.args[0]
    assert not demo.propose_from_camera(evidence)
    voice.speak.assert_called_once()


@pytest.mark.parametrize('detections', [None, VisionResult((), (0, 0, 0), 0),
    result(box=(0, 0, 80, 80)), result(name='person'), result(score=.59)])
def test_non_qualifying_detections_never_trigger(detections):
    monitor = ChairRegionMonitor()
    for i in range(20):
        assert not monitor.update(detections, i * .2, (640, 480))['trigger']


def test_short_burst_and_stale_observations_do_not_trigger():
    monitor = ChairRegionMonitor()
    for i in range(10):
        assert not monitor.update(result(), i * .01, (640, 480))['trigger']
    assert not monitor.update(result(), 3., (640, 480))['trigger']


def test_intermittent_chair_needs_eighty_percent_positive_evidence():
    monitor = ChairRegionMonitor()
    for i in range(20):
        assert not monitor.update(result() if i % 2 else None, i * .1, (640, 480))['trigger']


def test_invalid_region_and_time_are_rejected():
    with pytest.raises(ValueError):
        ChairRegionMonitor((0, 0, 2, 1))
    monitor = ChairRegionMonitor()
    monitor.update(None, 1., (640, 480))
    with pytest.raises(ValueError):
        monitor.update(result(), 0., (640, 480))


def test_table_trigger_keeps_actual_class_in_saved_aws_report(tmp_path):
    from aws_device_client import AwsDeviceClient

    monitor = ChairRegionMonitor()
    for i in range(6):
        evidence = monitor.update(result(name='dining table'), i * .2, (640, 480))
    assert evidence['trigger'] and evidence['transition'] == 'detected'
    client = AwsDeviceClient(api_base_url='https://example.invalid', outbox_dir=tmp_path)
    record = client.on_chair_overlap_trigger(evidence, b'test-frame')
    assert record.obstacle_class == 'dining table'
    client._http_request = Mock(return_value=(201, {
        'report_id': record.report_id, 'camera_id': record.camera_id,
        'photo_id': record.photo_id, 'status': 'PENDING'}))
    client._submit_report(record)
    payload = client._http_request.call_args.args[2]
    assert payload['obstacle_class'] == 'dining table'
    assert payload['distance_m'] is None and payload['clearance_m'] is None


def test_stable_absence_and_redetection_announce_updates_without_clearance():
    monitor = ChairRegionMonitor()
    for i in range(6):
        evidence = monitor.update(result(), i * .2, (640, 480))
    voice = Mock()
    demo = ManualRouteDemo(RouteMap.from_file(Path(__file__).resolve().parents[1] / 'map_graph.json'), voice)
    demo.propose_from_camera(evidence)
    assert monitor.update(None, 1.2, (640, 480))['transition'] is None
    absent = monitor.update(None, 2.3, (640, 480))
    assert absent['transition'] == 'not_detected'
    assert demo.announce_camera_update(absent)
    assert 'does not verify that the path is clear' in voice.speak.call_args.args[0]
    assert monitor.update(None, 2.4, (640, 480))['transition'] is None
    for i in range(11):
        detected = monitor.update(result(), 3. + i * .2, (640, 480))
        if detected['transition']:
            assert demo.announce_camera_update(detected)
    assert 'detected again' in voice.speak.call_args.args[0]
    assert demo.route == ('B', 'E', 'F', 'D')
