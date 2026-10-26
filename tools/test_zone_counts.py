"""
Test refined zones against actual 1280 YOLO detections
"""
import cv2
import numpy as np
from ultralytics import YOLO

# 1. FOB Stairs/Bridge
fob_stairs = np.array([
    [0, 100],
    [240, 130],
    [230, 420],
    [0, 420]
], np.int32)

# 2. Platform 2 Edge (danger strip where people line up for train along track)
pf2_edge = np.array([
    [520, 10],
    [580, 10],
    [480, 300],
    [430, 720],
    [320, 720],
    [410, 300]
], np.int32)

# 3. Platform 2 Waiting Area (inward under shed roof / near stairs)
pf2_waiting = np.array([
    [320, 300],
    [410, 300],
    [320, 720],
    [160, 720]
], np.int32)

# 4. Platform 1 Edge (right platform danger line)
pf1_edge = np.array([
    [850, 10],
    [900, 10],
    [1110, 720],
    [1040, 720]
], np.int32)

# 5. Platform 1 Waiting Area (right platform walking/waiting)
pf1_waiting = np.array([
    [900, 10],
    [960, 10],
    [1280, 720],
    [1110, 720]
], np.int32)

zones = {
    "FOB-STAIRS": (fob_stairs, (255, 150, 0), "stairs", 25.0),
    "PF2-EDGE": (pf2_edge, (0, 0, 255), "platform_edge", 35.0),
    "PF2-WAITING": (pf2_waiting, (0, 255, 0), "concourse", 40.0),
    "PF1-EDGE": (pf1_edge, (255, 0, 255), "platform_edge", 30.0),
    "PF1-WAITING": (pf1_waiting, (0, 255, 255), "concourse", 50.0)
}

# Run YOLO detection
model = YOLO('yolo11n.pt')
res = model('frame_0.jpg', classes=[0], imgsz=1280, conf=0.10, verbose=False)
boxes = res[0].boxes.xyxy.cpu().numpy()

img = cv2.imread('frame_0.jpg')
overlay = img.copy()

# Count per zone
zone_counts = {zid: 0 for zid in zones}
for b in boxes:
    x1, y1, x2, y2 = map(int, b)
    cx, cy = (x1 + x2) // 2, y2
    for zid, (pts, color, ztype, area) in zones.items():
        if cv2.pointPolygonTest(pts, (float(cx), float(cy)), False) >= 0:
            zone_counts[zid] += 1
            cv2.circle(img, (cx, cy), 4, (0, 255, 255), -1)
            break
    else:
        # Outside defined zones
        cv2.circle(img, (cx, cy), 3, (128, 128, 128), -1)

# Draw zones
for zid, (pts, color, ztype, area) in zones.items():
    cv2.polylines(img, [pts], True, color, 2)
    cv2.fillPoly(overlay, [pts], color)

cv2.addWeighted(overlay, 0.25, img, 0.75, 0, img)

for zid, (pts, color, ztype, area) in zones.items():
    count = zone_counts[zid]
    density = count / area
    M = cv2.moments(pts)
    cX = int(M["m10"] / M["m00"]) if M["m00"] != 0 else pts[0][0]
    cY = int(M["m01"] / M["m00"]) if M["m00"] != 0 else pts[0][1]
    cv2.putText(img, f"{zid}: {count}p ({density:.2f}/m2)", (cX - 80, cY),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2, cv2.LINE_AA)
    print(f"Zone {zid}: {count} people -> {density:.2f} p/m2")

cv2.imwrite("zone_counts_preview.jpg", img)
print("Saved zone_counts_preview.jpg")
