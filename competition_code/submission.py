"""
Competition instructions:
Please do not change anything else but fill out the to-do sections.
"""

from collections import deque
from functools import reduce
import json
import os
from typing import List, Tuple, Dict, Optional
import math
import numpy as np
import roar_py_interface
from LateralController import LatController
from ThrottleController import ThrottleController
import atexit

# from scipy.interpolate import interp1d

useDebug = True
useDebugPrinting = False
debugData = {}


def dist_to_waypoint(location, waypoint: roar_py_interface.RoarPyWaypoint):
    return np.linalg.norm(location[:2] - waypoint.location[:2])


def filter_waypoints(
    location: np.ndarray,
    current_idx: int,
    waypoints: List[roar_py_interface.RoarPyWaypoint],
) -> int:
    for i in range(current_idx, len(waypoints) + current_idx):
        if dist_to_waypoint(location, waypoints[i % len(waypoints)]) < 3:
            return i % len(waypoints)
    return current_idx


def findClosestIndex(location, waypoints: List[roar_py_interface.RoarPyWaypoint]):
    lowestDist = 100
    closestInd = 0
    for i in range(0, len(waypoints)):
        dist = dist_to_waypoint(location, waypoints[i % len(waypoints)])
        if dist < lowestDist:
            lowestDist = dist
            closestInd = i
    return closestInd % len(waypoints)

def get_radius(loc1, loc2, loc3):
    """Returns the radius of a curve given 3 waypoints using the Menger Curvature Formula

    Args:
        wp ([roar_py_interface.RoarPyWaypoint]): A list of 3 RoarPyWaypoints

    Returns:
        float: The radius of the curve made by the 3 given waypoints
    """

    point1 = (loc1[0], loc1[1])
    point2 = (loc2[0], loc2[1])
    point3 = (loc3[0], loc3[1])

    # Calculating length of all three sides
    len_side_1 = round(math.dist(point1, point2), 3)
    len_side_2 = round(math.dist(point2, point3), 3)
    len_side_3 = round(math.dist(point1, point3), 3)
    # sp is semi-perimeter
    sp = (len_side_1 + len_side_2 + len_side_3) / 2

    # Calculating area using Herons formula
    area_squared = sp * (sp - len_side_1) * (sp - len_side_2) * (sp - len_side_3)
    
    # Calculating curvature using Menger curvature formula
    radius = (len_side_1 * len_side_2 * len_side_3) / (4 * math.sqrt(area_squared))

    return radius

def findCorners(track: [roar_py_interface.RoarPyWaypoint]):
    curAngle = track[0].roll_pitch_yaw[2]
    angleDiffForCorner = 0.15
    angleDiffForEnd = 0.075
    # radForCorner = 100
    isCorner = False
    cornerStartIndex = None
    corners = []

    for i in range(len(track) + 5):        
        farAngleDiff = abs(curAngle - track[(i + 8) % len(track)].roll_pitch_yaw[2])
        shortAngleDiff = abs(curAngle - track[(i + 5) % len(track)].roll_pitch_yaw[2])
        
        if (farAngleDiff > angleDiffForCorner or (shortAngleDiff > angleDiffForCorner and farAngleDiff < angleDiffForEnd)) and not isCorner:
            # cornerStart = track[i % len(track)]
            cornerStartIndex = i + 2
            isCorner = True
        elif farAngleDiff < angleDiffForEnd and isCorner:
            isCorner = False
            if i - cornerStartIndex > 7:
                # cornerEnd = track[(i + 4) % len(track)]
                cornerInfo = {}
                cornerInfo["startLoc"] = track[cornerStartIndex].location
                cornerInfo["midLoc"] = track[cornerStartIndex + round((i - cornerStartIndex) * 0.4)].location
                cornerInfo["endLoc"] = track[i].location
                cornerInfo["radius"] = get_radius(cornerInfo["startLoc"], cornerInfo["midLoc"], cornerInfo["endLoc"])
                corners.append(cornerInfo)
        
        curAngle = track[i % len(track)].roll_pitch_yaw[2]
    return corners

@atexit.register
def saveDebugData():
    if useDebug:
        print("Saving debug data")
        jsonData = json.dumps(debugData, indent=4)
        with open(
            f"{os.path.dirname(__file__)}\\debugData\\debugData.json", "w+"
        ) as outfile:
            outfile.write(jsonData)
        print("Debug Data Saved")


class RoarCompetitionSolution:
    def __init__(
        self,
        maneuverable_waypoints: List[roar_py_interface.RoarPyWaypoint],
        vehicle: roar_py_interface.RoarPyActor,
        camera_sensor: roar_py_interface.RoarPyCameraSensor = None,
        location_sensor: roar_py_interface.RoarPyLocationInWorldSensor = None,
        velocity_sensor: roar_py_interface.RoarPyVelocimeterSensor = None,
        rpy_sensor: roar_py_interface.RoarPyRollPitchYawSensor = None,
        occupancy_map_sensor: roar_py_interface.RoarPyOccupancyMapSensor = None,
        collision_sensor: roar_py_interface.RoarPyCollisionSensor = None,
    ) -> None:
        self.maneuverable_waypoints = maneuverable_waypoints
        self.vehicle = vehicle
        self.camera_sensor = camera_sensor
        self.location_sensor = location_sensor
        self.velocity_sensor = velocity_sensor
        self.rpy_sensor = rpy_sensor
        self.occupancy_map_sensor = occupancy_map_sensor
        self.collision_sensor = collision_sensor
        self.lat_controller = LatController()
        self.throttle_controller = ThrottleController()
        self.section_indeces = []
        self.num_ticks = 0
        self.section_start_ticks = 0
        self.current_section = 0
        self.lapNum = 1

    async def initialize(self) -> None:      
        # NOTE waypoints are changed through this line
        self.maneuverable_waypoints = (
            roar_py_interface.RoarPyWaypoint.load_waypoint_list(
                np.load(f"{os.path.dirname(__file__)}\\waypoints\\waypointsPrimary.npz")
            )[50:]
        )

        sectionLocations = [[-278, 372], [64, 890], [511, 1037], [762, 908], [198, 307], [-12, 38], [-85, -339], [-150, -1042], [-318, -991], [-352, -119]]
        for i in sectionLocations:
            self.section_indeces.append(
                findClosestIndex(i, self.maneuverable_waypoints)
            )
            
        self.cornerInfo = findCorners(roar_py_interface.RoarPyWaypoint.load_waypoint_list(
                np.load(f"{os.path.dirname(__file__)}\\waypoints\\monzaOriginalWaypoints.npz")
            ))

        print(f"True total length: {len(self.maneuverable_waypoints) * 3}")
        print(f"1 lap length: {len(self.maneuverable_waypoints)}")
        print(f"Section indexes: {self.section_indeces}")
        print("\nLap 1\n")

        # Receive location, rotation and velocity data
        vehicle_location = self.location_sensor.get_last_gym_observation()
        vehicle_rotation = self.rpy_sensor.get_last_gym_observation()
        vehicle_velocity = self.velocity_sensor.get_last_gym_observation()

        self.current_waypoint_idx = 0
        self.current_waypoint_idx = filter_waypoints(
            vehicle_location, self.current_waypoint_idx, self.maneuverable_waypoints
        )

    async def step(self) -> None:
        """
        This function is called every world step.
        Note: You should not call receive_observation() on any sensor here, instead use get_last_observation() to get the last received observation.
        You can do whatever you want here, including apply_action() to the vehicle.
        """
        self.num_ticks += 1

        # Receive location, rotation and velocity data
        vehicle_location = self.location_sensor.get_last_gym_observation()
        vehicle_rotation = self.rpy_sensor.get_last_gym_observation()
        vehicle_velocity = self.velocity_sensor.get_last_gym_observation()
        vehicle_velocity_norm = np.linalg.norm(vehicle_velocity)
        current_speed_kmh = vehicle_velocity_norm * 3.6

        # Find the waypoint closest to the vehicle
        self.current_waypoint_idx = filter_waypoints(
            vehicle_location, self.current_waypoint_idx, self.maneuverable_waypoints
        )

        # compute and print section timing
        for i, section_ind in enumerate(self.section_indeces):
            if (
                abs(self.current_waypoint_idx - section_ind) <= 2
                and i != self.current_section
            ):
                print(f"Section {i}: {self.num_ticks - self.section_start_ticks} ticks")
                self.section_start_ticks = self.num_ticks
                self.current_section = i
                if self.current_section == 0 and self.lapNum != 3:
                    self.lapNum += 1
                    print(f"\nLap {self.lapNum}\n")

        nextWaypointIndex = self.get_lookahead_index(current_speed_kmh)
        waypoint_to_follow = self.next_waypoint_smooth(current_speed_kmh)

        # Pure pursuit controller to steer the vehicle
        steer_control = self.lat_controller.run(
            vehicle_location, vehicle_rotation, waypoint_to_follow
        )

        # Custom controller to control the vehicle's speed
        waypoints_for_throttle = (self.maneuverable_waypoints * 2)[
            nextWaypointIndex : nextWaypointIndex + 300
        ]
        throttle, brake, gear = self.throttle_controller.run(
            waypoints_for_throttle,
            vehicle_location,
            current_speed_kmh,
            self.current_section,
            self.cornerInfo
        )

        steerMultiplier = round(abs(current_speed_kmh) / 120, 3)

        if self.current_section in [3]:
            steerMultiplier *= 1
        # if self.current_section == 4:
        #     steerMultiplier = min(1.4, steerMultiplier * 1.4)
        # if self.current_section in [6]:
        #     steerMultiplier = min(steerMultiplier * 5, 5.35)
        if self.current_section == 6:
            steerMultiplier *= 2.6
        # if self.current_section == 7:
        #     steerMultiplier *= 2
        # if self.current_section == 9:
        #     steerMultiplier = max(steerMultiplier, 1.6)

        control = {
            "throttle": np.clip(throttle, 0, 1),
            "steer": np.clip(steer_control * steerMultiplier, -1, 1),
            "brake": np.clip(brake, 0, 1),
            "hand_brake": 0,
            "reverse": 0,
            "target_gear": gear,  # Gears do not appear to have an impact on speed
        }
        
        # Store debug data for later use
        if useDebug:
            debugData[self.num_ticks] = {}
            debugData[self.num_ticks]["loc"] = [
                round(vehicle_location[0].item(), 3),
                round(vehicle_location[1].item(), 3),
            ]
            debugData[self.num_ticks]["throttle"] = round(float(control["throttle"]), 3)
            debugData[self.num_ticks]["brake"] = round(float(control["brake"]), 3)
            debugData[self.num_ticks]["steer"] = round(float(control["steer"]), 10)
            debugData[self.num_ticks]["speed"] = round(current_speed_kmh, 3)
            debugData[self.num_ticks]["lap"] = self.lapNum
            
            # Print debug data
            if useDebugPrinting and self.num_ticks % 2 == 0:
                print(
                    f"- Current location: ({vehicle_location[0].item():.2f}, {vehicle_location[1].item():.2f}) index {self.current_waypoint_idx} section {self.current_section} \n\
Target waypoint: ({waypoint_to_follow.location[0]:.2f}, {waypoint_to_follow.location[1]:.2f}) index {nextWaypointIndex} \n\
Distance to target waypoint: {math.sqrt((waypoint_to_follow.location[0] - vehicle_location[0].item()) ** 2 + (waypoint_to_follow.location[1] - vehicle_location[1].item()) ** 2):.3f}\n"
                )

                print(
                    f"--- Speed: {current_speed_kmh:.2f} kph \n\
Throttle: {control['throttle']:.3f} \n\
Brake: {control['brake']:.3f} \n\
Steer: {control['steer']:.10f} \n"
                )

        await self.vehicle.apply_action(control)
        return control

    def get_lookahead_value(self, speed):
        """
        Returns the number of waypoints to look ahead based on the speed the car is currently going
        """
        speed_to_lookahead_dict = {
            90: 9,
            110: 11,
            130: 14,
            160: 18,
            180: 22,
            200: 26,
            250: 30,
            300: 35,
        }

        # Interpolation method
        # NOTE does not work as well as the dictionary lookahead method, likely to cause crashes.

        # speedBoundList = [0, 90, 110, 130, 160, 180, 200, 250, 300]
        # lookaheadList = [5, 11, 13, 15, 18, 22, 25, 28, 32]

        # interpolationFunction = interp1d(speedBoundList, lookaheadList)
        # return int(interpolationFunction(speed))

        for speed_upper_bound, num_points in speed_to_lookahead_dict.items():
            if speed < speed_upper_bound:
                return num_points
        return 8

    def get_lookahead_index(self, speed):
        """
        Adds the lookahead waypoint to the current waypoint and normalizes it so that the value does not go out of bounds
        """
        num_waypoints = self.get_lookahead_value(speed)
        # print("speed " + str(speed)
        #       + " cur_ind " + str(self.current_waypoint_idx)
        #       + " num_points " + str(num_waypoints)
        #       + " index " + str((self.current_waypoint_idx + num_waypoints) % len(self.maneuverable_waypoints)) )
        if self.current_section == 2:
            return (self.current_waypoint_idx + 20) % len(
                self.maneuverable_waypoints
            )
        return (self.current_waypoint_idx + num_waypoints) % len(
            self.maneuverable_waypoints
        )
    
    # Old code (used with PID)
    # def get_lateral_pid_config(self):
    #     """
    #     Returns the PID values for the lateral (steering) PID
    #     """   
    #     with open(
    #         f"{os.path.dirname(__file__)}\\configs\\LatPIDConfig.json", "r"
    #     ) as file:
    #         config = json.load(file)
    #     return config

    # The idea and code for averaging points is from smooth_waypoint_following_local_planner.py (Summer 2023)
    def next_waypoint_smooth(self, current_speed: float):
        """
        If the speed is higher than 70, 'smooth out' the path that the car will take
        """
        if current_speed > 70 and current_speed < 300:
            target_waypoint = self.average_point(current_speed)
        else:
            new_waypoint_index = self.get_lookahead_index(current_speed)
            target_waypoint = self.maneuverable_waypoints[new_waypoint_index]

        return target_waypoint

    def average_point(self, current_speed):
        """
        Returns a new averaged waypoint based on the location of a number of other waypoints
        """
        next_waypoint_index = self.get_lookahead_index(current_speed)
        lookahead_value = self.get_lookahead_value(current_speed)
        num_points = lookahead_value * 2

        # Section specific tuning
        if self.current_section == 0:
            num_points = round(lookahead_value * 1.5)
        if self.current_section == 3:
            next_waypoint_index = self.current_waypoint_idx + 15
        if self.current_section == 4:
            # num_points = lookahead_value - 4
            next_waypoint_index = self.current_waypoint_idx + 12
        # if self.current_section == 5:
        #     num_points = round(lookahead_value * 1.35)
        if self.current_section == 6:
            num_points = 4
            next_waypoint_index = self.current_waypoint_idx + 16
        # if self.current_section == 7:
        #     num_points = round(lookahead_value * 1.25)
        if self.current_section == 9:
            (self.current_waypoint_idx + 14) % len(self.maneuverable_waypoints)
            num_points = 0

        start_index_for_avg = (next_waypoint_index - (num_points // 2)) % len(
            self.maneuverable_waypoints
        )

        next_waypoint = self.maneuverable_waypoints[next_waypoint_index]
        next_location = next_waypoint.location

        sample_points = [
            (start_index_for_avg + i) % len(self.maneuverable_waypoints)
            for i in range(0, num_points)
        ]
        if num_points > 3:
            location_sum = reduce(
                lambda x, y: x + y,
                (self.maneuverable_waypoints[i].location for i in sample_points),
            )
            num_points = len(sample_points)
            new_location = location_sum / num_points
            shift_distance = np.linalg.norm(next_location - new_location)
            max_shift_distance = 2.0
            if self.current_section == 1:
                max_shift_distance = 0.2
            if shift_distance > max_shift_distance:
                uv = (new_location - next_location) / shift_distance
                new_location = next_location + uv * max_shift_distance

            target_waypoint = roar_py_interface.RoarPyWaypoint(
                location=new_location,
                roll_pitch_yaw=np.ndarray([0, 0, 0]),
                lane_width=0.0,
            )
            # if next_waypoint_index > 1900 and next_waypoint_index < 2300:
            #   print("AVG: next_ind:" + str(next_waypoint_index) + " next_loc: " + str(next_location)
            #       + " new_loc: " + str(new_location) + " shift:" + str(shift_distance)
            #       + " num_points: " + str(num_points) + " start_ind:" + str(start_index_for_avg)
            #       + " curr_speed: " + str(current_speed))

        else:
            target_waypoint = self.maneuverable_waypoints[next_waypoint_index]

        return target_waypoint
