from pathlib import Path
from unittest.mock import Mock

from local_agent import RouteMap
from manual_route_demo import ManualRouteDemo


MAP = Path(__file__).resolve().parents[1] / 'map_graph.json'


def test_operator_confirmation_reroutes_without_changing_sensor_map():
    sensor_map = RouteMap.from_file(MAP)
    voice = Mock()
    demo = ManualRouteDemo(RouteMap.from_file(MAP), voice)
    assert demo.route == ('B', 'C', 'D')
    assert demo.confirm_blocked()
    assert demo.route == ('B', 'E', 'F', 'D')
    assert sensor_map.route('B', 'D') == ('B', 'C', 'D')
    assert demo.last_event['source'] == 'operator_confirmation'
    assert demo.last_event['camera_verified_blockage'] is False
    assert demo.last_event['sent_to_cloud'] is False
    message = voice.speak.call_args.args[0]
    assert 'B, E, F, D' in message
    assert 'Remain stopped' in message
    assert not demo.confirm_blocked()
    voice.speak.assert_called_once()


def test_no_alternative_produces_stop_without_direction():
    graph = RouteMap.from_file(MAP)
    graph.block('B', 'E')
    voice = Mock()
    demo = ManualRouteDemo(graph, voice)
    demo.confirm_blocked()
    assert demo.route == ()
    assert 'No alternative route' in voice.speak.call_args.args[0]


def test_replay_requires_confirmation_and_keeps_route_unchanged():
    voice = Mock()
    demo = ManualRouteDemo(RouteMap.from_file(MAP), voice)
    assert not demo.repeat_announcement()
    voice.speak.assert_not_called()
    demo.confirm_blocked()
    assert demo.repeat_announcement()
    assert demo.route == ('B', 'E', 'F', 'D')
    assert voice.speak.call_count == 2
