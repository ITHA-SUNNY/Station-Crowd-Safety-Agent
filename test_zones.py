"""
Script to test and visualize zones on frame_0.jpg
"""
import cv2
import numpy as np

img = cv2.imread("frame_0.jpg")
h, w = img.shape[:2]

# Define 3 key zones:
# 1. FOB Stairs/Bridge (top-left elevated structure)
fob_stairs = np.array([
    [0, 140],
    [230, 150],
    [210, 360],
    [0, 360]
], np.int32)

# 2. Platform 2 Edge (the critical danger strip along the track)
pf2_edge = np.array([
    [525, 10],
    [575, 10],
    [525, 200],
    [465, 380],
    [410, 520],
    [355, 720],
    [280, 720],
    [350, 520],
    [410, 380],
    [480, 200]
], np.int32)

# 3. Platform 2 Waiting Area / Concourse (under the shed / behind the edge)
pf2_waiting = np.array([
    [470, 10],
    [525, 10],
    [480, 200],
    [410, 380],
    [350, 520],
    [280, 720],
    [170, 720],
    [240, 400]
], np.int32)

# 4. Platform 1 Edge (right platform, danger strip along the track)
pf1_edge = np.array([
    [820, 10],
    [870, 10],
    [1100, 720],
    [1030, 720]
], np.int32)

# 5. Platform 1 Waiting Area
pf1_waiting = np.array([
    [870, 10],
    [930, 10],
    [1280, 720],
    [1100, 720]
], np.int32)

zones = {
    "FOB-STAIRS": (fob_stairs, (255, 150, 0), "stairs", 25.0),
    "PF2-EDGE": (pf2_edge, (0, 0, 255), "platform_edge", 35.0),
    "PF2-WAITING": (pf2_waiting, (0, 255, 0), "concourse", 45.0),
    "PF1-EDGE": (pf1_edge, (255, 0, 255), "platform_edge", 30.0),
    "PF1-WAITING": (pf1_waiting, (0, 255, 255), "concourse", 50.0)
}

overlay = img.copy()
for zid, (pts, color, ztype, area) in zones.items():
    cv2.polylines(overlay, [pts], True, color, 3)
    # Fill semi-transparent
    cv2.fillPoly(overlay, [pts], color)

alpha = 0.3
cv2.addWeighted(overlay, alpha, img, 1 - alpha, 0, img)

# Add labels
for zid, (pts, color, ztype, area) in zones.items():
    M = cv2.moments(pts)
    if M["m00"] != 0:
        cX = int(M["m10"] / M["m00"])
        cY = int(M["m01"] / M["m00"])
    else:
        cX, cY = pts[0]
    cv2.putText(img, f"{zid} ({ztype})", (cX - 60, cY),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)

cv2.imwrite("zones_preview.jpg", img)
print("Saved zones_preview.jpg")
