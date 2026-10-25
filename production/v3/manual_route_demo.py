"""Operator-confirmed graph rerouting, separate from camera evidence and AWS."""

from local_agent import RouteMap


class ManualRouteDemo:
    def __init__(self, route_map: RouteMap, voice):
        if frozenset(('B', 'C')) not in route_map.edges:
            raise ValueError('Manual demo requires a B-C map edge')
        self.map = route_map
        self.voice = voice
        self.route = route_map.route('B', 'D')
        self.confirmed = False
        self.last_event = None
        self.announcement = None

    def confirm_blocked(self):
        if self.confirmed:
            return False
        self.map.block('B', 'C')
        self.route = self.map.route('B', 'D')
        self.confirmed = True
        self.last_event = {
            'source': 'operator_confirmation',
            'mode': 'manual_route_demo',
            'assigned_junction': 'B',
            'blocked_edge': ['B', 'C'],
            'proposed_route': list(self.route),
            'camera_verified_blockage': False,
            'alternative_path_verified_clear': False,
            'sent_to_cloud': False,
        }
        if self.route:
            message = ('Manual demo. Route B to C confirmed blocked. '
                       'Proposed alternative route: ' + ', '.join(self.route) +
                       '. Remain stopped; the path is not verified clear.')
        else:
            message = 'Manual demo. Route blocked. No alternative route. Please remain stopped.'
        self.announcement = message
        self.repeat_announcement()
        return True

    def repeat_announcement(self):
        if self.announcement is None:
            return False
        self.voice.speak(self.announcement, force=True, priority=True)
        return True
