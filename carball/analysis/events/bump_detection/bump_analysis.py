import itertools
import numpy as np
import pandas as pd
from carball.generated.api.stats.events_pb2 import Bump

from carball.generated.api.player_id_pb2 import PlayerId
from carball.json_parser.game import Game

from carball.generated.api import game_pb2

# Longest car hitbox is 131.49 (Breakout)
PLAYER_CONTACT_MAX_DISTANCE = 150


class BumpAnalysis:
    def __init__(self, game: Game, proto_game: game_pb2):
        self.proto_game = proto_game

    def get_bumps_from_game(self, data_frame: pd.DataFrame, player_map):
        self.create_bumps_from_demos(self.proto_game)
        self.create_bumps_from_player_contact(data_frame, player_map)

        self.analyze_bumps(data_frame)

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

    def analyze_bumps(self, data_frame: pd.DataFrame):
        for bump in self.proto_game.game_stats.bumps:
            self.analyze_bump(bump, data_frame)

    def analyze_bump(self, bump: Bump, data_frame: pd.DataFrame):
        frame_number = bump.frame_number

    def create_bumps_from_player_contact(self, data_frame, player_map):
        # NOTES:
        #   Contact is not guaranteed (but most likely).
        #   Attacker/Victim is not determined.

        # Get an array of player names to use for player combinations.
        player_names = []
        for player in player_map.values():
            player_names.append(player.name)

        # For each player pair combination, get possible contact distances.
        for player_pair in itertools.combinations(player_names, 2):
            p1_pos_df = data_frame[str(player_pair[0])][['pos_x', 'pos_y', 'pos_z']].dropna(axis=0)
            p2_pos_df = data_frame[str(player_pair[1])][['pos_x', 'pos_y', 'pos_z']].dropna(axis=0)

            # Calculate the vector distances between the players.
            distances = (p1_pos_df.pos_x - p2_pos_df.pos_x) ** 2 + (p1_pos_df.pos_y - p2_pos_df.pos_y) ** 2 + (
                        p1_pos_df.pos_z - p2_pos_df.pos_z) ** 2
            distances = np.sqrt(distances)
            # Only keep values < PLAYER_CONTACT_MAX_DISTANCE (see top of class).
            players_close_series = distances[distances < PLAYER_CONTACT_MAX_DISTANCE]
            # Get the frame indexes of the values.
            players_close_frame_idxs = players_close_series.index.to_numpy()
            # Filter consecutive indexes.
            players_close_single_frame_idxs = BumpAnalysis.filter_consecutive_idxs(players_close_frame_idxs)

            for possible_bump_frame_idx in players_close_single_frame_idxs:

                # Calculate bump alignments both ways.
                p1_bump_ang = BumpAnalysis.get_player_bump_alignment(data_frame, possible_bump_frame_idx,
                                                                     player_pair[0], player_pair[1])
                p2_bump_ang = BumpAnalysis.get_player_bump_alignment(data_frame, possible_bump_frame_idx,
                                                                     player_pair[1], player_pair[0])

                if p1_bump_ang < 30:
                    print(data_frame.game.seconds_remaining.loc[possible_bump_frame_idx])
                    print(" > " + player_pair[0] + " on " + player_pair[1])

                if p2_bump_ang < 30:
                    print(data_frame.game.seconds_remaining.loc[possible_bump_frame_idx])
                    print(" > " + player_pair[1] + " on " + player_pair[0])

                # ang_diff = abs(p1_bump_ang - p2_bump_ang)
                # if ang_diff > 90:
                #     print(" > PRIORITY 1")
                # elif ang_diff > 60:
                #     print(" >> Priority 2")
                # elif ang_diff > 30:
                #     print(" >>> Priority 3")

    @staticmethod
    def filter_consecutive_idxs(players_close_frame_idxs):
        # THIS SHOULD BE REDONE.
        # Two problems:
        #   Probably not best performance with that many loops. (This is the important one.)
        #   Values are taken from the start/end of time in close distance (bump likely happens in the middle).

        # Only append a value, if its diff is >= 3.
        players_close_single_frame_idxs = players_close_frame_idxs[np.append([0],
                                                                             np.diff(players_close_frame_idxs)) >= 3]

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
