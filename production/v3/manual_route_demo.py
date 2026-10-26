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
        return self._propose('operator_confirmation')

    def propose_from_camera(self, evidence):
        return self._propose('camera_region_demo', evidence)

    def _propose(self, source, evidence=None):
        if self.confirmed:
            return False
        self.map.block('B', 'C')
        self.route = self.map.route('B', 'D')
        self.confirmed = True
        self.last_event = {
            'source': source,
            'mode': 'manual_route_demo' if source == 'operator_confirmation' else 'camera_region_demo',
            'assigned_junction': 'B',
            'blocked_edge': ['B', 'C'],
            'proposed_route': list(self.route),
            'camera_verified_blockage': False,
            'alternative_path_verified_clear': False,
            'sent_to_cloud': False,
        }
        if evidence is not None:
            self.last_event['demo_detection_evidence'] = evidence
        prefix = ('Manual demo. Route B to C confirmed blocked. '
                  if source == 'operator_confirmation' else
                  'Camera demo. A chair repeatedly overlaps the monitored B to C area. ')
        if self.route:
            message = (prefix +
                       'Proposed alternative route: ' + ', '.join(self.route) +
                       '. Remain stopped; the path is not verified clear.')
        else:
            message = prefix + 'No alternative route. Please remain stopped.'
        self.announcement = message
        self.repeat_announcement()
        return True

    def repeat_announcement(self):
        if self.announcement is None:
            return False
        self.voice.speak(self.announcement, force=True, priority=True)
        return True

    def announce_camera_update(self, evidence):
        """Speak stable camera-state changes without treating absence as clearance."""
        if not self.confirmed:
            return False
        object_class = evidence.get('object_class') or 'obstacle'
        if evidence.get('transition') == 'not_detected':
            message = (f'Camera update. No {object_class} is currently detected in the monitored B to C area. '
                       'This does not verify that the path is clear. Remain stopped and wait for a human check.')
        elif evidence.get('transition') == 'detected':
            message = (f'Camera update. A {object_class} is detected again in the monitored B to C area. '
                       'The proposed route remains ' + ', '.join(self.route) +
                       '. The alternative path is not verified clear. Remain stopped.')
        else:
            return False
        self.announcement = message
        self.voice.speak(message, force=True, priority=True)
        return True
