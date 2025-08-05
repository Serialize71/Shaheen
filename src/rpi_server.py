#!/usr/bin/env python3
"""
Raspberry Pi Camera Server
Streams camera feed and handles drone commands from a remote client.
"""

import socket
import threading
import time
import json
import cv2
import pickle
import struct
import sys
from datetime import datetime

class RPiCameraServer:
    def __init__(self, host='0.0.0.0', video_port=8080, command_port=8081):
        self.host = host
        self.video_port = video_port
        self.command_port = command_port
        
        # Camera setup
        self.camera = None
        self.is_streaming = False
        
        # Socket setup
        self.video_socket = None
        self.command_socket = None
        self.clients = []
        
        # Camera settings
        self.color_mode = True  # True for color, False for grayscale
        
        # Drone status
        self.drone_status = {
            'connected': True,
            'battery': 100,
            'altitude': 0,
            'speed': 0,
            'mode': 'standby'
        }
        
        self.running = True
        
    def log_message(self, message, level="INFO"):
        """Log a message with timestamp"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] {level}: {message}")
        
        # Send log message to all connected clients
        log_data = {
            'type': 'log',
            'timestamp': timestamp,
            'level': level,
            'message': message
        }
        self.broadcast_message(log_data)
    
    def init_camera(self):
        """Initialize the camera"""
        try:
            self.camera = cv2.VideoCapture(0)
            if not self.camera.isOpened():
                raise Exception("Could not open camera")
            
            # Set camera properties for better performance
            self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            self.camera.set(cv2.CAP_PROP_FPS, 30)
            
            self.log_message("Camera initialized successfully")
            return True
        except Exception as e:
            self.log_message(f"Failed to initialize camera: {e}", "ERROR")
            return False
    
    def start_video_server(self):
        """Start the video streaming server"""
        try:
            self.video_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.video_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.video_socket.bind((self.host, self.video_port))
            self.video_socket.listen(5)
            
            self.log_message(f"Video server started on {self.host}:{self.video_port}")
            
            while self.running:
                try:
                    client_socket, addr = self.video_socket.accept()
                    self.log_message(f"Video client connected from {addr}")
                    
                    # Start streaming thread for this client
                    thread = threading.Thread(
                        target=self.stream_video, 
                        args=(client_socket, addr)
                    )
                    thread.daemon = True
                    thread.start()
                    
                except Exception as e:
                    if self.running:
                        self.log_message(f"Error accepting video connection: {e}", "ERROR")
                        
        except Exception as e:
            self.log_message(f"Failed to start video server: {e}", "ERROR")
    
    def stream_video(self, client_socket, addr):
        """Stream video to a specific client"""
        try:
            frame_count = 0
            while self.running and self.camera and self.camera.isOpened():
                ret, frame = self.camera.read()
                if not ret:
                    self.log_message(f"Failed to read frame from camera for {addr}", "WARNING")
                    break
                
                # Debug logging every 30 frames (once per second at 30fps)
                frame_count += 1
                if frame_count % 30 == 0:
                    mode_str = "Color (3-channel)" if self.color_mode else "Grayscale (1-channel)"
                    frame_shape = frame.shape
                    self.log_message(f"Streaming frame #{frame_count} in {mode_str} mode ({frame_shape}) to {addr}")
                
                # Handle color vs grayscale mode
                if not self.color_mode:
                    # Convert to single-channel grayscale for bandwidth efficiency
                    frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    # Encode single-channel grayscale
                    encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 90]
                    result, encoded_img = cv2.imencode('.jpg', frame, encode_param)
                else:
                    # Encode full-color frame
                    encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 90]
                    result, encoded_img = cv2.imencode('.jpg', frame, encode_param)
                
                if result:
                    # Serialize frame data
                    data = pickle.dumps(encoded_img)
                    size = len(data)
                    
                    # Log data size every 30 frames to show bandwidth differences
                    if frame_count % 30 == 0:
                        size_kb = size / 1024
                        mode_desc = "Color (3-channel)" if self.color_mode else "Grayscale (1-channel)"
                        self.log_message(f"Frame data size: {size_kb:.1f}KB ({mode_desc})")
                    
                    try:
                        # Send frame size first, then frame data
                        client_socket.sendall(struct.pack("L", size) + data)
                    except socket.error as e:
                        self.log_message(f"Socket error streaming to {addr}: {e}", "ERROR")
                        break
                        
                time.sleep(0.033)  # ~30 FPS
                
        except Exception as e:
            self.log_message(f"Error streaming to {addr}: {e}", "ERROR")
        finally:
            try:
                client_socket.close()
            except:
                pass
            self.log_message(f"Video client {addr} disconnected")
    
    def start_command_server(self):
        """Start the command server"""
        try:
            self.command_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.command_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.command_socket.bind((self.host, self.command_port))
            self.command_socket.listen(5)
            
            self.log_message(f"Command server started on {self.host}:{self.command_port}")
            
            while self.running:
                try:
                    client_socket, addr = self.command_socket.accept()
                    self.clients.append(client_socket)
                    self.log_message(f"Command client connected from {addr}")
                    
                    # Start command handler thread for this client
                    thread = threading.Thread(
                        target=self.handle_commands, 
                        args=(client_socket, addr)
                    )
                    thread.daemon = True
                    thread.start()
                    
                except Exception as e:
                    if self.running:
                        self.log_message(f"Error accepting command connection: {e}", "ERROR")
                        
        except Exception as e:
            self.log_message(f"Failed to start command server: {e}", "ERROR")
    
    def handle_commands(self, client_socket, addr):
        """Handle commands from a specific client"""
        try:
            while self.running:
                try:
                    data = client_socket.recv(1024)
                    if not data:
                        break
                    
                    command_data = json.loads(data.decode('utf-8'))
                    self.process_command(command_data, addr)
                    
                except json.JSONDecodeError:
                    self.log_message(f"Invalid JSON from {addr}", "WARNING")
                except socket.error:
                    break
                    
        except Exception as e:
            self.log_message(f"Error handling commands from {addr}: {e}", "ERROR")
        finally:
            if client_socket in self.clients:
                self.clients.remove(client_socket)
            client_socket.close()
            self.log_message(f"Command client {addr} disconnected")
    
    def process_command(self, command_data, addr):
        """Process received commands"""
        command_type = command_data.get('type', '')
        command = command_data.get('command', '')
        
        self.log_message(f"Received {command_type}: {command} from {addr}")
        
        if command_type == 'drone_control':
            self.handle_drone_command(command)
        elif command_type == 'text_command':
            self.handle_text_command(command)
        elif command_type == 'system':
            self.handle_system_command(command)
    
    def handle_drone_command(self, command):
        """Handle drone control commands"""
        drone_commands = {
            'takeoff': self.drone_takeoff,
            'land': self.drone_land,
            'forward': lambda: self.drone_move('forward'),
            'backward': lambda: self.drone_move('backward'),
            'left': lambda: self.drone_move('left'),
            'right': lambda: self.drone_move('right'),
            'up': lambda: self.drone_move('up'),
            'down': lambda: self.drone_move('down'),
            'rotate_left': lambda: self.drone_rotate('left'),
            'rotate_right': lambda: self.drone_rotate('right'),
            'emergency_stop': self.drone_emergency_stop
        }
        
        if command in drone_commands:
            drone_commands[command]()
        else:
            self.log_message(f"Unknown drone command: {command}", "WARNING")
    
    def handle_text_command(self, command):
        """Handle text-based commands"""
        if command.lower() == 'status':
            self.send_status_update()
        elif command.lower() == 'reboot':
            self.log_message("Reboot command received - simulating restart", "WARNING")
        elif command.lower().startswith('battery'):
            # Simulate battery check
            self.log_message(f"Battery level: {self.drone_status['battery']}%")
        else:
            self.log_message(f"Processing text command: {command}")
    
    def handle_system_command(self, command):
        """Handle system commands"""
        if command == 'shutdown':
            self.log_message("Shutdown command received", "WARNING")
            self.shutdown()
        elif command == 'restart_camera':
            self.restart_camera()
        elif command == 'toggle_color_mode':
            self.toggle_color_mode()
    
    def drone_takeoff(self):
        """Simulate drone takeoff"""
        self.drone_status['mode'] = 'flying'
        self.drone_status['altitude'] = 2.0
        self.log_message("Drone takeoff initiated")
        self.send_status_update()
    
    def drone_land(self):
        """Simulate drone landing"""
        self.drone_status['mode'] = 'landing'
        self.drone_status['altitude'] = 0.0
        self.drone_status['speed'] = 0
        self.log_message("Drone landing initiated")
        self.send_status_update()
    
    def drone_move(self, direction):
        """Simulate drone movement"""
        self.drone_status['speed'] = 5.0
        self.log_message(f"Drone moving {direction}")
        self.send_status_update()
        
        # Simulate movement completion
        threading.Timer(2.0, lambda: self.movement_complete()).start()
    
    def drone_rotate(self, direction):
        """Simulate drone rotation"""
        self.log_message(f"Drone rotating {direction}")
    
    def drone_emergency_stop(self):
        """Emergency stop"""
        self.drone_status['mode'] = 'emergency_stop'
        self.drone_status['speed'] = 0
        self.log_message("EMERGENCY STOP ACTIVATED", "WARNING")
        self.send_status_update()
    
    def movement_complete(self):
        """Called when movement is complete"""
        self.drone_status['speed'] = 0
        self.send_status_update()
    
    def restart_camera(self):
        """Restart the camera"""
        self.log_message("Restarting camera - this will temporarily disconnect video clients...")
        
        # Release the current camera
        if self.camera:
            self.camera.release()
            self.camera = None
        
        # Wait a moment for proper cleanup
        time.sleep(1)
        
        # Reinitialize camera
        if self.init_camera():
            self.log_message("Camera restarted successfully")
        else:
            self.log_message("Failed to restart camera", "ERROR")
    
    def toggle_color_mode(self):
        """Toggle between color and grayscale mode"""
        old_mode = self.color_mode
        self.color_mode = not self.color_mode
        mode_str = "Color" if self.color_mode else "Grayscale"
        
        self.log_message(f"Camera mode switched from {'Color' if old_mode else 'Grayscale'} to {mode_str}")
        self.log_message(f"New color_mode setting: {self.color_mode}")
        
        # Update drone status to reflect camera mode
        self.drone_status['mode'] = f'scanning_{mode_str.lower()}'
        self.send_status_update()
        
        # Send immediate confirmation to all clients
        confirmation_data = {
            'type': 'log',
            'timestamp': datetime.now().strftime("%H:%M:%S"),
            'level': 'SUCCESS',
            'message': f'Video feed switched to {mode_str} mode'
        }
        self.broadcast_message(confirmation_data)
    
    def send_status_update(self):
        """Send drone status to all clients"""
        status_data = {
            'type': 'status_update',
            'status': self.drone_status.copy()
        }
        self.broadcast_message(status_data)
    
    def broadcast_message(self, message_data):
        """Broadcast a message to all connected clients"""
        message_json = json.dumps(message_data)
        disconnected_clients = []
        
        for client in self.clients:
            try:
                client.send(message_json.encode('utf-8'))
            except socket.error:
                disconnected_clients.append(client)
        
        # Remove disconnected clients
        for client in disconnected_clients:
            if client in self.clients:
                self.clients.remove(client)
    
    def start(self):
        """Start the server"""
        if not self.init_camera():
            return False
        
        self.log_message("Starting RPi Camera Server...")
        
        # Start video streaming server
        video_thread = threading.Thread(target=self.start_video_server)
        video_thread.daemon = True
        video_thread.start()
        
        # Start command server
        command_thread = threading.Thread(target=self.start_command_server)
        command_thread.daemon = True
        command_thread.start()
        
        # Send periodic status updates
        status_thread = threading.Thread(target=self.status_updater)
        status_thread.daemon = True
        status_thread.start()
        
        return True
    
    def status_updater(self):
        """Send periodic status updates"""
        while self.running:
            time.sleep(5)  # Send status every 5 seconds
            if self.clients:  # Only if clients are connected
                # Simulate battery drain
                if self.drone_status['battery'] > 0:
                    self.drone_status['battery'] = max(0, self.drone_status['battery'] - 1)
                self.send_status_update()
    
    def shutdown(self):
        """Shutdown the server"""
        self.log_message("Shutting down server...")
        self.running = False
        
        if self.camera:
            self.camera.release()
        
        if self.video_socket:
            self.video_socket.close()
        
        if self.command_socket:
            self.command_socket.close()
        
        for client in self.clients:
            client.close()


def main():
    """Main function"""
    server = RPiCameraServer()
    
    try:
        if server.start():
            print("Server started successfully. Press Ctrl+C to stop.")
            while True:
                time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        server.shutdown()


if __name__ == "__main__":
    main() 