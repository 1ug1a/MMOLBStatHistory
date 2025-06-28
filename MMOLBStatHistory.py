import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator
from cycler import cycler
import numpy as np
import pandas as pd

from aiohttp_client_cache import CachedSession, SQLiteBackend
import asyncio

from inspect import getsourcefile
from pathlib import Path

import re
from pprint import pprint
from collections import defaultdict
import json

#######################################
# mmolb stat history by dusk (@1ug1a) #
#######################################

# config stuff!

# STAT_MODE: decides what gets graphed. 'Player', 'Batters', or 'Pitchers'.
STAT_MODE = 'Batters' 
MEAN_TYPE = 'Rolling'
# ID: make sure to use a player ID for 'Player' mode, and a team ID for 'Batters'/'Pitchers'.
ID = '6806c6869edf4f7b46032b9a'

# SEASON_NUM, DAY_START, DAY_END: choose which days to start counting from.
TIME_START = [1, 0]
TIME_END = [2, 120]

# GRAPH_SMOOTHING: 1 uses the raw graph values. higher makes the graph smoother at the cost of accuracy.
GRAPH_SMOOTHING = 10
ROLLING_WINDOW = 40

# USE_SOLO_CUSTOM_STATS, SOLO_CUSTOM_STATS: lets you choose which stats you want to include in the individual-player stat mode.
USE_SOLO_CUSTOM_STATS = False
SOLO_CUSTOM_STATS = ['ops', 'era']

# TEAM_BATTER_STAT, TEAM_PITCHER_STAT: the stat that gets compared across a team when in either 'Batters' or 'Pitchers' mode.
TEAM_BATTER_STAT = 'ops'
TEAM_PITCHER_STAT = 'era'

# SOLO_BATTING_STATS, SOLO_PITCHING_STATS: stats you can choose from (and show up in the individual-player stat mode). don't touch this!
SOLO_BATTING_STATS = ['ba', 'obp', 'slg', 'ops', 'babip', 'bb_p', 'k_p', 'sb_p']
SOLO_PITCHING_STATS = ['era', 'fip_r', 'whip', 'h9', 'hr9', 'k9', 'bb9', 'kpbb']

# USE_CUSTOM_COLORS, CUSTOM_COLORS: lets you choose a custom set of line colors for your graph.
USE_CUSTOM_COLORS = False
CUSTOM_COLORS = '#7F3C8D,#11A579,#3969AC,#F2B701,#E73F74,#80BA5A,#E68310,#008695,#CF1C90,#f97b72,#4b4b8f,#A5AA99'.split(',')

# MAX_CONNECTIONS: the number of simultaneous API requests that can be active at a time. please don't overload freecashe.ws
MAX_CONNECTIONS = 4

##################################################################
# don't change anything below unless you know what you're doing! #
##################################################################

# cache stuff
SCRIPT_PATH = Path(getsourcefile(lambda: 0)).resolve()
DB_PATH = SCRIPT_PATH.parent / 'MMOLBStatHistory.db'
CACHE = SQLiteBackend(
  cache_name=DB_PATH,  # For SQLite, this will be used as the filename
  expire_after=60*25,                         
)

# custom color handler
CYCLER = cycler(color=CUSTOM_COLORS) if USE_CUSTOM_COLORS else None

# x-tick stuff
XTICK_OPTIONS = MaxNLocator(nbins=15, integer=True, prune=None, steps=[1, 2, 4, 5, 10])

async def get_url(session, url, semaphore):
  async with semaphore:
    async with session.get(url) as response:
      return await response.json()

async def get_urls(session, urls, max_con_req=1):
  match urls:
    case str():
      url_list = [urls]
    case dict():
      url_list = urls.values()
    case list():
      url_list = urls
  semaphore = asyncio.Semaphore(max_con_req)
  tasks = [get_url(session, url, semaphore) for url in url_list]
  result = await asyncio.gather(*tasks)
  match urls:
    case str():
      return result[0]
    case dict():
      return dict(zip(urls.keys(), result))
    case list():
      return result

async def cashews_get_chron(session, kind, ids):
  print(f'Getting {kind} info... ', end='')
  ids = ','.join(ids) if not isinstance(ids, str) else ids
  api_url = f'https://freecashe.ws/api/chron/v0/entities?kind={kind}&id={ids}'
  response = await get_urls(session, api_url)
  response = [response['items'][idx]['data'] for idx in range(0, len(response['items']))]
  print('Done!')
  return response[0] if len(response) == 1 else response

async def cashews_get_stat_history(session, kind, id, time_start, time_end, is_greater_league, mean_type):
  api_urls = {}
  time_list = []
  print('Obtaining stat history... ', end='')
  process_days(time_start, time_end, time_list, is_greater_league, gather_stat_urls, kind, id, time_start, api_urls, mean_type)
  api_data = await get_urls(session, api_urls, MAX_CONNECTIONS)
  #print(api_data)

  player_first_history = defaultdict(dict)
  for time, players in api_data.items():
    for player in players:
      player_id = player['player_id']
      stats = player['stats']
      player_first_history[player_id][time] = stats
  print('Done!')

  return dict(player_first_history)

def parse_statistics(history_dict):
  print('Parsing statistics... ', end='')
  statistics = defaultdict(dict)
  for player_id, history in history_dict.items():
    for time, stats in history.items():
      statistics[player_id][time] = (parse_batting_stats(stats), parse_pitching_stats(stats))
  print('Done!')
  return dict(statistics)

def gather_stat_urls(idx, time_list, kind, id, time_start, api_urls, mean_type):
  match mean_type:
    case 'Cumulative':
      url = f'https://freecashe.ws/api/player-stats?{kind}={id}&start={time_start[0]},{time_start[1]}&end={time_list[idx][0]},{time_list[idx][1]}'
    case 'Rolling':
      constant = round(ROLLING_WINDOW/2)
      idx_start = max(idx-constant, 0)
      idx_end = min(idx+constant, len(time_list)-1)
      # print(idx, ':', idx_start, 'to', idx_end)
      url = f'https://freecashe.ws/api/player-stats?{kind}={id}&start={time_list[idx_start][0]},{time_list[idx_start][1]}&end={time_list[idx_end][0]},{time_list[idx_end][1]}'
  #print(url)
  api_urls[time_list[idx]] = url

def process_days(time_start, time_end, time_list, is_greater_league, function, *args):
  for season in range(time_start[0], time_end[0]+1):
    season_day_start = time_start[1] if time_start[1] != 0 and season == time_start[0] else (1 if is_greater_league else 2)
    season_day_end = time_end[1] if season == time_end[0] else (255 if is_greater_league else 240)
    for day in range(season_day_start, season_day_end+1, 2):
      time_list.append((season, day))
  #pprint(time_list)
  for idx in range(0, len(time_list)):
    function(idx, time_list, *args)

def get_valid_start(time_start, is_greater_league):
  season = time_start[0]
  day = time_start[1]
  if is_greater_league: # e.g. if DAY_START == 1, no change. if DAY_START == 2, add 1
    day = day + (day + 1) % 2
    day = 1 if day < 1 else day
  else:
    day = day + (day) % 2
    day = 2 if day < 2 else day
  return (season, day)

def get_valid_end(time_end, is_greater_league):
  season = time_end[0]
  day = time_end[1]
  if is_greater_league: # e.g. if DAY_END == 140, subtract 1.
    day = day - (day + 1) % 2
    day = 255 if day > 255 else day
  else:
    day = day - (day) % 2
    day = 240 if day > 240 else day
  return (season, day)

def parse_batting_stats(stats):
  _pa   = stats.get('plate_appearances', 0)
  _ab   = stats.get('at_bats', 0)
  _1b   = stats.get('singles', 0)
  _2b   = stats.get('doubles', 0)
  _3b   = stats.get('triples', 0)
  _hr   = stats.get('home_runs', 0)
  _h    = _1b + _2b + _3b + _hr
  _bb   = stats.get('walked', 0)
  _hbp  = stats.get('hit_by_pitch', 0)
  _k    = stats.get('struck_out', 0)
  _sf   = stats.get('sac_flies', 0)
  _sb   = stats.get('stolen_bases', 0)
  _cs   = stats.get('caught_stealing', 0)

  ba    = _h / _ab if _ab != 0 else np.nan
  obp   = (_h + _bb + _hbp) / _pa if _pa != 0 else np.nan
  slg   = (_1b + 2*_2b + 3*_3b + 4*_hr) / _ab if _ab != 0 else np.nan
  ops   = obp + slg
  babip = (_h - _hr) / (_ab - _hr - _k + _sf) if (_ab - _hr - _k + _sf) != 0 else np.nan
  bb_p  = _bb / _pa if _pa != 0 else np.nan
  k_p   = _k / _pa if _pa != 0 else np.nan
  sb_p  = _sb / (_sb + _cs) if (_sb + _cs) != 0 else np.nan

  stats_dict = {}
  stats_used = list(set(SOLO_BATTING_STATS) & set(SOLO_CUSTOM_STATS)) if USE_SOLO_CUSTOM_STATS else SOLO_BATTING_STATS
  for i in stats_used:
    stats_dict[i] = locals()[i]

  return stats_dict

def parse_pitching_stats(stats):
  _ip   = stats.get('outs', 0)/3
  _h    = stats.get('hits_allowed', 0)
  _hr   = stats.get('home_runs_allowed', 0)
  _k    = stats.get('strikeouts', 0)
  _bb   = stats.get('walks', 0)
  _er   = stats.get('earned_runs', 0)
  _hb   = stats.get('hit_batters', 0)
  
  era   = 9*_er / _ip if _ip != 0 else np.nan
  fip_r = (13*_hr + 3*(_bb + _hb) - 2*_k) / _ip if _ip != 0 else np.nan
  whip  = (_h + _bb) / _ip if _ip != 0 else np.nan
  h9    = 9*_h / _ip if _ip != 0 else np.nan
  hr9   = 9*_hr / _ip if _ip != 0 else np.nan
  k9    = 9*_k / _ip if _ip != 0 else np.nan
  bb9   = 9*_bb / _ip if _ip != 0 else np.nan
  kpbb  = _k / _bb if _bb != 0 else np.nan

  stats_dict = {}
  stats_used = list(set(SOLO_PITCHING_STATS) & set(SOLO_CUSTOM_STATS)) if USE_SOLO_CUSTOM_STATS else SOLO_PITCHING_STATS
  for i in stats_used:
    stats_dict[i] = locals()[i]

  return stats_dict

def parse_feed(feed, valid_players, disp_start, disp_end):
  parsed_feed = {}
  valid_date = False
  for idx, entry in enumerate(feed):
    entry = feed[idx]
    season, day = entry['season'], entry['day']

    if type(day) == int:
      day = int(day)
      if season == disp_start[0]:
        valid_date = day >= disp_start[1]
      elif season == disp_end[0]:
        valid_date = day <= disp_end[1]
      else:
        valid_date = True

    query_conditions = [
      entry['type'] == 'augment',
      'Special Delivery' in entry['text'],
      'Shipment' in entry['text']
    ]
    if valid_date and any(query_conditions) and any(name in entry['text'] for name in valid_players):
      time = (entry['season'], entry['day'])
      if time not in parsed_feed: 
        parsed_feed[time] = process_entry(entry['text'], valid_players)
      else:
        parsed_feed[time] += ' ' + process_entry(entry['text'], valid_players)
  return parsed_feed

def process_entry(text, valid_players):
  for name in valid_players:
    text = text.replace(name, name.replace('.', '*'))
  split_text = text.split('.')
  new_sentences = []
  for sentence in split_text:
    for name in valid_players:
      if name.replace('.', '*') in sentence:
        new_sentence = sentence.replace('*', '.').lstrip()
        try:
          new_sentence = new_sentence[new_sentence.index('!')+2:]
        except:
          pass
        new_sentences.append(new_sentence)
  return '. '.join(new_sentences) + '.'

def parse_player_dict(team_info):
  players = team_info['Players']
  player_dict = defaultdict()
  for player in players:
    player_id = player.pop('PlayerID')
    player.pop('Stats')
    player_dict[player_id] = player
  return dict(player_dict)

def plot_graph(stat_mode, mean_type, rolling_window, stats, team_info, feed, player_dict, time_start, time_end):
  match stat_mode:
    case 'Player':
      plot_solo_graph(mean_type, rolling_window, stats, team_info, feed, player_dict, time_start, time_end)
    case 'Batters' | 'Pitchers':
      plot_team_graph(stat_mode, mean_type, rolling_window, stats, team_info, feed, player_dict, time_start, time_end)

def plot_team_graph(stat_mode, mean_type, rolling_window, stats, team_info, feed, player_dict, valid_ids, time_start, time_end):
  player_ids = valid_ids
  player_names = [f"{player_dict[id]['FirstName']} {player_dict[id]['LastName']}" for id in player_ids]
  player_labels = {id: f"{player_dict[id]['Slot']} {player_dict[id]['FirstName']} {player_dict[id]['LastName']}" for id in player_ids}
  
  match stat_mode:
    case 'Batters':
      stat = TEAM_BATTER_STAT
      stat_index = 0
    case 'Pitchers':
      stat = TEAM_PITCHER_STAT
      stat_index = 1

  len_stats = len(stats[next(iter(stats))])
  time_units = range(0, len_stats)
  plots = {}
  for id, history in stats.items():
    #print(list(history.values()))
    plots[id] = [value[stat_index][stat] for value in history.values()]
  #print(len_stats)
  #print(len(stat_lines[next(iter(stat_lines))]))

  means = {}
  for id in valid_ids:
    means[id] = pd.Series(plots[id]).rolling(window=GRAPH_SMOOTHING, min_periods=1, center=True).mean()

  # start plotting
  fig, ax = plt.subplots(layout="constrained", figsize=(12, 6))
  ax.set_prop_cycle(CYCLER)

  for id in player_ids:
    ax.plot(time_units, means[id], label = player_labels[id])
    #print(id)

  t_name = f'{team_info['Location']} {team_info['Name']}'

  ax.set_xlabel('Game')
  ax.set_xlim(left=0, right=len_stats)
  ax.set_title(f'{t_name} S{time_start[0]}D{time_start[1]}-S{time_end[0]}D{time_end[1]} {mean_type} {stat_mode[:-3] + "ing"} History ({stat.upper()}) - {rolling_window} Game Average (Smoothed)')
  ax.grid(which='major', color='#999999', linewidth=0.8)
  ax.grid(which='minor', color='#CCCCCC', linestyle=':', linewidth=0.5)
  ax.minorticks_on()
  ax.legend()

  ax.xaxis.set_major_locator(XTICK_OPTIONS)

  #print(feed)
  cmap = plt.get_cmap("tab10")
  for time_unit, actual_time in enumerate(stats[next(iter(stats))]):
    #print(time_unit, actual_time)
    if isinstance(actual_time[1], int) and (actual_time in feed or (actual_time[0], actual_time[1]+1) in feed):
      names_found = [name in feed.get(actual_time, '') or name in feed.get((actual_time[0], actual_time[1]+1), '') for name in player_names]
      if names_found.count(True) > 1:
        ax.axvline(x=time_unit, color='black', linestyle='--')
      else:
        i = names_found.index(True)
        #print(i)
        ax.axvline(x=time_unit, color=cmap(i), linestyle='--')

  plt.show()

def plot_solo_graph(stats, team_info, player_dict, time_start, time_end):
  pass

async def main():
  async with CachedSession(cache=CACHE) as session:
    team_info = await cashews_get_chron(session, 'team', ID)
    player_dict = parse_player_dict(team_info)
    #pprint(player_dict)
    valid_ids = [id for id, info in player_dict.items() if info['PositionType'] == STAT_MODE[:-1]]
    valid_names = [f"{info['FirstName']} {info['LastName']}" for id, info in player_dict.items() if info['PositionType'] == STAT_MODE[:-1]]
    feed = parse_feed(team_info['Feed'], valid_names, TIME_START, TIME_END)
    is_greater_league = team_info['League'] in ['6805db0cac48194de3cd3fe4', '6805db0cac48194de3cd3fe5']
    valid_start = get_valid_start(TIME_START, is_greater_league)
    valid_end = get_valid_end(TIME_END, is_greater_league)
    team_stat_history = await cashews_get_stat_history(session, 'team', ID, valid_start, valid_end, is_greater_league, MEAN_TYPE)
    team_statistics = parse_statistics(team_stat_history)
    #pprint(team_statistics[next(iter(team_statistics))])
    for time, entry in feed.items():
      print(f"{team_info['Emoji']} Season {time[0]}, {'Day ' if type(time[1]) == int else ''}{time[1]}: {entry}")
    plot_team_graph(STAT_MODE, MEAN_TYPE, ROLLING_WINDOW, team_statistics, team_info, feed, player_dict, valid_ids, TIME_START, TIME_END)

if __name__ == '__main__':
  asyncio.run(main())