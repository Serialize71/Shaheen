import cv2
from pyzbar import pyzbar

def main():
    """
    This function captures video from the default camera, detects and decodes QR codes,
    and displays the video feed with the QR code information.
    """
    # Initialize the camera
    cap = cv2.VideoCapture(0)
    
    if not cap.isOpened():
        print("Error: Could not open video stream.")
        return
    
    cap.set(cv2.CAP_PROP_FRAME_WIDTH , 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT , 480)
        
    while True:
        
        # Capture frame-by-frame
        ret, photo = cap.read()

        if not ret:
            print("Error: Can't receive frame (stream end?). Exiting ...")
            break
        
        photo = cv2.cvtColor(photo , cv2.COLOR_RGB2GRAY)
        frame = cv2.resize(photo , (480, 360))

        # Find and decode QR codes
        decoded_objects = pyzbar.decode(frame)

        for obj in decoded_objects:
            # Extract the bounding box location of the QR code
            (x, y, w, h) = obj.rect
            # Draw a rectangle around the QR code
            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)

            # The data is a bytes object, so convert it to a string
            qr_data = obj.data.decode("utf-8")
            qr_type = obj.type

            # Put the QR code's data and type on the screen
            text = f"Data: {qr_data} | Type: {qr_type}"
            cv2.putText(frame, text, (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

            print(f"Detected {qr_type}: {qr_data}")


        # Display the resulting frame
        cv2.imshow("QR Code Scanner", frame)

        # Break the loop on 'q' key press
        if cv2.waitKey(15) == 27: #esc key
            break

    # When everything is done, release the capture
    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()