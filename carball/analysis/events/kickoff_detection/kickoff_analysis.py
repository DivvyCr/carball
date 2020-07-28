import logging
from typing import Dict, Callable

import numpy as np
import pandas as pd

from carball.generated.api import game_pb2
from carball.generated.api.metadata.game_metadata_pb2 import Goal
from carball.generated.api.player_pb2 import Player
from carball.generated.api.stats.kickoff_pb2 import KickoffStats
from carball.generated.api.stats import kickoff_pb2 as kickoff
from carball.json_parser.game import Game

logger = logging.getLogger(__name__)

FRAMES_AFTER_TOUCH = 20        # Arbitrary.
KICKOFF_GOAL_MAX_TURNOVERS = 5 # 2x fifty-fifty and a shot.


class BaseKickoff:

    @staticmethod
    def analyse_kickoffs(game: Game, proto_game: game_pb2,
                         id_creator: Callable, player_map: Dict[str, Player],
                         data_frame: pd.DataFrame, kickoff_frames: pd.DataFrame,
                         first_touch_frames: pd.DataFrame) -> Dict[int, KickoffStats]:
        kickoffs = dict()
        goals = proto_game.game_metadata.goals
        num_goals = len(goals)

        # Set DataFrame extremes.
        last_frame = data_frame.last_valid_index()
        first_frame = data_frame.first_valid_index()
        #
        # pd.set_option("display.max_rows", None)
        # pd.set_option("display.max_columns", None)
        # print(data_frame.game)

        ot = data_frame.game.is_overtime.at[data_frame.last_valid_index()]

        for index, frame_idx in enumerate(kickoff_frames):
            print("Kickoff #" + str(index))
            print("\twith " + str(data_frame.game.seconds_remaining.at[frame_idx]) + " seconds remaining.")

            proto_kickoff = proto_game.game_stats.kickoff_stats.add()

            # Create a DataFrame for the kickoff.
            #    'max()' and 'min()' are used to avoid underflow/overflow errors.
            #    'touch_frame+20' is used arbitrarily to extend the DataFrame a bit beyond the first touch.
            touch_frame = first_touch_frames[index]
            kickoff_data_frame = data_frame.loc[
                                 max(first_frame, frame_idx):  min(touch_frame + FRAMES_AFTER_TOUCH, last_frame)]

            # Set API fields to appropriate values.
            proto_kickoff.start_frame = frame_idx
            proto_kickoff.touch_frame = touch_frame
            proto_kickoff.type = BaseKickoff.get_kickoff_type(proto_kickoff.touch.players)

            # NOTE: Need check, because the first kickoff is without a goal
            # (and FFs may also be after kickoff but before a goal).
            if index < num_goals:
                BaseKickoff.get_goal_data(proto_kickoff, goals[index], data_frame)

            BaseKickoff.debug_kickoff_timings(data_frame, kickoff_data_frame, proto_kickoff)

            BaseKickoff.set_first_touch_player(data_frame, kickoff_data_frame, proto_kickoff, player_map)

            BaseKickoff.is_kickoff_goal(data_frame, proto_kickoff)

            # DivvyC: Not sure why we use frame_idx instead of index.
            kickoffs[frame_idx] = proto_kickoff

        return kickoffs

    @staticmethod
    def set_kickoff_player_stats(proto_kickoff, player, data_frame: pd.DataFrame):
        kickoff_start_frame = proto_kickoff.start_frame
        kickoff_touch_frame = proto_kickoff.touch_frame

        kickoff_player = proto_kickoff.touch.players.add()
        kickoff_player.player.id = player.id.id

        kickoff_player.kickoff_position, kickoff_player.start_left = BaseKickoff.get_kickoff_position(player,
                                                                                                      data_frame,
                                                                                                      kickoff_start_frame)

        kickoff_player.touch_position = BaseKickoff.get_touch_position(player, data_frame,
                                                                       kickoff_start_frame, kickoff_touch_frame)
        kickoff_player.boost = data_frame[player.name]['boost'][kickoff_touch_frame]
        kickoff_player.ball_dist = BaseKickoff.get_dist(data_frame, player.name, kickoff_touch_frame)
        kickoff_player.player_position.pos_x = data_frame[player.name]['pos_x'][kickoff_touch_frame]
        kickoff_player.player_position.pos_y = data_frame[player.name]['pos_y'][kickoff_touch_frame]
        kickoff_player.player_position.pos_z = data_frame[player.name]['pos_z'][kickoff_touch_frame]

        kickoff_player.start_position.pos_x = data_frame[player.name]['pos_x'][kickoff_start_frame]
        kickoff_player.start_position.pos_y = data_frame[player.name]['pos_y'][kickoff_start_frame]
        kickoff_player.start_position.pos_z = data_frame[player.name]['pos_z'][kickoff_start_frame]
        BaseKickoff.set_jumps(kickoff_player, player, data_frame, kickoff_start_frame)
        BaseKickoff.set_boost_time(kickoff_player, player, data_frame, kickoff_start_frame)
        return kickoff_player

    @staticmethod
    def set_first_touch_player(data_frame: pd.DataFrame, kickoff_data_frame: pd.DataFrame, proto_kickoff,
                               player_map: Dict[str, Player]):
        """
        Find and set (to the API) the player who touched the ball first on kickoff.
        """
        kickoff_start_frame = proto_kickoff.start_frame
        kickoff_touch_frame = proto_kickoff.touch_frame

        # Initialise variables for closest player calculation.
        closest_player_distance = 10000000
        closest_player_id = 0

        # Calculate and set player stats for the kickoff.
        for player in player_map.values():
            if player.name not in data_frame:
                continue

            # NOTE: kickoff_player is a proto object within the proto_kickoff object.
            kickoff_player = BaseKickoff.set_kickoff_player_stats(proto_kickoff, player, kickoff_data_frame)

            # NOTE: The ball_dist was calculated previously, at the touch frame.
            if kickoff_player.ball_dist < closest_player_distance:
                closest_player_distance = kickoff_player.ball_dist
                closest_player_id = player.id.id

        if closest_player_distance != 10000000:
            # Todo use hit analysis
            proto_kickoff.touch.first_touch_player.id = closest_player_id

    @staticmethod
    def set_boost_time(kickoff_player, player: Player, data_frame: pd.DataFrame, frame: int):
        if 'boost_collect' in data_frame[player.name].keys():
            collected_boost_df = data_frame[player.name]['boost_collect']
            collected_boost_df = collected_boost_df[collected_boost_df > 34]
            if len(collected_boost_df) > 0:
                kickoff_player.boost_time = data_frame['game']['delta'][frame:collected_boost_df.index.values[0]].sum()

    @staticmethod
    def set_jumps(kickoff_player, player: Player, data_frame: pd.DataFrame, frame: int):
        jump_active_df = data_frame[player.name]['jump_active']

        # Make sure that we are not doing diffs on booleans
        jump_active_df = jump_active_df.astype(float)

        # check the kickoff frames (and then some) for jumps & big boost collection
        jump_active_df = jump_active_df[jump_active_df.diff(1) > 0]
        BaseKickoff.add_jumps(kickoff_player, data_frame, frame, jump_active_df)

        """for f in range(frame, )):
            if boost:
                if collected_boost_df[f] == True:

            if jump_active_df[f] != jump_active_df[f-1] or double_jump_active_df[f] != double_jump_active_df[f-1]:
                kPlayer.jumps.append(data_frame['game']['delta'][frame:f].sum())"""

    @staticmethod
    def add_jumps(kPlayer, data_frame, frame, jumps):
        pass

    @staticmethod
    def get_kickoff_type(players: list):
        #
        diagonals = [player.kickoff_position for player in players].count(0)
        offcenter = [player.kickoff_position for player in players].count(1)
        goalies = [player.kickoff_position for player in players].count(2)
        if len(players) == 6:
            # 3's
            if diagonals == 4:
                if offcenter == 2:
                    return kickoff.THREES_DIAG_DIAG_OFFCENT
                if goalies == 2:
                    return kickoff.THREES_DIAG_DIAG_GOAL
            if diagonals == 2:
                if offcenter == 4:
                    return kickoff.THREES_DIAG_OFFCENT_OFFCENT
                if offcenter == 2:
                    return kickoff.THREES_DIAG_OFFCENT_GOAL
            if offcenter == 4:
                return kickoff.THREES_OFFCENT_OFFCENT_GOAL
        if len(players) == 4:
            if diagonals == 4:
                return kickoff.TWOS_DIAG_DIAG
            if diagonals == 2:
                if offcenter == 2:
                    return kickoff.TWOS_DIAG_OFFCENT
                if goalies == 2:
                    return kickoff.TWOS_DIAG_GOAL
            if offcenter == 4:
                return kickoff.TWOS_OFFCENT_OFFCENT
            if offcenter == 2:
                if goalies == 2:
                    return kickoff.TWOS_OFFCENT_GOAL
        if len(players) == 2:
            if diagonals == 2:
                return kickoff.DUEL_DIAG
            if offcenter == 2:
                return kickoff.DUEL_OFFCENT
            if goalies == 2:
                return kickoff.DUEL_GOAL
        return kickoff.UNKNOWN_KICKOFF_TYPE

    @staticmethod
    def get_kickoff_position(player_class: Player, data_frame: pd.DataFrame, frame: int):
        player = player_class.name
        player_df = data_frame[player]
        pos_x = player_df['pos_x'][frame]
        start_left = not ((pos_x < 0) ^ player_class.is_orange)
        kickoff_position = kickoff.UNKNOWN_KICKOFF_POS
        if abs(abs(pos_x) - 2050) < 100:
            kickoff_position = kickoff.DIAGONAL
        elif abs(abs(pos_x) - 256) < 100:
            kickoff_position = kickoff.OFFCENTER
        elif abs(abs(pos_x)) < 4:
            kickoff_position = kickoff.GOALIE

        return kickoff_position, start_left

    @staticmethod
    def get_dist(data_frame: pd.DataFrame, player: str, frame: int):
        player_df = data_frame[player]
        dist = (player_df['pos_x'][frame] ** 2 + player_df['pos_y'][frame] ** 2 + player_df['pos_z'][frame] ** 2) ** (
            0.5)
        return dist

    @staticmethod
    def get_afk(data_frame: pd.DataFrame, player: str, frame: int, kick_frame: int):
        player_df = data_frame[player]
        return (player_df['pos_x'][frame] == player_df['pos_x'][kick_frame] and
                player_df['pos_y'][frame] == player_df['pos_y'][kick_frame] and
                player_df['pos_z'][frame] == player_df['pos_z'][kick_frame])

    @staticmethod
    def get_touch_position(player: Player, data_frame: pd.DataFrame, k_frame: int, touch_frame: int):
        player_df = data_frame[player.name]
        x = abs(player_df['pos_x'][touch_frame])
        y = abs(player_df['pos_y'][touch_frame])
        if BaseKickoff.get_dist(data_frame, player.name, touch_frame) < 700:
            return kickoff.BALL
        if BaseKickoff.get_afk(data_frame, player.name, touch_frame, k_frame):
            return kickoff.AFK
        if (x > 2200) and (y > 3600):
            return kickoff.BOOST
        if (x < 500) and (y > 3600):
            return kickoff.GOAL
        if (x < 500) and (y < 3600):
            return kickoff.CHEAT
        return kickoff.UNKNOWN_TOUCH_POS

    @staticmethod
    def debug_kickoff_timings(data_frame: pd.DataFrame, kickoff_data_frame: pd.DataFrame, proto_kickoff):
        kickoff_start_frame = proto_kickoff.start_frame
        kickoff_touch_frame = proto_kickoff.touch_frame

        # Set kickoff_time for debugging later.
        kickoff_start_time = data_frame.game.time[kickoff_start_frame]
        kickoff_end_time = kickoff_data_frame['game']['time'][kickoff_touch_frame]
        kickoff_time = proto_kickoff.touch_time = kickoff_end_time - kickoff_start_time

        # Debug.
        differs = kickoff_data_frame['game']['time'][kickoff_start_frame:kickoff_touch_frame].diff()
        summed_time_diff = differs.sum()
        summed_time = kickoff_data_frame['game']['delta'][kickoff_start_frame:kickoff_touch_frame].sum()
        if summed_time > 0:
            proto_kickoff.touch_time = summed_time

        logger.info("STRAIGHT TIME " + str(kickoff_time))
        logger.info("SUM TIME" + str(summed_time))
        sum_vs_adding_diff = kickoff_time - summed_time

    # Todo get what team scored next
    @classmethod
    def get_goal_data(cls, cur_kickoff: KickoffStats, current_goal: Goal, data_frame: pd.DataFrame):
        game_time = data_frame['game', 'time']
        cur_kickoff.touch.kickoff_goal = game_time[current_goal.frame_number] - game_time[cur_kickoff.touch_frame]

    @staticmethod
    def is_kickoff_goal(data_frame: pd.DataFrame, proto_kickoff):
        kickoff_to_goal_turnover_count = -1
        kickoff_to_goal_defender_boost = -1

        kickoff_start_frame = proto_kickoff.start_frame

        next_goal_frame_idx = BaseKickoff.get_next_goal_frame_idx(data_frame, kickoff_start_frame)
        if next_goal_frame_idx > 0:
            kickoff_to_goal_turnover_count = BaseKickoff.get_turnover_count(data_frame,
                                                                            kickoff_start_frame, next_goal_frame_idx)
        else:
            print("Invalid kickoff-goal pair.")
            return

        if KICKOFF_GOAL_MAX_TURNOVERS >= kickoff_to_goal_turnover_count >= 0:
            print("Possible kickoff goal.")
        else:
            print("Turnovers exceeded " + str(KICKOFF_GOAL_MAX_TURNOVERS) + ".")
            return

    @staticmethod
    def get_next_goal_frame_idx(data_frame: pd.DataFrame, kickoff_start_frame: int):
        # Get last (current) goal number.
        goal_number_data_frame = data_frame.game.goal_number

        if data_frame.game.is_overtime.at[kickoff_start_frame]:
            # If the kickoff is for OT, the next goal must be at the end.
            next_goal_frame_idx = data_frame.last_valid_index()
        else:
            # Get next goal number at current kickoff, and +1 for next goal number.
            next_goal_number = int(goal_number_data_frame.at[kickoff_start_frame]) + 1
            # Get the index of the first occurrence of next_goal_number.
            # If next_goal_number is not in the DataFrame, return -1. (no goal following a kickoff)
            if goal_number_data_frame.eq(next_goal_number).any():
                next_goal_frame_idx = goal_number_data_frame.eq(next_goal_number).idxmax()
            else:
                next_goal_frame_idx = -1

        return next_goal_frame_idx

    @staticmethod
    def get_turnover_count(data_frame: pd.DataFrame, kickoff_start_frame, next_goal_frame_idx):
        # Get a smaller DataFrame, from current kickoff to next goal (only possession).
        kickoff_to_goal_possession = data_frame.loc[kickoff_start_frame: next_goal_frame_idx] \
            .ball.hit_team_no
        # Get possession diffs and drop NaNs.
        kickoff_to_goal_turnovers = kickoff_to_goal_possession.diff().dropna(axis=0, how='any')
        # Sum non-zero values.
        return kickoff_to_goal_turnovers.astype(bool).sum()
