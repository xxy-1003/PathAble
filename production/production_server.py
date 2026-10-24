import cv2
import numpy as np
import networkx as nx
import asyncio
import websockets
import json
import base64
import time
from collections import deque
from dataclasses import dataclass

# COCO dataset class names (80 classes)
COCO_CLASSES = {
    0: "person", 1: "bicycle", 2: "car", 3: "motorcycle", 4: "airplane", 5: "bus",
    6: "train", 7: "truck", 8: "boat", 9: "traffic light", 10: "fire hydrant",
    11: "stop sign", 12: "parking meter", 13: "bench", 14: "bird", 15: "cat",
    16: "dog", 17: "horse", 18: "sheep", 19: "cow", 20: "elephant", 21: "bear",
    22: "zebra", 23: "giraffe", 24: "backpack", 25: "umbrella", 26: "handbag",
    27: "tie", 28: "suitcase", 29: "frisbee", 30: "skis", 31: "snowboard",
    32: "sports ball", 33: "kite", 34: "baseball bat", 35: "baseball glove",
    36: "skateboard", 37: "surfboard", 38: "tennis racket", 39: "bottle",
    40: "wine glass", 41: "cup", 42: "fork", 43: "knife", 44: "spoon", 45: "bowl",
    46: "banana", 47: "apple", 48: "sandwich", 49: "orange", 50: "broccoli",
    51: "carrot", 52: "hot dog", 53: "pizza", 54: "donut", 55: "cake", 56: "chair",
    57: "couch", 58: "potted plant", 59: "bed", 60: "dining table", 61: "toilet",
    62: "tv", 63: "laptop", 64: "mouse", 65: "remote", 66: "keyboard",
    67: "cell phone", 68: "microwave", 69: "oven", 70: "toaster", 71: "sink",
    72: "refrigerator", 73: "book", 74: "clock", 75: "vase", 76: "scissors",
    77: "teddy bear", 78: "hair drier", 79: "toothbrush"
}

# Physical obstacle classes relevant to walking corridors
OBSTACLE_CLASSES = {
    0,   # person
    13,  # bench
    24,  # backpack
    26,  # handbag
    28,  # suitcase
    39,  # bottle
    56,  # chair
    57,  # couch
    58,  # potted plant
    59,  # bed
    60,  # dining table
    62,  # tv
    63,  # laptop
}

@dataclass
class SensorState:
    heading: float = 0.0
    tof_dist_cm: float = -1.0
    last_update: float = 0.0

class ProductionPathAbleEngine:
    def __init__(self, model_path="yolo11n-seg.onnx", map_path="map_graph.json"):
        self.sensor_state = SensorState()
        self.map_path = map_path
        
        # 1. Load Map & Dijkstra Router
        with open(map_path, 'r', encoding='utf-8') as f:
            self.map_data = json.load(f)
        self.graph = nx.Graph()
        self.blocked_edges = set()
        self.rebuild_graph()
        
        self.current_node = "A"
        self.target_node = "D"
        self.current_route = self.plan_route(self.current_node, self.target_node)

        # 2. Initialize OpenCV DNN Engine with ONNX Model
        print(f"[VISION]: Loading YOLO ONNX model from: {model_path}")
        self.net = cv2.dnn.readNetFromONNX(model_path)
        self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)

        # 3. Initialize ArUco Detector (DICT_4X4_50)
        self.aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
        self.aruco_params = cv2.aruco.DetectorParameters()
        self.aruco_detector = cv2.aruco.ArucoDetector(self.aruco_dict, self.aruco_params)

        # Optimization & Multi-Frame Smoothing State
        self.frame_counter = 0
        self.cached_detections = []
        self.cached_zones = {"left": False, "center": False, "right": False}
        self.blockage_history = deque(maxlen=6)
        self.last_speech_time = 0.0
        self.last_speech_text = ""
        self.last_fps = 0.0
        self.fps_timer = time.time()
        self.fps_frames = 0

    def rebuild_graph(self):
        self.graph.clear()
        for edge in self.map_data['edges']:
            edge_key = frozenset((edge['from'], edge['to']))
            if not edge.get('blocked', False) and edge_key not in self.blocked_edges:
                self.graph.add_edge(edge['from'], edge['to'], weight=edge['distance'])

    def plan_route(self, start, target):
        try:
            return nx.dijkstra_path(self.graph, start, target, weight='weight')
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return []

    def reset_blockages(self):
        """Re-opens all blocked corridors."""
        self.blocked_edges.clear()
        self.rebuild_graph()
        self.current_route = self.plan_route(self.current_node, self.target_node)
        self.blockage_history.clear()
        print("[ROUTER]: All corridor blockages cleared, route reset.")

    def process_onnx_inference(self, frame):
        h, w, _ = frame.shape
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
            class_id = int(np.argmax(scores))
            confidence = float(scores[class_id])

            # Detect obstacles with confidence >= 0.35
            if confidence >= 0.35 and (class_id in OBSTACLE_CLASSES or confidence >= 0.50):
                cx, cy, bw, bh = pred[0], pred[1], pred[2], pred[3]
                left = int(max(0, (cx - 0.5 * bw) * x_factor))
                top = int(max(0, (cy - 0.5 * bh) * y_factor))
                width = int(min(w - left, bw * x_factor))
                height = int(min(h - top, bh * y_factor))

                if width > 10 and height > 10:
                    boxes.append([left, top, width, height])
                    confidences.append(confidence)
                    class_ids.append(class_id)

        indices = cv2.dnn.NMSBoxes(boxes, confidences, 0.35, 0.45)
        
        detected_objects = []
        center_occ, left_occ, right_occ = False, False, False

        if len(indices) > 0:
            flat_indices = np.array(indices).flatten()
            for idx in flat_indices:
                idx = int(idx)
                box = boxes[idx]
                box_left = box[0]
                box_top = box[1]
                box_right = box[0] + box[2]
                box_bottom = box[1] + box[3]
                
                cid = class_ids[idx]
                cname = COCO_CLASSES.get(cid, f"item_{cid}")
                conf = confidences[idx]

                # Distance estimation based on contact line (bottom of bounding box)
                # Lower 60% of frame represents physical floor walking space
                distance_band = "far"
                if box_bottom > (h * 0.75):
                    distance_band = "near"
                elif box_bottom > (h * 0.50):
                    distance_band = "medium"

                detected_objects.append({
                    "box": box, # [x, y, w, h]
                    "class_name": cname,
                    "confidence": round(conf, 2),
                    "distance": distance_band
                })

                # Zone occupancy: check if obstacle touches lower walking floor
                if box_bottom > (h * 0.40):
                    # Check overlap with left zone (0 to 30% of width)
                    if box_left < 0.30 * w:
                        left_occ = True
                    # Check overlap with center walking path (30% to 70% of width)
                    if (box_right > 0.30 * w) and (box_left < 0.70 * w):
                        center_occ = True
                    # Check overlap with right zone (70% to 100% of width)
                    if box_right > 0.70 * w:
                        right_occ = True

        zones = {"left": left_occ, "center": center_occ, "right": right_occ}
        return detected_objects, zones

    def process_aruco(self, frame):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        corners, ids, _ = self.aruco_detector.detectMarkers(gray)
        aruco_info = None

        if ids is not None and len(ids) > 0:
            flat_ids = ids.flatten()
            marker_id = str(flat_ids[0])
            node_map = {"0": "A", "1": "B", "2": "C", "3": "D", "4": "E", "5": "F"}
            pts = corners[0].reshape(-1, 2).tolist()
            detected_node = node_map.get(marker_id)
            
            aruco_info = {
                "id": int(flat_ids[0]),
                "node": detected_node,
                "corners": pts
            }

            if detected_node:
                if detected_node != self.current_node:
                    print(f"[LOCALIZATION]: Junction reached: {detected_node}")
                    self.current_node = detected_node
                    self.current_route = self.plan_route(self.current_node, self.target_node)
                    self.blockage_history.clear()
                    return f"Reached junction {self.current_node}", aruco_info
                
        return None, aruco_info

    def fuse_sensors_and_decide(self, zones):
        c_occ = zones["center"]
        l_occ = zones["left"]
        r_occ = zones["right"]

        # Sensor Fusion: ToF Laser override (< 80cm)
        if 0 < self.sensor_state.tof_dist_cm < 80.0:
            c_occ = True

        # Multi-frame smoothing for full blockage
        is_full_block = c_occ and (l_occ or r_occ)
        self.blockage_history.append(is_full_block)

        action = "CONTINUE"
        message = ""

        if not c_occ:
            action = "CONTINUE"
            message = ""
        elif c_occ and not r_occ:
            action = "STEP_ASIDE_RIGHT"
            message = "Obstacle ahead. Step slightly right."
        elif c_occ and not l_occ:
            action = "STEP_ASIDE_LEFT"
            message = "Obstacle ahead. Step slightly left."
        else:
            # Both sides blocked or unclear: check multi-frame persistence
            # Require at least 4 out of last 6 frames to confirm real corridor blockage
            confirmed_blockage = sum(self.blockage_history) >= 4
            
            if not confirmed_blockage:
                action = "WAIT_AND_REOBSERVE"
                message = "Obstacle ahead. Checking path..."
            else:
                # Trigger Dijkstra Reroute
                if len(self.current_route) >= 2:
                    next_node = self.current_route[1]
                    blocked_edge = frozenset((self.current_node, next_node))
                    
                    if blocked_edge not in self.blocked_edges:
                        print(f"[REROUTE]: Corridor {self.current_node}-{next_node} blocked! Re-routing...")
                        self.blocked_edges.add(blocked_edge)
                        self.rebuild_graph()
                        self.current_route = self.plan_route(self.current_node, self.target_node)
                        self.blockage_history.clear()

                    if self.current_route:
                        action = "REROUTE"
                        message = f"Route blocked. Turn towards junction {self.current_route[1]}."
                    else:
                        action = "STOP"
                        message = "No safe route available. Please stop."

        return action, message

    def process_frame_smart(self, frame):
        self.frame_counter += 1
        self.fps_frames += 1

        # Calculate FPS every 1 second
        now = time.time()
        if now - self.fps_timer >= 1.0:
            self.last_fps = round(self.fps_frames / (now - self.fps_timer), 1)
            self.fps_timer = now
            self.fps_frames = 0

        # 1. Fast ArUco detection every frame (~5 ms)
        loc_msg, aruco_info = self.process_aruco(frame)

        # 2. YOLO ONNX inference (runs every frame or caches smoothly)
        # On modern CPUs with OpenCV 5, inference takes ~60ms (~16 FPS)
        detections, zones = self.process_onnx_inference(frame)
        self.cached_detections = detections
        self.cached_zones = zones

        # 3. Fuse and compute navigation decision
        action, nav_msg = self.fuse_sensors_and_decide(self.cached_zones)

        return loc_msg, action, nav_msg, self.cached_detections, self.cached_zones, aruco_info

# Global Engine Instance
engine = ProductionPathAbleEngine()

async def handler(websocket, path=None):
    print("[SERVER]: Client connected")
    try:
        async for message in websocket:
            data = json.loads(message)

            # Handle route reset request
            if data.get("type") == "reset":
                engine.reset_blockages()
                await websocket.send(json.dumps({
                    "action": "RESET",
                    "message": "Route reset to default.",
                    "current_node": engine.current_node,
                    "route": engine.current_route
                }))
                continue
            
            # Handle incoming IoT sensor packet
            if data.get("type") == "iot_telemetry":
                engine.sensor_state.heading = data.get("heading", 0.0)
                engine.sensor_state.tof_dist_cm = data.get("tof_dist_cm", -1.0)
                engine.sensor_state.last_update = time.time()
                continue

            # Handle incoming Frame from Mobile/Laptop Client
            if data.get("type") == "frame":
                img_data = data.get("data", "")
                if not img_data or "," not in img_data:
                    continue

                try:
                    img_bytes = base64.b64decode(img_data.split(",")[1])
                    np_arr = np.frombuffer(img_bytes, np.uint8)
                    frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
                except Exception as decode_err:
                    print(f"[WARN] Frame decode error: {decode_err}")
                    continue

                if frame is None or frame.size == 0:
                    continue

                # Process frame using Smart Frame Execution
                loc_msg, action, nav_msg, detections, zones, aruco_info = engine.process_frame_smart(frame)

                response_msg = loc_msg if loc_msg else nav_msg

                # Transmit structured response back to client with boxes and zones
                await websocket.send(json.dumps({
                    "action": action,
                    "message": response_msg,
                    "current_node": engine.current_node,
                    "target_node": engine.target_node,
                    "route": engine.current_route,
                    "heading": engine.sensor_state.heading,
                    "boxes": detections,
                    "zones": zones,
                    "aruco": aruco_info,
                    "fps": engine.last_fps
                }))

    except websockets.exceptions.ConnectionClosed:
        print("[SERVER]: Client disconnected")
    except Exception as e:
        print(f"[ERROR]: WebSocket handler exception: {e}")

async def main():
    async with websockets.serve(handler, "0.0.0.0", 8080):
        print("=" * 65)
        print("  PathAble Live Production Edge Engine (OpenCV 5)")
        print("  Listening on: ws://0.0.0.0:8080")
        print("=" * 65)
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
