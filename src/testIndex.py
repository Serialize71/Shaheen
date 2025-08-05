import cv2

def list_cameras(max_index=10):
    print("Searching for available camera indices...")
    for i in range(max_index):
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            print(f"Camera found at index {i}")
            cap.release()
        else:
            print(f"No camera at index {i}")
    print("Done.")

if __name__ == "__main__":
    list_cameras()