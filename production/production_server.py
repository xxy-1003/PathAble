import cv2
import numpy as np
import networkx as nx
import asyncio
import websockets
import json
import base64
import time
import requests
from dataclasses import dataclass

@dataclass
class SensorState:
    heading: float = 0.0
    tof_dist_cm: float = -1.0
    last_update: float = 0.0

class ProductionPathAbleEngine:
    def __init__(self, model_path="yolo11n-seg.onnx", map_path="map_graph.json"):
        self.sensor_state = SensorState()
        
        # 1. Load Map & Dijkstra Router
        with open(map_path, 'r') as f:
            self.map_data = json.load(f)
        self.graph = nx.Graph()
        self.rebuild_graph()
        
        self.current_node = "A"
        self.target_node = "D"
        self.current_route = self.plan_route(self.current_node, self.target_node)

        # 2. Initialize OpenCV DNN Engine with ONNX Model
        print(f"[VISION]: Loading YOLO ONNX model: {model_path}")
        self.net = cv2.dnn.readNetFromONNX(model_path)
        self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
        self.net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)

        # 3. Initialize ArUco Detector
        self.aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
        self.aruco_params = cv2.aruco.DetectorParameters()
        self.aruco_detector = cv2.aruco.ArucoDetector(self.aruco_dict, self.aruco_params)

        # COCO Target Obstacle Classes: person(0), chair(56), couch(57), dining table(60)
        self.target_classes = {0, 56, 57, 60}

        # Optimization & Caching State
        self.frame_counter = 0
        self.cached_l_occ = False
        self.cached_c_occ = False
        self.cached_r_occ = False

    def rebuild_graph(self):
        self.graph.clear()
        for edge in self.map_data['edges']:
            if not edge['blocked']:
                self.graph.add_edge(edge['from'], edge['to'], weight=edge['distance'])

    def plan_route(self, start, target):
        try:
            return nx.dijkstra_path(self.graph, start, target, weight='weight')
        except nx.NetworkXNoPath:
            return []

    def process_onnx_inference(self, frame):
        h, w, _ = frame.shape
        # ONNX models exported with default settings require 640x640 input
        blob_size = 640
        blob = cv2.dnn.blobFromImage(frame, 1/255.0, (blob_size, blob_size), swapRB=True, crop=False)
        self.net.setInput(blob)
        outputs = self.net.forward()

        # Parse YOLO outputs (Output shape: [1, N, 8400] -> transpose to [8400, N])
        predictions = np.squeeze(outputs[0]).T
        
        boxes, confidences, class_ids = [], [], []
        x_factor = w / float(blob_size)
        y_factor = h / float(blob_size)

        for pred in predictions:
            scores = pred[4:84]
            class_id = np.argmax(scores)
            confidence = scores[class_id]

            if confidence > 0.40 and class_id in self.target_classes:
                cx, cy, bw, bh = pred[0], pred[1], pred[2], pred[3]
                left = int((cx - 0.5 * bw) * x_factor)
                top = int((cy - 0.5 * bh) * y_factor)
                width = int(bw * x_factor)
                height = int(bh * y_factor)

                boxes.append([left, top, width, height])
                confidences.append(float(confidence))
                class_ids.append(class_id)

        indices = cv2.dnn.NMSBoxes(boxes, confidences, 0.40, 0.45)
        
        # Analyze zone occupancy from bounding boxes
        center_occ, left_occ, right_occ = False, False, False
        if len(indices) > 0:
            for i in indices:
                idx = i[0] if isinstance(i, (list, np.ndarray)) else i
                box = boxes[idx]
                box_cx = box[0] + box[2] / 2.0
                box_bottom = box[1] + box[3]
                
                # Check if obstacle contact point is in lower 60% walking path
                if box_bottom > (h * 0.4):
                    if 0.3 * w <= box_cx <= 0.7 * w:
                        center_occ = True
                    elif box_cx < 0.3 * w:
                        left_occ = True
                    else:
                        right_occ = True

        return left_occ, center_occ, right_occ

    def process_aruco(self, frame):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        corners, ids, _ = self.aruco_detector.detectMarkers(gray)
        if ids is not None and len(ids) > 0:
            marker_id = str(ids.flatten()[0])
            node_map = {"0": "A", "1": "B", "2": "C", "3": "D", "4": "E", "5": "F"}
            if marker_id in node_map:
                detected_node = node_map[marker_id]
                if detected_node != self.current_node:
                    self.current_node = detected_node
                    self.current_route = self.plan_route(self.current_node, self.target_node)
                    return f"Reached junction {self.current_node}"
        return None

    def fuse_sensors_and_decide(self, l_occ, c_occ, r_occ, frame):
        # Sensor Fusion: ToF Laser override (< 80cm)
        if 0 < self.sensor_state.tof_dist_cm < 80.0:
            c_occ = True

        action = "CONTINUE"
        message = ""

        if not c_occ:
            action = "CONTINUE"
        elif c_occ and not r_occ:
            action = "STEP_ASIDE_RIGHT"
            message = "Obstacle ahead. Step slightly right."
        elif c_occ and not l_occ:
            action = "STEP_ASIDE_LEFT"
            message = "Obstacle ahead. Step slightly left."
        else: # Full blockage -> Trigger Dijkstra Reroute
            if len(self.current_route) >= 2:
                next_node = self.current_route[1]
                blocked_edge = (self.current_node, next_node)
                
                if self.graph.has_edge(*blocked_edge):
                    self.graph.remove_edge(*blocked_edge)
                
                self.current_route = self.plan_route(self.current_node, self.target_node)
                if self.current_route:
                    action = "REROUTE"
                    message = f"Route blocked. Turn towards junction {self.current_route[1]}."
                else:
                    action = "STOP"
                    message = "No safe route available. Please stop."

        return action, message

    def process_frame_smart(self, frame):
        self.frame_counter += 1

        t0 = time.time()
        # 1. Always run ArUco detection every frame (Fast ~5ms execution)
        loc_msg = self.process_aruco(frame)
        t_aruco = (time.time() - t0) * 1000

        # 2. Run YOLO ONNX inference once every 3 frames (~100ms interval)
        t1 = time.time()
        if self.frame_counter % 3 == 0:
            self.cached_l_occ, self.cached_c_occ, self.cached_r_occ = self.process_onnx_inference(frame)
            t_yolo = (time.time() - t1) * 1000
            print(f"[PERF] ArUco: {t_aruco:.1f}ms | YOLO (Run): {t_yolo:.1f}ms")
        else:
            print(f"[PERF] ArUco: {t_aruco:.1f}ms | YOLO (Cached)")

        # 3. Fuse cached occupancy state with live sensors
        action, nav_msg = self.fuse_sensors_and_decide(
            self.cached_l_occ, self.cached_c_occ, self.cached_r_occ, frame
        )

        return loc_msg, action, nav_msg

# Global Engine Instance
engine = ProductionPathAbleEngine()

async def handler(websocket, path=None):
    print("[SERVER]: Client connected")
    try:
        async for message in websocket:
            data = json.loads(message)
            
            # Handle incoming IoT sensor packet
            if data.get("type") == "iot_telemetry":
                engine.sensor_state.heading = data.get("heading", 0.0)
                engine.sensor_state.tof_dist_cm = data.get("tof_dist_cm", -1.0)
                engine.sensor_state.last_update = time.time()
                continue

            # Handle incoming Frame from Mobile Client
            if data.get("type") == "frame":
                img_bytes = base64.b64decode(data["data"].split(",")[1])
                np_arr = np.frombuffer(img_bytes, np.uint8)
                frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

                # Process frame using Smart Frame Execution
                loc_msg, action, nav_msg = engine.process_frame_smart(frame)

                response_msg = loc_msg if loc_msg else nav_msg

                await websocket.send(json.dumps({
                    "action": action,
                    "message": response_msg,
                    "current_node": engine.current_node,
                    "route": engine.current_route,
                    "heading": engine.sensor_state.heading
                }))
    except websockets.exceptions.ConnectionClosed:
        print("[SERVER]: Client disconnected")

async def main():
    async with websockets.serve(handler, "0.0.0.0", 8080):
        print("[SERVER]: PathAble Edge Engine running on ws://0.0.0.0:8080")
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())