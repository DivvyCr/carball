import itertools
import numpy as np
import pandas as pd
from carball.generated.api.stats.events_pb2 import Bump

from carball.generated.api.player_id_pb2 import PlayerId
from carball.json_parser.game import Game

from carball.generated.api import game_pb2

# Longest car hitbox is 131.49 (Breakout):
PLAYER_CONTACT_MAX_DISTANCE = 140
# Currently arbitrary:
MIN_BUMP_VELOCITY = 5000
# Currently arbitrary (degrees):
MAX_BUMP_ALIGN_ANGLE = 60
# Approx. half of goal height:
AERIAL_BUMP_HEIGHT = 300


class BumpAnalysis:
    def __init__(self, game: Game, proto_game: game_pb2):
        self.proto_game = proto_game

    def get_bumps_from_game(self, data_frame: pd.DataFrame, player_map):
        self.create_bumps_from_demos(self.proto_game)
        self.create_bumps_from_player_contact(data_frame, player_map)

    def create_bumps_from_demos(self, proto_game):
        for demo in proto_game.game_metadata.demos:
            self.add_bump(demo.frame_number, demo.victim_id, demo.attacker_id, True)

    def add_bump(self, frame: int, victim_id: PlayerId, attacker_id: PlayerId, is_demo: bool) -> Bump:
        bump = self.proto_game.game_stats.bumps.add()
        bump.frame_number = frame
        bump.attacker_id.id = attacker_id.id
        bump.victim_id.id = victim_id.id
        if is_demo:
            bump.is_demo = True

    # def analyse_bumps(self, data_frame: pd.DataFrame):

    def create_bumps_from_player_contact(self, data_frame, player_map):
        print("Entered.")
        # NOTES:
        #   Contact is not guaranteed (but most likely).
        #   [WIP] Attacker/Victim is not (yet) determined.

        # Get an array of player names to use for player combinations.
        player_names = []
        for player in player_map.values():
            player_names.append(player.name)

        # For each player pair combination, get possible contact distances.
        for player_pair in itertools.combinations(player_names, 2):
            # Get all frame idxs where players were within PLAYER_CONTACT_MAX_DISTANCE.
            players_close_frame_idxs = BumpAnalysis.get_players_close_frame_idxs(data_frame,
                                                                                 str(player_pair[0]),
                                                                                 str(player_pair[1]))
            BumpAnalysis.determine_bumps(data_frame, player_pair, players_close_frame_idxs)

            # if len(players_close_frame_idxs) > 0:
            #     BumpAnalysis.analyse_bump(data_frame, player_pair, players_close_frame_idxs)
            # else:
            #     print("Players did not get close.")

    @staticmethod
    def filter_consecutive_idxs(players_close_frame_idxs):
        # THIS SHOULD BE REDONE.
        # Two problems:
        #   Probably not best performance with that many loops. (This is the important one.)
        #   Values are taken from the start/end of time in close distance (bump likely happens in the middle).

        # Only append a value, if its diff is >= 3.
        diffs = np.diff(players_close_frame_idxs)
        players_close_single_frame_idxs = players_close_frame_idxs[np.append([0], diffs) >= 3]

        # If the above didn't append anything (all diffs <= 3), append the first value.
        if len(players_close_single_frame_idxs) == 0:
            players_close_single_frame_idxs = np.append(players_close_single_frame_idxs, players_close_frame_idxs[0])

        return players_close_single_frame_idxs

    @staticmethod
    def get_player_bump_alignment(data_frame, frame_idx, p1_name, p2_name):
        p1_vel_df = data_frame[p1_name][['vel_x', 'vel_y', 'vel_z']].loc[frame_idx]
        p1_pos_df = data_frame[p1_name][['pos_x', 'pos_y', 'pos_z']].loc[frame_idx]
        p2_pos_df = data_frame[p2_name][['pos_x', 'pos_y', 'pos_z']].loc[frame_idx]

        # Get the distance vector, directed from p1 to p2.
        # Then, convert it to a unit vector.
        pos1_df = p2_pos_df - p1_pos_df
        pos1 = [pos1_df.pos_x, pos1_df.pos_y, pos1_df.pos_y]
        unit_pos1 = pos1 / np.linalg.norm(pos1)

        # Get the velocity vector of p1.
        # Then, convert it to a unit vector.
        vel1 = [p1_vel_df.vel_x, p1_vel_df.vel_y, p1_vel_df.vel_z]
        unit_vel1 = vel1 / np.linalg.norm(vel1)

        # Find the angle between the position vector and the velocity vector.
        # If this is relatively aligned - p1 probably significantly bumped p2.
        ang = (np.arccos(np.clip(np.dot(unit_vel1, unit_pos1), -1.0, 1.0))) * 180 / np.pi
        # print(p1_name + "'s bump angle=" + str(ang))
        return ang

    @staticmethod
    def get_players_close_frame_idxs(data_frame, p1_name, p2_name):
        p1_pos_df = data_frame[p1_name][['pos_x', 'pos_y', 'pos_z']].dropna(axis=0)
        p2_pos_df = data_frame[p2_name][['pos_x', 'pos_y', 'pos_z']].dropna(axis=0)

        # Calculate the vector distances between the players.
        distances = (p1_pos_df.pos_x - p2_pos_df.pos_x) ** 2 + \
                    (p1_pos_df.pos_y - p2_pos_df.pos_y) ** 2 + \
                    (p1_pos_df.pos_z - p2_pos_df.pos_z) ** 2
        distances = np.sqrt(distances)
        # Only keep values < PLAYER_CONTACT_MAX_DISTANCE (see top of class).
        players_close_series = distances[distances < PLAYER_CONTACT_MAX_DISTANCE]
        # Get the frame indexes of the values (as ndarray).
        players_close_frame_idxs = players_close_series.index.to_numpy()
        return players_close_frame_idxs

    @staticmethod
    def get_players_close_intervals(players_close_frame_idxs):
        array = []
        subarray = []
        for index, i in enumerate(players_close_frame_idxs):
            diffs = np.diff(players_close_frame_idxs)
            subarray.append(i)
            if index >= len(diffs) or diffs[index] >= 3:
                array.append(subarray)
                subarray = []
        return array

    @staticmethod
    def analyse_bump(data_frame, player_pair, players_close_frame_idxs):
        # Filter consecutive indexes.
        players_close_single_frame_idxs = BumpAnalysis.filter_consecutive_idxs(players_close_frame_idxs)

        for possible_bump_frame_idx in players_close_single_frame_idxs:
            # Calculate bump alignments both ways.
            p1_bump_ang = BumpAnalysis.get_player_bump_alignment(data_frame, possible_bump_frame_idx,
                                                                 player_pair[0], player_pair[1])
            p2_bump_ang = BumpAnalysis.get_player_bump_alignment(data_frame, possible_bump_frame_idx,
                                                                 player_pair[1], player_pair[0])

            if p1_bump_ang < 30:
                s_rem = data_frame.game.seconds_remaining.loc[possible_bump_frame_idx] * -1
                # if data_frame.game.is_overtime.loc[possible_bump_frame_idx] is None:
                #     s_rem = s_rem * (-1)
                bump = (int(s_rem), str(player_pair[0]), str(player_pair[1]))
                # print(bump)

            if p2_bump_ang < 30:
                s_rem = data_frame.game.seconds_remaining.loc[possible_bump_frame_idx] * -1
                # if data_frame.game.is_overtime.loc[possible_bump_frame_idx] is None:
                #     s_rem = s_rem * (-1)
                bump = (int(s_rem), str(player_pair[1]), str(player_pair[0]))
                # print(bump)

    @staticmethod
    def determine_bumps(data_frame, player_pair, players_close_frame_idxs):
        players_close_frame_idxs_intervals = BumpAnalysis.get_players_close_intervals(players_close_frame_idxs)
        for interval in players_close_frame_idxs_intervals:
            first_frame = -1
            middle_frame = interval[int(len(interval) / 2)]
            last_frame = -1
            if len(interval) > 4:
                first_frame = interval[0]
                last_frame = interval[len(interval) - 1]

                p1_bump_ang1 = BumpAnalysis.get_player_bump_alignment(data_frame, first_frame,
                                                                      player_pair[0], player_pair[1])
                p1_bump_ang2 = BumpAnalysis.get_player_bump_alignment(data_frame, middle_frame,
                                                                      player_pair[0], player_pair[1])
                p1_bump_ang3 = BumpAnalysis.get_player_bump_alignment(data_frame, last_frame,
                                                                      player_pair[0], player_pair[1])
                p2_bump_ang1 = BumpAnalysis.get_player_bump_alignment(data_frame, first_frame,
                                                                      player_pair[1], player_pair[0])
                p2_bump_ang2 = BumpAnalysis.get_player_bump_alignment(data_frame, middle_frame,
                                                                      player_pair[1], player_pair[0])
                p2_bump_ang3 = BumpAnalysis.get_player_bump_alignment(data_frame, last_frame,
                                                                      player_pair[1], player_pair[0])
                BumpAnalysis.get_attacker_and_victim(player_pair[0], player_pair[1],
                                                     np.round(p1_bump_ang1, 2), np.round(p1_bump_ang3, 2),
                                                     np.round(p2_bump_ang1, 2), np.round(p2_bump_ang3, 2))
                # print(data_frame.game.seconds_remaining.loc[middle_frame], end=": ")
                # if BumpAnalysis.is_bump_alignment([p1_bump_ang1, p1_bump_ang2, p2_bump_ang1, p2_bump_ang2]) and BumpAnalysis.is_bump_velocity(data_frame, player_pair[0], player_pair[1], first_frame):
                #     print("Bump!", end=" ")
                #
                # if BumpAnalysis.is_aerial_bump(data_frame, player_pair[0], player_pair[1], first_frame):
                #     print("(high altitude)", end=" ")
                # print()

    @staticmethod
    def get_attacker_and_victim(p1_name, p2_name, p1_ba1, p1_ba3, p2_ba1, p2_ba3):
        # Basics.
        print(p1_name, end=": ")
        print(p1_ba1, end=" > ")
        print(p1_ba3)
        print(p2_name, end=": ")
        print(p2_ba1, end=" > ")
        print(p2_ba3)
        # print("===")

        # Angle differences.
        # print("Initial difference", end=": ")
        # print(np.round(abs(p1_ba1-p2_ba1), 2))
        # print("Last difference", end=": ")
        # print(np.round(abs(p1_ba3-p2_ba3), 2))
        # print("===")

        # Testing which player had a better initial angle,
        # then, need to check if the other player's angle has changed towards the primary player's (think momentum).
        if p1_ba1 < p2_ba1:
            if p1_ba1 < 45 and p2_ba1 > p2_ba3:
                print("p1 effectively attacked?")
            else:
                print("p1 attacked?")
        if p2_ba1 < p1_ba1:
            if p2_ba1 < 45 and p1_ba1 > p1_ba3:
                print("p2 effectively attacked?")
            else:
                print("p2 attacked?")
        print("===")

    @staticmethod
    def is_aerial_bump(data_frame: pd.DataFrame, p1_name: str, p2_name: str, at_frame: int):
        p1_pos_z = data_frame[p1_name].pos_z.loc[at_frame]
        p2_pos_z = data_frame[p2_name].pos_z.loc[at_frame]
        if all(x > AERIAL_BUMP_HEIGHT for x in [p1_pos_z, p2_pos_z]):
            # if all(abs(y) > 5080 for y in [p1_pos_y, p2_pos_y]):
            #     print("Backboard bump?")
            return True
        else:
            return False

    @staticmethod
    def is_bump_alignment(bump_angles):
        # Check if all bump alignment angles in the first half of the interval are above MAX_BUMP_ALIGN_ANGLE.
        if all(x > MAX_BUMP_ALIGN_ANGLE for x in bump_angles):
            return False
        else:
            return True

    @staticmethod
    def is_bump_velocity(data_frame: pd.DataFrame, p1_name: str, p2_name: str, at_frame: int):
        p1_vel_mag = np.sqrt(data_frame[p1_name].vel_x.loc[at_frame] ** 2 +
                             data_frame[p1_name].vel_y.loc[at_frame] ** 2 +
                             data_frame[p1_name].vel_z.loc[at_frame] ** 2)
        p2_vel_mag = np.sqrt(data_frame[p2_name].vel_x.loc[at_frame] ** 2 +
                             data_frame[p2_name].vel_y.loc[at_frame] ** 2 +
                             data_frame[p2_name].vel_z.loc[at_frame] ** 2)
        # Check if initial player velocities are below MIN_BUMP_VELOCITY.
        if all(x < MIN_BUMP_VELOCITY for x in [p1_vel_mag, p2_vel_mag]):
            return False
        else:
            return True
