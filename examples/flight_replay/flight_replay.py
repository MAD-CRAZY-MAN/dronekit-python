"""
flight_replay.py: 

This example requests a past flight from Droneshare, and then 'replays' 
the flight by sending waypoints to a vehicle.

Full documentation is provided at http://python.dronekit.io/examples/flight_replay.html
"""

from dronekit import connect, Command, VehicleMode, LocationGlobalRelative
from pymavlink import mavutil
import json, urllib, math
import time

#Set up option parsing to get connection string
import argparse  
parser = argparse.ArgumentParser(description='Load a telemetry log and use position data to create mission waypoints for a vehicle. Connects to SITL on local PC by default.')
parser.add_argument('--connect', help="vehicle connection target.")
parser.add_argument('--tlog', default='flight.tlog',
                   help="Telemetry log containing path to replay")
args = parser.parse_args()


def start_default_sitl(lat=None, lon=None):
    print "Starting copter simulator (SITL)"
    from dronekit_sitl import SITL
    sitl = SITL()
    sitl.download('copter', '3.3', verbose=True)
    if ((lat is not None and lon is None) or
        (lat is None and lon is not None)):
        print("Supply both lat and lon, or neither")
        exit(1)
    sitl_args = ['-I0', '--model', 'quad', ]
    if lat is not None:
        sitl_args.append('--home=%f,%f,584,353' % (lat,lon,))
    sitl.launch(sitl_args, await_ready=True, restart=True)
    connection_string='tcp:127.0.0.1:5760'
    return (sitl, connection_string)

def get_distance_metres(aLocation1, aLocation2):
    """
    Returns the ground distance in metres between two LocationGlobal objects.

    This method is an approximation, and will not be accurate over large distances and close to the 
    earth's poles. It comes from the ArduPilot test code: 
    https://github.com/diydrones/ardupilot/blob/master/Tools/autotest/common.py
    """
    dlat = aLocation2.lat - aLocation1.lat
    dlong = aLocation2.lon - aLocation1.lon
    return math.sqrt((dlat*dlat) + (dlong*dlong)) * 1.113195e5



def distance_to_current_waypoint():
    """
    Gets distance in metres to the current waypoint. 
    It returns None for the first waypoint (Home location).
    """
    nextwaypoint = vehicle.commands.next
    if nextwaypoint==0:
        return None
    missionitem=vehicle.commands[nextwaypoint-1] #commands are zero indexed
    lat = missionitem.x
    lon = missionitem.y
    alt = missionitem.z
    targetWaypointLocation = LocationGlobalRelative(lat,lon,alt)
    distancetopoint = get_distance_metres(vehicle.location.global_frame, targetWaypointLocation)
    return distancetopoint

def position_messages_from_tlog(filename):
    """Given telemetry log, get a series of wpts approximating the previous flight"""
    # Pull out just the global position msgs
    messages = []
    mlog = mavutil.mavlink_connection(filename)
    while True:
        try:
            m = mlog.recv_match(type=['GLOBAL_POSITION_INT'])
            if m is None:
                break
        except Exception:
            break
        # ignore we get where there is no fix:
        if m.lat == 0:
            continue
        messages.append(m)

        # Shrink the # of pts to be lower than the max # of wpts allowed by vehicle
    num_points = len(messages)
    max_points = 99
    if num_points > max_points:
        step = int(math.ceil((float(num_points) / max_points)))
        shorter = [messages[i] for i in xrange(0, num_points, step)]
        messages = shorter
    return messages

print("Generating waypoints from tlog...")
messages = position_messages_from_tlog(args.tlog)
print "Generated %d waypoints from tlog" % len(messages)
if len(messages) == 0:
    print("No position messages found in log")
    exit(0)

#Start SITL if no connection string specified
if args.connect:
    connection_string = args.connect
    sitl = None
else:
    start_lat = messages[0].lat/1.0e7
    start_lon = messages[0].lon/1.0e7

    (sitl, connection_string) = start_default_sitl(lat=start_lat,lon=start_lon)

# Connect to the Vehicle
print 'Connecting to vehicle on: %s' % connection_string
vehicle = connect(connection_string, wait_ready=True)


# Now download the vehicle waypoints
cmds = vehicle.commands
cmds.wait_ready()


cmds = vehicle.commands
cmds.clear()
for i in xrange(0, len(messages)):
    pt = messages[i]
    print "Point: %d %d" % (pt.lat, pt.lon,)
    lat = pt.lat
    lon = pt.lon
    # To prevent accidents we don't trust the altitude in the original flight, instead
    # we just put in a conservative cruising altitude.
    altitude = 30.0
    cmd = Command( 0,
                   0,
                   0,
                   mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT,
                   mavutil.mavlink.MAV_CMD_NAV_WAYPOINT,
                   0, 0, 0, 0, 0, 0,
                   lat/1.0e7, lon/1.0e7, altitude)
    cmds.add(cmd)

#Upload clear message and command messages to vehicle.
print("Uploading %d waypoints to vehicle..." % len(messages))
cmds.upload()

# Set mode to STABILISE for arming and takeoff:
while (vehicle.mode.name != "GUIDED"):
    vehicle.mode = VehicleMode("GUIDED")
    time.sleep(0.1)

while not vehicle.armed:      
    print("Arming vehicle")
    vehicle.armed = True
    print "Waiting for arming..."
    time.sleep(1)

print("Taking off")
aTargetAltitude = 30.0
vehicle.simple_takeoff(aTargetAltitude)

# Wait until the vehicle reaches a safe height
while True:
    requiredAlt = aTargetAltitude*0.95
    #Break and return from function just below target altitude.        
    if vehicle.location.global_relative_frame.alt>=requiredAlt: 
        print "Reached target altitude of ~%f" % (aTargetAltitude)
        break
    print " Altitude: %f < %f" % (vehicle.location.global_relative_frame.alt,
                                  requiredAlt)
    time.sleep(1)

print "Starting mission"

# Reset mission set to first (0) waypoint
vehicle.commands.next=0

# Set mode to AUTO to start mission:
while (vehicle.mode.name != "AUTO"):
    vehicle.mode = VehicleMode("AUTO")
    time.sleep(0.1)

# Monitor mission for 60 seconds then RTL and quit:
time_start = time.time()
while time.time() - time_start < 60:
    nextwaypoint=vehicle.commands.next
    print 'Distance to waypoint (%s): %s' % (nextwaypoint, distance_to_current_waypoint())

    if nextwaypoint==len(messages):
        print "Exit 'standard' mission when start heading to final waypoint"
        break;
    time.sleep(1)

print 'Return to launch'
while (vehicle.mode.name != "RTL"):
    vehicle.mode = VehicleMode("RTL")
    time.sleep(0.1)

#Close vehicle object before exiting script
print "Close vehicle object"
vehicle.close()

# Shut down simulator if it was started.
if sitl is not None:
    sitl.stop()

print("Completed...")
