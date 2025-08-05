#!/usr/bin/env python3
"""
Laptop Client GUI for RPi Camera QR Code Scanner
Provides live video feed for QR code scanning with computer-side processing.
Note: Drone control is done via separate controller hardware.
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import socket
import threading
import time
import json
import cv2
import pickle
import struct
import numpy as np
from PIL import Image, ImageTk
from datetime import datetime
import pyzbar.pyzbar as pyzbar
import requests
import urllib3

class DroneControlClient:
    def __init__(self, root):
        self.root = root
        self.root.title("QR Code Scanner Station")
        self.root.geometry("1200x800")
        self.root.configure(bg='#2c3e50')
        
        # Connection settings
        self.server_ip = ""  # Will be set by user input
        self.video_port = 8080
        self.command_port = 8081
        
        # Socket connections
        self.video_socket = None
        self.command_socket = None
        self.connected = False
        
        # Video variables
        self.video_frame = None
        self.video_label = None
        
        # Status variables
        self.drone_status = {
            'connected': False,
            'battery': 0,
            'altitude': 0,
            'speed': 0,
            'mode': 'unknown'
        }
        
        self.setup_ui()
        self.running = True
        
        # Round number tracking
        self.current_round = 1
        
        # QR code scanning
        self.qr_scanning_active = False
        self.last_qr_data = None
        self.qr_scan_count = 0
        
        # QR Server Configuration
        self.qr_server_host = "127.0.0.1"  # Local server IP
        self.qr_server_port = 8080         # Server port
        self.qr_server_timeout = 5         # Request timeout in seconds
    
    def send_qr_to_server(self, round_num, qr_code):
        """Send QR code to local network server and get response"""
        try:
            # Disable SSL warnings for local development
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            
            # Prepare the request data
            request_data = {
                'round': round_num,
                'qr_code': qr_code,
                'timestamp': datetime.now().isoformat()
            }
            
            # Server URL
            server_url = f"http://{self.qr_server_host}:{self.qr_server_port}/qr"
            
            self.log_qr_message(f"Sending QR code to server...", "INFO")
            self.log_qr_message(f"Server: {server_url}", "INFO")
            self.log_qr_message(f"Round {round_num} - QR: {qr_code}", "SCAN")
            
            # Send POST request to server
            response = requests.post(
                server_url,
                json=request_data,
                timeout=self.qr_server_timeout,
                verify=False  # For local development
            )
            
            # Check if request was successful
            if response.status_code == 200:
                try:
                    response_data = response.json()
                    
                    # Display server response in QR console
                    if 'content' in response_data:
                        self.log_qr_message("Server Response:", "SUCCESS")
                        self.log_qr_message(response_data['content'], "CONTENT")
                        
                        # Display additional information if provided
                        if 'additional_info' in response_data:
                            for info in response_data['additional_info']:
                                self.log_qr_message(info, "INFO")
                                
                    elif 'message' in response_data:
                        self.log_qr_message("Server Response:", "SUCCESS")
                        self.log_qr_message(response_data['message'], "CONTENT")
                    else:
                        self.log_qr_message("Server Response:", "SUCCESS")
                        self.log_qr_message(str(response_data), "CONTENT")
                        
                    # Add separator
                    self.log_qr_message("─" * 50, "SEPARATOR")
                    
                except json.JSONDecodeError:
                    # Handle non-JSON response
                    self.log_qr_message("Server Response:", "SUCCESS")
                    self.log_qr_message(response.text, "CONTENT")
                    self.log_qr_message("─" * 50, "SEPARATOR")
                    
            else:
                # Handle HTTP error responses
                self.log_qr_message(f"Server Error: HTTP {response.status_code}", "ERROR") 
                try:
                    error_data = response.json()
                    if 'error' in error_data:
                        self.log_qr_message(error_data['error'], "ERROR")
                except:
                    self.log_qr_message(response.text, "ERROR")
                    
        except requests.exceptions.ConnectionError:
            self.log_qr_message("Connection Error: Cannot reach QR server", "ERROR")
            self.log_qr_message(f"Check if server is running on {self.qr_server_host}:{self.qr_server_port}", "ERROR")
            
        except requests.exceptions.Timeout:
            self.log_qr_message(f"Timeout Error: Server took longer than {self.qr_server_timeout}s to respond", "ERROR")
            
        except requests.exceptions.RequestException as e:
            self.log_qr_message(f"Request Error: {str(e)}", "ERROR")
            
        except Exception as e:
            self.log_qr_message(f"Unexpected Error: {str(e)}", "ERROR")
    
    def log_qr_message(self, message, level="INFO"):
        """Add a message to the QR console"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        color_map = {
            "SCAN": "#2980b9",      # Blue for QR scan
            "CONTENT": "#27ae60",   # Green for revealed content
            "SEPARATOR": "#7f8c8d", # Gray for separators
            "INFO": "#34495e",      # Dark gray for info
            "ERROR": "#e74c3c"      # Red for errors
        }
        
        self.qr_console.config(state=tk.NORMAL)
        
        if level == "SEPARATOR":
            self.qr_console.insert(tk.END, f"{message}\n")
        else:
            self.qr_console.insert(tk.END, f"[{timestamp}] {message}\n")
        
        # Color coding for different log levels
        if level in color_map:
            start_line = self.qr_console.index(tk.END + "-2l linestart")
            end_line = self.qr_console.index(tk.END + "-1l lineend")
            self.qr_console.tag_add(level, start_line, end_line)
            self.qr_console.tag_config(level, foreground=color_map[level], font=('Consolas', 9, 'bold'))
        
        self.qr_console.config(state=tk.DISABLED)
        self.qr_console.see(tk.END)

    def setup_ui(self):
        """Setup the user interface"""
        # Main container
        main_frame = tk.Frame(self.root, bg='#2c3e50')
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Top section - Connection and Status
        self.setup_top_section(main_frame)
        
        # Middle section - Video and Controls
        self.setup_middle_section(main_frame)
        
        # Bottom section - Console and Command Input
        self.setup_bottom_section(main_frame)
        
    def setup_top_section(self, parent):
        """Setup raspberry pi address, round number, and status on the same row"""
        top_frame = tk.Frame(parent, bg='#34495e', relief=tk.RAISED, bd=2)
        top_frame.pack(fill=tk.X, pady=(0, 10))
        
        # Single row layout with all elements
        main_row_frame = tk.Frame(top_frame, bg='#34495e')
        main_row_frame.pack(fill=tk.X, pady=15, padx=20)
        
        # Left side: IP Address and Connection
        left_frame = tk.Frame(main_row_frame, bg='#34495e')
        left_frame.pack(side=tk.LEFT, anchor='w')
        
        tk.Label(left_frame, text="Raspberry Pi IP Address:", bg='#34495e', fg='black', 
                font=('Arial', 10, 'bold')).pack(anchor=tk.W)
        
        # IP entry with placeholder text
        self.ip_entry = tk.Entry(left_frame, width=18, font=('Arial', 11), 
                               bg='white', fg='black', relief=tk.SUNKEN, bd=2)
        self.ip_entry.pack(pady=(2, 5))
        
        # Add placeholder text
        self.ip_placeholder = "e.g., 192.168.1.100"
        self.ip_entry.insert(0, self.ip_placeholder)
        self.ip_entry.config(fg='gray')
        
        # Bind events for placeholder behavior
        self.ip_entry.bind('<FocusIn>', self.on_ip_focus_in)
        self.ip_entry.bind('<FocusOut>', self.on_ip_focus_out)
        self.ip_entry.bind('<KeyPress>', self.on_ip_key_press)
        
        # Connection buttons
        button_frame = tk.Frame(left_frame, bg='#34495e')
        button_frame.pack()
        
        self.connect_btn = tk.Button(button_frame, text="Connect", command=self.connect_to_server,
                                   bg='#27ae60', fg='black', font=('Arial', 10, 'bold'),
                                   width=10, relief=tk.RAISED, cursor='hand2')
        self.connect_btn.pack(side=tk.LEFT, padx=2)
        
        self.disconnect_btn = tk.Button(button_frame, text="Disconnect", command=self.disconnect_from_server,
                                      bg='#e74c3c', fg='black', font=('Arial', 10, 'bold'),
                                      width=10, relief=tk.RAISED, state=tk.DISABLED, cursor='hand2')
        self.disconnect_btn.pack(side=tk.LEFT, padx=2)
        
        # Center: Round Number Display
        center_frame = tk.Frame(main_row_frame, bg='#34495e')
        center_frame.pack(side=tk.LEFT, padx=(50, 50))
        
        tk.Label(center_frame, text="CURRENT ROUND", bg='#34495e', fg='black', 
                font=('Arial', 12, 'bold')).pack()
        
        # Round number display with larger font
        self.round_number_var = tk.StringVar(value="1")
        self.round_display = tk.Label(center_frame, textvariable=self.round_number_var, 
                                     bg='#ecf0f1', fg='black', font=('Arial', 24, 'bold'),
                                     width=10, relief=tk.SUNKEN, bd=1)
        self.round_display.pack(pady=(5, 5))
        
        # Round control buttons
        round_controls = tk.Frame(center_frame, bg='#34495e')
        round_controls.pack()
        
        self.prev_round_btn = tk.Button(round_controls, text="◀ PREV", command=self.prev_round, bg='#3498db', fg='black',
                 font=('Arial', 10, 'bold'), width=8)
        self.prev_round_btn.pack(side=tk.LEFT, padx=2)
        
        self.next_round_btn = tk.Button(round_controls, text="NEXT ▶", command=self.next_round, bg='#3498db', fg='black',
                 font=('Arial', 10, 'bold'), width=8)
        self.next_round_btn.pack(side=tk.LEFT, padx=2)
        
        # Right side: Status Display
        status_frame = tk.Frame(main_row_frame, bg='#34495e')
        status_frame.pack(side=tk.RIGHT, anchor='e')
        
        tk.Label(status_frame, text="System Status", bg='#34495e', fg='black', 
                font=('Arial', 12, 'bold')).pack()
        
        # Status grid
        status_grid = tk.Frame(status_frame, bg='#34495e')
        status_grid.pack(pady=(5, 0))
        
        self.status_labels = {}
        status_items = ['Connected', 'Battery', 'Altitude', 'Speed', 'Mode']
        
        for i, item in enumerate(status_items):
            label_frame = tk.Frame(status_grid, bg='#34495e')
            label_frame.grid(row=i//3, column=i%3, padx=8, pady=2, sticky='w')
            
            tk.Label(label_frame, text=f"{item}:", bg='#34495e', fg='black', 
                    font=('Arial', 9, 'bold')).pack(side=tk.LEFT)
            self.status_labels[item.lower()] = tk.Label(label_frame, text="--", bg='#34495e', 
                                                       fg='black', font=('Arial', 9))
            self.status_labels[item.lower()].pack(side=tk.LEFT, padx=(5, 0))
    
    def setup_middle_section(self, parent):
        """Setup video feed and control buttons"""
        middle_frame = tk.Frame(parent, bg='#2c3e50')
        middle_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        # Video Frame (Left side)
        video_frame = tk.Frame(middle_frame, bg='#34495e', relief=tk.RAISED, bd=2)
        video_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))
        
        tk.Label(video_frame, text="Live QR Code Scanner Feed", bg='#34495e', fg='black', 
                font=('Arial', 12, 'bold')).pack(pady=10)
        
        # Video display area
        self.video_label = tk.Label(video_frame, bg='black', text="No Video Signal",
                                   fg='white', font=('Arial', 16))
        self.video_label.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        
        # Control Panel (Right side)
        control_frame = tk.Frame(middle_frame, bg='#34495e', relief=tk.RAISED, bd=2)
        control_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=10)
        
        tk.Label(control_frame, text="System Controls", bg='#34495e', fg='black', 
                font=('Arial', 12, 'bold')).pack(pady=10)
        
        # Add note about controller usage
        note_label = tk.Label(control_frame, text="Note: Drone control via hardware controller", 
                             bg='#34495e', fg='black', font=('Arial', 8, 'italic'), 
                             wraplength=150, justify='center')
        note_label.pack(pady=(0, 10))
        
        # QR Code Scanning Controls
        qr_frame = tk.LabelFrame(control_frame, text="QR Scanning Controls", bg='#34495e', 
                                   fg='black', font=('Arial', 10, 'bold'))
        qr_frame.pack(pady=10, padx=10, fill=tk.X)
        
        # QR Code Scanning buttons
        scan_control_frame = tk.Frame(qr_frame, bg='#34495e')
        scan_control_frame.pack(pady=20)
        
        self.create_control_button(scan_control_frame, "START SCAN", self.start_qr_scan, '#27ae60', 0, 0, width=15)
        self.create_control_button(scan_control_frame, "STOP SCAN", self.stop_qr_scan, '#e74c3c', 0, 1, width=15)
        
        # Color mode toggle
        color_frame = tk.Frame(qr_frame, bg='#34495e')
        color_frame.pack(pady=10)
        
        self.create_control_button(color_frame, "TOGGLE COLOR/GRAY", self.toggle_color_mode, '#9b59b6', 0, 0, width=18)
        
        # System Controls
        system_frame = tk.LabelFrame(control_frame, text="System Controls", bg='#34495e', 
                                   fg='black', font=('Arial', 10, 'bold'))
        system_frame.pack(pady=10, padx=10, fill=tk.X)
        
        self.create_control_button(system_frame, "Restart Camera", self.restart_camera, '#e67e22', 0, 0, width=12)
        
    def create_control_button(self, parent, text, command, color, row, col, width=8):
        """Create a control button with consistent styling and black text"""
        # Use larger font for wider buttons
        font_size = 11 if width > 12 else 9
        
        btn = tk.Button(parent, text=text, command=command, bg=color, fg='black',
                       font=('Arial', font_size, 'bold'), width=width, height=2,
                       relief=tk.RAISED, bd=2)
        btn.grid(row=row, column=col, padx=2, pady=2)
        
        # Add hover effects
        def on_enter(e):
            btn.config(relief=tk.RAISED, bd=4)
        def on_leave(e):
            btn.config(relief=tk.RAISED, bd=2)
            
        btn.bind("<Enter>", on_enter)
        btn.bind("<Leave>", on_leave)
        
        return btn
    
    def setup_bottom_section(self, parent):
        """Setup split console and command input"""
        bottom_frame = tk.Frame(parent, bg='#2c3e50')
        bottom_frame.pack(fill=tk.X)
        
        # Split Console Frame
        console_frame = tk.Frame(bottom_frame, bg='#34495e', relief=tk.RAISED, bd=2)
        console_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 5))
        
        # Left Console - General Messages
        left_console_frame = tk.Frame(console_frame, bg='#34495e')
        left_console_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(5, 2))
        
        tk.Label(left_console_frame, text="System Messages", bg='#34495e', fg='black', 
                font=('Arial', 10, 'bold')).pack(pady=(5, 0))
        
        self.console = scrolledtext.ScrolledText(left_console_frame, height=12, bg='#ecf0f1', 
                                               fg='black', font=('Consolas', 9),
                                               wrap=tk.WORD, state=tk.DISABLED)
        self.console.pack(fill=tk.BOTH, expand=True, padx=5, pady=(5, 10))
        
        # Right Console - QR Code Content
        right_console_frame = tk.Frame(console_frame, bg='#34495e')
        right_console_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(2, 5))
        
        tk.Label(right_console_frame, text="QR Code Content", bg='#34495e', fg='black', 
                font=('Arial', 10, 'bold')).pack(pady=(5, 0))
        
        self.qr_console = scrolledtext.ScrolledText(right_console_frame, height=12, bg='#f8f9fa', 
                                                  fg='black', font=('Consolas', 9),
                                                  wrap=tk.WORD, state=tk.DISABLED)
        self.qr_console.pack(fill=tk.BOTH, expand=True, padx=5, pady=(5, 10))
        
        # Command Input
        input_frame = tk.Frame(bottom_frame, bg='#34495e', relief=tk.RAISED, bd=2)
        input_frame.pack(fill=tk.X, pady=(5, 0))
        
        tk.Label(input_frame, text="Command Input:", bg='#34495e', fg='black', 
                font=('Arial', 10, 'bold')).pack(side=tk.LEFT, padx=(10, 5), pady=10)
        
        self.command_entry = tk.Entry(input_frame, font=('Arial', 10), bg='white')
        self.command_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5), pady=10)
        self.command_entry.bind('<Return>', self.send_text_command)
        
        self.send_btn = tk.Button(input_frame, text="Send", command=self.send_text_command,
                                bg='#3498db', fg='white', font=('Arial', 10, 'bold'),
                                width=8, relief=tk.RAISED)
        self.send_btn.pack(side=tk.RIGHT, padx=(5, 10), pady=10)
    
    def log_message(self, message, level="INFO"):
        """Add a message to the console"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        color_map = {
            "INFO": "black",
            "WARNING": "#d35400", 
            "ERROR": "#c0392b",
            "SUCCESS": "#27ae60"
        }
        
        self.console.config(state=tk.NORMAL)
        self.console.insert(tk.END, f"[{timestamp}] {level}: {message}\n")
        
        # Color coding for different log levels
        if level in color_map:
            start_line = self.console.index(tk.END + "-2l linestart")
            end_line = self.console.index(tk.END + "-1l lineend")
            self.console.tag_add(level, start_line, end_line)
            self.console.tag_config(level, foreground=color_map[level])
        
        self.console.config(state=tk.DISABLED)
        self.console.see(tk.END)
    
    def on_ip_focus_in(self, event):
        """Handle focus in event for IP entry (remove placeholder)"""
        if self.ip_entry.get() == self.ip_placeholder:
            self.ip_entry.delete(0, tk.END)
            self.ip_entry.config(fg='black')
    
    def on_ip_focus_out(self, event):
        """Handle focus out event for IP entry (restore placeholder if empty)"""
        if self.ip_entry.get().strip() == "":
            self.ip_entry.insert(0, self.ip_placeholder)
            self.ip_entry.config(fg='gray')
    
    def on_ip_key_press(self, event):
        """Handle key press in IP entry (remove placeholder on first key)"""
        if self.ip_entry.get() == self.ip_placeholder:
            self.ip_entry.delete(0, tk.END)
            self.ip_entry.config(fg='black')
    
    def validate_ip_address(self, ip):
        """Validate IP address format"""
        try:
            parts = ip.split('.')
            if len(parts) != 4:
                return False
            for part in parts:
                num = int(part)
                if num < 0 or num > 255:
                    return False
            return True
        except ValueError:
            return False

    def connect_to_server(self):
        """Connect to the RPi server"""
        # Get IP from entry field
        entered_ip = self.ip_entry.get().strip()
        
        # Check if placeholder text is still there
        if entered_ip == self.ip_placeholder or entered_ip == "":
            self.log_message("Please enter a valid IP address", "ERROR")
            messagebox.showerror("Connection Error", "Please enter the Raspberry Pi IP address")
            self.ip_entry.focus()
            return
        
        # Validate IP address format
        if not self.validate_ip_address(entered_ip):
            self.log_message(f"Invalid IP address format: {entered_ip}", "ERROR")
            messagebox.showerror("Connection Error", "Please enter a valid IP address (e.g., 192.168.1.100)")
            self.ip_entry.focus()
            self.ip_entry.select_range(0, tk.END)
            return
        
        self.server_ip = entered_ip
        command_socket = None
        video_socket = None
        
        try:
            # Connect to command server first
            self.log_message(f"Connecting to command server at {self.server_ip}:{self.command_port}...")
            command_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            command_socket.settimeout(10)  # Increased timeout for initial connection
            command_socket.connect((self.server_ip, self.command_port))
            
            # Connect to video server
            self.log_message(f"Connecting to video server at {self.server_ip}:{self.video_port}...")
            video_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            video_socket.settimeout(10)  # Increased timeout for initial connection
            video_socket.connect((self.server_ip, self.video_port))
            
            # Only assign if both connections successful
            self.command_socket = command_socket
            self.video_socket = video_socket
            
            self.connected = True
            self.connect_btn.config(state=tk.DISABLED)
            self.disconnect_btn.config(state=tk.NORMAL)
            self.ip_entry.config(state=tk.DISABLED)  # Disable IP entry while connected
            
            # Disable round number controls when connected
            self.prev_round_btn.config(state=tk.DISABLED)
            self.next_round_btn.config(state=tk.DISABLED)
            
            # Start threads for receiving data
            self.start_receiver_threads()
            
            self.log_message(f"Connected to server at {self.server_ip}", "SUCCESS")
            
        except socket.timeout:
            self.log_message(f"Connection timeout to {self.server_ip}", "ERROR")
            # Clean up any partial connections
            if command_socket:
                command_socket.close()
            if video_socket:
                video_socket.close()
            messagebox.showerror("Connection Error", f"Connection timeout to server at {self.server_ip}.\n\nPlease check:\n• Raspberry Pi is powered on and accessible\n• Server is running on Raspberry Pi\n• Network connectivity")
        except ConnectionRefusedError:
            self.log_message(f"Connection refused by {self.server_ip}", "ERROR")
            # Clean up any partial connections
            if command_socket:
                command_socket.close()
            if video_socket:
                video_socket.close()
            messagebox.showerror("Connection Error", f"Connection refused by server at {self.server_ip}.\n\nPlease check:\n• Server is running on Raspberry Pi\n• Correct ports (8080, 8081) are open\n• Firewall settings")
        except Exception as e:
            self.log_message(f"Failed to connect to {self.server_ip}: {e}", "ERROR")
            # Clean up any partial connections
            if command_socket:
                command_socket.close()
            if video_socket:
                video_socket.close()
            messagebox.showerror("Connection Error", f"Failed to connect to server at {self.server_ip}:\n\n{str(e)}\n\nPlease check:\n• Raspberry Pi is powered on\n• IP address is correct\n• Both devices are on same network\n• Server is running on Raspberry Pi")
    
    def disconnect_from_server(self):
        """Disconnect from the RPi server"""
        self.connected = False
        
        # Close sockets with proper error handling
        if self.command_socket:
            try:
                self.command_socket.close()
            except Exception:
                pass  # Ignore errors when closing
            self.command_socket = None
            
        if self.video_socket:
            try:
                self.video_socket.close()
            except Exception:
                pass  # Ignore errors when closing
            self.video_socket = None
            
        # Update UI
        self.connect_btn.config(state=tk.NORMAL)
        self.disconnect_btn.config(state=tk.DISABLED)
        self.ip_entry.config(state=tk.NORMAL)  # Re-enable IP entry when disconnected
        
        # Re-enable round number controls when disconnected
        self.prev_round_btn.config(state=tk.NORMAL)
        self.next_round_btn.config(state=tk.NORMAL)
        
        # Clear video display
        if self.video_label:
            self.video_label.config(image='', text="No Video Signal")
            # Clear the reference to avoid memory leaks
            self.video_label.image = None
        
        # Reset status display
        self.drone_status = {
            'connected': False,
            'battery': 0,
            'altitude': 0,
            'speed': 0,
            'mode': 'unknown'
        }
        self.update_status_display(self.drone_status)
        
        self.log_message("Disconnected from server", "WARNING")
    
    def start_receiver_threads(self):
        """Start threads to receive video and messages"""
        # Video receiver thread
        video_thread = threading.Thread(target=self.receive_video)
        video_thread.daemon = True
        video_thread.start()
        
        # Message receiver thread  
        message_thread = threading.Thread(target=self.receive_messages)
        message_thread.daemon = True
        message_thread.start()
    
    def receive_video(self):
        """Receive and display video frames"""
        payload_size = struct.calcsize("L")
        consecutive_errors = 0
        max_consecutive_errors = 5
        
        while self.connected and self.video_socket:
            try:
                # Set socket timeout for video receiving
                self.video_socket.settimeout(2.0)
                
                # Receive frame size
                data = b''
                while len(data) < payload_size:
                    try:
                        packet = self.video_socket.recv(4096)
                        if not packet:
                            break
                        data += packet
                    except socket.timeout:
                        if self.connected:
                            continue  # Try again
                        else:
                            break
                
                if len(data) < payload_size:
                    break
                    
                packed_msg_size = data[:payload_size]
                data = data[payload_size:]
                msg_size = struct.unpack("L", packed_msg_size)[0]
                
                # Sanity check on frame size
                if msg_size > 10 * 1024 * 1024:  # 10MB max frame size
                    self.log_message(f"Received invalid frame size: {msg_size} bytes", "WARNING")
                    continue
                
                # Receive frame data
                while len(data) < msg_size:
                    try:
                        remaining = msg_size - len(data)
                        chunk_size = min(4096, remaining)
                        packet = self.video_socket.recv(chunk_size)
                        if not packet:
                            break
                        data += packet
                    except socket.timeout:
                        if self.connected:
                            continue  # Try again
                        else:
                            break
                
                if len(data) < msg_size:
                    break
                    
                frame_data = data[:msg_size]
                
                # Deserialize and display frame
                try:
                    frame = pickle.loads(frame_data)
                    # Try to decode as color first, fallback to grayscale
                    decoded_frame = cv2.imdecode(frame, cv2.IMREAD_COLOR)
                    
                    # If color decode failed or resulted in grayscale, try grayscale decode
                    if decoded_frame is None or len(decoded_frame.shape) == 2:
                        decoded_frame = cv2.imdecode(frame, cv2.IMREAD_GRAYSCALE)
                        if decoded_frame is not None:
                            # Convert single-channel grayscale to 3-channel for display
                            decoded_frame = cv2.cvtColor(decoded_frame, cv2.COLOR_GRAY2BGR)
                    
                    if decoded_frame is not None and decoded_frame.size > 0:
                        self.display_frame(decoded_frame)
                        consecutive_errors = 0  # Reset error counter on success
                    else:
                        consecutive_errors += 1
                        if consecutive_errors < max_consecutive_errors:
                            continue
                        else:
                            self.log_message("Too many consecutive invalid frames", "ERROR")
                            break
                except (pickle.PickleError, cv2.error) as e:
                    consecutive_errors += 1
                    if consecutive_errors < max_consecutive_errors:
                        self.log_message(f"Frame decode error: {e}", "WARNING")
                        continue
                    else:
                        self.log_message(f"Too many frame decode errors: {e}", "ERROR")
                        break
                    
            except socket.error as e:
                if self.connected:
                    self.log_message(f"Video socket error: {e}", "ERROR")
                break
            except Exception as e:
                consecutive_errors += 1
                if self.connected and consecutive_errors < max_consecutive_errors:
                    self.log_message(f"Video reception error: {e}", "WARNING")
                    time.sleep(0.1)  # Brief pause before retry
                    continue
                else:
                    if self.connected:
                        self.log_message(f"Too many video errors: {e}", "ERROR")
                    break
        
        # Update UI when video stops
        if self.video_label:
            self.video_label.config(image='', text="No Video Signal")
    
    def display_frame(self, frame):
        """Display a video frame in the GUI"""
        try:
            # Perform QR code scanning if active
            if self.qr_scanning_active:
                self.scan_qr_codes(frame.copy())
            
            # Convert BGR to RGB
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            
            # Resize frame to fit display area
            height, width = frame_rgb.shape[:2]
            max_width, max_height = 640, 480
            
            if width > max_width or height > max_height:
                scale = min(max_width/width, max_height/height)
                new_width = int(width * scale)
                new_height = int(height * scale)
                frame_rgb = cv2.resize(frame_rgb, (new_width, new_height))
            
            # Convert to PIL Image and then to PhotoImage
            image = Image.fromarray(frame_rgb)
            photo = ImageTk.PhotoImage(image)
            
            # Update the label
            self.video_label.config(image=photo, text="")
            self.video_label.image = photo  # Keep a reference
            
        except Exception as e:
            self.log_message(f"Frame display error: {e}", "ERROR")
    
    def receive_messages(self):
        """Receive messages from the server"""
        while self.connected and self.command_socket:
            try:
                data = self.command_socket.recv(1024)
                if not data:
                    break
                    
                message_data = json.loads(data.decode('utf-8'))
                self.process_server_message(message_data)
                
            except Exception as e:
                if self.connected:
                    self.log_message(f"Message reception error: {e}", "ERROR")
                break
    
    def process_server_message(self, message_data):
        """Process messages received from server"""
        msg_type = message_data.get('type', '')
        
        if msg_type == 'log':
            level = message_data.get('level', 'INFO')
            message = message_data.get('message', '')
            self.log_message(f"RPi: {message}", level)
            
        elif msg_type == 'status_update':
            self.update_status_display(message_data.get('status', {}))
    
    def update_status_display(self, status):
        """Update the status display"""
        self.drone_status.update(status)
        
        self.status_labels['connected'].config(text="Yes" if status.get('connected', False) else "No",
                                             fg='#27ae60' if status.get('connected', False) else '#e74c3c')
        self.status_labels['battery'].config(text=f"{status.get('battery', 0)}%")
        self.status_labels['altitude'].config(text=f"{status.get('altitude', 0):.1f}m")
        self.status_labels['speed'].config(text=f"{status.get('speed', 0):.1f}m/s")
        self.status_labels['mode'].config(text=status.get('mode', 'unknown'))
    
    def send_command(self, command_type, command):
        """Send a command to the server"""
        if not self.connected or not self.command_socket:
            self.log_message("Not connected to server", "ERROR")
            return False
            
        try:
            command_data = {
                'type': command_type,
                'command': command,
                'timestamp': time.time()
            }
            
            message = json.dumps(command_data)
            message_bytes = message.encode('utf-8')
            
            # Set a timeout for sending
            self.command_socket.settimeout(3.0)
            self.command_socket.sendall(message_bytes)
            
            self.log_message(f"Sent {command_type}: {command}")
            return True
            
        except socket.timeout:
            self.log_message(f"Command send timeout: {command_type} - {command}", "ERROR")
            return False
        except socket.error as e:
            self.log_message(f"Socket error sending command: {e}", "ERROR")
            # Connection may be broken, trigger reconnection
            if self.connected:
                self.disconnect_from_server()
            return False
        except Exception as e:
            self.log_message(f"Failed to send command: {e}", "ERROR")
            return False
    
    # QR Code scanning and camera control methods
    def start_qr_scan(self):
        """Start QR code scanning mode"""
        self.qr_scanning_active = True
        self.qr_scan_count = 0
        self.last_qr_data = None
        self.log_message(f"Started QR code scanning for Round {self.current_round}", "SUCCESS")
        
    def stop_qr_scan(self):
        """Stop QR code scanning mode"""
        self.qr_scanning_active = False
        self.log_message(f"Stopped QR code scanning. Total scanned: {self.qr_scan_count}", "INFO")
    
    def scan_qr_codes(self, frame):
        """Scan for QR codes in the current frame"""
        try:
            # Convert to grayscale for better QR detection
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            
            # Decode QR codes
            qr_codes = pyzbar.decode(gray)
            
            for qr_code in qr_codes:
                # Extract QR code data
                qr_data = qr_code.data.decode('utf-8')
                
                # Avoid duplicate processing of the same QR code
                if qr_data != self.last_qr_data:
                    self.last_qr_data = qr_data
                    self.qr_scan_count += 1
                    
                    # Log the QR code detection
                    self.log_message(f"QR Code #{self.qr_scan_count} detected in Round {self.current_round}:", "SUCCESS")
                    self.log_message(f"Data: {qr_data}", "INFO")
                    
                    # Process the QR code data
                    self.process_qr_code(qr_data)
                    
        except Exception as e:
            self.log_message(f"QR scanning error: {e}", "ERROR")
    
    def process_qr_code(self, qr_data):
        """Process the detected QR code data and send to local server"""
        try:
            # Log QR scan to system console
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.log_message(f"[Round {self.current_round}] QR Code #{self.qr_scan_count} scanned", "SUCCESS")
            self.log_message(f"QR Data: {qr_data}", "INFO")
            
            # Send QR code to local server for processing
            self.send_qr_to_server(self.current_round, qr_data)
            
            # Send to RPI server for logging
            self.send_command('qr_result', {
                'round': self.current_round,
                'timestamp': timestamp,
                'qr_code': qr_data,
                'count': self.qr_scan_count
            })
            
        except Exception as e:
            self.log_message(f"QR processing error: {e}", "ERROR")
    
    def toggle_color_mode(self):
        """Toggle between color and grayscale camera mode"""
        if not self.connected:
            self.log_message("Cannot toggle color mode - not connected to server", "ERROR")
            return
        
        self.log_message("Sending color mode toggle command to RPI...", "INFO")
        success = self.send_command('system', 'toggle_color_mode')
        
        if success:
            self.log_message("Color mode toggle command sent successfully", "SUCCESS")
        else:
            self.log_message("Failed to send color mode toggle command", "ERROR")
        
        # Round number management
    def prev_round(self):
        """Go to previous round"""
        if self.connected:
            self.log_message("Round number locked while connected to drone", "WARNING")
            return
        if self.current_round > 1:
            self.current_round -= 1
            self.round_number_var.set(str(self.current_round))
            self.log_message(f"Moved to Round {self.current_round}", "INFO")
    
    def next_round(self):
        """Go to next round"""
        if self.connected:
            self.log_message("Round number locked while connected to drone", "WARNING")
            return
        self.current_round += 1
        self.round_number_var.set(str(self.current_round))
        self.log_message(f"Moved to Round {self.current_round}", "INFO")
        
    # Legacy drone control methods (for controller interface)
    def takeoff(self):
        self.send_command('drone_control', 'takeoff')
        
    def land(self):
        self.send_command('drone_control', 'land')
        
    def rotate(self, direction):
        self.send_command('drone_control', f'rotate_{direction}')
        
    def emergency_stop(self):
        self.send_command('drone_control', 'emergency_stop')
        
    def get_status(self):
        self.send_command('text_command', 'status')
        
    def restart_camera(self):
        """Restart the camera on RPI (will temporarily disconnect video)"""
        if not self.connected:
            self.log_message("Cannot restart camera - not connected to server", "ERROR")
            return
        
        self.log_message("Sending camera restart command to RPI...", "WARNING")
        self.log_message("Note: Video feed will temporarily disconnect during restart", "INFO")
        success = self.send_command('system', 'restart_camera')
        
        if success:
            self.log_message("Camera restart command sent successfully", "SUCCESS")
        else:
            self.log_message("Failed to send camera restart command", "ERROR")
    
    def send_text_command(self, event=None):
        """Send a text command from the input field"""
        command = self.command_entry.get().strip()
        if command:
            self.send_command('text_command', command)
            self.command_entry.delete(0, tk.END)
            self.log_message(f"Sent: {command}")
    
    def on_closing(self):
        """Handle application closing"""
        self.running = False
        if self.connected:
            self.disconnect_from_server()
        self.root.destroy()


def main():
    """Main function"""
    root = tk.Tk()
    app = DroneControlClient(root)
    
    # Handle window closing
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    
    try:
        root.mainloop()
    except KeyboardInterrupt:
        app.on_closing()


if __name__ == "__main__":
    main() 