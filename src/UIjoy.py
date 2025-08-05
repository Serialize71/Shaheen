import time
import curses
from collections import deque
from itertools import cycle
import serial.tools.list_ports
import os
import pygame
from yamspy import MSPy
from pygame.locals import MOUSEMOTION, MOUSEBUTTONUP, MOUSEBUTTONDOWN

CTRL_LOOP_TIME = 1 / 100
SLOW_MSGS_LOOP_TIME = 1 / 5
NO_OF_CYCLES_AVERAGE_GUI_TIME = 10

pygame.init()
pygame.event.set_blocked((MOUSEMOTION, MOUSEBUTTONUP, MOUSEBUTTONDOWN))
pygame.joystick.init()
if pygame.joystick.get_count() == 0:
    raise RuntimeError("No joystick detected.")
joy = pygame.joystick.Joystick(0)
joy.init()

axis = []
button = []
throttle_trim = 0


def update():
    global axis, button, joy

    pygame.event.pump()
    if pygame.joystick.get_count() == 0:
        raise RuntimeError("Joystick disconnected!")

    try:
        joy = pygame.joystick.Joystick(0)
        axis = [joy.get_axis(i) for i in range(joy.get_numaxes())]
        button = [joy.get_button(i) for i in range(joy.get_numbuttons())]
    except pygame.error as err:
        raise RuntimeError("Joystick error during update!") from err


def detect_serial_port():
    ports = serial.tools.list_ports.comports()
    for port in ports:
        if "ACM" in port.device or "USB" in port.device:
            return port.device
    return "/dev/ttyACM0"


SERIAL_PORT = detect_serial_port()


def run_curses(external_function):
    result = 1
    try:
        screen = curses.initscr()
        curses.noecho()
        curses.cbreak()
        screen.timeout(0)
        screen.keypad(True)
        screen.addstr(1, 0, "Joystick mode: 'A' to arm, 'B' to disarm, 'X' to switch mode, hold R2 to reboot, 'Y' for failsafe", curses.A_BOLD)
        result = external_function(screen)
    finally:
        curses.nocbreak()
        screen.keypad(0)
        curses.echo()
        curses.endwin()
        if result == 1:
            print("An error occurred... probably the serial port is not available ;)")


def joy_controller(screen):
    global throttle_trim
    CMDS = {
        'roll': 1500,
        'pitch': 1500,
        'throttle': 900,
        'yaw': 1500,
        'aux1': 1000,
        'aux2': 1000
    }
    CMDS_ORDER = ['roll', 'pitch', 'throttle', 'yaw', 'aux1', 'aux2']

    try:
        screen.addstr(15, 0, f"Connecting to the FC on {SERIAL_PORT}...")
        with MSPy(device=SERIAL_PORT, loglevel='WARNING', baudrate=115200) as board:
            if board == 1:
                return 1

            board.INAV = getattr(board, 'INAV', False)
            screen.addstr(15, 0, f"Connected to FC on {SERIAL_PORT}")
            screen.clrtoeol()
            screen.move(1, 0)

            average_cycle = deque([0]*NO_OF_CYCLES_AVERAGE_GUI_TIME)
            screen.addstr(2, 0, f"Joystick: {joy.get_name()}")
            time.sleep(0.2)
            update()

            while True:
                start_time = time.time()
                char = screen.getch()
                curses.flushinp()

                try:
                    update()
                except Exception as e:
                    screen.addstr(3, 0, f"Joystick lost: {e}. Sending failsafe...")
                    CMDS['aux2'] = 1800
                    continue

                # Adjust throttle using buttons
                if len(button) > 7 and button[7]:  # R2 held
                    throttle_trim = min(1200, throttle_trim + 5)
                elif len(button) > 6 and button[6]:  # L2 held
                    throttle_trim = max(0, throttle_trim - 5)

                CMDS['throttle'] = 900 + throttle_trim

                def scale_axis(val): return int(1500 + max(-200, min(200, int(val * 200))))

                CMDS['roll'] = scale_axis(axis[3])
                CMDS['pitch'] = scale_axis(-axis[4])
                CMDS['yaw'] = scale_axis(axis[0])

                # Arm/disarm/mode buttons
                if len(button) > 0 and button[0]:
                    CMDS['aux1'] = 1800
                elif len(button) > 1 and button[1]:
                    CMDS['aux1'] = 1000
                elif len(button) > 3 and button[3]:
                    CMDS['aux2'] = (CMDS['aux2'] + 500) % 2000
                elif len(button) > 2 and button[2]:
                    CMDS['aux2'] = 1800
                elif len(button) > 9 and button[9]:
                    board.reboot()
                    time.sleep(0.2)
                    break

                # Send RC command
                if board.send_RAW_RC([CMDS[k] for k in CMDS_ORDER]):
                    dataHandler = board.receive_msg()
                    board.process_recv_data(dataHandler)

                screen.addstr(5, 0, f"Throttle: {CMDS['throttle']} ")
                screen.clrtoeol()

                end_time = time.time()
                cycle_time = end_time - start_time
                if cycle_time < CTRL_LOOP_TIME:
                    time.sleep(CTRL_LOOP_TIME - cycle_time)
                average_cycle.append(cycle_time)
                average_cycle.popleft()

    finally:
        screen.addstr(5, 0, "Disconnected from FC. Failsafe triggered.")
        screen.clrtoeol()


if __name__ == "__main__":
    run_curses(joy_controller)