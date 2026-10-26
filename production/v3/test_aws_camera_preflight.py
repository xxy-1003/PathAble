from unittest.mock import patch

import pytest

from aws_camera_preflight import preflight
from aws_device_client import RequestRejected


@pytest.mark.parametrize("token", [None, "", "copied PowerShell command", "a.b.c\nPRIVATE", "Bearer a.b.c"])
def test_bad_paste_never_reaches_network(tmp_path, token):
    with patch("aws_camera_preflight.AwsDeviceClient") as client:
        with pytest.raises(RequestRejected, match="camera access token"):
            preflight("https://example.invalid", tmp_path, token)
        client.assert_not_called()


def test_preflight_only_reads_map_and_preserves_saved_files(tmp_path):
    before = list(tmp_path.iterdir())
    with patch("aws_camera_preflight.AwsDeviceClient._http_request", return_value=(200, {"map_id": "prototype", "version": 4})) as request:
        assert preflight("https://example.invalid", tmp_path, "a.b.c") == (4, 0)
    request.assert_called_once_with("GET", "/map/version")
    assert list(tmp_path.iterdir()) == before


def test_expired_signin_has_actionable_error(tmp_path):
    with patch("aws_camera_preflight.AwsDeviceClient._http_request", return_value=(401, {})):
        with pytest.raises(RequestRejected, match="Sign in again as camera-demo"):
            preflight("https://example.invalid", tmp_path, "a.b.c")


def test_duplicate_api_prefix_is_rejected_before_sending_token(tmp_path):
    with patch("aws_camera_preflight.AwsDeviceClient") as client:
        with pytest.raises(RequestRejected, match="without /api/v2"):
            preflight("https://example.invalid/api/v2", tmp_path, "a.b.c")
        client.assert_not_called()
